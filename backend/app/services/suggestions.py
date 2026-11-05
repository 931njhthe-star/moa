"""답장 변경 제안 — 담당자가 전체 주문을 한 번 공유하고 **바꿀 것만** 받는다.

제안은 주문을 바꾸지 않는다. `status='pending'` 인 동안 `order_item` 에
아무 변화가 없어야 한다 (FR-007 · NFR-011). Q-01 이 "분석만으로 바뀐 건수 0건"을 검사한다.

사람별 확인 상태 · 전원 확인은 없다. 참여자는 서비스에 접근하지 않는다.
"""

import json

from app import db, ids
from app.services import chat_parse, changes, edits, intake
from app.services import menu as menu_service
from app.services import questions


def analyze(session: dict, raw_text: str) -> dict:
    """API-031 — 답장 대화 분석 → 변경 제안. **주문을 고치지 않는다.**

    해석은 그래프가 한다(D-12 source=reply) — 경로 5종 · 출력 가드가 분석 · 채팅과 같다.
    """
    from app import graph

    parsed = chat_parse.parse(raw_text)
    named = [m for m in parsed["messages"] if m["sender"] != chat_parse.UNNAMED]
    if not parsed["messages"] or (not named and not _nameless_session(session)):
        # 누가 보낸 답장인지 모르면 누구 주문을 바꿀지 정할 수 없다 — "찾지 못했어요"로 끝내지 않고 형식을 알려 준다.
        # 이름 없는 대화로 시작한 세션은 예외다 — 거기서는 주문자가 처음부터 `이름 없음` 하나다(보고 1번)
        return {"found_text": NO_SENDER_TEXT, "ai_notice": "AI가 찾은 내용이에요", "suggestions": [],
                "blocked_reason_text": None}
    return graph.run("reply", session, text=raw_text, messages=parsed["messages"])["result"]


NO_SENDER_TEXT = "보낸 사람 이름이 있어야 찾을 수 있어요. [이름] 바꿀 내용 형식으로 붙여 주세요"


def _nameless_session(session: dict) -> bool:
    """이 세션의 주문자가 `이름 없음` 뿐인가 (보고 1번). DB 를 못 읽으면 거짓 — 이름을 요구하는 쪽이 안전하다."""
    from app import db

    try:
        rows = db.fetch_all(
            "SELECT DISTINCT person FROM app.order_item "
            " WHERE session_id = %s AND removed = false", (session["session_id"],))
    except Exception:      # noqa: BLE001 — DB 가 없으면 판정하지 않는다
        return False
    return bool(rows) and all(r["person"] == chat_parse.UNNAMED for r in rows)


def analyze_and_apply(session: dict, raw_text: str) -> dict:
    """API-031 (apply=true) — 답장을 분석하고 **분명한 변경은 바로 반영**, 불분명한 것은 확인 질문으로 올린다.

    2026-11-05 사용자 보고 11번: 담당자는 답장을 붙여넣은 뒤 주문 정리 화면으로 돌아가 "반영된 결과"와
    "더 확인할 것"만 보면 된다. 제안마다 [반영] · [무시]를 누르게 하지 않는다.

    낙관적 잠금은 쓰지 않는다(expected_version=None) — 제안 여러 건을 잇따라 반영하므로 버전이 매번 오른다.
    화면이 들고 있던 버전으로 검사하면 둘째 건부터 409 가 된다. 되돌리기는 제안마다 그대로 남는다.
    """
    out = analyze(session, raw_text)
    applied, skipped = [], 0
    for suggestion in out.get("suggestions") or []:
        if not suggestion.get("actionable"):
            continue
        try:
            result = decide(session, suggestion["suggestion_id"], "apply", expected_version=None)
            # 무엇이 어떻게 바뀌었는지 문장으로 남긴다 — 화면이 채팅에 그대로 건다(3차 보고 6번)
            applied.append({"suggestion_id": suggestion["suggestion_id"],
                            "text": f'{suggestion["person"]} 님 주문을 {suggestion["change_text"]}로 바꿨어요.',
                            "undo_token": result.get("undo_token"),
                            "item_id": suggestion.get("item_id")})
        except (edits.NotApplicable, edits.Conflict):
            skipped += 1                      # 반영할 값이 없거나 대상이 사라졌다 — 질문으로 남는다
    asked = promote_ambiguous(session)
    if asked:
        _mark_needs_review(session, [q["item_id"] for q in asked])
    found = []
    if applied:
        found.append(f"바뀐 주문 {len(applied)}건을 반영했어요")
    if asked:
        found.append(f"확인할 것 {len(asked)}건이 생겼어요")
    if not applied and not asked:
        found.append("바뀐 주문을 찾지 못했어요")
    return {**out, "applied_count": len(applied), "asked_count": len(asked),
            "applied": applied, "skipped_count": skipped, "found_text": " · ".join(found),
            "changed_item_ids": [a["item_id"] for a in applied if a.get("item_id")],
            "blocked_reason_text": None}


