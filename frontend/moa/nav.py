# 페이지 등록과 이동 — URL은 P-06 화면 목록을 따른다
#
#   /          SCR-001  A. 주문 시작 (대화 입력)  <- 기본 페이지. url_path를 주지 않는다
#   /s         SCR-002  B. 주문 정리        -> 관리 토큰은 쿼리 파라미터 `?s=`
#   /s/order   SCR-005  E. 주문서
#   /ops       SCR-006  O. 운영 대시보드
#
# P-06 Streamlit 구현 대응: "페이지 분리 + 세션 관리 토큰은 쿼리 파라미터(`?s=`)".
# 토큰을 경로에 넣지 않는 이유는 D-02 1.1 — 액세스 로그 · 리퍼러에 원문이 남는다.
# `/confirm` 페이지는 없다(v3.0 — 확정 단계 삭제).
import pathlib

import streamlit as st

# 상대 경로("screens/start.py")는 **실행 중인 메인 스크립트 기준**으로 풀린다.
# app.py 로 띄우면 맞지만, 화면 파일을 직접 실행하는 AppTest(screens/review.py)에서는
# screens/screens/start.py 가 되어 페이지 생성이 실패한다 — 이 파일 위치 기준 절대 경로로 둔다.
_SCREENS = pathlib.Path(__file__).resolve().parent.parent / "screens"

_PAGES: dict | None = None


def pages() -> dict:
    """한 번만 만들어 두고 재사용한다. `st.switch_page`가 같은 객체를 받아야 한다."""
    global _PAGES
    if _PAGES is None:
        _PAGES = {
            # 기본 페이지에 url_path를 주면 그 경로가 404가 된다 — 기본 페이지는 `/`로만 열린다
            "start": st.Page(_SCREENS / "start.py", title="주문 시작", default=True),
            "review": st.Page(_SCREENS / "review.py", title="주문 정리", url_path="s"),
            "order": st.Page(_SCREENS / "order.py", title="주문서", url_path="order"),
            "ops": st.Page(_SCREENS / "ops.py", title="운영 대시보드", url_path="ops"),
        }
    return _PAGES


def go(name: str) -> None:
    """화면 이동. 넣은 대화 · 정리 결과는 session_state에 남으므로 사라지지 않는다(U-9)."""
    st.switch_page(pages()[name])
