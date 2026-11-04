"""확인 질문 — AI 가 임의 확정하지 않고 담당자에게 넘기는 자리 (NEEDS_REVIEW).

한 번에 하나만 묻는 것은 **조회 규칙**이다. 테이블은 전부 가지고 있고
답한 질문도 지우지 않는다 — 대화 흐름에 남아야 한다 (D-07 4.6 · P-06).

후보에 `reason_tags` 가 반드시 붙는다 — 없으면 FR-004("정렬 근거 태그를 함께 표시")가
화면까지 오지 않는다. 추천을 암시하는 필드(`recommended` 등)는 두지 않는다.
"""

from app import db, ids
from app.services import menu as menu_service

# 사유별 질문 문구 — 서버가 완성형으로 만든다 (화면이 조립하지 않는다)
_TEMPLATES = {
    "ambiguous_spec": '{person} 님 {menu}는 어떤 사이즈인가요?',
    "trait_expression": '{person} 님이 말한 표현에 맞는 메뉴를 골라 주세요',
    # `{source}` 가 조사까지 들고 온다(`_source_clause`) — 받침에 따라 "로 / 으로"가 갈린다
    "reference_menu": '{person} 님 {quote}는 {source} 이해했어요. 메뉴를 골라 주세요',
    "unregistered_menu": '{person} 님 {quote}는 메뉴판에서 찾지 못했어요. 메뉴를 골라 주세요',
    "ambiguous_target": '{person} 님 주문 중 어느 것을 말하는지 골라 주세요',
    # 변경 · 취소 문장이 이 주문을 가리키는지 묻는다 — 질문은 항목마다 하나라서 "어느 것"이 아니라 "이것이 맞나요"다
    "ambiguous_target_change": '{person} 님 "{change}"는 {menu} 주문을 말하는 건가요?',
    # 대리 주문 — 후보가 하나면 "맞나요?", 둘 이상이면 "누구 주문인가요?" (2026-11-04 · INT-002)
    "ambiguous_person": '"{said}" 님의 {menu} 주문이에요. {candidate} 님 주문이 맞나요?',
}
_PERSON_MANY = '"{said}" 님의 {menu} 주문이에요. 누구 주문인가요?'

# ambiguous_target 버튼 값 — 메뉴 이름이 아닌 답은 이 둘뿐이다(edits._apply_answer)
TARGET_APPLY = "apply_change"
TARGET_KEEP = "keep"

# `ambiguous_spec` 안에서 무엇이 모호한가 — 사유 문자열(P-03 2.2 · DB CHECK · Q-02)은 그대로 두고
# 질문 문구와 버튼만 나눈다. 순서가 규칙이다: 온도가 메뉴를 정하고, 메뉴가 정해져야 사이즈 버튼이 뜬다
SPEC_ORDER = ("temperature", "size", "quantity")
_SPEC_TEMPLATES = {
    "temperature": '{person} 님 {quote}는 따뜻한 것과 아이스 중 어느 쪽인가요?',
    "size": '{person} 님 {menu}는 어떤 사이즈인가요?',
    "quantity": '{person} 님 {menu} 수량이 {raw}로 적혀 있어요. 몇 잔인가요?',
}


def spec_key(ambiguous: dict | None) -> str | None:
    """지금 물을 사양 하나. 없으면 None."""
    for key in SPEC_ORDER:
        if (ambiguous or {}).get(key):
            return key
    return None


def _quantity_choices(raw: str) -> list[dict]:
    """수량 후보 — 적힌 값이 양수면 그 값을 먼저, 그다음 1 · 2잔."""
    digits = "".join(ch for ch in raw if ch.isdigit() or ch == "-")
    try:
        said = int(digits)
    except ValueError:
        said = 0
    values = ([said] if said > 0 else []) + [n for n in (1, 2, 3) if n != said]
    return [{"value": str(n), "label": f"{n}잔", "reason_tags": []} for n in values[:3]]


_APPLIED = {
    "ambiguous_spec": "{person} 님 {menu}를 {{answer}}로 했어요.",
    "trait_expression": "{person} 님 주문을 {{answer}}로 했어요.",
    "reference_menu": "{person} 님 주문을 {{answer}}로 했어요.",
    "unregistered_menu": "{person} 님 주문을 {{answer}}로 했어요.",
    "ambiguous_target": "{person} 님 주문을 {{answer}}로 했어요.",
    "ambiguous_person": "{{answer}} 님 주문으로 정했어요.",
}


