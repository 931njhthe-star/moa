# 서비스 진입 게이트 (2026-11-05 사용자 요청) — app.py 가 어느 화면보다 먼저 비밀번호를 받는다
import os
import pathlib

os.environ.setdefault("MOA_UI_PREVIEW", "1")

from streamlit.testing.v1 import AppTest  # noqa: E402

from moa import copy, state  # noqa: E402

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")


def _texts(at):
    return "\n".join([e.body for e in at.markdown] + [getattr(e, "body", "") for e in at.get("html")])


def test_gate_blocks_until_password():
    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception
    assert copy.G0_PROMPT in _texts(at)
    assert len(at.text_input) == 1
    assert not at.session_state[state.SERVICE_AUTHED]


def test_gate_empty_password_shows_error():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button[0].click().run()

    assert copy.O0_ERROR_FALLBACK in _texts(at)
    assert not at.session_state[state.SERVICE_AUTHED]


def test_gate_passes_when_authed():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state[state.SERVICE_AUTHED] = True
    at.run()

    assert not at.exception
    assert copy.G0_PROMPT not in _texts(at)


def test_ops_asks_again_after_leaving_dashboard():
    """운영 인증을 가진 채 담당자 화면으로 나오면 버린다 — 다음 [운영 대시보드]에서 다시 묻는다."""
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state[state.SERVICE_AUTHED] = True
    at.session_state[state.OPS_AUTHED] = True
    at.session_state[state.OPS_TOKEN] = "preview-ops-token"
    at.run()   # 기본 페이지 `/` — 운영 화면 밖

    assert not at.session_state[state.OPS_AUTHED]
    assert at.session_state[state.OPS_TOKEN] is None
    assert at.session_state[state.SERVICE_AUTHED]   # 서비스 게이트 통과는 그대로

    [b for b in at.button if (b.key or "").startswith("ops_entry")][0].click().run()
    assert len(at.text_input) == 1   # O-0 비밀번호 칸
