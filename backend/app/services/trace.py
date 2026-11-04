"""에이전트 계측 — API-090 (디버깅 전용).

이 엔드포인트가 "에러 없이 반쪽으로 동작"을 잡는 유일한 수단이다. 화면이 정상이라는
것은 아무 증거도 아니므로, **검색 축 · 툴 호출 · 경로 분류를 각각 따로 센다**.

`ENABLE_DEBUG_API=false` 면 호출자가 404 로 막는다 — 공개 URL 에 열어 두지 않는다.
"""

from app import db


def session_trace(session_id: str) -> dict | None:
    session = db.fetch_one(
        "SELECT session_id, trace_id, brand_id, brand_source, menu_version, status, "
        "       version, checkpoint, checkpoint_at, created_at "
        "  FROM app.order_session WHERE session_id = %s", (session_id,))
    if not session:
        return None

    # 경로 분류 — 이벤트 5종이 각각 몇 건인가
    routes = db.fetch_all(
        "SELECT event_type, COUNT(*) AS n, COUNT(*) FILTER (WHERE is_reference) AS reference "
        "  FROM app.order_event WHERE session_id = %s GROUP BY event_type ORDER BY event_type",
        (session_id,))

    # 판정 계층 — 규칙이 통과시켰나 LLM 이 통과시켰나 (REQ-004 ①)
    verdicts = db.fetch_one(
        "SELECT COUNT(*) AS total, "
        "       COUNT(*) FILTER (WHERE validation_status = 'passed')        AS passed, "
        "       COUNT(*) FILTER (WHERE validation_status = 'needs_review')  AS needs_review, "
        "       COUNT(*) FILTER (WHERE validation_status = 'failed')        AS failed, "
        "       COUNT(*) FILTER (WHERE rule_verdict = 'passed')             AS rule_passed, "
        "       COUNT(*) FILTER (WHERE rule_verdict = 'undecided')          AS rule_undecided, "
        "       COUNT(*) FILTER (WHERE llm_review_verdict IS NOT NULL)      AS llm_reviewed, "
        "       COUNT(*) FILTER (WHERE validation_status = 'passed' "
        "                          AND rule_verdict <> 'passed')            AS llm_only_passed, "
        "       COUNT(*) FILTER (WHERE menu_id IS NULL)                     AS unmatched "
        "  FROM app.order_item WHERE session_id = %s AND removed = false", (session_id,))

    # LLM 호출 — 비어 있으면 "툴을 안 불렀다 · 대체로 답했다"를 알 수 없다
    llm = db.fetch_all(
        "SELECT agent, task, service, model, prompt_version, schema_valid, missing_fields, "
        "       regenerate_count, duration_ms, input_tokens, output_tokens, created_at "
        "  FROM app.llm_history WHERE session_id = %s ORDER BY created_at", (session_id,))

    conflicts = db.fetch_all(
        "SELECT conflict_id, person, conflict_kind, conflicting_event_ids, resolved_question_id "
        "  FROM app.intake_conflict WHERE session_id = %s ORDER BY created_at", (session_id,))

    requests = db.fetch_all(
        "SELECT method, path, status, duration_ms, error, created_at "
        "  FROM app.request_history WHERE session_id = %s ORDER BY created_at DESC LIMIT 50",
        (session_id,))

    return {
        "session": {**session,
                    "checkpoint_at": _iso(session["checkpoint_at"]),
                    "created_at": _iso(session["created_at"])},
        "routes": [{"event_type": r["event_type"], "count": int(r["n"]),
                    "reference": int(r["reference"])} for r in routes],
        "verdicts": {k: int(v) for k, v in (verdicts or {}).items()},
        # REQ-004 ① — 이 값이 0 이 아니면 설계 위반이다
        "llm_only_passed": int((verdicts or {}).get("llm_only_passed") or 0),
        "llm_calls": [{**row, "created_at": _iso(row["created_at"]),
                       "missing_fields": list(row["missing_fields"] or [])} for row in llm],
        "llm_call_count": len(llm),
        "backup_used": sum(1 for row in llm if row["service"] == "backup"),
        "schema_invalid": sum(1 for row in llm if not row["schema_valid"]),
        "conflicts": [{**row, "conflicting_event_ids": list(row["conflicting_event_ids"] or [])}
                      for row in conflicts],
        "requests": [{**row, "created_at": _iso(row["created_at"])} for row in requests],
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def checkpoint_age_sec() -> int | None:
    """/health 의 checkpoint_age_sec (API-001).

    Monitor 가 "60초 이상 미갱신"으로 F-3(WORKER_DOWN)을 판정하는 **유일한 근거**다
    (PRD 5.6.1). 진행 중 세션이 없으면 None 이고, 그것은 장애가 아니다.
    """
    row = db.fetch_one(
        "SELECT MAX(EXTRACT(EPOCH FROM (NOW() - checkpoint_at)))::int AS age "
        "  FROM app.order_session "
        " WHERE status IN ('running','recovering') AND checkpoint_at IS NOT NULL")
    return None if not row or row["age"] is None else int(row["age"])
