"""식별자 생성 — 사람이 읽는 접두어 형식 (D-07 3절).

숫자 ID 는 모두 문자열이다. 로그 · 화면 · 사건이 같은 값을 쓴다.
"""

import hashlib
import secrets

from app import db


def _next_no(table: str, column: str, prefix: str, width: int) -> str:
    """ORD-0012 처럼 접두어 + 0 채운 번호. 현재 최대값 + 1."""
    row = db.fetch_one(
        f"SELECT COALESCE(MAX(NULLIF(regexp_replace({column}, '^{prefix}', ''), '')::int), 0) AS n "
        f"FROM {table} WHERE {column} ~ %s",
        (f"^{prefix}[0-9]+$",),
    )
    return f"{prefix}{(row['n'] + 1):0{width}d}"


def next_session_id() -> str:
    return _next_no("app.order_session", "session_id", "ORD-", 4)


def next_incident_id() -> str:
    return _next_no("healing.incident", "incident_id", "INC-", 4)


# ---------------------------------------------------------------------
# 세션 범위 식별자 — 세션 ID 를 접두어로 붙인다
#
# ★ D-07 3절은 식별자 예시를 `it_01` · `snap_1` · `m1` 로 적었지만, 같은 표의
#   테이블 정의에서 이 컬럼들은 **전역 PK** 다. 세션이 2개가 되는 순간
#   `snap_1` · `m1` · `it_01` 이 충돌한다(실측: 두 번째 세션 생성에서
#   snapshot_pkey UniqueViolation). 복합 PK 로 바꾸면 FK 24건이 전부 바뀌므로
#   접두어로 전역 유일성을 만든다 — 화면은 이 값을 불투명 키로만 쓴다.
# ---------------------------------------------------------------------
def scoped(session_id: str, local: str) -> str:
    return f"{session_id}-{local}"


def snapshot_id(session_id: str, snapshot_no: int) -> str:
    return scoped(session_id, f"snap_{snapshot_no}")


def message_id(session_id: str, seq: int) -> str:
    return scoped(session_id, f"m{seq}")


def item_id(session_id: str, seq: int) -> str:
    return scoped(session_id, f"it_{seq:02d}")


def event_id(session_id: str, seq: int) -> str:
    return scoped(session_id, f"ev_{seq:02d}")


def question_id(session_id: str, seq: int) -> str:
    return scoped(session_id, f"q{seq}")


def suggestion_id(session_id: str, seq: int) -> str:
    return scoped(session_id, f"sg_{seq:02d}")


def change_id() -> str:
    return "ch_" + secrets.token_hex(6)


def share_id() -> str:
    return "sh_" + secrets.token_hex(6)


def injection_id() -> str:
    return "fi_" + secrets.token_hex(6)


def new_token() -> str:
    """세션 관리 토큰 원문. 저장하지 않는다 — 해시만 넣는다 (D-07 D-2)."""
    return secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def undo_token() -> str:
    return "undo_" + secrets.token_urlsafe(12)
