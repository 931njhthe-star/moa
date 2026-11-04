"""디버깅 — `ENABLE_DEBUG_API=true` 일 때만 등록된다 (D-02 4.5).

공개 URL 로 노출할 때는 반드시 false 다. 등록 여부는 app.main 이 정한다.
"""

from fastapi import APIRouter

from app import envelope
from app.services import trace

router = APIRouter(prefix="/api/debug")


@router.get("/sessions/{session_id}/trace")
def session_trace(session_id: str):
    """API-090 — 에이전트별 호출 계측. 에이전트는 에러 없이 반쪽으로 동작한다."""
    data = trace.session_trace(session_id)
    if data is None:
        raise envelope.not_found("session")
    return envelope.ok(data)


@router.post("/boom")
def boom():
    """API-091 — 의도된 예외. 500 · 오류 로그 · 탐지 경로를 확인한다."""
    raise RuntimeError("intended failure (API-091)")
