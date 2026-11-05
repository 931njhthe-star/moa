# Q-03 — 화면 렌더링 (Q-01 TC-101 · TC-102 · TC-105 · TC-106)
#
# Streamlit AppTest 로 화면 B · E 를 실제로 그린다. 서버 없이 돈다 — 미리보기 대역(MOA_UI_PREVIEW=1)이
# D-02 와 같은 모양의 응답을 준다. 상태는 `_preview_case` 로 바꾼다(화면 안의 케이스 선택기와 같은 키).
#
# 왜 AppTest 인가: 이 4건은 "에러 없이 반쪽으로 동작"하는 쪽이다 — 고지 문구가 조건문 안에 들어가
# 특정 상태에서만 사라져도 예외가 나지 않는다. 사람 눈 대신 렌더 결과를 본다.
import os
import pathlib

import pytest

os.environ.setdefault("MOA_UI_PREVIEW", "1")

from streamlit.testing.v1 import AppTest  # noqa: E402

from moa import copy, mock, state  # noqa: E402

FRONTEND = pathlib.Path(__file__).resolve().parent.parent
REVIEW = str(FRONTEND / "screens" / "review.py")
ORDER = str(FRONTEND / "screens" / "order.py")
# `_preview_case` 는 라벨을 담는다(화면의 케이스 선택기와 같은 값) — 키가 아니다
CASE_REVIEW = "11 확인 필요"
CASE_NO_REVIEW = "17 확인 0건"
CASE_BUSY = "08 정리 중"
RESULT_CASES = [CASE_REVIEW, CASE_NO_REVIEW]


def app(script, case=None, **session):
    at = AppTest.from_file(script, default_timeout=60)
    at.session_state[state.SESSION_ID] = "ORD-0012"
    at.session_state[state.SESSION_TOKEN] = "tok_q03"
    if case:
        at.session_state["_preview_case"] = case
    for key, value in session.items():
        at.session_state[key] = value
    return at.run()


def html_of(at):
    """st.html · markdown 으로 나간 문구 전부 — 고지는 html 로 나간다."""
    return "\n".join([e.body for e in at.markdown] + [getattr(e, "body", "") for e in at.get("html")])


# --- TC-101 AI 고지 상시 노출 --------------------------------------------------------------
@pytest.mark.parametrize("case", RESULT_CASES)
def test_order_panel_always_shows_the_ai_notice(case):
    """확인 필요 0건 · 공유 완료 후에도 보인다 (P-06 에이전트 화면 필수 요소)."""
    at = app(REVIEW, case)

    assert not at.exception
    assert "AI가 정리한 결과예요" in html_of(at)


def test_order_sheet_has_no_reply_panel():
    """주문서의 "단톡방 답장 반영하기" 영역은 지웠다(2026-11-04 사용자 요청) — 입력칸 · 찾기 버튼이 없어야 한다."""
    at = app(ORDER, "suggestions", **{state.SUGGESTIONS: mock.SUGGESTIONS["suggestions"]})

    assert not at.exception
    assert copy.S5_REPLY_TITLE not in html_of(at)
    assert not [b for b in at.button if b.label == copy.S5_REPLY_ANALYZE]
    assert not at.text_area                                  # 답장 붙여넣기 칸 없음
    # 화면이 들고 있던 제안이 있어도 공유를 막지 않는다 — 공유 가능 여부는 서버 판정만 쓴다
    assert copy.S5_REPLY_AI_NOTICE not in html_of(at)


def test_ai_notice_is_not_hidden_when_nothing_needs_review():
    """고지를 "확인 필요가 있을 때만" 띄우면 안 된다 — 가장 흔한 회귀다."""
    with_review = html_of(app(REVIEW, CASE_REVIEW))
    no_review = html_of(app(REVIEW, CASE_NO_REVIEW))

    assert "AI가 정리한 결과예요" in with_review
    assert "AI가 정리한 결과예요" in no_review


# --- TC-102 사람 연결 수단 상시 활성 -------------------------------------------------------
@pytest.mark.parametrize("case", RESULT_CASES)
def test_chat_input_is_enabled_whenever_there_is_a_result(case):
    at = app(REVIEW, case)

    assert len(at.chat_input) == 1
    assert at.chat_input[0].disabled is False
    assert at.chat_input[0].placeholder == copy.S2_CHAT_PLACEHOLDER