def build(item: dict, *, session_id: str, brand_id: str, menu_version: str, seq: int,
          source_text: str | None = None, change_text: str | None = None) -> dict:
    """확인 필요 항목 1건 → 질문 1건. DB 행으로 넣을 수 있는 모양이다.

    change_text — 대상이 모호한 변경 · 취소 문장 원문(ambiguous_target). 있으면 "이 주문이 맞나요"로 묻고
    [네, 바꿔 주세요]가 그 문장을 이 항목에 반영한다(edits._apply_answer).
    """
    reason = item.get("review_reason") or "ambiguous_spec"
    person = item["person"]
    menu_name = item.get("menu_name") or item.get("menu_text") or "주문"
    quote = f'"{item.get("menu_text")}"' if item.get("menu_text") else "주문"

    options, sort_basis = _options(item, brand_id=brand_id, menu_version=menu_version,
                                   reason=reason, change_text=change_text)
    template = _TEMPLATES[reason]
    key = spec_key(item.get("ambiguous_options")) if reason == "ambiguous_spec" else None
    if key:
        template = _SPEC_TEMPLATES[key]
    change = _head(change_text)
    if reason == "ambiguous_target" and change:
        template = _TEMPLATES["ambiguous_target_change"]
        # 같은 메뉴 두 잔이 후보일 때 질문이 똑같아지지 않게 옵션을 붙인다 — "아이스 아메리카노(톨 · 샷 추가)"
        labels = [menu_service.option_label(brand_id, menu_version, g, v)
                  for g, v in (item.get("options") or {}).items()]
        if labels:
            menu_name = f"{menu_name}({' · '.join(labels)})"
    check = item.get("person_check") or {}
    candidates = check.get("candidates") or []
    if reason == "ambiguous_person" and len(candidates) != 1:
        template = _PERSON_MANY
    text = template.format(person=person, menu=menu_name, quote=quote,
                           said=check.get("said") or person, candidate=(candidates or [""])[0],
                           raw=(item.get("ambiguous_options") or {}).get(key, ""),
                           source=_source_clause(source_text), change=change)
    return {
        "question_id": ids.question_id(session_id, seq),
        "item_id": item["item_id"],
        "seq": seq,
        "reason": reason,
        "question_text": text,
        "options": options,
        "sort_basis": sort_basis,
        "applied_text_template": _APPLIED[reason].format(person=person, menu=menu_name),
    }


def _with_ro(word: str) -> str:
    """`로` 와 `으로` 를 받침으로 가른다 — "2잔로"처럼 틀린 조사가 질문에 나가지 않게.

    판정은 **인용부호 안의 마지막 글자**로 한다(한국어 표기 관례). 한글 음절이 아니면 `로`.
    """
    last = word.strip().rstrip('"\'').strip()[-1:] if word.strip() else ""
    if last and "가" <= last <= "힣":
        has_final = (ord(last) - 0xAC00) % 28 != 0
        return f"{word}으로" if has_final else f"{word}로"
    return f"{word}로"


def _head(text: str | None) -> str:
    """원문의 첫 구절 — 질문에 문장을 통째로 넣지 않는다(_source_clause 와 같은 규칙)."""
    if not (text or "").strip():
        return ""
    head = text.strip().splitlines()[0]
    for separator in (",", ".", "!", "?"):
        head = head.split(separator)[0]
    return head.strip() or text.strip()


def _source_clause(source_text: str | None) -> str:
    """참조 근거를 **짧게** 인용하고 조사까지 붙인다.

    근거 메시지 원문을 통째로 넣으면 질문이 읽히지 않는다 — 예: 정하준 "나도 민수랑 같은
    걸로"는 "아이스 아메리카노 톨 2잔, 하나는 샷 추가요."로 이해했어요(2026-11-03 확인).
    **첫 구절만** 인용한다. 메뉴 표현만 떼어 내면("아이스 아메리카노 , 하나 요") 조사
    찌꺼기가 남아, 사람이 쓴 말의 앞부분을 그대로 보여 주는 쪽이 읽기 쉽고 근거로도 정확하다.
    """
    if not source_text:
        return "앞선 대화로"
    head = source_text.strip().splitlines()[0]
    for separator in (",", ".", "!", "?"):
        head = head.split(separator)[0]
    return _with_ro(f'"{head.strip() or source_text.strip()}"')


