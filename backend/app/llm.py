"""provider 추상화 — 단일 이탈 지점 (CLAUDE.md 원칙 ③ · D-03 3.1).

이 파일만 LLM 제공자를 안다. 나머지 코드는 어느 쪽이 붙었는지 몰라야 한다.
호출부에 `if PROVIDER ==` 가 생기면 그것이 위반이다(D-16 이 문자열 검색으로 대조한다).

    LLM_PROVIDER=openai      ->  OpenAI (기본 · D-03 v1.0 개정 2026-11-03)
    LLM_PROVIDER=anthropic   ->  Claude
    LLM_PROVIDER=ollama      ->  오픈웨이트 (로컬 / 폐쇄망)

공개 인터페이스 3개 + info
    generate(messages, system)                                  한 번에 전체 텍스트
    stream(messages, system)                                    토큰 단위 (이 제품 화면은 쓰지 않는다)
    generate_structured(messages, schema, system, temperature)  계약 강제 (D-03 1.3 A안)

지키는 것
  - **라이브러리 · HTTP 재시도 0회** (교안코드규약 4.14 규약 1). 재시도는 Recovery 한 곳에서만 센다
  - 실패는 provider 와 무관하게 `LLMError` 하나로 올린다. `code` 로 갈래를 준다
  - **지출 한도 도달은 재시도해도 계속 실패한다** — `code="limit_reached"` 로 따로 알린다
  - 결과 검증은 호출부가 한다 (D-03 1.3 — 서비스 · 모델을 믿지 않는다)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Iterator

import httpx
from pydantic import BaseModel

from app import config


class LLMError(RuntimeError):
    """제공자 종류와 무관한 단일 예외. 호출부는 이것만 잡으면 된다.

    code
      timeout        제한시간 초과                     -> DEP_TIMEOUT (F-2)
      http_5xx       제공자 서버 오류                  -> DEP_HTTP_5XX (F-1)
      rate_limited   일시적 속도 제한(재시도 가능)
      limit_reached  지출 한도 도달 — **다시 해도 실패한다**
      invalid_output 형식이 깨진 응답 · 거절 · 잘림     -> AGENT_OUTPUT_INVALID (F-5)
      bad_request    요청이 틀렸다(모델명 · 인자)
      config         키 · provider 설정이 없다
    """

    def __init__(self, message: str, *, code: str = "error", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.code in ("timeout", "http_5xx", "rate_limited")


@dataclass
class LLMResult:
    """generate_structured 결과. `data` 는 아직 검증 전 값이다 — 호출부가 계약으로 검증한다."""

    data: dict
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int = 0
    raw: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def generate(messages: list[dict], system: str | None = None, *, model: str | None = None,
             temperature: float | None = None) -> str:
    """한 번에 전체 답변을 받는다."""
    provider = _provider()
    if provider == "openai":
        return _openai_chat(messages, system, model=model, temperature=temperature)[0]
    if provider == "anthropic":
        return _anthropic_generate(messages, system, model=model, temperature=temperature)
    return _ollama_generate(messages, system, model=model)


def stream(messages: list[dict], system: str | None = None, *,
           model: str | None = None) -> Iterator[str]:
    """토큰 단위로 받는다. 이 제품의 담당자 화면은 폴링이라 쓰지 않는다(D-03 3.1)."""
    provider = _provider()
    if provider == "openai":
        yield from _openai_stream(messages, system, model=model)
    elif provider == "anthropic":
        yield from _anthropic_stream(messages, system, model=model)
    else:
        yield from _ollama_stream(messages, system, model=model)


def generate_structured(messages: list[dict], schema: type[BaseModel] | dict,
                        system: str | None = None, temperature: float = 0, *,
                        model: str | None = None, timeout: float | None = None) -> LLMResult:
    """계약(스키마)에 맞는 JSON 을 받는다. 판정 · 분류는 temperature=0 (D-03 생성용 · 판정용 2계통).

    schema 는 Pydantic 계약 클래스 또는 JSON Schema dict 다. 제공자마다 강제 수단이 다르다
      openai     response_format json_schema (strict)
      anthropic  tool 1개 + tool_choice
      ollama     format 필드 — 작은 모델은 지키지 못할 수 있다(검증은 호출부)
    """
    json_schema, name = _schema_of(schema)
    provider = _provider()
    if provider == "openai":
        return _openai_structured(messages, system, json_schema, name, temperature,
                                  model=model, timeout=timeout)
    if provider == "anthropic":
        return _anthropic_structured(messages, system, json_schema, name, temperature,
                                     model=model, timeout=timeout)
    return _ollama_structured(messages, system, json_schema, model=model, timeout=timeout)


def info() -> dict:
    """현재 어느 제공자 · 모델이 붙어 있는가. /health 에서 노출한다(키는 내보내지 않는다)."""
    return {"provider": config.LLM_PROVIDER, "model": config.LLM_MODEL,
            "backup_model": config.LLM_MODEL_BACKUP}


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def _provider() -> str:
    provider = config.LLM_PROVIDER
    if provider not in ("openai", "anthropic", "ollama"):
        raise LLMError(f"알 수 없는 LLM_PROVIDER: {provider!r} (openai | anthropic | ollama)",
                       code="config")
    return provider


def _schema_of(schema: type[BaseModel] | dict) -> tuple[dict, str]:
    if isinstance(schema, dict):
        return schema, schema.get("title", "result")
    return schema.model_json_schema(), schema.__name__


def strict_schema(schema: dict) -> dict:
    """OpenAI strict 모드가 요구하는 모양으로 바꾼다 — 모든 객체에 required 전체 ·
    additionalProperties false · default 제거. 선택 필드는 계약에서 `X | None` 으로 둔다(null 허용)."""
    def walk(node):
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key in ("default", "title"):
                continue                     # 스키마 키워드만 뺀다
            if key in ("properties", "$defs"):
                # 이 아래의 키는 필드 · 정의 이름이다 — 'title' 이라는 필드도 지우지 않는다
                out[key] = {name: walk(sub) for name, sub in value.items()}
            else:
                out[key] = walk(value)
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out
    return walk(schema)


def _timeout(timeout: float | None) -> httpx.Timeout:
    total = timeout if timeout is not None else 60.0
    return httpx.Timeout(total, connect=min(5.0, total))


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# ---------------------------------------------------------------------------
# OpenAI — httpx 직접 호출 (SDK 의 자동 재시도를 끌 필요가 없다)
# ---------------------------------------------------------------------------

def _is_reasoning_model(model: str) -> bool:
    """추론 강도 인자를 받는 계열. gpt-4o · gpt-4.1 은 이 인자를 400 으로 거부한다(실측)."""
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


def _openai_body(messages, system, model, temperature) -> dict:
    model = model or config.LLM_MODEL
    body = {"model": model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "max_completion_tokens": config.LLM_MAX_TOKENS}
    if temperature is not None:
        body["temperature"] = temperature
    if _is_reasoning_model(model) and config.LLM_REASONING_EFFORT:
        body["reasoning_effort"] = config.LLM_REASONING_EFFORT
    return body


def _openai_post(body: dict, timeout: float | None) -> dict:
    if not config.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY 가 비어 있다", code="config")
    try:
        res = httpx.post(f"{config.OPENAI_BASE_URL}/chat/completions", json=body,
                         headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                         timeout=_timeout(timeout))
    except httpx.TimeoutException as exc:
        raise LLMError(f"OpenAI 제한시간 초과: {exc}", code="timeout") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"OpenAI 연결 실패: {exc}", code="http_5xx") from exc
    if res.status_code >= 400:
        raise _openai_error(res)
    return res.json()


def _openai_error(res: httpx.Response) -> LLMError:
    try:
        err = res.json().get("error") or {}
    except ValueError:
        err = {}
    message = str(err.get("message") or res.text)[:300]
    code = str(err.get("code") or err.get("type") or "")
    lowered = (message + " " + code).lower()
    # 지출 한도 · 크레딧 소진 — 일반 429 와 상태 코드가 같다. 다시 보내도 다음 달까지 실패한다
    if code in ("insufficient_quota", "billing_hard_limit_reached") or "hard limit" in lowered \
            or "usage limit" in lowered or "spend limit" in lowered or "quota" in lowered:
        return LLMError(f"OpenAI 지출 한도 도달: {message}", code="limit_reached",
                        status=res.status_code)
    if res.status_code == 429:
        return LLMError(f"OpenAI 속도 제한: {message}", code="rate_limited", status=429)
    if res.status_code >= 500:
        return LLMError(f"OpenAI 서버 오류 {res.status_code}: {message}", code="http_5xx",
                        status=res.status_code)
    return LLMError(f"OpenAI 요청 오류 {res.status_code}: {message}", code="bad_request",
                    status=res.status_code)


def _openai_chat(messages, system, *, model=None, temperature=None, timeout=None):
    started = time.perf_counter()
    payload = _openai_post(_openai_body(messages, system, model, temperature), timeout)
    choice = payload["choices"][0]
    return choice["message"].get("content") or "", payload, _ms(started)


def _openai_structured(messages, system, json_schema, name, temperature, *, model, timeout):
    body = _openai_body(messages, system, model, temperature)
    body["response_format"] = {"type": "json_schema", "json_schema": {
        "name": name[:64], "schema": strict_schema(json_schema), "strict": True}}
    started = time.perf_counter()
    payload = _openai_post(body, timeout)
    choice = payload["choices"][0]
    message = choice["message"]
    if message.get("refusal"):
        raise LLMError(f"모델이 응답을 거절했다: {message['refusal'][:200]}", code="invalid_output")
    if choice.get("finish_reason") == "length":
        raise LLMError("응답이 max_completion_tokens 에서 잘렸다", code="invalid_output")
    try:
        data = json.loads(message.get("content") or "")
    except ValueError as exc:
        raise LLMError("응답이 JSON 이 아니다", code="invalid_output") from exc
    usage = payload.get("usage") or {}
    return LLMResult(data=data, model=payload.get("model", body["model"]),
                     input_tokens=usage.get("prompt_tokens"),
                     output_tokens=usage.get("completion_tokens"),
                     duration_ms=_ms(started), raw=payload)


def _openai_stream(messages, system, *, model=None) -> Iterator[str]:
    if not config.OPENAI_API_KEY:
        raise LLMError("OPENAI_API_KEY 가 비어 있다", code="config")
    body = {**_openai_body(messages, system, model, None), "stream": True}
    try:
        with httpx.stream("POST", f"{config.OPENAI_BASE_URL}/chat/completions", json=body,
                          headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                          timeout=_timeout(None)) as res:
            if res.status_code >= 400:
                res.read()
                raise _openai_error(res)
            for line in res.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                delta = json.loads(line[6:])["choices"][0].get("delta", {}).get("content")
                if delta:
                    yield delta
    except httpx.TimeoutException as exc:
        raise LLMError(f"OpenAI 제한시간 초과: {exc}", code="timeout") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"OpenAI 스트리밍 실패: {exc}", code="http_5xx") from exc


# ---------------------------------------------------------------------------
# Anthropic — 전환 경로로 남긴다 (D-03 v1.0 의 원래 선택). 이 저장소에서 실호출 검증 전이다
# ---------------------------------------------------------------------------

def _anthropic_client(timeout: float | None = None):
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover
        raise LLMError("anthropic 패키지가 없다. pip install anthropic", code="config") from exc
    if not config.ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY 가 비어 있다", code="config")
    # max_retries=0 — 재시도는 Recovery 한 곳에서만 센다 (교안코드규약 4.14)
    return Anthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=0,
                     timeout=timeout if timeout is not None else 60.0)


def _anthropic_kwargs(messages, system, model, temperature) -> dict:
    kwargs = {"model": model or config.LLM_MODEL, "max_tokens": config.LLM_MAX_TOKENS,
              "messages": messages}
    if system:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature
    return kwargs


def _anthropic_call(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — SDK 예외를 LLMError 하나로 모은다
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        code = ("timeout" if "Timeout" in name else
                "http_5xx" if (status or 0) >= 500 or "Connection" in name else
                "rate_limited" if status == 429 else "bad_request")
        raise LLMError(f"Anthropic 호출 실패: {name}: {exc}"[:300], code=code,
                       status=status) from exc


def _anthropic_generate(messages, system, *, model=None, temperature=None) -> str:
    resp = _anthropic_call(lambda: _anthropic_client().messages.create(
        **_anthropic_kwargs(messages, system, model, temperature)))
    return "".join(b.text for b in resp.content if b.type == "text")


def _anthropic_stream(messages, system, *, model=None) -> Iterator[str]:
    client = _anthropic_client()
    with client.messages.stream(**_anthropic_kwargs(messages, system, model, None)) as s:
        yield from s.text_stream


def _anthropic_structured(messages, system, json_schema, name, temperature, *, model, timeout):
    kwargs = _anthropic_kwargs(messages, system, model, temperature)
    kwargs["tools"] = [{"name": name[:64], "description": "결과를 이 형식으로 돌려준다",
                        "input_schema": json_schema}]
    kwargs["tool_choice"] = {"type": "tool", "name": name[:64]}
    started = time.perf_counter()
    resp = _anthropic_call(lambda: _anthropic_client(timeout).messages.create(**kwargs))
    block = next((b for b in resp.content if b.type == "tool_use"), None)
    if block is None:
        raise LLMError("tool_use 응답이 없다", code="invalid_output")
    return LLMResult(data=dict(block.input), model=resp.model,
                     input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                     duration_ms=_ms(started))


# ---------------------------------------------------------------------------
# Ollama (로컬 / 폐쇄망) — 전환 경로. 이 저장소에서 실호출 검증 전이다
# ---------------------------------------------------------------------------

def _ollama_payload(messages, system, model, stream_: bool) -> dict:
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    return {"model": model or config.LLM_MODEL, "messages": msgs, "stream": stream_}


def _ollama_post(payload: dict, timeout: float | None) -> dict:
    try:
        res = httpx.post(f"{config.OLLAMA_BASE_URL}/api/chat", json=payload,
                         timeout=_timeout(timeout if timeout is not None else 120.0))
    except httpx.TimeoutException as exc:
        raise LLMError(f"Ollama 제한시간 초과: {exc}", code="timeout") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama 호출 실패: {exc}", code="http_5xx") from exc
    if res.status_code >= 400:
        raise LLMError(f"Ollama 오류 {res.status_code}: {res.text[:200]}",
                       code="http_5xx" if res.status_code >= 500 else "bad_request",
                       status=res.status_code)
    return res.json()


def _ollama_generate(messages, system, *, model=None) -> str:
    return _ollama_post(_ollama_payload(messages, system, model, False), None) \
        .get("message", {}).get("content", "")


def _ollama_stream(messages, system, *, model=None) -> Iterator[str]:
    try:
        with httpx.stream("POST", f"{config.OLLAMA_BASE_URL}/api/chat",
                          json=_ollama_payload(messages, system, model, True),
                          timeout=_timeout(120.0)) as res:
            res.raise_for_status()
            for line in res.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    yield piece
                if chunk.get("done"):
                    break
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama 스트리밍 실패: {exc}", code="http_5xx") from exc


def _ollama_structured(messages, system, json_schema, *, model, timeout) -> LLMResult:
    payload = {**_ollama_payload(messages, system, model, False), "format": json_schema,
               "options": {"temperature": 0}}
    started = time.perf_counter()
    body = _ollama_post(payload, timeout)
    try:
        data = json.loads(body.get("message", {}).get("content", ""))
    except ValueError as exc:
        raise LLMError("Ollama 응답이 JSON 이 아니다", code="invalid_output") from exc
    return LLMResult(data=data, model=body.get("model", payload["model"]),
                     input_tokens=body.get("prompt_eval_count"),
                     output_tokens=body.get("eval_count"), duration_ms=_ms(started))
