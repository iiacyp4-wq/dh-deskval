"""DH의 탁상감정 - Streamlit 진입점.

워크시트(index.html)를 화면에 띄우고, 공공데이터포털(국토교통부) API로
실거래가와 건축물대장을 자동 조회해 워크시트에 채워 넣는다.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="DH의 탁상감정", page_icon="🏢", layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    """
    <style>
      #MainMenu, footer {visibility: hidden;}
      header[data-testid="stHeader"] {background: transparent; height: 2.2rem;}
      .block-container {padding: 0.6rem 1rem 0 1rem !important; max-width: 100% !important;}
      iframe[title="st.iframe"], div[data-testid="stIFrame"] iframe {height: calc(100vh - 3rem) !important; width: 100% !important; border: 0;}
      div[data-testid="stExpander"] details summary p {font-size: 0.95rem; font-weight: 600;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- 상수
PROPERTY_TYPES = ["아파트", "오피스텔", "연립다세대", "단독다가구", "상업업무용", "토지"]
TYPE_TO_SHEET = {"아파트": "apt", "오피스텔": "officetel", "연립다세대": "villa", "단독다가구": "house", "상업업무용": "shop", "토지": "land"}
NAME_COL = {"아파트": "aptNm", "오피스텔": "offiNm", "연립다세대": "mhouseNm", "단독다가구": "houseType", "상업업무용": "buildingUse", "토지": "jimok"}
AREA_COL = {"아파트": "excluUseAr", "오피스텔": "excluUseAr", "연립다세대": "excluUseAr", "단독다가구": "totalFloorAr", "상업업무용": "buildingAr", "토지": "dealArea"}
AREA_LABEL = {"아파트": "전용면적", "오피스텔": "전용면적", "연립다세대": "전용면적", "단독다가구": "연면적", "상업업무용": "건물면적", "토지": "거래면적"}
SC_BASIS = {"아파트": "areaEx", "오피스텔": "areaEx", "연립다세대": "areaEx", "단독다가구": "bldgArea", "상업업무용": "bldgArea", "토지": "landArea"}
STRUCT_MAP = [("철골철근", "src"), ("철근콘크리트", "rc"), ("경량철골", "lsteel"), ("철골", "steel"), ("벽돌", "brick"), ("조적", "brick"), ("블록", "block"), ("목", "wood")]


# ---------------------------------------------------------------- 도우미
def service_key() -> str:
    key = ""
    try:
        key = st.secrets.get("DATA_GO_KR_KEY", "")
    except Exception:
        key = ""
    return st.session_state.get("api_key") or key or ""


@st.cache_data(show_spinner=False)
def bdong_table() -> pd.DataFrame:
    import PublicDataReader as pdr

    df = pdr.code_bdong()
    df = df[df["말소일자"].fillna("") == ""].copy()
    return df


def sigungu_options(df: pd.DataFrame, sido: str) -> pd.DataFrame:
    sub = df[(df["시도명"] == sido) & (df["시군구명"] != "") & (df["읍면동명"] == "")]
    return sub[["시군구명", "시군구코드"]].drop_duplicates("시군구코드")


def bdong_options(df: pd.DataFrame, sigungu_code: str) -> pd.DataFrame:
    sub = df[(df["시군구코드"] == sigungu_code) & (df["읍면동명"] != "")].copy()
    sub["label"] = sub["읍면동명"] + sub["동리명"].apply(lambda x: f" {x}" if x else "")
    sub["bdong"] = sub["법정동코드"].astype(str).str[5:10]
    return sub[["label", "bdong", "법정동코드"]]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_trades(key: str, property_type: str, sigungu_code: str, start_ym: str, end_ym: str) -> pd.DataFrame:
    from PublicDataReader import TransactionPrice

    api = TransactionPrice(key)
    df = api.get_data(property_type=property_type, trade_type="매매", sigungu_code=sigungu_code,
                      start_year_month=start_ym, end_year_month=end_ym, translate=False)
    return df if df is not None else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ledger(key: str, ledger_type: str, sigungu_code: str, bdong_code: str, bun: str, ji: str, plat: str) -> pd.DataFrame:
    from PublicDataReader import BuildingLedger

    api = BuildingLedger(key)
    df = api.get_data(ledger_type=ledger_type, sigungu_code=sigungu_code, bdong_code=bdong_code,
                      bun=bun, ji=ji, plat_code=plat, translate=False)
    return df if df is not None else pd.DataFrame()


def to_won(amount_manwon) -> int:
    s = re.sub(r"[^0-9]", "", str(amount_manwon or ""))
    return int(s) * 10000 if s else 0


def to_float(v) -> float:
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return 0.0


def months_back(n: int) -> tuple[str, str]:
    today = date.today()
    y, m = today.year, today.month
    end = f"{y}{m:02d}"
    m -= n - 1
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}{m:02d}", end


