"""매장 되묻기와 매장 바꾸기 — API-012 되묻기 분기 · API-013 · API-027.

왜 별 모듈인가: 세 흐름이 **같은 일**(매장 기준을 정하고 결과를 새로 만든다)을 한다.
흐름마다 따로 쓰면 "되묻기로 고른 매장"과 "채팅으로 바꾼 매장"이 다른 경로를 타고,
한쪽만 재분석을 빠뜨린다.

되묻기는 오류가 아니라 **물을 것이 생긴 정상 결과**다 (D-02 2.3).
"""

import json

from app import config, db, ids, logging_setup
from app.services import brand as brand_service
from app.services import chat_parse, sessions


def start(raw_text: str, *, source: str, trace_id: str, owner_token: str | None = None) -> dict:
    """API-012 — 분석 요청의 입구. 세 분기를 여기서 가른다.

      reused            같은 담당자의 같은 대화 재입력 (FR-011)
      awaiting_brand    매장이 2종 이상 → 되묻기
      running           바로 분석

    ★ 재사용은 **그 세션의 관리 토큰을 가진 요청만** 받는다. 토큰은 해시로만 저장돼 다시 줄 수 없으므로,
      토큰 없는 요청에 기존 세션을 돌려주면 화면이 열 방법이 없다 — 예시 대화처럼 모두가 같은 원문을
      넣으면 **두 번째 사람부터 전부** "이 링크는 더 이상 쓸 수 없어요"에 막혔다(D-05 확인 2026-11-03).
      남의 세션 ID 를 알려 주지 않는 효과도 있다. 토큰이 없거나 다르면 새로 분석한다.
    """
    existing = (sessions.find_by_content(ids.content_hash(raw_text), ids.token_hash(owner_token))
                if owner_token else None)
    if existing:
        return {"kind": "reused", "session": existing,
                "user_notice": "이미 정리한 대화예요. 지난 결과를 보여 드릴게요"}

    resolved = brand_service.resolve(raw_text)
    if resolved.get("needs_ask"):
        created = _create_awaiting(raw_text, source=source, trace_id=trace_id,
                                   question=resolved["question"])
        return {"kind": "awaiting_brand", **created,
                "brand_question": resolved["question"]}

    created = sessions.create(raw_text, source=source, brand=resolved, trace_id=trace_id)
    return {"kind": "running", **created, "brand": resolved}


def _create_awaiting(raw_text: str, *, source: str, trace_id: str, question: dict) -> dict:
    """되묻기 대기 세션. 원문과 토큰은 저장하고 **분석은 시작하지 않는다**.

    임시 brand_id 를 넣는 이유: brand_id 가 NOT NULL 이다. 답을 받으면 덮어쓰고,
    그 전까지 status 가 awaiting_brand_answer 라 분석이 돌지 않는다.
    대기 중 세션을 메뉴 조회에 쓰지 않으므로 임시값이 결과에 섞이지 않는다.
    """
    parsed = chat_parse.parse(raw_text)
    token = ids.new_token()

    with db.transaction() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(NULLIF(regexp_replace(session_id, '^ORD-', ''), '')::int), 0) "
            "       AS n FROM app.order_session WHERE session_id ~ '^ORD-[0-9]+$'")
        session_id = f"ORD-{cur.fetchone()['n'] + 1:04d}"
        cur.execute(
            "INSERT INTO app.order_session "
            "  (session_id, token_hash, brand_id, brand_source, menu_version, status, trace_id) "
            "VALUES (%s, %s, 'generic', 'default', %s, %s, %s)",
            (session_id, ids.token_hash(token), config.MENU_VERSION,
             sessions.AWAITING_BRAND, trace_id))
        snapshot_id = ids.snapshot_id(session_id, 1)
        cur.execute(
            "INSERT INTO app.snapshot "
            "  (snapshot_id, session_id, snapshot_no, raw_text, content_hash, source, "
            "   message_count, person_count, unreadable_lines) "
            "VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s)",
            (snapshot_id, session_id, raw_text, ids.content_hash(raw_text), source,
             parsed["message_count"], parsed["person_count"],
             json.dumps(parsed["unreadable_lines"], ensure_ascii=False)))
        for message in parsed["messages"]:
            message["message_id"] = ids.message_id(session_id, message["seq"])
        cur.executemany(
            "INSERT INTO app.message (message_id, snapshot_id, seq, sender, text) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(m["message_id"], snapshot_id, m["seq"], m["sender"], m["text"])
             for m in parsed["messages"]])
        sessions.set_checkpoint(cur, session_id, "created")

    logging_setup.log("session_created", session_id=session_id, trace_id=trace_id,
                      status=sessions.AWAITING_BRAND, messages=parsed["message_count"])
    return {"session_id": session_id, "session_token": token, "snapshot_id": snapshot_id,
            "parsed": parsed}


