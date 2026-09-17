from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="DH의 탁상감정", page_icon="🏢", layout="wide")

# Streamlit 기본 여백·헤더를 없애고 앱 iframe이 화면을 꽉 채우도록 함
st.markdown(
    """
    <style>
      header[data-testid="stHeader"] {display: none;}
      #MainMenu, footer {visibility: hidden;}
      .block-container {padding: 0 !important; max-width: 100% !important;}
      div[data-testid="stAppViewContainer"] > .main {padding: 0;}
      iframe[title="st.iframe"] {height: 100vh !important; width: 100% !important; border: 0;}
    </style>
    """,
    unsafe_allow_html=True,
)

html = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>html,body{{margin:0;height:100%}} [hidden]{{display:none!important}} img{{max-width:100%}}</style>
</head>
<body>
{html}
</body>
</html>"""

components.html(page, height=1000, scrolling=True)
