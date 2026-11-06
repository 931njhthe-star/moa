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
import os

import streamlit as st

from moa import copy, dialogs, layout, nav, state

# set_page_config는 앱 실행마다 **첫 Streamlit 명령**이어야 하므로 여기서 한 번만 한다.
# 화면 제목은 브라우저 탭 제목이며 화면 안에는 두지 않는다(P-06 U-2).
st.set_page_config(page_title="Moa", layout="wide", initial_sidebar_state="collapsed")

page = st.navigation(list(nav.pages().values()), position="hidden")

# 운영 대시보드 전용 스택(moa-ops · :8502, docker-compose.ops.yml 이 MOA_OPS_ONLY=1 을 준다)
# 어느 주소로 들어와도 /ops 로 보내고, 서비스 진입 게이트 없이 O-0 비밀번호 한 번으로 들어간다.
# 두 문의 비밀번호가 같은 값(OPS_DASHBOARD_PASSWORD)이라 보안 수준은 그대로다.
# [나가기]는 start 로 가지만 여기서 다시 /ops(O-0)로 돌아온다. 앱 A · B(8501)는 이 값이 없어 그대로다
if os.getenv("MOA_OPS_ONLY", "").strip() == "1":
    if page.url_path != "ops":
        nav.go("ops")
    page.run()
    st.stop()

# 서비스 진입 게이트 — 어느 URL로 들어와도 비밀번호를 먼저 받는다(2026-11-05 사용자 요청).
# O-0(운영 대시보드 비밀번호)과 같은 구성 · 같은 비밀번호(`OPS_DASHBOARD_PASSWORD`)이며, 비교는 서버가 한다.
# 통과 여부는 브라우저 세션 동안 유지된다. 운영 대시보드는 들어간 뒤에도 따로 비밀번호를 묻는다.
# `st.navigation`은 먼저 불러 둔다 — 부르지 않으면 `/s` · `/ops` 같은 URL이 "없는 페이지"가 된다.
if not st.session_state.get(state.SERVICE_AUTHED):
    layout.page_setup()
    layout.header(gate=True)
    with st.container(key="moa_service_login"):
        submitted, _, password = dialogs.password_form(
            "service_login", title=copy.G0_TITLE, prompt=copy.G0_PROMPT,
            error_key=state.SERVICE_ERROR, with_cancel=False)
    if submitted:
        dialogs.try_service_login(password)
        st.rerun()
    st.stop()   # 통과 전에는 화면 · API를 하나도 부르지 않는다

# 운영 대시보드 밖으로 나오면 운영 인증을 버린다 — [운영 대시보드]로 들어갈 때마다 비밀번호를 다시 받는다.
# 서비스 게이트 통과(`service_authed`)와 운영 인증(`ops_authed`)은 같은 비밀번호여도 서로 다른 문이다.
# [나가기]가 아니라 로고 · 뒤로 가기로 나와도 같게 처리한다.
if page.url_path != "ops" and st.session_state.get(state.OPS_AUTHED):
    dialogs.drop_ops_auth()

page.run()
