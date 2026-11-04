# api_client 테스트 — 가짜 서버(httpx.MockTransport)로 D-02 계약을 확인한다
#
# 화면(app.py · screens/)은 Streamlit 런타임이 필요하므로 커버리지 대상이 아니다.
# 여기서 확인하는 것은 **계약을 지키는 배관**이다.
#   - 경로 · 메서드가 D-02와 같은가
#   - 세션 토큰이 URL이 아니라 `X-Session-Token` 헤더로 가는가 (D-02 1.1)
#   - ops 토큰이 `Authorization: Bearer`로 가는가
#   - 쓰기 요청에 `If-Match`가 붙는가 (D-02 2.5)
#   - `error` 응답에서 `user_message`만 화면으로 올라오고 `detail`은 섞이지 않는가 (2.2)
import httpx
import pytest

import api_client


def fake(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")


def ok(data, status=200):
    return lambda request: httpx.Response(status, json={"data": data, "meta": {"trace_id": "tr_1"}})


def seen(store):
    def handler(request):
        store.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})
    return handler


# --- 성공 응답 포장 벗기기 ----------------------------------------------------
def test_meta_unwraps_data():
    data = api_client.get_meta(client=fake(ok({"menu_as_of": "2026-10-29"})))
    assert data["menu_as_of"] == "2026-10-29"


def test_health_has_no_envelope():
    """`/health`는 `/api` 밖이라 `data` 포장이 없다 (D-02 API-001)."""
    handler = lambda request: httpx.Response(200, json={"status": "ok", "checks": {"db": False}})
    assert api_client.get_health(client=fake(handler))["status"] == "ok"


@pytest.mark.parametrize("status,alive", [("ok", True), ("degraded", True), ("down", False)])
def test_is_backend_alive_follows_three_way_health(status, alive):
    """`degraded`는 살아 있다 — DB 끊김 · 대체 경로 전환은 200 degraded다."""
    handler = lambda request: httpx.Response(200, json={"status": status})
    assert api_client.is_backend_alive(client=fake(handler)) is alive


def test_is_backend_alive_false_when_unreachable():
    def handler(request):
        raise httpx.ConnectError("no server")
    assert api_client.is_backend_alive(client=fake(handler)) is False


# --- 에러 응답 — user_message만 화면으로 ------------------------------------
def test_error_response_exposes_only_user_message():
    handler = lambda request: httpx.Response(400, json={"error": {
        "code": "CONVERSATION_EMPTY",
        "user_message": "대화를 붙여넣어 주세요",
        "detail": "messages[] is empty after parsing",
        "field": "conversation",
        "retryable": False,
    }})
    with pytest.raises(api_client.ApiError) as caught:
        api_client.create_session("", client=fake(handler))
    err = caught.value
    assert err.code == "CONVERSATION_EMPTY"
    assert err.user_message == "대화를 붙여넣어 주세요"
    # 기술 사유는 따로 담기고 화면 문구에 섞이지 않는다
    assert err.detail == "messages[] is empty after parsing"
    assert err.detail not in err.user_message
    assert err.field == "conversation"
    assert err.retryable is False


def test_unreachable_server_raises_api_unreachable():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")
    with pytest.raises(api_client.ApiUnreachable) as caught:
        api_client.get_meta(client=fake(handler))
    assert caught.value.retryable is True
    assert caught.value.user_message


def test_non_json_response_is_an_error():
    handler = lambda request: httpx.Response(200, text="<html>proxy</html>")
    with pytest.raises(api_client.ApiError) as caught:
        api_client.get_meta(client=fake(handler))
    assert caught.value.code == "BAD_RESPONSE"


def test_http_error_without_error_body():
    handler = lambda request: httpx.Response(500, json={"nope": 1})
    with pytest.raises(api_client.ApiError) as caught:
        api_client.get_meta(client=fake(handler))
    assert caught.value.status == 500


# --- 분석 요청 — brand_id를 보내지 않는다 ------------------------------------
def test_create_session_sends_raw_text_only():
    store = []
    api_client.create_session("[김민수] 아아 톨", source="paste", client=fake(seen(store)))
    request = store[0]
    assert request.method == "POST" and request.url.path == "/api/sessions"
    body = request.read().decode()
    assert "raw_text" in body and "source" in body
    # 화면이 매장을 정하는 경로를 만들지 않는다 (PRD 2.4.1 · FR-001)
    assert "brand_id" not in body


def test_brand_question_is_not_an_error():
    """되묻기는 200 + `brand_question`이다 — 오류가 아니다 (D-02 2.3)."""
    question = {"question_text": "어디 기준으로 정리할까요?", "options": []}
    data = api_client.create_session("...", client=fake(ok({"brand_question": question})))
    assert data["brand_question"]["question_text"]


