# API 테스트 — 서버를 띄우지 않고 프로세스 안에서 검사한다 (TestClient)
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_check_endpoint():
    res = client.post(
        "/check",
        json={
            "text": "숲속 캠핑 의자는 가볍습니다. 컵홀더가 있으며 가격은 29,900원입니다. 지금 만나보세요.",
            "name": "숲속 캠핑 의자",
            "price": "29,900원",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["passed"] is True
    assert body["violations"] == []


def test_check_endpoint_reports_violations():
    res = client.post(
        "/check",
        json={"text": "최고의 의자입니다!", "name": "숲속 캠핑 의자", "price": "29,900원"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["passed"] is False
    assert len(body["violations"]) > 0


def test_check_endpoint_rejects_missing_field():
    res = client.post("/check", json={"text": "숲속 캠핑 의자입니다."})
    assert res.status_code == 422
