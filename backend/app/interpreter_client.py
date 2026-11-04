"""주문 해석 서비스 호출 — DEP-001 의 호출부 (D-02 6절).

지키는 것
  - 제한시간 5초(PRD 5.6). 넘으면 DEP_TIMEOUT
  - **재시도 · 대체 전환을 여기서 하지 않는다.** 재시도는 Recovery 한 곳에서만 센다(교안코드규약 4.14 ·
    D-03 1.3). 여기서도 세면 실제 호출 횟수를 모르고 비용 사고로 직결된다
  - **결과를 우리 계약으로 다시 검증한다**(F-011). 서비스 · 모델을 믿지 않는다 — F-5 탐지 지점
  - 어느 서비스 · 모델이 답했는지 llm_history 에 남긴다(교안 4.14 규약 2)
  - **보내기 직전 요청 본문 전체의 PII 를 가린다**(D-13 · D-10 4절). LLM 으로 나가는 유일한 경계가 여기다 —
    호출부가 가렸는지에 기대지 않는다

에이전트(Intake · Menu · Validation)에 배선하는 것은 D-13 ~ D-15 다. 지금은 이 모듈만 있다.
"""

import time

import httpx
from pydantic import BaseModel, ValidationError

from app import config, logging_setup
from app.contracts import TASK_CONTRACTS
from app.tools.pii import mask_payload


# DEP-001 task → 호출하는 에이전트. llm_history.agent CHECK(intake · menu · validation)와 같은 값이어야 한다 —
# 다른 값을 넣으면 INSERT 가 실패하고, 이력 실패는 삼키므로 **기록이 조용히 0건**이 된다
TASK_AGENT = {"extract_events": "intake", "normalize_menu": "menu", "review": "validation"}


class InterpreterError(RuntimeError):
    """의존 서비스 실패. fault_code 는 P-03 7절 장애 코드다 — 사건 레코드에 그대로 들어간다."""

    def __init__(self, fault_code: str, detail: str, *, service: str,
                 missing_fields: list[str] | None = None):
        super().__init__(detail)
        self.fault_code = fault_code
        self.service = service
        self.missing_fields = missing_fields or []


def service_url(service: str) -> str:
    return {"primary": config.ORDER_INTERPRETER_PRIMARY_URL,
            "backup": config.ORDER_INTERPRETER_BACKUP_URL}.get(service, "")


def interpret(task: str, messages: list[dict], context: dict, *, service: str = "primary",
              trace_id: str | None = None, session_id: str | None = None,
              client: httpx.Client | None = None) -> BaseModel:
    """한 번 부르고, 계약으로 검증한 결과를 돌려준다. 실패는 InterpreterError 하나다."""
    contract = TASK_CONTRACTS[task]
    url = service_url(service)
    if not url:
        raise InterpreterError("UNKNOWN", f"ORDER_INTERPRETER_{service.upper()}_URL 미설정",
                               service=service)
    (messages, context), found = mask_payload([messages, context])
    pii_masked = sorted(set(found))     # 종류만 남긴다 — 원문은 로그에도 쓰지 않는다
    payload = {"task": task, "messages": messages, "context": context,
               "schema": contract.model_json_schema(), "trace_id": trace_id}

    started = time.perf_counter()
    try:
        if client is not None:
            res = client.post(f"{url}/interpret", json=payload,
                              timeout=config.ORDER_INTERPRETER_TIMEOUT_SEC)
        else:
            res = httpx.post(f"{url}/interpret", json=payload,
                             timeout=config.ORDER_INTERPRETER_TIMEOUT_SEC)
    except httpx.TimeoutException as exc:
        raise InterpreterError("DEP_TIMEOUT", f"{service} {config.ORDER_INTERPRETER_TIMEOUT_SEC}초 초과",
                               service=service) from exc
    except httpx.HTTPError as exc:
        raise InterpreterError("DEP_HTTP_5XX", f"{service} 연결 실패: {exc}",
                               service=service) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)

    if res.status_code == 504:
        raise InterpreterError("DEP_TIMEOUT", f"{service} 제공자 제한시간 초과", service=service)
    if res.status_code >= 500:
        raise InterpreterError("DEP_HTTP_5XX", f"{service} HTTP {res.status_code}", service=service)
    if res.status_code >= 400:
        raise InterpreterError("UNKNOWN", f"{service} HTTP {res.status_code}: {res.text[:200]}",
                               service=service)

    body = res.json()
    try:
        parsed = contract.model_validate(body.get("result"))
    except ValidationError as exc:
        missing = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()
                          if e["type"] == "missing"})
        _save(task, body, service, duration_ms, trace_id, session_id, valid=False, missing=missing,
              pii_masked=pii_masked)
        raise InterpreterError("AGENT_OUTPUT_INVALID", f"{service} 계약 위반: {len(exc.errors())}건",
                               service=service, missing_fields=missing) from exc

    _save(task, body, service, duration_ms, trace_id, session_id, valid=True, missing=[],
          pii_masked=pii_masked)
    return parsed


def _save(task, body, service, duration_ms, trace_id, session_id, *, valid, missing,
          pii_masked=None) -> None:
    """llm_history — 실패해도 삼킨다(비치명). 규칙 원천(모델 'rules')은 LLM 호출이 아니므로 남기지 않는다."""
    if body.get("model") in (None, "rules"):
        if not valid:
            logging_setup.log("schema_invalid", level="warning", trace_id=trace_id,
                              agent=TASK_AGENT[task], task=task, service=service,
                              missing_fields=missing)
        return
    usage = body.get("usage") or {}
    if config.db_configured():
        from app.services import history

        history.save_llm_call(trace_id=trace_id or "", agent=TASK_AGENT[task], task=task,
                              service=service, model=body.get("model"), duration_ms=duration_ms,
                              schema_valid=valid, session_id=session_id,
                              input_tokens=usage.get("input_tokens"),
                              output_tokens=usage.get("output_tokens"),
                              missing_fields=missing,
                              prompt_version=body.get("prompt_version") or "unknown",
                              pii_masked=pii_masked)
    elif not valid:
        logging_setup.log("schema_invalid", level="warning", trace_id=trace_id, agent=TASK_AGENT[task],
                          task=task, service=service, missing_fields=missing)