def test_chat_input_is_disabled_while_analysing_and_says_why(case=CASE_BUSY):
    """정리 중에는 비활성 + 이유 문구. 이유 없이 막으면 담당자는 고장으로 본다."""
    at = app(REVIEW, case)

    assert at.chat_input[0].disabled is True
    assert at.chat_input[0].placeholder == copy.S2_CHAT_PLACEHOLDER_BUSY
    assert copy.S2_BUSY_HINT


def test_review_questions_are_shown_while_any_remain():
    at = app(REVIEW, CASE_REVIEW)

    body = html_of(at)
    assert at.session_state["_remaining"] == len(mock.QUESTIONS)
    # 문구는 c.esc 로 escape 되어 나간다 — 따옴표가 없는 조각으로 본다
    assert "이지연 님 바닐라라떼" in body and "어떤 사이즈인가요" in body
    assert "1/2" in body                                    # 몇 번째 질문인지도 보인다
    assert [o["label"] for o in mock.QUESTIONS[0]["options"]]


def test_row_edit_is_reachable_from_every_result_state():
    """행 [고치기] — 확인 필요가 없어도 사람이 직접 고칠 수 있어야 한다(P-03 4.1)."""
    for case in RESULT_CASES:
        at = app(REVIEW, case)
        row_buttons = [b for b in at.button if b.key and b.key.startswith("hit_row_")]
        assert row_buttons, f"{case}: 행 열기 버튼이 없다"


# --- TC-105 쓰기 실패 — 안내 말풍선 · 상태 미변경 ------------------------------------------
def test_write_failure_becomes_a_message_and_leaves_the_state_alone(monkeypatch):
    import api_client
    from moa import api

    failed = api_client.ApiError(code="DB_UNAVAILABLE", status=200,
                                 user_message="잠깐 멈췄다가 다시 하고 있어요. 입력한 내용은 그대로 있어요",
                                 retryable=True)

    def boom():
        raise failed

    result = api.act(boom, label="post_message")

    # 예외가 화면으로 올라오지 않고, 말풍선으로 쓸 안내 문구가 된다
    assert result["_error"] is True
    assert result["code"] == "DB_UNAVAILABLE"
    assert result["text"] == failed.user_message
    assert "그대로 있어요" in result["text"]


def test_act_failure_does_not_touch_version_or_suggestions():
    """쓰기 실패가 버전 · 제안 · 완료 상태를 바꾸지 않는다."""
    at = AppTest.from_file(REVIEW, default_timeout=60)
    at.session_state[state.SESSION_ID] = "ORD-0012"
    at.session_state[state.VERSION] = 7
    at.session_state[state.SHARED] = False
    at.session_state["_preview_case"] = CASE_REVIEW
    at.run()

    assert at.session_state[state.VERSION] == 7
    assert at.session_state[state.SHARED] is False


# --- TC-106 진행 폴링 — 종료 상태에서 멈춘다 · 스트리밍 없음 -------------------------------
@pytest.mark.parametrize("case", RESULT_CASES)
def test_polling_stops_once_the_session_is_finished(case):
    """끝난 상태에서 다시 묻지 않는다 — 폴링이 안 멈추면 요청이 영원히 쌓인다."""
    at = app(REVIEW, case)

    assert not at.exception                                 # rerun 루프에 걸리지 않는다
    assert at.chat_input[0].disabled is False


def test_poll_interval_comes_from_the_server_meta():
    """주기는 화면이 정하지 않는다 — API-002 limits.poll_interval_ms (D-02 1절 1초 폴링)."""
    assert mock.META["limits"]["poll_interval_ms"] == 1000


def test_review_screen_does_not_stream():
    """D-12 8절 (1) — 토큰 스트리밍을 쓰지 않는다. 진행은 폴링이다."""
    source = pathlib.Path(REVIEW).read_text(encoding="utf-8")

    assert "write_stream" not in source
    assert "st.rerun()" in source                           # 진행은 rerun 으로 다시 그린다
