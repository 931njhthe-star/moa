# provider 추상화 — 진짜 LLM 을 부르지 않는다 (교안코드규약 4.16 규약 1). httpx 를 가짜로 바꿔 끼운다
#
# 보는 것: 계약 강제 요청 모양 · 응답 해석 · 오류 갈래(특히 지출 한도는 재시도 불가) · **재시도 0회**
import json

import httpx
import pytest

from app import config, llm
from app.contracts import OrderEvents


class FakePost:
    """httpx.post 대역. 호출 횟수를 센다 — 결과만 보면 재시도가 몇 번 돌았는지 모른다(4.16 규약 2)."""

    def __init__(self, status=200, body=None, exc=None):
        self.status, self.body, self.exc = status, body, exc
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.exc:
            raise self.exc
        return httpx.Response(self.status, json=self.body,
                              request=httpx.Request("POST", url))


def ok_body(content, model="gpt-4o-mini-2024-07-18", finish="stop"):
    return {"model": model, "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5}}


@pytest.fixture
def openai(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "LLM_MODEL", "gpt-4o-mini-2024-07-18")
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "none")


def install(monkeypatch, fake):
    monkeypatch.setattr(llm.httpx, "post", fake)
    return fake


# --- 계약 강제 --------------------------------------------------------------------
def test_structured_sends_strict_schema_and_parses(openai, monkeypatch):
    fake = install(monkeypatch, FakePost(body=ok_body(json.dumps({"events": []}))))
    result = llm.generate_structured([{"role": "user", "content": "x"}], OrderEvents, system="s")
    body = fake.calls[0]["json"]
    fmt = body["response_format"]["json_schema"]
    assert fmt["strict"] is True and fmt["name"] == "OrderEvents"
    assert body["temperature"] == 0                       # 판정 · 분류는 0 (D-03 2계통)
    assert body["messages"][0] == {"role": "system", "content": "s"}
    assert "reasoning_effort" not in body                 # gpt-4o 는 이 인자를 400 으로 거부한다(실측)
    assert result.data == {"events": []}
    assert (result.input_tokens, result.output_tokens) == (12, 5)
    assert len(fake.calls) == 1


def test_reasoning_effort_only_for_reasoning_models(openai, monkeypatch):
    fake = install(monkeypatch, FakePost(body=ok_body("{}", model="gpt-5.4-mini-2026-03-17")))
    llm.generate_structured([{"role": "user", "content": "x"}], {"type": "object",
                            "properties": {}}, model="gpt-5.4-mini-2026-03-17")
    assert fake.calls[0]["json"]["reasoning_effort"] == "none"


def test_strict_schema_requires_every_field_and_keeps_field_named_title():
    schema = {"type": "object", "title": "T", "properties": {
        "title": {"type": "string", "title": "Title"},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}},
        "required": ["title"]}
    out = llm.strict_schema(schema)
    assert out["required"] == ["title", "note"]            # 선택 필드도 required — null 로 비운다
    assert out["additionalProperties"] is False
    assert "title" in out["properties"]                    # 필드 이름 'title' 은 지우지 않는다
    assert "title" not in out and "default" not in out["properties"]["note"]


def test_contract_schema_is_strict_compatible():
    out = llm.strict_schema(OrderEvents.model_json_schema())
    item = out["$defs"]["OrderItemDraft"]
    assert set(item["required"]) == set(item["properties"])
    assert out["$defs"]["OrderEvent"]["additionalProperties"] is False


# --- 실패 갈래 -------------------------------------------------------------------
@pytest.mark.parametrize("status,error,code,retryable", [
    (429, {"code": "insufficient_quota", "message": "You exceeded your current quota"},
     "limit_reached", False),
    (429, {"code": "rate_limit_exceeded", "message": "Rate limit reached for requests"},
     "rate_limited", True),
    (500, {"message": "server error"}, "http_5xx", True),
    (400, {"message": "Unrecognized request argument supplied: reasoning_effort"},
     "bad_request", False),
])
def test_error_classes(openai, monkeypatch, status, error, code, retryable):
    fake = install(monkeypatch, FakePost(status=status, body={"error": error}))
    with pytest.raises(llm.LLMError) as caught:
        llm.generate_structured([{"role": "user", "content": "x"}], OrderEvents)
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert len(fake.calls) == 1                            # 재시도 0회 — Recovery 한 곳에서만 센다


def test_timeout_is_timeout(openai, monkeypatch):
    install(monkeypatch, FakePost(exc=httpx.ReadTimeout("slow")))
    with pytest.raises(llm.LLMError) as caught:
        llm.generate_structured([{"role": "user", "content": "x"}], OrderEvents, timeout=5)
    assert caught.value.code == "timeout"


@pytest.mark.parametrize("body", [
    ok_body("not json"),
    ok_body('{"events": [', finish="length"),
    {"model": "m", "choices": [{"message": {"content": None, "refusal": "no"},
                                "finish_reason": "stop"}]},
])
def test_broken_output_is_invalid_output(openai, monkeypatch, body):
    install(monkeypatch, FakePost(body=body))
    with pytest.raises(llm.LLMError) as caught:
        llm.generate_structured([{"role": "user", "content": "x"}], OrderEvents)
    assert caught.value.code == "invalid_output"


def test_missing_key_is_config_error_without_calling(openai, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    fake = install(monkeypatch, FakePost(body=ok_body("{}")))
    with pytest.raises(llm.LLMError) as caught:
        llm.generate([{"role": "user", "content": "x"}])
    assert caught.value.code == "config" and fake.calls == []


def test_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "nope")
    with pytest.raises(llm.LLMError) as caught:
        llm.generate([{"role": "user", "content": "x"}])
    assert caught.value.code == "config"


def test_info_has_no_secret(openai):
    assert "sk-test" not in json.dumps(llm.info())