def push_prefill(data: dict, note: str) -> None:
    st.session_state["prefill"] = {"nonce": int(time.time() * 1000), "data": data}
    st.session_state["prefill_note"] = note


def struct_code(name: str) -> str:
    for token, code in STRUCT_MAP:
        if token in (name or ""):
            return code
    return "rc"


# ---------------------------------------------------------------- 자동 조회 UI
with st.expander("자동 조회 (실거래가 · 건축물대장) - 국토교통부 공공데이터", expanded=False):
    key = service_key()
    tab_trade, tab_bld, tab_set = st.tabs(["실거래가 → 비교사례", "건축물대장 → 물건개요", "설정 · 인증키"])

    with tab_set:
        st.markdown(
            """
            **인증키 발급 (무료, 한 번만)**
            1. [공공데이터포털](https://www.data.go.kr) 회원가입 후 로그인
            2. 아래 API를 검색해 각각 **활용신청** (자동 승인)
               - 국토교통부_아파트 매매 실거래가 자료 / 오피스텔 / 연립다세대 / 단독·다가구 / 상업업무용 / 토지 매매 실거래가
               - 국토교통부_건축HUB_건축물대장정보 서비스
            3. 마이페이지에서 **일반 인증키**를 복사해 아래에 붙여넣기 (Encoding·Decoding 어느 쪽이든 됨)

            운영자는 Streamlit Cloud 앱 설정의 Secrets에 `DATA_GO_KR_KEY = "키"`를 넣어 두면 모든 사용자가 키 입력 없이 씁니다.
            """
        )
        entered = st.text_input("공공데이터포털 인증키", value=st.session_state.get("api_key", ""), type="password", key="api_key_input")
        if entered != st.session_state.get("api_key", ""):
            st.session_state["api_key"] = entered
            st.rerun()
        st.caption("연결 상태: " + ("인증키 있음" if key else "인증키 없음 - 위에 입력하거나 Secrets에 설정하세요"))

    codes = bdong_table()
    sidos = list(codes["시도명"].drop_duplicates())

    # ---------- 실거래가
    with tab_trade:
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        sido = c1.selectbox("시·도", sidos, key="t_sido")
        sgg = sigungu_options(codes, sido)
        sgg_name = c2.selectbox("시·군·구", list(sgg["시군구명"]), key="t_sgg")
        sgg_code = str(sgg[sgg["시군구명"] == sgg_name]["시군구코드"].iloc[0])
        ptype = c3.selectbox("물건 유형", PROPERTY_TYPES, key="t_ptype")
        months = c4.slider("조회 기간 (개월)", 1, 24, 6, key="t_months")
        f1, f2, f3 = st.columns([2, 1, 1])
        name_q = f1.text_input("단지명·동 필터 (포함 검색, 비우면 전체)", key="t_name")
        area_q = f2.number_input(f"{AREA_LABEL[ptype]} 기준 (㎡, 0이면 전체)", min_value=0.0, value=0.0, step=1.0, key="t_area")
        tol = f3.number_input("면적 허용 오차 (±㎡)", min_value=0.0, value=3.0, step=0.5, key="t_tol")

        if st.button("실거래가 조회", type="primary", disabled=not key, key="t_go"):
            start_ym, end_ym = months_back(months)
            try:
                with st.spinner(f"{sido} {sgg_name} {ptype} {start_ym}~{end_ym} 조회 중…"):
                    df = fetch_trades(key, ptype, sgg_code, start_ym, end_ym)
                st.session_state["trades"] = (ptype, df)
            except Exception as e:  # noqa: BLE001
                st.error(f"조회 실패: {e}. 인증키가 해당 API에 활용신청 되어 있는지 확인하세요.")
        if not key:
            st.info("먼저 '설정 · 인증키' 탭에서 인증키를 넣으세요.")

        if "trades" in st.session_state and st.session_state["trades"][0] == ptype:
            _, raw = st.session_state["trades"]
            if raw.empty:
                st.warning("해당 기간에 거래가 없습니다.")
            else:
                df = raw.copy()
                ncol, acol = NAME_COL[ptype], AREA_COL[ptype]
                for c in [ncol, acol, "umdNm", "jibun", "floor", "buildYear", "dealYear", "dealMonth", "dealDay", "dealAmount", "cdealType", "dealingGbn", "aptDong", "plottageAr", "landAr"]:
                    if c not in df.columns:
                        df[c] = ""
                df["거래일"] = pd.to_datetime(dict(year=pd.to_numeric(df["dealYear"], errors="coerce"), month=pd.to_numeric(df["dealMonth"], errors="coerce"), day=pd.to_numeric(df["dealDay"], errors="coerce")), errors="coerce")
                df["거래금액(원)"] = df["dealAmount"].apply(to_won)
                df["면적(㎡)"] = df[acol].apply(to_float)
                df["단가(원/㎡)"] = (df["거래금액(원)"] / df["면적(㎡)"].replace(0, pd.NA)).round(0)
                df["취소"] = df["cdealType"].astype(str).str.strip().apply(lambda x: "취소" if x and x != "nan" else "")
                if name_q.strip():
                    mask = df[ncol].astype(str).str.contains(name_q.strip(), na=False) | df["umdNm"].astype(str).str.contains(name_q.strip(), na=False)
                    df = df[mask]
                if area_q > 0:
                    df = df[(df["면적(㎡)"] - area_q).abs() <= tol]
                df = df.sort_values("거래일", ascending=False).reset_index(drop=True)
                show = pd.DataFrame({
                    "명칭": df[ncol].astype(str), "법정동": df["umdNm"].astype(str), "지번": df["jibun"].astype(str),
                    "거래일": df["거래일"].dt.strftime("%Y-%m-%d"), "거래금액(원)": df["거래금액(원)"], AREA_LABEL[ptype] + "(㎡)": df["면적(㎡)"],
                    "단가(원/㎡)": df["단가(원/㎡)"], "층": df["floor"].astype(str), "건축년도": df["buildYear"].astype(str),
                    "거래유형": df["dealingGbn"].astype(str), "취소": df["취소"],
                })
                st.caption(f"{len(show)}건 · 행을 클릭해 최대 3건 선택 후 '비교사례로 보내기'. 취소 거래는 제외하세요.")
                ev = st.dataframe(show, hide_index=True, on_select="rerun", selection_mode="multi-row", key="t_table",
                                  column_config={"거래금액(원)": st.column_config.NumberColumn(format="%d"), "단가(원/㎡)": st.column_config.NumberColumn(format="%d")})
                rows = list(ev.selection.rows)[:3] if ev and ev.selection else []
                b1, b2 = st.columns([1, 3])
                if b1.button(f"선택 {len(rows)}건 → 비교사례로 보내기", disabled=not rows, key="t_send"):
                    cases = []
                    for i in rows:
                        r = df.iloc[i]
                        fl = f" {r['floor']}층" if str(r["floor"]).strip() not in ("", "nan") else ""
                        cases.append({
                            "name": f"{r[ncol]}{fl} ({r['umdNm']} {r['jibun']})".strip(),
                            "date": r["거래일"].strftime("%Y-%m-%d") if pd.notna(r["거래일"]) else "",
                            "price": str(int(r["거래금액(원)"])), "area": str(r["면적(㎡)"]),
                            "situ": 100, "time": 100, "region": 100, "indiv": 100, "w": 1,
                        })
                    latest = df.iloc[rows[0]]
                    data = {"prop": {"type": TYPE_TO_SHEET[ptype]},
                            "sc": {"cases": cases, "basis": SC_BASIS[ptype]},
                            "ref": {"trade": str(int(latest["거래금액(원)"])), "tradeDate": latest["거래일"].strftime("%Y-%m-%d") if pd.notna(latest["거래일"]) else ""},
                            "check": {"trade": {"d": True, "m": f"국토부 실거래가 API {months}개월 조회, {len(cases)}건 사례 채택 ({sido} {sgg_name} {ptype})"}}}
                    push_prefill(data, f"비교사례 {len(cases)}건을 워크시트에 넣었습니다. 가격산정 탭에서 보정치를 조정하세요.")
                    st.rerun()
                b2.caption("보정치(사정·시점·지역·개별)는 100으로 들어갑니다. 워크시트에서 조정하세요.")

    # ---------- 건축물대장
    with tab_bld:
        c1, c2, c3 = st.columns(3)
        sido_b = c1.selectbox("시·도", sidos, key="b_sido")
        sgg_b = sigungu_options(codes, sido_b)
        sgg_name_b = c2.selectbox("시·군·구", list(sgg_b["시군구명"]), key="b_sgg")
        sgg_code_b = str(sgg_b[sgg_b["시군구명"] == sgg_name_b]["시군구코드"].iloc[0])
        bd = bdong_options(codes, sgg_code_b)
        bd_label = c3.selectbox("읍·면·동 (리)", list(bd["label"]), key="b_bdong")
        bd_code = str(bd[bd["label"] == bd_label]["bdong"].iloc[0])
        d1, d2, d3 = st.columns([1, 1, 1])
        plat = d1.selectbox("대지 구분", ["일반 (0)", "산 (1)"], key="b_plat")
        bun = d2.text_input("본번", key="b_bun", placeholder="예: 542")
        ji = d3.text_input("부번 (없으면 비움)", key="b_ji", placeholder="예: 3")

        if st.button("건축물대장 조회", type="primary", disabled=not (key and bun.strip()), key="b_go"):
            pc = "1" if plat.startswith("산") else "0"
            try:
                with st.spinner("건축HUB 표제부·기본개요·주택가격 조회 중…"):
                    title = fetch_ledger(key, "표제부", sgg_code_b, bd_code, bun.strip(), ji.strip(), pc)
                    basis = fetch_ledger(key, "기본개요", sgg_code_b, bd_code, bun.strip(), ji.strip(), pc)
                    try:
                        hsprc = fetch_ledger(key, "주택가격", sgg_code_b, bd_code, bun.strip(), ji.strip(), pc)
                    except Exception:  # noqa: BLE001
                        hsprc = pd.DataFrame()
                st.session_state["ledger"] = (title, basis, hsprc)
            except Exception as e:  # noqa: BLE001
                st.error(f"조회 실패: {e}. 건축HUB 건축물대장정보 서비스 활용신청 여부를 확인하세요.")
        if not key:
            st.info("먼저 '설정 · 인증키' 탭에서 인증키를 넣으세요.")

        if "ledger" in st.session_state:
            title, basis, hsprc = st.session_state["ledger"]
            if title.empty:
                st.warning("해당 지번의 표제부가 없습니다. 본번·부번과 읍면동을 확인하세요.")
            else:
                t = title.copy()
                for c in ["bldNm", "dongNm", "mainPurpsCdNm", "etcPurps", "strctCdNm", "totArea", "platArea", "archArea", "grndFlrCnt", "ugrndFlrCnt", "useAprDay", "hhldCnt", "rideUseElvtCnt", "platPlc", "newPlatPlc", "bcRat", "vlRat", "regstrGbCdNm", "regstrKindCdNm"]:
                    if c not in t.columns:
                        t[c] = ""
                zone = ""
                if not basis.empty:
                    z = basis.get("jiyukCdNm")
                    zone = ", ".join(sorted({str(x) for x in z if str(x).strip() and str(x) != "nan"})) if z is not None else ""
                price = 0
                if not hsprc.empty and "hsprc" in hsprc.columns:
                    vals = [to_float(x) for x in hsprc["hsprc"]]
                    price = int(max(vals)) if vals else 0
                show = pd.DataFrame({
                    "건물명": t["bldNm"].astype(str), "동": t["dongNm"].astype(str), "대장구분": t["regstrKindCdNm"].astype(str),
                    "주용도": t["mainPurpsCdNm"].astype(str), "구조": t["strctCdNm"].astype(str),
                    "연면적(㎡)": t["totArea"].apply(to_float), "대지면적(㎡)": t["platArea"].apply(to_float),
                    "지상/지하": t["grndFlrCnt"].astype(str) + "/" + t["ugrndFlrCnt"].astype(str),
                    "사용승인일": t["useAprDay"].astype(str), "세대수": t["hhldCnt"].astype(str), "승강기": t["rideUseElvtCnt"].astype(str),
                })
                st.caption(f"표제부 {len(show)}건 · 용도지역: {zone or '조회 없음'} · 대장상 주택가격: {format(price, ',')}원" if price else f"표제부 {len(show)}건 · 용도지역: {zone or '조회 없음'}")
                ev = st.dataframe(show, hide_index=True, on_select="rerun", selection_mode="single-row", key="b_table")
                sel = list(ev.selection.rows) if ev and ev.selection else []
                if st.button("선택 건물 → 물건개요·원가법에 반영", disabled=not sel, key="b_send"):
                    r = t.iloc[sel[0]]
                    apr = re.sub(r"[^0-9]", "", str(r["useAprDay"]))
                    year = apr[:4] if len(apr) >= 4 else ""
                    struct = struct_code(str(r["strctCdNm"]))
                    memo = (f"건축HUB 표제부: {r['bldNm']} {r['dongNm']} / 주용도 {r['mainPurpsCdNm']} {r['etcPurps']} / 구조 {r['strctCdNm']} / "
                            f"연면적 {r['totArea']}㎡ / 대지 {r['platArea']}㎡ / 지상 {r['grndFlrCnt']}층 지하 {r['ugrndFlrCnt']}층 / 사용승인 {r['useAprDay']} / "
                            f"건폐율 {r['bcRat']}% 용적률 {r['vlRat']}%. 위반건축물 표기는 API 미제공, 대장 원본에서 확인.")
                    data = {
                        "prop": {"addr": str(r["platPlc"] or r["newPlatPlc"]), "dongho": str(r["bldNm"] or ""), "structure": struct,
                                 "builtYear": year, "bldgArea": str(to_float(r["totArea"]) or ""), "landArea": str(to_float(r["platArea"]) or ""),
                                 "floors": str(r["grndFlrCnt"] or ""), "zone": zone},
                        "cost": {"structure": struct, "area": str(to_float(r["totArea"]) or ""), "builtYear": year},
                        "land": {"area": str(to_float(r["platArea"]) or "")},
                        "check": {"bld": {"d": True, "m": memo}, "zone": {"d": bool(zone), "m": f"건축물대장 기본개요 지역지구: {zone}" if zone else ""}},
                    }
                    if price:
                        data["ref"] = {"official": str(price)}
                        data["check"]["price"] = {"d": True, "m": f"건축물대장 주택가격(공시) {format(price, ',')}원"}
                    push_prefill(data, "건축물대장 내용을 물건개요·원가법·자료조사에 반영했습니다. 면적·전용면적은 확인 후 수정하세요.")
                    st.rerun()

if st.session_state.get("prefill_note"):
    st.success(st.session_state.pop("prefill_note"))

# ---------------------------------------------------------------- 워크시트
html = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
prefill = st.session_state.get("prefill")
prefill_js = f"<script>window.PREFILL = {json.dumps(prefill, ensure_ascii=False)};</script>" if prefill else ""
page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>html,body{{margin:0;height:100%}} [hidden]{{display:none!important}} img{{max-width:100%}}</style>
{prefill_js}
</head>
<body>
{html}
</body>
</html>"""

components.html(page, height=1000, scrolling=True)