# --- 토큰 전달 경로 -----------------------------------------------------------
def test_session_token_goes_in_header_not_url():
    store = []
    api_client.get_session("ORD-0012", session_token="st_secret", client=fake(seen(store)))
    request = store[0]
    assert request.headers["X-Session-Token"] == "st_secret"
    # 토큰이 경로 · 쿼리에 남으면 액세스 로그에 원문이 남는다 (NFR-003)
    assert "st_secret" not in str(request.url)


def test_ops_token_goes_in_bearer_header():
    store = []
    api_client.ops_incidents(ops_token="ops_secret", client=fake(seen(store)))
    assert store[0].headers["Authorization"] == "Bearer ops_secret"
    assert "ops_secret" not in str(store[0].url)


def test_ops_login_does_not_put_password_in_url():
    store = []
    api_client.ops_login("hunter2", client=fake(seen(store)))
    assert "hunter2" not in str(store[0].url)
    assert store[0].url.path == "/api/ops/login"


# --- 낙관적 잠금 · 멱등성 헤더 ----------------------------------------------
def test_write_requests_send_if_match_version():
    store = []
    api_client.patch_item("ORD-0012", "it_02", {"options": {"사이즈": "벤티"}},
                          session_token="st_1", version=7, client=fake(seen(store)))
    request = store[0]
    assert request.method == "PATCH"
    assert request.headers["If-Match"] == "7"


def test_stale_version_surfaces_as_error_code():
    handler = lambda request: httpx.Response(409, json={"error": {
        "code": "STALE_VERSION", "user_message": "다른 곳에서 먼저 바뀌었어요. 새로 불러올게요"}})
    with pytest.raises(api_client.ApiError) as caught:
        api_client.answer_question("ORD-0012", "q1", "벤티", session_token="st_1", version=3,
                                   client=fake(handler))
    assert caught.value.code == "STALE_VERSION"


def test_idempotency_key_header_is_optional():
    store = []
    api_client.request("POST", "/api/sessions/ORD-0012/undo", client=fake(seen(store)),
                       session_token="st_1", idempotency_key="uuid-1", json={"undo_token": "u"})
    assert store[0].headers["Idempotency-Key"] == "uuid-1"


# --- 경로 전수 — D-02 4절과 같은 경로 · 메서드인가 --------------------------
def test_endpoint_paths_match_spec():
    store = []
    client = fake(seen(store))
    api_client.get_sample_conversation(client=client)
    api_client.preview_conversation(raw_text="x", client=client)
    api_client.submit_brand_answer("ORD-1", "other", "메가커피", session_token="t", client=client)
    api_client.get_progress("ORD-1", session_token="t", client=client)
    api_client.get_questions("ORD-1", session_token="t", client=client)
    api_client.post_message("ORD-1", "서연이 라떼로", session_token="t", version=1, client=client)
    api_client.undo("ORD-1", "u1", session_token="t", client=client)
    api_client.get_evidence("ORD-1", item_id="it_01", session_token="t", client=client)
    api_client.search_menus("아메리카노", session_token="t", client=client)
    api_client.change_brand("ORD-1", "generic", session_token="t", version=2, client=client)
    api_client.get_order_sheet("ORD-1", session_token="t", client=client)
    api_client.analyze_replies("ORD-1", "[이지연] 얼음 많이로", session_token="t", client=client)
    api_client.decide_suggestion("ORD-1", "sg1", "apply", session_token="t", version=3, client=client)
    api_client.complete_share("ORD-1", "text", session_token="t", client=client)
    api_client.ops_logout(ops_token="o", client=client)
    api_client.ops_incident("INC-1", ops_token="o", client=client)
    api_client.ops_decide("INC-1", "approve", ops_token="o", client=client)
    api_client.ops_status(ops_token="o", client=client)
    api_client.ops_metrics(ops_token="o", client=client)
    api_client.ops_orders(ops_token="o", client=client)
    api_client.ops_order("ORD-1", ops_token="o", client=client)
    api_client.ops_fault("F-6", "inject", ops_token="o", client=client)

    assert [(r.method, r.url.path) for r in store] == [
        ("GET", "/api/sample-conversation"),
        ("POST", "/api/conversations/preview"),
        ("POST", "/api/sessions/ORD-1/brand-answer"),
        ("GET", "/api/sessions/ORD-1/progress"),
        ("GET", "/api/sessions/ORD-1/questions"),
        ("POST", "/api/sessions/ORD-1/messages"),
        ("POST", "/api/sessions/ORD-1/undo"),
        ("GET", "/api/sessions/ORD-1/evidence"),
        ("GET", "/api/menus/search"),
        ("POST", "/api/sessions/ORD-1/brand-change"),
        ("GET", "/api/sessions/ORD-1/order-sheet"),
        ("POST", "/api/sessions/ORD-1/replies/analyze"),
        ("POST", "/api/sessions/ORD-1/suggestions/sg1/decision"),
        ("POST", "/api/sessions/ORD-1/share/complete"),
        ("POST", "/api/ops/logout"),
        ("GET", "/api/ops/incidents/INC-1"),
        ("POST", "/api/ops/incidents/INC-1/decision"),
        ("GET", "/api/ops/status"),
        ("GET", "/api/ops/metrics"),
        ("GET", "/api/ops/orders"),
        ("GET", "/api/ops/orders/ORD-1"),
        ("POST", "/api/ops/faults"),
    ]


