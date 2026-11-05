"""주문 해석 서비스 — DEP-001 `POST /interpret` 를 구현한다 (D-02 6절 · D-03 2.2).

1차 · 대체가 **같은 계약 · 같은 코드**를 쓰고 역할만 환경변수로 가른다. 계약이 같아야
전환이 URL 교체로 끝난다(FR-016).

    INTERPRETER_ROLE=primary   uvicorn interpreter.main:app --port 8101
    INTERPRETER_ROLE=backup    uvicorn interpreter.main:app --port 8102

응답 원천 (INTERPRETER_SOURCE)
  rules   기본. 규칙 해석(app.services.intake)을 계약 모양으로 돌려준다 — **같은 입력에 같은 결과**.
          정상 기준선(SC-1)을 재고 장애 실험을 반복하려면 이쪽이 먼저다(D-02 6.1 · NFR-006)
  llm     실제 LLM(app.llm) — 1차는 LLM_MODEL, 대체는 LLM_MODEL_BACKUP

모드 — 장애 주입의 대상 (D-02 6.1). API-049 가 healing.fault_injection 에 넣은 행을 읽는다
  normal   정상 응답
  error    503                      F-1 (F-4 는 이것의 반복)
  delay    6초 지연 후 응답          F-2 (호출 제한시간 5초 초과)
  invalid  event_type 을 뺀 응답     F-5
  INTERPRETER_MODE 를 주면 DB 대신 그 값으로 고정한다(로컬 실험용)

이 서비스는 결과를 검증하지 않는다 — 검증은 호출부(app.interpreter_client)가 한다.
"""

import os
import time

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

from app import config, llm, logging_setup, prompts
from app.contracts import TASK_CONTRACTS
from interpreter import rules

ROLE = os.getenv("INTERPRETER_ROLE", "primary").strip()
TARGET = f"order_interpreter_{ROLE}"            # healing.fault_injection.target 과 같은 이름
SOURCE = os.getenv("INTERPRETER_SOURCE", "rules").strip()
MODE_OVERRIDE = os.getenv("INTERPRETER_MODE", "").strip()
MODEL = config.LLM_MODEL if ROLE == "primary" else config.LLM_MODEL_BACKUP
DELAY_SEC = 6.0                                  # D-02 6.1 — 제한시간 5초를 넘기는 값
_MODE_TTL_SEC = 2.0
_mode_cache = {"value": "normal", "at": 0.0}

logging_setup.setup(f"interpreter-{ROLE}")
app = FastAPI(title=f"주문 해석 서비스 ({ROLE})")


def current_mode() -> str:
    """지금 모드. DB 를 2초마다 한 번만 본다 — DB 가 없거나 끊기면 normal."""
    if MODE_OVERRIDE:
        return MODE_OVERRIDE
    now = time.monotonic()
    if now - _mode_cache["at"] < _MODE_TTL_SEC:
        return _mode_cache["value"]
    mode = "normal"
    if config.db_configured():
        try:
            from app.services import incidents

            for row in incidents.active_injections():
                if row["target"] == TARGET and row["mode"] in ("error", "delay", "invalid"):
                    mode = row["mode"]
        except Exception:      # noqa: BLE001 — 주입 상태를 못 읽으면 정상으로 돈다
            mode = "normal"
    _mode_cache.update(value=mode, at=now)
    return mode


@app.get("/health")
def health():
    mode = current_mode()
    body = {"status": "down" if mode == "error" else "ok", "role": ROLE, "mode": mode,
            "source": SOURCE, "model": MODEL if SOURCE == "llm" else None}
    return JSONResponse(status_code=503 if mode == "error" else 200, content=body)


@app.post("/interpret")
def interpret(body: dict = Body(...)):
    """동기 함수다 — FastAPI 가 스레드에서 돌린다. 지연 모드 · LLM 호출이 다른 요청을 막지 않는다."""
    task = body.get("task")
    if task not in TASK_CONTRACTS:
        return JSONResponse(status_code=400, content={"error": f"unknown task: {task}"})
    messages = body.get("messages") or []
    context = body.get("context") or {}
    trace_id = body.get("trace_id")

    mode = current_mode()
    if mode == "error":
        return JSONResponse(status_code=503, content={"error": "injected failure (F-1)"})
    if mode == "delay":
        time.sleep(DELAY_SEC)

    started = time.perf_counter()
    if SOURCE == "llm":
        try:
            out = _from_llm(task, messages, context, body.get("schema"))
        except llm.LLMError as exc:
            # 제공자 실패를 그대로 상태 코드로 옮긴다 — 호출부가 F-1 · F-2 · F-5 로 가른다
            status = {"timeout": 504, "invalid_output": 502, "limit_reached": 503,
                      "rate_limited": 503, "http_5xx": 502}.get(exc.code, 500)
            logging_setup.log("llm_call", level="warning", trace_id=trace_id, agent="interpreter",
                              task=task, service=ROLE, model=MODEL, error_code=exc.code)
            return JSONResponse(status_code=status,
                                content={"error": str(exc)[:300], "llm_error_code": exc.code})
    elif task != "extract_events":
        # 규칙 원천은 대화 읽기만 한다 — 메뉴 대조 · 보조 검토의 규칙판은 업무 층(menu · validation)에 있다
        return JSONResponse(status_code=501, content={"error": f"rules source does not serve {task}"})
    else:
        out = {"result": rules.extract_events(messages, context), "model": "rules",
               "usage": {"input_tokens": 0, "output_tokens": 0}}

    if mode == "invalid":
        for event in out["result"].get("events", []):
            event.pop("event_type", None)          # F-5 — 필수 필드 누락

    duration_ms = int((time.perf_counter() - started) * 1000)
    _record(task, out, duration_ms, trace_id)
    return {"task": task, **out, "role": ROLE, "source": SOURCE, "mode": mode,
            "duration_ms": duration_ms}


def _from_llm(task: str, messages: list[dict], context: dict, schema: dict | None) -> dict:
    """프롬프트는 prompts/*.md(D-11 · D-14) — 고정 부분은 system, 가변 부분은 context_tmpl 로 user 에."""
    contract = TASK_CONTRACTS[task]
    # Intake 는 대화 묶음을, 툴을 쓰는 에이전트(Menu · 보조 검토)는 한 왕복 입력을 받는다
    user = (prompts.render_context(context, messages) if task == "extract_events"
            else prompts.render_agent(context, messages))
    result = llm.generate_structured([{"role": "user", "content": user}], schema or contract,
                                     system=prompts.system_for(task), temperature=0, model=MODEL,
                                     timeout=config.ORDER_INTERPRETER_TIMEOUT_SEC)
    return {"result": result.data, "model": result.model, "prompt_version": prompts.PROMPT_VERSION,
            "usage": {"input_tokens": result.input_tokens,
                      "output_tokens": result.output_tokens}}


def _record(task: str, out: dict, duration_ms: int, trace_id: str | None) -> None:
    """로그 한 줄. llm_history 는 **호출부가** 쓴다 — 계약 검증 결과(schema_valid)를 아는 쪽이 거기다."""
    if SOURCE != "llm":
        return
    usage = out.get("usage") or {}
    logging_setup.log("llm_call", trace_id=trace_id, agent="interpreter", task=task,
                      service=ROLE, model=out.get("model"), duration_ms=duration_ms,
                      input_tokens=usage.get("input_tokens"),
                      output_tokens=usage.get("output_tokens"))
