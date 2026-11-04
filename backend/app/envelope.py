"""응답 포장과 오류 — `data` · `error` 둘 중 하나다 (D-02 1절 · 2.1 · 2.2).

user_message 와 detail 을 분리한다. 기술 문구가 담당자 화면에 뜨는 것이
가장 흔한 누출 경로다 — 화면은 user_message 만 보여준다.

모든 응답에 `meta.trace_id` 를 싣는다. 값은 요청 미들웨어(app.main)가 정한다.
"""

import contextvars
import datetime

from fastapi import HTTPException
from fastapi.responses import JSONResponse

# 요청 1건의 trace_id. 미들웨어가 넣고 ok() · 오류 응답이 읽는다
current_trace: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id",
                                                                          default=None)


def meta() -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    return {"trace_id": current_trace.get(),
            "server_time": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"}


def ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=_jsonable({"data": data, "meta": meta()}))


def _jsonable(value):
    """datetime 을 UTC ISO 문자열로 바꾼다 (D-02 1절 시간 형식)."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        value = value.astimezone(datetime.timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if hasattr(value, "__float__") and not isinstance(value, (int, float, bool)):
        return float(value)          # Decimal (집계 질의 결과)
    return value


class ApiFailure(HTTPException):
    """업무 오류. 포장된 error 로 나간다."""

    def __init__(self, status: int, code: str, user_message: str, *,
                 detail: str | None = None, field: str | None = None, retryable: bool = False,
                 extra: dict | None = None):
        super().__init__(status_code=status, detail=detail or code)
        self.code = code
        self.user_message = user_message
        self.technical_detail = detail
        self.field = field
        self.retryable = retryable
        self.extra = extra

    def response(self) -> JSONResponse:
        body = {"code": self.code, "user_message": self.user_message,
                "retryable": self.retryable}
        if self.technical_detail:
            body["detail"] = self.technical_detail
        if self.field:
            body["field"] = self.field
        if self.extra:
            body.update(self.extra)
        return JSONResponse(status_code=self.status_code,
                            content=_jsonable({"error": body, "meta": meta()}))


# --- D-02 3절 공통 에러 코드 ---------------------------------------------------
LINK_GONE = "이 링크는 더 이상 쓸 수 없어요. 처음부터 다시 정리해 주세요"


def session_token_missing() -> ApiFailure:
    return ApiFailure(401, "SESSION_TOKEN_MISSING", LINK_GONE, detail="X-Session-Token missing")


def session_not_found() -> ApiFailure:
    # 토큰 불일치 · 다른 세션도 404 다 (D-02 1.1 — 존재 여부를 알려주지 않는다)
    return ApiFailure(404, "SESSION_NOT_FOUND", LINK_GONE, detail="session not found")


def not_found(what: str) -> ApiFailure:
    return ApiFailure(404, "NOT_FOUND", "찾는 내용이 없어요", detail=f"{what} not found")


def ops_auth_failed() -> ApiFailure:
    # 비밀번호 불일치 · 토큰 만료를 구분하지 않는다 (NFR-003)
    return ApiFailure(401, "OPS_AUTH_FAILED", "비밀번호가 맞지 않아요", detail="ops auth failed")


def stale_version(current: int | None) -> ApiFailure:
    # 화면은 409 를 받으면 조용히 다시 불러온다 (D-02 2.5)
    return ApiFailure(409, "STALE_VERSION", "다른 곳에서 먼저 바뀌었어요. 새로 불러올게요",
                      detail=f"current version={current}", retryable=True,
                      extra={"current_version": current})


def conflict(code: str, user_message: str, *, detail: str | None = None,
             extra: dict | None = None) -> ApiFailure:
    return ApiFailure(409, code, user_message, detail=detail, extra=extra)


def db_down(detail: str) -> ApiFailure:
    # DB 장애는 503 이 아니다 — 재시작으로 고쳐지지 않는다 (D-02 2.3 · R-14)
    return ApiFailure(200, "DB_UNAVAILABLE",
                      "잠깐 멈췄다가 다시 하고 있어요. 입력한 내용은 그대로 있어요",
                      detail=detail, retryable=True)


def bad_request(user_message: str = "요청을 처리하지 못했어요. 다시 시도해 주세요", *,
                code: str = "BAD_REQUEST", detail: str | None = None,
                field: str | None = None) -> ApiFailure:
    return ApiFailure(400, code, user_message, detail=detail, field=field)


def unprocessable(code: str, user_message: str, *, detail: str | None = None) -> ApiFailure:
    return ApiFailure(422, code, user_message, detail=detail)


def internal_error(detail: str | None = None) -> ApiFailure:
    return ApiFailure(500, "INTERNAL_ERROR", "잠시 후 다시 눌러 주세요", detail=detail)
