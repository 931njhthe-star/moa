"""운영 대시보드 인증 — 토큰을 **저장하지 않는다** (D-07 D-9).

비밀번호 1개로 재인증하는 비용이 낮다(FR-023). 저장하면 유출 표면만 늘어난다.
토큰은 프로세스 메모리에 두고, `agent` 가 재시작되면 재인증한다 —
`restart: "no"` 라 재시작이 드물다.

공용 비밀번호라 개인을 구분하지 않는다 (PRD R-17 · approver 는 '운영자' 고정).
"""

import secrets
import time

from app import config

_TTL_SEC = 3600
_TOKENS: dict[str, float] = {}       # token -> 만료 시각 (메모리 전용)


def login(password: str) -> dict | None:
    """비밀번호 비교는 서버가 한다. 화면은 받은 토큰만 보관한다 (P-06 O-0)."""
    if not config.OPS_DASHBOARD_PASSWORD:
        return None
    if not secrets.compare_digest(password or "", config.OPS_DASHBOARD_PASSWORD):
        return None
    token = secrets.token_urlsafe(24)
    _TOKENS[token] = time.monotonic() + _TTL_SEC
    _sweep()
    return {"ops_token": token, "expires_in": _TTL_SEC}


def logout(token: str | None) -> None:
    if token:
        _TOKENS.pop(token, None)


def verify(token: str | None) -> bool:
    if not token:
        return False
    expires = _TOKENS.get(token)
    if expires is None:
        return False
    if expires < time.monotonic():
        _TOKENS.pop(token, None)
        return False
    return True


def _sweep() -> None:
    now = time.monotonic()
    for token in [t for t, exp in _TOKENS.items() if exp < now]:
        _TOKENS.pop(token, None)
