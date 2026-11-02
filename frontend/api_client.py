# 백엔드(FastAPI) 호출 모음 — 화면(app.py)은 이 파일을 통해서만 백엔드와 통신한다
import os

import httpx

# 로컬: localhost:8000 / docker-compose: http://backend:8000 / 배포: 실제 주소
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
TIMEOUT = 5.0


def _request(method, path, client=None, **kwargs):
    # client는 테스트에서 가짜 서버를 끼워 넣을 때만 넘긴다
    if client is not None:
        return client.request(method, path, **kwargs)
    with httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT) as c:
        return c.request(method, path, **kwargs)


def is_backend_alive(client=None):
    """백엔드 /health가 정상 응답하면 True"""
    try:
        res = _request("GET", "/health", client)
        return res.status_code == 200 and res.json().get("status") == "ok"
    except httpx.HTTPError:
        return False


def check_copy(text, name, price, client=None):
    """소개문 검사를 요청한다.

    반환값: {"passed": bool, "violations": [str, ...]}
    통신 실패나 4xx/5xx 응답이면 httpx.HTTPError를 던진다
    """
    res = _request("POST", "/check", client, json={"text": text, "name": name, "price": price})
    res.raise_for_status()
    return res.json()