def test_preview_sends_file_without_extension_filter():
    """확장자 제한을 걸지 않는다 — 판정은 서버다 (P-06 Streamlit 구현 대응)."""
    store = []
    api_client.preview_conversation(file=("chat.bin", b"\x00\x01"), client=fake(seen(store)))
    assert store[0].url.path == "/api/conversations/preview"
    assert b"chat.bin" in store[0].read()


def test_share_image_returns_bytes():
    handler = lambda request: httpx.Response(200, content=b"\x89PNG...",
                                             headers={"content-type": "image/png"})
    data = api_client.get_share("ORD-1", "image", session_token="t", client=fake(handler))
    assert data.startswith(b"\x89PNG")


def test_share_image_error_still_raises():
    handler = lambda request: httpx.Response(409, json={"error": {
        "code": "SHARE_BLOCKED", "user_message": "아직 확인할 주문이 2개 남았어요"}})
    with pytest.raises(api_client.ApiError) as caught:
        api_client.get_share("ORD-1", "image", session_token="t", client=fake(handler))
    assert caught.value.code == "SHARE_BLOCKED"


def test_share_image_unreachable():
    def handler(request):
        raise httpx.ConnectError("down")
    with pytest.raises(api_client.ApiUnreachable):
        api_client.get_share("ORD-1", "image", session_token="t", client=fake(handler))


def test_share_text_requests_text_format():
    store = []
    api_client.get_share("ORD-1", "text", session_token="t", client=fake(seen(store)))
    assert store[0].url.params["format"] == "text"


def test_no_headers_when_no_tokens():
    store = []
    api_client.get_meta(client=fake(seen(store)))
    assert "X-Session-Token" not in store[0].headers
    assert "Authorization" not in store[0].headers


# --- D-05 확장 — 쓰기 요청 대기 한도 · 실패를 화면 예외로 올리지 않는다 ----------------------------
def test_write_requests_wait_longer_than_reads(monkeypatch):
    seen = []

    class FakeClient:
        def __init__(self, *, base_url, timeout):
            seen.append(timeout)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, path, **k):
            return httpx.Response(200, json={"data": {}}, request=httpx.Request(method, "http://x" + path))

    monkeypatch.setattr(api_client.httpx, "Client", FakeClient)
    api_client.request("GET", "/api/meta")
    api_client.request("POST", "/api/sessions/ORD-1/messages", json={"text": "x"})
    assert seen == [api_client.TIMEOUT, api_client.WRITE_TIMEOUT] and api_client.WRITE_TIMEOUT >= 30


def test_act_turns_failure_into_message(monkeypatch):
    from moa import api, mock

    monkeypatch.setattr(mock, "PREVIEW_ENABLED", False)

    def boom():
        raise api_client.ApiUnreachable(detail="ReadTimeout")

    data = api.act(boom, fallback={"text": "모의"}, label="message")
    assert data["_error"] and data["text"] == "잠시 후 다시 눌러 주세요"
    assert "ReadTimeout" not in str(data)                                   # 기술 문구는 화면에 안 나간다
    assert api.act(lambda: {"text": "ok"}, label="message") == {"text": "ok"}


def test_share_names_flag_is_sent_both_ways():
    """이름 노출 선택(2026-11-04) — 기본은 이름 표시, 끄면 names=false 로 보낸다."""
    store = []
    api_client.get_share("ORD-1", "text", session_token="t", client=fake(seen(store)))
    api_client.get_share("ORD-1", "text", names=False, session_token="t", client=fake(seen(store)))
    assert [r.url.params["names"] for r in store] == ["true", "false"]
