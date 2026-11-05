# 2026-11-05 사용자 보고 10 · 11번 — 실제 DB 로만 볼 수 있는 것 (MOA_LIVE_DB=1)
#
#   MOA_LIVE_DB=1 ../.venv/Scripts/python.exe -m pytest -q tests/test_user_fixes_1105_live.py
#
# 10번(질문 큐 구멍)과 11번(답장 반영)은 질문 테이블 · 제안 테이블 · 항목 상태가 **함께** 맞물려야
# 드러난다 — 가짜 저장소로는 "응답 200 인데 큐가 비어 있음"을 재현할 수 없다.
import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.getenv("MOA_LIVE_DB") != "1",
                                reason="MOA_LIVE_DB=1 일 때만 실제 DB 로 돈다")

CHAT = [
    "[이지연] 저는 따뜻한 카페라떼 하나 부탁드려요~",
    "[최유나] 저는 헤이즐넛 라떼 하나 주세요",      # 메뉴판에 없는 수식어 → 확인 필요로 남는다
    "스타벅스로 갈 예정이야",
]


@pytest.fixture
def live():
    from app import db
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    made = []
    yield client, made
    for session_id in made:
        db.execute("DELETE FROM app.order_session WHERE session_id = %s", (session_id,))


def _ok(res, status=200):
    body = res.json()
    assert res.status_code == status, body
    assert "error" not in body, body
    return body["data"]


def _start(client, made, lines):
    marker = f"live-1105 {uuid.uuid4().hex}"
    body = lines[:-1] + [marker, lines[-1]] if not lines[-1].startswith("[") else lines + [marker]
    data = _ok(client.post("/api/sessions", json={"raw_text": "\n".join(body), "source": "paste"}), 202)
    made.append(data["session_id"])
    # 분석은 TestClient 가 응답 직후 BackgroundTasks 로 **이미 돌렸다** — 여기서 다시 부르면
    # 같은 이벤트를 두 번 넣어 order_event 기본키가 충돌한다(2026-11-05 작성 중 확인)
    return data["session_id"], {"X-Session-Token": data["session_token"]}


# --- 10번 질문 큐가 비면 확인 필요도 0 이어야 한다 ---------------------------------------------
def test_10_queue_and_review_count_mean_the_same_thing(live):
    client, made = live
    session_id, token = _start(client, made, CHAT)

    progress = _ok(client.get(f"/api/sessions/{session_id}/progress", headers=token))
    assert progress["review_count"] >= 1, progress
    queue = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))
    assert queue["remaining"] == progress["review_count"], (queue, progress)


def test_10_missing_questions_are_refilled(live):
    """질문이 사라진 확인 필요 항목에도 질문이 다시 생긴다 — 주문서에서 막히지 않게."""
    from app import db

    client, made = live
    session_id, token = _start(client, made, CHAT)
    db.execute("UPDATE app.review_question SET status = 'voided' WHERE session_id = %s", (session_id,))
    assert db.fetch_one("SELECT COUNT(*) AS n FROM app.review_question "
                        " WHERE session_id = %s AND status = 'open'", (session_id,))["n"] == 0

    # 조회(API-020)가 빈 큐를 메운다

    queue = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))
    review_count = _ok(client.get(f"/api/sessions/{session_id}/progress", headers=token))["review_count"]
    assert queue["question"] is not None, queue
    assert queue["remaining"] == review_count, (queue, review_count)


def test_10_order_sheet_is_not_blocked_once_the_queue_is_empty(live):
    """질문을 다 답하면 주문서가 공유 가능해진다 — "확인이 필요한 주문이 N건" 이 주문서에서 처음 보이지 않게."""
    client, made = live
    session_id, token = _start(client, made, CHAT)

    for _ in range(10):
        queue = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))
        question = queue.get("question")
        if not question:
            break
        options = question.get("options") or []
        answer = options[0]["value"] if options else "카페 라떼"
        res = client.post(
            f"/api/sessions/{session_id}/questions/{question['question_id']}/answer",
            json={"answer": answer}, headers=token)
        assert res.status_code == 200, res.json()

    sheet = _ok(client.get(f"/api/sessions/{session_id}/order-sheet", headers=token))
    assert sheet["can_share"] is True, sheet.get("blocked_reason_text")


# --- 11번 답장 반영 — 분명한 변경은 바로 반영, 불분명한 것은 질문으로 ---------------------------
def test_11_reply_applies_a_clear_change(live):
    client, made = live
    session_id, token = _start(client, made, ["[이지연] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    before = _ok(client.get(f"/api/sessions/{session_id}", headers=token))["rows"]
    assert [r["menu_text"] for r in before] == ["카페 라떼"], before

    data = _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                           json={"raw_text": "[이지연] 그란데로 바꿔주세요", "apply": True},
                           headers=token))
    assert data["applied_count"] == 1, data
    rows = _ok(client.get(f"/api/sessions/{session_id}", headers=token))["rows"]
    sizes = [o["value"] for r in rows for o in r["options"] if o["label"] == "사이즈"]
    assert sizes == ["그란데"], rows


def test_11_reply_without_apply_still_changes_nothing(live):
    """기본값은 예전 그대로 — 분석만으로 주문이 바뀌지 않는다 (FR-007)."""
    client, made = live
    session_id, token = _start(client, made, ["[이지연] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                    json={"raw_text": "[이지연] 그란데로 바꿔주세요"}, headers=token))
    rows = _ok(client.get(f"/api/sessions/{session_id}", headers=token))["rows"]
    sizes = [o["value"] for r in rows for o in r["options"] if o["label"] == "사이즈"]
    assert sizes == ["톨"], rows


def test_11_unclear_reply_becomes_a_question(live):
    """무엇으로 바꾸는지 불분명한 답장은 반영하지 않고 확인 질문으로 올린다."""
    client, made = live
    session_id, token = _start(client, made, ["[이지연] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    data = _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                           json={"raw_text": "[이지연] 아 그거 좀 바꿔주세요", "apply": True},
                           headers=token))
    assert data["applied_count"] == 0, data
    assert data["asked_count"] >= 1, data
    queue = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))
    assert queue["question"] is not None
    sheet = _ok(client.get(f"/api/sessions/{session_id}/order-sheet", headers=token))
    assert sheet["can_share"] is False      # 확인이 끝나기 전에는 공유하지 않는다


def test_11_change_request_is_never_silently_dropped(live):
    """"그냥 좀 바꿔주세요" — 무엇으로 바꿀지 모르는 답장도 제안 · 질문으로 남는다(조용히 사라지지 않는다)."""
    client, made = live
    session_id, token = _start(client, made, ["[이지연] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    data = _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                           json={"raw_text": "[이지연] 저는 그냥 좀 바꿔주세요", "apply": True},
                           headers=token))
    assert data["asked_count"] >= 1, data
    assert "확인할 것" in data["found_text"], data


def test_11_question_from_a_reply_quotes_what_was_said(live):
    """답장에서 올라온 질문은 **그 답장을 인용한다** — "어느 것을 말하는지"만 보면 답할 수 없다."""
    client, made = live
    session_id, token = _start(client, made, ["[이지연] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                    json={"raw_text": "[이지연] 저는 그냥 좀 바꿔주세요", "apply": True}, headers=token))
    question = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))["question"]
    assert "그냥 좀 바꿔주세요" in question["text"], question["text"]
    assert question["allow_other_menu"] is True                     # 메뉴를 고를 수 있다
    assert [o["label"] for o in question["options"]] == ["그대로 둘게요"]
