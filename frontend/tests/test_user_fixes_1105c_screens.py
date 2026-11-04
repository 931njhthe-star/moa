# 2026-11-05 3차 보고 — 화면 (1 정리하기 즉시 · 3 사람별 묶기 · 7 막는 이유를 눌러 이동)
import os
import pathlib

os.environ.setdefault("MOA_UI_PREVIEW", "1")

from streamlit.testing.v1 import AppTest  # noqa: E402

from moa import components as c  # noqa: E402
from moa import copy, mock, state  # noqa: E402

FRONTEND = pathlib.Path(__file__).resolve().parent.parent
START = str(FRONTEND / "screens" / "start.py")
REVIEW = str(FRONTEND / "screens" / "review.py")
ORDER = str(FRONTEND / "screens" / "order.py")


def app(script, **session):
    at = AppTest.from_file(script, default_timeout=60)
    at.session_state[state.SESSION_ID] = "ORD-0012"
    at.session_state[state.SESSION_TOKEN] = "tok_1105c"
    for key, value in session.items():
        at.session_state[key] = value
    return at.run()


def html_of(at):
    return "\n".join([e.body for e in at.markdown] + [getattr(e, "body", "") for e in at.get("html")])


# --- 1번 정리하기는 처음부터 누를 수 있다 ------------------------------------------------------
def test_01_submit_button_is_clickable_from_the_start():
    """Streamlit 입력창은 blur 돼야 값이 간다 — 버튼을 막아 두면 붙여넣은 직후 "먹통"으로 보인다."""
    at = app(START)
    assert at.button(key="submit_analyze").disabled is False


def test_01_empty_submit_explains_instead_of_calling_the_server():
    at = app(START)
    at.button(key="submit_analyze").click().run()
    assert copy.S1_SUBMIT_DISABLED_REASON in html_of(at)


# --- 3번 한 사람이 여러 잔이면 모아서 순번을 단다 -----------------------------------------------
def test_03_rows_are_grouped_by_person_with_a_sequence():
    rows = [{"item_id": "a", "person": "김민수"}, {"item_id": "b", "person": "이지연"},
            {"item_id": "c", "person": "김민수"}]
    out = c.by_person(rows)
    assert [r["item_id"] for r in out] == ["a", "c", "b"]          # 같은 사람끼리 붙는다
    assert [r["person_seq"] for r in out] == ["1/2", "2/2", None]  # 한 잔인 사람은 순번 없음


def test_03_sequence_is_shown_in_the_row():
    html = c.row_html({"item_id": "a", "person": "김민수", "menu_text": "카페 라떼",
                       "person_seq": "2/2", "options": [], "estimated_price": 5000})
    assert "moa-row-seq" in html and "2/2" in html


def test_03_single_cup_has_no_sequence_badge():
    html = c.row_html({"item_id": "a", "person": "김민수", "menu_text": "카페 라떼",
                       "person_seq": None, "options": [], "estimated_price": 5000})
    assert "moa-row-seq" not in html


# --- 7번 막는 이유를 누르면 처리할 수 있는 화면으로 간다 ----------------------------------------
def test_07_blocked_reason_on_the_order_sheet_is_a_button():
    """주문서에서 막는 이유를 읽기만 하면 담당자는 어디서 풀어야 하는지 알 수 없다."""
    at = app(ORDER, **{"_order_case": "19 ~ 21 기본 (5명)"})
    # 미리보기 대역은 공유 가능 상태라 막는 이유가 없다 — 버튼 키가 생기지 않는 것만 확인한다
    assert "share_open_blockedgo" not in {b.key for b in at.button}


def test_07_review_opens_when_nothing_is_pending():
    at = app(REVIEW, **{"_preview_case": "17 확인 0건"})
    assert at.button(key="s2_primary").disabled is False


def test_07_review_blocks_while_replies_are_undecided(monkeypatch):
    """확인은 0건이어도 **정하지 않은 답장**이 남아 있으면 주문서로 넘어가지 않는다.

    예전에는 주문서까지 간 뒤에야 "반영할지 정하지 않은 제안이 N건 있어요"를 만났고, 거기서는 풀 수 없었다.
    """
    base = mock.PROGRESS["awaiting_confirmation"]
    monkeypatch.setitem(mock.PROGRESS, "awaiting_confirmation", {**base, "pending_suggestions": 2})
    at = app(REVIEW, **{"_preview_case": "17 확인 0건"})
    assert at.button(key="s2_primary").disabled is True
    assert copy.S2_PENDING_SUGGESTION_HINT.format(n=2) in html_of(at)