def _options(item: dict, *, brand_id: str, menu_version: str, reason: str,
             change_text: str | None = None):
    """후보와 정렬 근거. 모든 후보에 reason_tags 를 붙인다."""
    if reason == "ambiguous_target" and item.get("menu_id"):
        # 버튼이 하나도 없는 질문을 만들지 않는다 — 예전에는 메뉴 후보(candidates)만 봐서, 메뉴가 정해진 행이면
        # 후보가 비고 [다른 메뉴 찾기]도 막혀 답할 길이 없었다(2026-11-04 사용자 보고 2번).
        # [네] 는 변경 문장을 이 항목에 반영하고, [아니에요] 는 그대로 둔다. 다른 메뉴는 메뉴 찾기 · 채팅으로 고른다
        keep = {"value": TARGET_KEEP, "label": "아니에요, 그대로 둘게요", "reason_tags": []}
        if _head(change_text):
            return [{"value": TARGET_APPLY, "label": "네, 바꿔 주세요", "reason_tags": [],
                     "change_text": change_text}, keep], "reference_message"
        return [{**keep, "label": "네, 이대로 둘게요"}], "reference_message"
    if reason == "ambiguous_person":
        # 버튼 값은 주문자 이름 그대로다 — 고른 이름이 주문자 칸에 들어간다(edits._apply_answer).
        # 마지막 버튼은 "아니에요" — 대화에 적힌 표현 그대로 두고 확인만 끝낸다(대화에 없는 사람일 수 있다)
        check = item.get("person_check") or {}
        said = check.get("said") or item["person"]
        many = len(check.get("candidates") or []) > 1
        picks = [{"value": name, "label": f"{name} 님" if many else f"{name} 님 맞아요", "reason_tags": []}
                 for name in check.get("candidates") or []]
        return picks + [{"value": said, "label": f"아니에요, \"{said}\" 그대로 둘게요", "reason_tags": []}], None
    key = spec_key(item.get("ambiguous_options")) if reason == "ambiguous_spec" else None
    if key == "temperature":
        candidates = item.get("temperature_candidates") or []
        return ([{"value": c["name"], "label": c["name"],
                  "reason_tags": c.get("trait_tags", [])} for c in candidates], "alias_score")
    if key == "quantity":
        return _quantity_choices(item["ambiguous_options"]["quantity"]), "alias_score"

    if reason == "ambiguous_spec" and item.get("menu_id"):
        groups = menu_service.option_groups(brand_id, menu_version, item["menu_id"])
        sizes = next((g["values"] for g in groups if g["option_group"] == "size"), [])
        return ([{"value": o["option_value"], "label": o["value_label"], "reason_tags": []}
                 for o in sizes], "alias_score")

    if reason == "trait_expression" and item.get("candidates_by") == "menu_agent" and item.get("candidates"):
        # Menu Agent 가 툴(find_menu_by_traits · search_menu)로 고른 후보 — 순서가 에이전트의 판단이다
        return ([{"value": c["name"], "label": c["name"], "reason_tags": c.get("trait_tags", [])}
                 for c in item["candidates"][:5]], "trait_tags")
    if reason == "trait_expression" and item.get("traits"):
        candidates = menu_service.by_traits(brand_id, menu_version, item["traits"])
        return ([{"value": c["name"], "label": c["name"], "reason_tags": c["reason_tags"]}
                 for c in candidates[:5]], "trait_tags")

    if reason == "reference_menu":
        candidates = item.get("candidates") or []
        return ([{"value": c["name"], "label": c["name"],
                  "reason_tags": c.get("trait_tags", [])} for c in candidates[:5]],
                "reference_message")

    # unregistered_menu · ambiguous_target — 매칭 후보가 있으면 쓰고, 없으면 메뉴 찾기로 보낸다
    candidates = item.get("candidates") or []
    return ([{"value": c["name"], "label": c["name"], "reason_tags": c.get("trait_tags", [])}
             for c in candidates[:5]], "alias_score")


