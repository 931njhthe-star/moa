# api_client 테스트 — 백엔드를 띄우지 않고 가짜 응답(MockTransport)으로 검사한다
import httpx
import pytest

from api_client import check_copy, is_backend_alive


def make_client(handler):
    return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))


def test_check_copy_sends_request_and_returns_result():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/check"
        assert request.read() == httpx.Request(
            "POST", "http://test", json={"text": "소개문", "name": "의자", "price": "1원"}
        ).read()
        return httpx.Response(200, json={"passed": False, "violations": ["R1"]})

    result = check_copy("소개문", "의자", "1원", client=make_client(handler))
    assert result == {"passed": False, "violations": ["R1"]}


def test_check_copy_raises_on_error_status():
    client = make_client(lambda request: httpx.Response(422, json={"detail": []}))
    with pytest.raises(httpx.HTTPStatusError):
        check_copy("소개문", "의자", "1원", client=client)


def test_backend_alive():
    client = make_client(lambda request: httpx.Response(200, json={"status": "ok"}))
    assert is_backend_alive(client) is True


def test_backend_down_returns_false():
    def handler(request):
        raise httpx.ConnectError("연결 실패")

    assert is_backend_alive(make_client(handler)) is False


def test_default_client_uses_backend_url(monkeypatch):
    # client를 넘기지 않으면 BACKEND_URL로 접속한다 (연결 실패 → False)
    monkeypatch.setattr("api_client.BACKEND_URL", "http://127.0.0.1:9")
    assert is_backend_alive() is False