def answer(session: dict, answer_value: str, store_name: str | None = None, *,
           run: bool = True) -> dict:
    """API-013 — 되묻기 답 제출. 답을 받은 뒤에야 분석이 시작된다.

    `run=False` 면 매장 기준만 고정하고 분석은 호출자가 맡는다 — API 는 202 를 먼저
    돌려주고 백그라운드로 분석한다(D-02 API-012 · 013). 시더는 기본값으로 바로 돌린다.

    `other` 는 일반 카페 메뉴로 정리하고 적어 준 매장 이름을 안내 문구에 쓴다
    (brand_id 는 generic 이고 brand_store_name 에 이름이 남는다 — D-07 4.1).
    """
    if session["status"] != sessions.AWAITING_BRAND:
        raise ValueError("되묻기 대기 상태가 아니다")
    if answer_value not in ("starbucks", "generic", "other"):
        raise ValueError(answer_value)

    if answer_value == "other":
        brand_id = "generic"
        name = (store_name or "").strip() or "그 매장"
        evidence = f"{name} 메뉴는 아직 없어 일반 카페 메뉴로 정리했어요"
    else:
        brand_id = answer_value
        name = None
        label = brand_service.BRAND_LABEL[brand_id]
        evidence = f"{label}으로 답해 주셨어요"

    with db.transaction() as cur:
        cur.execute(
            "UPDATE app.order_session "
            "   SET brand_id = %s, brand_source = 'asked', brand_evidence_text = %s, "
            "       brand_store_name = %s, status = 'running', updated_at = NOW() "
            " WHERE session_id = %s AND status = %s",
            (brand_id, evidence, name, session["session_id"], sessions.AWAITING_BRAND))
        if cur.rowcount != 1:
            raise ValueError("되묻기 상태가 이미 바뀌었다")

    logging_setup.log("brand_decision", session_id=session["session_id"],
                      trace_id=session["trace_id"], brand_id=brand_id,
                      brand_source="asked", llm_calls=0)
    if not run:
        return {"session_id": session["session_id"]}
    return sessions.run_pipeline(session["session_id"], trace_id=session["trace_id"])


def change(session: dict, brand_id: str, *, expected_version: int | None,
           run: bool = True) -> dict:
    """API-027 — 매장 기준 바꾸기 실행([새로 정리]). `run` 은 answer() 와 같다.

    **기존 해석 결과를 지우고 다시 만든다.** 메뉴 · 가격 · 옵션 용어가 전부 매장
    기준에 묶여 있어, 남겨 두면 스타벅스 가격이 붙은 행이 일반 카페 주문서에 남는다.
    원문(snapshot · message)은 유지한다 — FR-008.

    변경 이력에는 남긴다 — 담당자가 "왜 결과가 바뀌었나"를 O-6 에서 볼 수 있어야 한다.
    """
    from app.services import changes

    if brand_id not in ("starbucks", "generic"):
        raise ValueError(brand_id)
    session_id = session["session_id"]
    before_label = brand_service.BRAND_LABEL[session["brand_id"]]
    after_label = brand_service.BRAND_LABEL[brand_id]

    with db.transaction() as cur:
        version = sessions.bump_version(cur, session_id, expected_version)
        if version is None:
            cur.execute("SELECT version FROM app.order_session WHERE session_id = %s",
                        (session_id,))
            from app.services.edits import Conflict
            raise Conflict(cur.fetchone()["version"])

        # 재분석 전에 파생물을 비운다. 원문은 건드리지 않는다
        cur.execute("DELETE FROM app.settlement_line WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM app.suggestion WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM app.review_question WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM app.intake_conflict WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM app.order_item WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM app.order_event WHERE session_id = %s", (session_id,))

        cur.execute(
            "UPDATE app.order_session "
            "   SET brand_id = %s, brand_source = 'asked', brand_evidence_text = %s, "
            "       status = 'running', updated_at = NOW() WHERE session_id = %s",
            (brand_id, f"채팅으로 {after_label}으로 바꿨어요", session_id))
        changes.record(cur, session_id, method="chat_edit",
                       before_text=before_label, after_text=after_label, issue_undo=False)

    logging_setup.log("brand_decision", session_id=session_id, trace_id=session["trace_id"],
                      brand_id=brand_id, brand_source="asked", llm_calls=0)
    user_message = f"{after_label}으로 새로 정리했어요"
    if not run:
        return {"session_id": session_id, "user_message": user_message}
    result = sessions.run_pipeline(session_id, trace_id=session["trace_id"])
    return {**result, "user_message": user_message}
