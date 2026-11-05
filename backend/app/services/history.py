"""요청 · LLM 호출 이력 — 교안코드규약 4.12 승계.

이력 저장 실패는 서비스를 죽이지 않는다. 예외를 삼키고 `history_save_failed`
warning 만 남긴다.

**단 체크포인트 저장 실패는 치명이다** — 그쪽은 sessions.set_checkpoint 가
예외를 올린다. 교안의 "전부 삼킨다"를 그대로 쓰지 않는 지점이다.
"""

from app import db, logging_setup


def save_request(*, method: str, path: str, status: int, duration_ms: int,
                 error: str | None = None, trace_id: str | None = None,
                 session_id: str | None = None) -> None:
    try:
        db.execute(
            "INSERT INTO app.request_history "
            "  (method, path, status, duration_ms, error, trace_id, session_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (method, path, status, duration_ms, error, trace_id, session_id))
    except Exception:          # noqa: BLE001 — 비치명
        logging_setup.log("history_save_failed", level="warning", detail="request_history",
                          path=path, trace_id=trace_id)


def save_llm_call(*, trace_id: str, agent: str, task: str, service: str, model: str,
                  duration_ms: int, schema_valid: bool,
                  session_id: str | None = None, input_tokens: int | None = None,
                  output_tokens: int | None = None, missing_fields: list[str] | None = None,
                  prompt_version: str | None = None, regenerate_count: int = 0,
                  pii_masked: list[str] | None = None) -> None:
    """주문 해석 서비스 호출 1건.

    이 테이블이 비어 있으면 **"툴을 안 불렀다 · 대체로 답했다"를 알 수 없다**
    (API-090 의 원천). `missing_fields` 는 FR-025 가 요구하는 "빠진 필드"다 —
    로그 파일에만 두면 별도 컨테이너인 healing 이 읽을 수 없다.
    """
    try:
        db.execute(
            "INSERT INTO app.llm_history "
            "  (trace_id, session_id, agent, task, service, model, input_tokens, "
            "   output_tokens, duration_ms, schema_valid, missing_fields, prompt_version, "
            "   regenerate_count) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (trace_id, session_id, agent, task, service, model, input_tokens, output_tokens,
             duration_ms, schema_valid, missing_fields or [], prompt_version,
             regenerate_count))
    except Exception:          # noqa: BLE001 — 비치명
        logging_setup.log("history_save_failed", level="warning", detail="llm_history",
                          trace_id=trace_id, agent=agent)

    if not schema_valid:
        logging_setup.log("schema_invalid", level="warning", trace_id=trace_id, agent=agent,
                          task=task, service=service,
                          missing_fields=missing_fields or [], prompt_version=prompt_version)
    else:
        logging_setup.log("llm_call", trace_id=trace_id, agent=agent, task=task,
                          service=service, model=model, duration_ms=duration_ms,
                          pii_masked=pii_masked or None)   # 가린 종류 (D-13) — 원문은 남기지 않는다
