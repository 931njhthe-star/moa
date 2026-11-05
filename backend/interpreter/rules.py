"""규칙 원천 — 업무 층 규칙 해석(app.services.intake)을 DEP-001 계약 모양으로 옮긴다.

모의 서비스의 정상 응답이다. LLM 을 부르지 않으므로 **같은 입력에 같은 결과**가 나온다
(D-02 6.1 "고정 응답이 먼저" · NFR-006). 계약은 app.contracts.OrderEvents 다.
"""

from app.services import intake
from app.services.sessions import SIZE_WORD


def extract_events(messages: list[dict], context: dict) -> dict:
    prepared = [{"message_id": m["message_id"], "seq": m.get("order") or index,
                 "sender": m.get("sender", ""), "text": m.get("text", "")}
                for index, m in enumerate(messages, start=1)]
    events = intake.extract_events(prepared, brand_id=context.get("brand_id", "generic"),
                                   menu_version=context.get("menu_version", ""))
    return {"events": [_event(e) for e in events]}


def _event(event: dict) -> dict:
    return {
        "message_id": event["message_id"],
        "evidence_message_ids": list(event["evidence_message_ids"]),
        "target_message_id": None,      # 규칙은 대상을 메시지가 아니라 메뉴 표현으로 찾는다(target_hint)
        "reason": "규칙 해석",
        "event_type": event["event_type"],
        "person": event.get("person"),
        "person_unclear": False,
        "target_unclear": False,
        "is_reference": bool(event.get("is_reference")),
        "items": [_item(i) for i in event.get("items", [])],
    }


def _item(item: dict) -> dict:
    options = dict(item.get("options") or {})
    ambiguous = item.get("ambiguous_options") or {}
    size = options.pop("size", None)
    size_text = (ambiguous.get("size") or "").strip('"') or (SIZE_WORD.get(size) if size else None)
    temperature = (ambiguous.get("temperature") or "").strip('"') or None
    return {
        "menu_text": item.get("match_text") or item.get("menu_text") or "",
        "temperature_text": temperature,
        "size_text": size_text,
        "quantity": int(item.get("quantity") or 1),
        "option_texts": [f"{group}={value}" for group, value in options.items()],
        "custom_request": item.get("custom_request"),
    }
