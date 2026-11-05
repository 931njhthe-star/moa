# 2026-11-05 2차 보고 6 · 7번 — 질문 답 반영 · 채팅 수정 (MOA_LIVE_DB=1)
import os
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(os.getenv("MOA_LIVE_DB") != "1",
                                reason="MOA_LIVE_DB=1 일 때만 실제 DB 로 돈다")


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
    marker = f"live-1105b {uuid.uuid4().hex}"
    body = lines[:-1] + [marker, lines[-1]] if not lines[-1].startswith("[") else lines + [marker]
    data = _ok(client.post("/api/sessions", json={"raw_text": "\n".join(body), "source": "paste"}), 202)
    made.append(data["session_id"])
    return data["session_id"], {"X-Session-Token": data["session_token"]}


def _rows(client, session_id, token):
    return _ok(client.get(f"/api/sessions/{session_id}", headers=token))["rows"]


def _size_of(row):
    return next((o["value"] for o in row["options"] if o["label"] == "사이즈"), None)


BIG = ["[박서연 과장] 저는 따뜻한 카페라떼 큰 거로 주세요", "스타벅스로 갈 예정이야"]


# --- 6번 사이즈 ------------------------------------------------------------------------------
def test_06_plain_order_is_not_asked_about_size(live):
    client, made = live
    session_id, token = _start(client, made, ["[박서연 과장] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    assert _ok(client.get(f"/api/sessions/{session_id}/progress", headers=token))["review_count"] == 0
    assert _size_of(_rows(client, session_id, token)[0]) == "톨"


def test_06_size_button_is_applied(live):
    """사이즈 버튼을 누르면 그 사이즈로 반영된다 — "반영하지 못했어요"가 뜨지 않는다."""
    client, made = live
    session_id, token = _start(client, made, BIG)
    question = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))["question"]
    assert "사이즈" in question["text"], question["text"]
    labels = [o["label"] for o in question["options"]]
    assert labels, question

    for label, value in [(o["label"], o["value"]) for o in question["options"]]:
        pass
    pick = question["options"][-1]          # 마지막 버튼(벤티)로 눌러 본다
    res = client.post(f"/api/sessions/{session_id}/questions/{question['question_id']}/answer",
                      json={"answer": pick["value"]}, headers=token)
    assert res.status_code == 200, res.json()
    assert _size_of(_rows(client, session_id, token)[0]) == pick["label"]


def test_06_size_by_chat_is_applied(live):
    """채팅으로 "톨로 처리해줘" 라고 해도 그 질문의 답으로 읽힌다."""
    client, made = live
    session_id, token = _start(client, made, BIG)
    question = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))["question"]
    res = client.post(f"/api/sessions/{session_id}/questions/{question['question_id']}/answer",
                      json={"text": "톨로 처리해줘"}, headers=token)
    assert res.status_code == 200, res.json()
    assert _size_of(_rows(client, session_id, token)[0]) == "톨"


# --- 7번 채팅으로 빼기 -------------------------------------------------------------------------
@pytest.mark.parametrize("said", ["박서연 과장님은 제외", "박서연 과장 빼줘", "박서연 과장님 주문 취소해줘"])
def test_07_removing_a_person_by_chat(live, said):
    client, made = live
    session_id, token = _start(client, made, ["[박서연 과장] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "[김민수 대리] 저는 아이스 아메리카노 톨 하나요",
                                              "스타벅스로 갈 예정이야"])
    assert len(_rows(client, session_id, token)) == 2
    data = _ok(client.post(f"/api/sessions/{session_id}/messages", json={"text": said}, headers=token))
    assert data["kind"] == "applied", data
    people = [r["person"] for r in _rows(client, session_id, token)]
    assert people == ["김민수 대리"], (people, data)


# --- 3차 보고 7번 — 질문으로 올린 제안이 공유를 영원히 막지 않는다 ------------------------------
def test_promoted_suggestion_does_not_block_sharing_forever(live):
    client, made = live
    session_id, token = _start(client, made, ["[이지연 사원] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "[김민수 대리] 저는 아이스 아메리카노 톨 하나요",
                                              "스타벅스로 갈 예정이야"])
    data = _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                           json={"raw_text": "[이지연 사원] 저 그냥 좀 바꿔주세요", "apply": True},
                           headers=token))
    assert data["asked_count"] == 1, data

    # 진행 상태가 "정하지 않은 답장"을 알린다 — 화면이 이것으로 주문서 이동을 막는다
    progress = _ok(client.get(f"/api/sessions/{session_id}/progress", headers=token))
    assert progress["pending_suggestions"] == 0, progress   # 질문으로 올린 것은 질문 큐가 맡는다

    question = _ok(client.get(f"/api/sessions/{session_id}/questions", headers=token))["question"]
    res = client.post(f"/api/sessions/{session_id}/questions/{question['question_id']}/answer",
                      json={"answer": question["options"][0]["value"]}, headers=token)
    assert res.status_code == 200, res.json()

    sheet = _ok(client.get(f"/api/sessions/{session_id}/order-sheet", headers=token))
    assert sheet["can_share"] is True, sheet.get("blocked_reason_text")


def test_reply_returns_what_changed_for_the_chat(live):
    """반영한 변경을 문장으로 돌려준다 — 화면이 채팅에 남긴다(3차 보고 6번)."""
    client, made = live
    session_id, token = _start(client, made, ["[이지연 사원] 저는 따뜻한 카페라떼 하나 부탁드려요~",
                                              "스타벅스로 갈 예정이야"])
    data = _ok(client.post(f"/api/sessions/{session_id}/replies/analyze",
                           json={"raw_text": "[이지연 사원] 저 그란데로 바꿔주세요", "apply": True},
                           headers=token))
    assert len(data["applied"]) == 1
    text = data["applied"][0]["text"]
    assert "이지연 사원" in text and "그란데" in text, text
    assert data["applied"][0]["undo_token"]
    assert data["changed_item_ids"], data
