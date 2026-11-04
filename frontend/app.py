# Moa 화면 진입점 — 페이지 등록만 한다
#
# 화면 4종의 내용은 `screens/` 안에 있고, URL 규약은 `moa/nav.py`에 있다.
#   /        SCR-001  A. 주문 시작 (기본 페이지)
#   /s       SCR-002  B. 주문 정리
#   /order   SCR-005  E. 주문서
#   /ops     SCR-006  O. 운영 대시보드
#
# 사이드바 네비게이션을 쓰지 않는다 — 화면 제목 · 사이드바 · 진행 막대가 없다(P-06 U-2).
# 이동은 각 화면의 하단 바 보조 버튼 · 주 버튼과 헤더 [운영 대시보드] · [나가기]로만 한다.
import streamlit as st

from moa import nav

# set_page_config는 앱 실행마다 **첫 Streamlit 명령**이어야 하므로 여기서 한 번만 한다.
# 화면 제목은 브라우저 탭 제목이며 화면 안에는 두지 않는다(P-06 U-2).
st.set_page_config(page_title="Moa", layout="wide", initial_sidebar_state="collapsed")

st.navigation(list(nav.pages().values()), position="hidden").run()