def _mark_needs_review(session: dict, item_ids: list[str]) -> None:
    """확인 질문이 생긴 항목은 확인 필요여야 한다 — 그래야 화면이 질문을 묻고 공유가 막힌다 (보고 10 · 11번)."""
    if not item_ids:
        return
    with db.transaction() as cur:
        cur.execute(
            "UPDATE app.order_item SET validation_status = 'needs_review', "
            "       rule_verdict = 'undecided', review_reason = 'ambiguous_target', "
            "       review_reason_text = COALESCE(review_reason_text, '어느 주문인지 확인해 주세요') "
            " WHERE session_id = %s AND item_id = ANY(%s) AND removed = false",
            (session["session_id"], item_ids))
        edits._commit(cur, session, expected_version=None)


def persist(session: dict, messages: list[dict], event_types: dict[int, str]) -> dict:
    """D-12 N-09 (source=reply) — 답장 메시지를 Snapshot 뒤에 붙이고 변경 제안만 저장한다.

    event_types: 답장 메시지 순번(0부터) → 경로. 그래프 N-03 이 정한 값이다.
    """
    session_id = session["session_id"]
    brand_id, menu_version = session["brand_id"], session["menu_version"]
    parsed = {"messages": messages}

    rows = db.fetch_all(
        "SELECT i.item_id, i.person, i.menu_text, i.options, m.name AS menu_name "
        "  FROM app.order_item i LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
        " WHERE i.session_id = %s AND i.removed = false", (session_id,))
    by_person: dict[str, list[dict]] = {}
    for row in rows:
        by_person.setdefault(row["person"], []).append(row)

    snapshot = db.fetch_one(
        "SELECT snapshot_id, snapshot_no FROM app.snapshot WHERE session_id = %s "
        " ORDER BY snapshot_no DESC LIMIT 1", (session_id,))

    built: list[dict] = []
    with db.transaction() as cur:
        base_seq = db.fetch_one(
            "SELECT COALESCE(MAX(seq), 0) AS n FROM app.message WHERE snapshot_id = %s",
            (snapshot["snapshot_id"],))["n"]
        # 제안 번호는 세션 안에서 이어 매긴다 — 매번 1부터 매기면 두 번째 [답장 분석]이 sg_01 을 또 만들어
        # 중복 키(UniqueViolation)로 500 이 났다(2026-11-04 · 사용자 보고 #6). 제안은 지우지 않으므로 개수 + 1 이 비어 있다
        cur.execute("SELECT COUNT(*) AS n FROM app.suggestion WHERE session_id = %s", (session_id,))
        sg_base = int(cur.fetchone()["n"])

        for offset, message in enumerate(parsed["messages"], start=1):
            # 답장은 기존 Snapshot 뒤에 이어 붙인다 (D-07 4.3 is_reply)
            message_id = ids.scoped(session_id, f"r{base_seq + offset}")
            cur.execute(
                "INSERT INTO app.message (message_id, snapshot_id, seq, sender, text, is_reply) "
                "VALUES (%s, %s, %s, %s, %s, true) ON CONFLICT (message_id) DO NOTHING",
                (message_id, snapshot["snapshot_id"], base_seq + offset,
                 message["sender"], message["text"]))

            suggestion = _build(message, message_id, by_person.get(message["sender"], []),
                                session_id=session_id, brand_id=brand_id,
                                menu_version=menu_version, seq=sg_base + len(built) + 1,
                                event_type=_event_type(event_types.get(offset - 1, "ignore"),
                                                       message["text"]))
            if suggestion is None:
                continue
            built.append(suggestion)
            cur.execute(
                "INSERT INTO app.suggestion "
                "  (suggestion_id, session_id, item_id, reply_message_id, person, quote, "
                "   change_text, change_json, kind) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (suggestion["suggestion_id"], session_id, suggestion["item_id"], message_id,
                 suggestion["person"], suggestion["quote"], suggestion["change_text"],
                 json.dumps(suggestion["change_json"], ensure_ascii=False)
                 if suggestion["change_json"] else None,
                 suggestion["kind"]))

    pending = int(db.fetch_one(
        "SELECT COUNT(*) AS n FROM app.suggestion WHERE session_id = %s AND status = 'pending'",
        (session_id,))["n"])

    return {
        "found_text": (f"바뀐 주문 {len(built)}건을 찾았어요" if built
                       else "바뀐 주문을 찾지 못했어요"),
        "ai_notice": "AI가 찾은 내용이에요",
        "suggestions": [_projection(s) for s in built],
        "blocked_reason_text": (f"반영할지 정하지 않은 제안이 {pending}건 있어요"
                                if pending else None),
    }


