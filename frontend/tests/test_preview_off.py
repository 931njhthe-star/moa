# 2026-11-04 사용자 보고 — 주문서 공유에서 "이미지는 아직 만들지 못했어요"
#
# 원인: 화면 재시작으로 세션을 잃었는데(session_id=None → 서버 401) 미리보기 모드가 켜져 있어,
# 오류 대신 예시 주문서 · 예시 공유 응답(image_available=False)을 그렸다. 미리보기 기본값을 끄고
# "화면 미리보기 — 고르기" 칸도 지웠다. 미리보기가 꺼져 있으면 세션을 잃었다고 알려야 한다.
import pathlib

from streamlit.testing.v1 import AppTest

from moa import copy, mock, state

SCREENS = pathlib.Path(__file__).resolve().parent.parent / "screens"


def _run(script, monkeypatch, *, preview):
    monkeypatch.setattr(mock, "PREVIEW_ENABLED", preview)
    at = AppTest.from_file(str(SCREENS / script), default_timeout=60)
    at.session_state[state.SESSION_TOKEN] = "tok_lost"      # 토큰은 있는데 세션 번호가 없다 = 새로고침 · 재시작
    return at.run()


def _text(at) -> str:
    return " ".join(str(getattr(e, "value", "") or getattr(e, "body", "")) for e in at.main)


def test_lost_session_says_so_instead_of_showing_example_sheet(monkeypatch):
    for script in ("order.py", "review.py"):
        at = _run(script, monkeypatch, preview=False)
        assert not at.exception
        assert copy.S2_SESSION_LOST in _text(at)
        assert not at.expander                                   # 미리보기 고르기 칸 없음


def test_preview_pickers_are_gone_even_in_preview_mode(monkeypatch):
    for script in ("order.py", "review.py"):
        at = _run(script, monkeypatch, preview=True)
        assert not [e for e in at.expander if "미리보기" in str(e.label)]