def insert(session_id: str, questions: list[dict], *, cur=None) -> None:
    import json

    if not questions:
        return
    sql = (
        "INSERT INTO app.review_question "
        "  (question_id, session_id, item_id, seq, reason, question_text, options, sort_basis) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (question_id) DO NOTHING"
    )
    params = [(q["question_id"], session_id, q["item_id"], q["seq"], q["reason"],
               q["question_text"], json.dumps(q["options"], ensure_ascii=False), q["sort_basis"])
              for q in questions]
    if cur is not None:
        cur.executemany(sql, params)
        return
    with db.cursor() as own:
        own.executemany(sql, params)


def next_open(session_id: str) -> dict | None:
    """다음 질문 1건 — 한 번에 하나다 (D-07 4.6 조회 규칙)."""
    return db.fetch_one(
        "SELECT question_id, item_id, seq, reason, question_text, options, sort_basis "
        "  FROM app.review_question "
        " WHERE session_id = %s AND status = 'open' "
        " ORDER BY seq LIMIT 1",
        (session_id,),
    )


def counts(session_id: str) -> dict:
    row = db.fetch_one(
        "SELECT COUNT(*) FILTER (WHERE status = 'open')     AS remaining, "
        "       COUNT(*) FILTER (WHERE status <> 'voided')  AS total, "
        "       COUNT(*) FILTER (WHERE status = 'answered') AS answered "
        "  FROM app.review_question WHERE session_id = %s",
        (session_id,),
    )
    return {"remaining": int(row["remaining"]), "total": int(row["total"]),
            "answered": int(row["answered"])}


def projection(session_id: str) -> dict:
    """API-020 응답 모양 — {"question": {...} | None, "remaining": N}."""
    row = next_open(session_id)
    stats = counts(session_id)
    if not row:
        return {"question": None, "remaining": stats["remaining"]}
    return {
        "question": {
            "question_id": row["question_id"],
            "index": stats["answered"] + 1,
            "total": stats["total"],
            "text": row["question_text"],
            "options": row["options"],
            "item_id": row["item_id"],
            "sort_basis": row["sort_basis"],
            # ambiguous_target 도 메뉴 찾기를 연다 — 가리킨 변경이 메뉴 바꾸기일 수 있다
            "allow_other_menu": row["reason"] in ("unregistered_menu", "reference_menu",
                                                  "trait_expression", "ambiguous_target"),
        },
        "remaining": stats["remaining"],
    }


def reopen_last_answered(cur, session_id: str, item_id: str) -> str | None:
    """되돌리기(API-024) — 그 항목에서 **마지막으로 답한 질문을 다시 묻는 상태**로 되돌린다.

    항목만 확인 필요로 돌려놓고 질문을 `answered` 로 남기면 `next_open` 이 그 질문을
    건너뛴다. 그러면 상태 줄은 "1건만 답해 주시면 돼요"인데 물을 질문이 없고, 확인 필요
    항목이 남아 공유도 막힌다 — 되돌리기가 이전 단계로 돌아가지 않고 처리된 상태로
    지나가 버린다. 되돌리기는 답과 질문을 **같이** 되돌려야 한다.

    답한 뒤에 생긴 후속 질문(`_follow_up`)은 **되돌린 그 답이 만든 것**이므로 함께
    무효로 둔다. 남겨 두면 이미 없는 상태를 근거로 묻는 질문이 큐에 남는다.
    """
    cur.execute(
        "SELECT question_id, seq FROM app.review_question "
        " WHERE session_id = %s AND item_id = %s AND status = 'answered' "
        " ORDER BY answered_at DESC NULLS LAST, seq DESC LIMIT 1",
        (session_id, item_id))
    row = cur.fetchone()
    if not row:
        return None
    cur.execute(
        "UPDATE app.review_question SET status = 'voided' "
        " WHERE session_id = %s AND item_id = %s AND status = 'open' AND seq > %s",
        (session_id, item_id, row["seq"]))
    cur.execute(
        "UPDATE app.review_question "
        "   SET status = 'open', chosen_value = NULL, answered_at = NULL "
        " WHERE question_id = %s", (row["question_id"],))
    return row["question_id"]


def void_for_item(session_id: str, item_id: str, *, cur=None) -> None:
    """항목이 빠지면 그 질문은 무효다 — 지우지 않고 voided 로 둔다."""
    sql = ("UPDATE app.review_question SET status = 'voided' "
           " WHERE session_id = %s AND item_id = %s AND status = 'open'")
    if cur is not None:
        cur.execute(sql, (session_id, item_id))
        return
    db.execute(sql, (session_id, item_id))