def _event_type(from_llm: str, text: str) -> str:
    """답장 1건의 경로 — LLM 판정이 잡담(ignore · confirm)이어도 **바꿔 달라는 말은 변경으로 받는다**.

    "저는 그냥 좀 바꿔주세요"가 ignore 로 분류되어 제안도 질문도 없이 사라졌다(2026-11-05 보고 11번 확인 중).
    무엇으로 바꾸는지 불분명한 것은 _build 가 `ambiguous` 로 올리고 확인 질문이 된다 — 조용히 버리지 않는다.
    """
    if from_llm in ("ignore", "confirm"):
        ruled = intake.classify(text)
        if ruled in ("update", "cancel"):
            return ruled
    return from_llm


def _build(message: dict, message_id: str, candidates: list[dict], *,
           session_id: str, brand_id: str, menu_version: str, seq: int,
           event_type: str) -> dict | None:
    """메시지 1건 → 제안 1건. 대상이 불분명하면 `ambiguous` 로 올린다.

    `confirm` 은 바뀌는 것이 없어 제안을 만들지 않는다(P-03 5절 하단 · P-02 F-007).
    """
    text = message["text"]
    if event_type in ("ignore", "confirm"):
        return None

    options = intake._options(text)
    menu_hint = intake._menu_text(text)
    matched = menu_service.match(brand_id, menu_version, menu_hint) if menu_hint else {}

    if not candidates or len(candidates) > 1 or (not options and not matched.get("menu_id")):
        # 어느 주문인지 · 무엇으로 바꾸는지가 불분명하다 → 확인 질문으로 보낸다
        return {
            "suggestion_id": ids.suggestion_id(session_id, seq),
            "item_id": candidates[0]["item_id"] if len(candidates) == 1 else None,
            "person": message["sender"], "quote": text,
            "change_text": "확인해 주세요", "change_json": None, "kind": "ambiguous",
        }

    target = candidates[0]
    change_json: dict = {}
    parts = []
    if options:
        change_json["options"] = options
        for group, value in options.items():
            before = (target["options"] or {}).get(group)
            label_before = (menu_service.option_label(brand_id, menu_version, group, before)
                            if before else "기본")
            label_after = menu_service.option_label(brand_id, menu_version, group, value)
            parts.append(f"{label_before} → {label_after}")
    if matched.get("menu_id") and matched["menu_id"] != target.get("menu_id"):
        change_json["menu_name"] = matched["name"]
        parts.append(f'{target.get("menu_name") or target["menu_text"]} → {matched["name"]}')

    return {
        "suggestion_id": ids.suggestion_id(session_id, seq),
        "item_id": target["item_id"], "person": message["sender"], "quote": text,
        "change_text": " · ".join(parts) or "확인해 주세요",
        "change_json": change_json or None,
        "kind": "change" if change_json else "ambiguous",
    }


def _projection(suggestion: dict) -> dict:
    return {
        "suggestion_id": suggestion["suggestion_id"],
        "tone": "warning" if suggestion["kind"] == "change" else "question",
        "person": suggestion["person"],
        "quote": suggestion["quote"],
        "change_text": suggestion["change_text"],
        "actionable": suggestion["kind"] == "change",
        "item_id": suggestion["item_id"],
    }


