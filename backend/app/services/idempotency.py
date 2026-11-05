"""멱등 재시도 — 같은 Idempotency-Key 로 다시 오면 처음 결과를 그대로 돌려준다 (D-02 1.2).

왜 필요한가: 담당자가 [공유하기]를 두 번 누르거나 네트워크가 끊겨 재시도되면
share_history 가 두 번 쌓이고 변경 이력이 중복된다. 10분 안의 같은 키는
**실행하지 않고** 보관한 응답을 돌려준다.

같은 키로 다른 엔드포인트를 부르면 409 다 — 키를 재사용한 것이지 재시도가 아니다.
"""

import json

from app import db

TTL_MINUTES = 10


class KeyReused(Exception):
    """같은 키가 다른 엔드포인트에 쓰였다 — 호출자가 409 를 돌려준다."""


def lookup(key: str | None, endpoint: str) -> dict | None:
    """보관된 응답. 없으면 None (처음 호출이다)."""
    if not key:
        return None
    row = db.fetch_one(
        "SELECT endpoint, response_json, status_code FROM app.idempotency_key "
        " WHERE key = %s AND expires_at > NOW()", (key,))
    if not row:
        return None
    if row["endpoint"] != endpoint:
        raise KeyReused(f'{key} 는 {row["endpoint"]} 에 쓰였다')
    return {"data": row["response_json"], "status_code": row["status_code"]}


def remember(key: str | None, endpoint: str, response: dict, status_code: int = 200,
             *, session_id: str | None = None) -> None:
    """처음 결과를 보관한다. 실패하면 삼킨다 — 멱등 보관이 서비스를 죽이지 않는다."""
    if not key:
        return
    try:
        db.execute(
            "INSERT INTO app.idempotency_key "
            "  (key, session_id, endpoint, response_json, status_code, expires_at) "
            f"VALUES (%s, %s, %s, %s, %s, NOW() + INTERVAL '{TTL_MINUTES} minutes') "
            "ON CONFLICT (key) DO NOTHING",
            (key, session_id, endpoint, json.dumps(response, ensure_ascii=False, default=str),
             status_code))
    except Exception:          # noqa: BLE001 — 보관 실패는 비치명 (교안 4.12 규약 3)
        from app import logging_setup
        logging_setup.log("history_save_failed", level="warning",
                          detail="idempotency_remember", key=key, endpoint=endpoint)


def sweep() -> int:
    """만료 정리. 90_cleanup.sql 과 같은 조건이다."""
    return db.execute("DELETE FROM app.idempotency_key WHERE expires_at < NOW()")
