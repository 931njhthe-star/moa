"""근거 메시지 조회 — `원본 보기` · `대화 보기` (API-025).

이벤트 라벨을 함께 준다. 참조 주문은 **남의 메시지까지** 근거에 들어간다 —
`evidence_message_ids` 가 그것을 담고 있다 (D-07 4.4).
"""

from app import db

# P-03 3절 경로 5종 → 화면 라벨. 서버가 문구를 정한다
EVENT_LABEL = {
    "add": "추가",
    "update": "변경",
    "cancel": "취소",
    "confirm": "확정",
    "ignore": "주문 아님",
}


def _label(event_type: str, is_reference: bool) -> str:
    base = EVENT_LABEL.get(event_type, event_type)
    if event_type == "ignore" and is_reference:
        return "주문 아님 · 참고"
    return base


def all_messages(session_id: str) -> dict:
    """넣은 대화 전체 + 이벤트 라벨."""
    rows = db.fetch_all(
        "SELECT m.message_id, m.sender, m.text, m.is_reply, "
        "       e.event_type, e.is_reference "
        "  FROM app.message m "
        "  JOIN app.snapshot s ON s.snapshot_id = m.snapshot_id "
        "  LEFT JOIN app.order_event e ON e.message_id = m.message_id "
        " WHERE s.session_id = %s ORDER BY m.seq",
        (session_id,),
    )
    return {"messages": [_projection(row) for row in rows]}


def for_item(session_id: str, item_id: str) -> dict:
    """항목 1건의 근거 — 그 항목을 만든 이벤트의 evidence_message_ids."""
    rows = db.fetch_all(
        "SELECT m.message_id, m.sender, m.text, m.is_reply, e.event_type, e.is_reference "
        "  FROM app.order_item i "
        "  JOIN app.order_event e ON e.event_id = i.source_event_id "
        "  JOIN app.message m ON m.message_id = ANY(e.evidence_message_ids) "
        " WHERE i.session_id = %s AND i.item_id = %s ORDER BY m.seq",
        (session_id, item_id),
    )
    return {"messages": [_projection(row) for row in rows]}


def for_question(session_id: str, question_id: str) -> dict:
    """질문 1건의 근거 — 질문이 걸린 항목을 거쳐 찾는다."""
    row = db.fetch_one(
        "SELECT item_id FROM app.review_question "
        " WHERE session_id = %s AND question_id = %s", (session_id, question_id))
    if not row:
        return {"messages": []}
    return for_item(session_id, row["item_id"])


def _projection(row: dict) -> dict:
    out = {
        "message_id": row["message_id"],
        "sender": row["sender"],
        "text": row["text"],
        "is_reply": bool(row["is_reply"]),
    }
    if row.get("event_type"):
        out["event"] = {"type": row["event_type"],
                        "label": _label(row["event_type"], bool(row["is_reference"]))}
    return out