def decide(session: dict, suggestion_id: str, decision: str, *,
           expected_version: int | None) -> dict:
    """API-032 — 반영 · 무시. 반영할 때만 주문이 바뀐다."""
    if decision not in ("apply", "ignore"):
        raise edits.NotApplicable(decision)
    session_id = session["session_id"]

    with db.transaction() as cur:
        cur.execute(
            "SELECT * FROM app.suggestion "
            " WHERE session_id = %s AND suggestion_id = %s AND status = 'pending'",
            (session_id, suggestion_id))
        suggestion = cur.fetchone()
        if not suggestion:
            raise edits.NotApplicable(suggestion_id)

        if decision == "ignore":
            cur.execute("UPDATE app.suggestion SET status = 'ignored', decided_at = NOW() "
                        " WHERE suggestion_id = %s", (suggestion_id,))
            version = edits._commit(cur, session, expected_version=expected_version)
            return {"user_message": "무시했어요", "version": version, "undo_token": None}

        change = suggestion["change_json"] or {}
        if not suggestion["item_id"] or not change:
            raise edits.NotApplicable("제안에 반영할 값이 없다")

        cur.execute(
            "SELECT i.*, m.name AS menu_name FROM app.order_item i "
            "  LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
            " WHERE i.session_id = %s AND i.item_id = %s",
            (session_id, suggestion["item_id"]))
        before = cur.fetchone()

        if change.get("options"):
            merged = {**(before["options"] or {}), **change["options"]}
            # 바꾼 옵션의 모호 표시만 지운다 — 수량 · 온도 확인은 남긴다 (edits 와 같은 규칙)
            ambiguous = {k: v for k, v in (before["ambiguous_options"] or {}).items()
                         if k not in change["options"]}
            cur.execute("UPDATE app.order_item SET options = %s, "
                        "       ambiguous_options = %s, updated_at = NOW() "
                        " WHERE item_id = %s",
                        (json.dumps(merged, ensure_ascii=False),
                         json.dumps(ambiguous, ensure_ascii=False), before["item_id"]))
        if change.get("menu_name"):
            matched = menu_service.match(session["brand_id"], session["menu_version"],
                                         change["menu_name"])
            if matched.get("menu_id"):
                cur.execute("UPDATE app.order_item SET menu_id = %s, menu_text = %s, "
                            "       updated_at = NOW() WHERE item_id = %s",
                            (matched["menu_id"], matched["name"], before["item_id"]))

        after = edits._revalidate(cur, session, before["item_id"])
        cur.execute("UPDATE app.suggestion SET status = 'applied', decided_at = NOW() "
                    " WHERE suggestion_id = %s", (suggestion_id,))
        token = changes.record(cur, session_id, method="reply_applied",
                               item_id=before["item_id"], who=suggestion["person"],
                               before_text=edits._row_text(before, session),
                               after_text=edits._row_text(after, session),
                               before_json=edits._row_json(before),
                               after_json=edits._row_json(after),
                               suggestion_id=suggestion_id)
        version = edits._commit(cur, session, expected_version=expected_version)

    return {"user_message": "반영했어요", "undo_token": token, "version": version,
            "changed_item_ids": [before["item_id"]]}


def pending_count(session_id: str) -> int:
    return int(db.fetch_one(
        "SELECT COUNT(*) AS n FROM app.suggestion WHERE session_id = %s AND status = 'pending'",
        (session_id,))["n"])


def promote_ambiguous(session: dict) -> list[dict]:
    """`ambiguous` 제안을 확인 질문으로 올린다 (D-07 4.8 → review_question)."""
    session_id = session["session_id"]
    rows = db.fetch_all(
        "SELECT s.*, i.person, i.menu_text, i.menu_id, m.name AS menu_name FROM app.suggestion s "
        "  JOIN app.order_item i ON i.item_id = s.item_id "
        "  LEFT JOIN app.menu m ON m.menu_id = i.menu_id "
        " WHERE s.session_id = %s AND s.kind = 'ambiguous' AND s.status = 'pending' "
        "   AND s.question_id IS NULL", (session_id,))
    base = questions.counts(session_id)["total"]
    built = []
    for offset, row in enumerate(rows, start=1):
        question = questions.build(
            {**row, "item_id": row["item_id"], "review_reason": "ambiguous_target",
             "traits": [], "candidates": [], "reply_quote": row["quote"]},
            session_id=session_id, brand_id=session["brand_id"],
            menu_version=session["menu_version"], seq=base + offset)
        built.append(question)
    questions.insert(session_id, built)
    for row, question in zip(rows, built):
        db.execute("UPDATE app.suggestion SET question_id = %s WHERE suggestion_id = %s",
                   (question["question_id"], row["suggestion_id"]))
    return built
