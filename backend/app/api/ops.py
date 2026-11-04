"""운영 대시보드 — API-040 ~ 049 (SCR-006 · O-0 ~ O-6).

로그인 외 전부 ops 토큰이 필요하다. 담당자 세션 토큰과 섞이지 않는다 (D-02 1.1).
"""

from fastapi import APIRouter, Depends, Request

from app import envelope, logging_setup
from app.api import deps
from app.api.review import _body
from app.services import incidents, ops_auth

router = APIRouter(prefix="/api/ops")


def _limit(limit: int) -> int:
    return max(1, min(int(limit), 200))      # D-02 1절 — 기본 50 · 최대 200


@router.post("/login")
async def login(request: Request):
    result = ops_auth.login((await _body(request)).get("password") or "")
    # 결과만 남긴다 — 비밀번호 · 토큰 원문은 로그에 0건 (D-03 1.5 · NFR-003 · R-17)
    logging_setup.log("ops_login", level="info" if result else "warning",
                      trace_id=envelope.current_trace.get(),
                      result="success" if result else "fail")
    if not result:
        raise envelope.ops_auth_failed()
    return envelope.ok(result)


@router.post("/logout")
def logout(token: str = Depends(deps.ops_token)):
    ops_auth.logout(token)
    return envelope.ok({"logged_out": True})


@router.get("/incidents")
def incident_list(limit: int = 50, _: str = Depends(deps.ops_token)):
    return envelope.ok(incidents.incident_list(_limit(limit)))


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, _: str = Depends(deps.ops_token)):
    detail = incidents.incident_detail(incident_id)
    if detail is None:
        raise envelope.not_found("incident")
    return envelope.ok(detail)


@router.post("/incidents/{incident_id}/decision")
async def decide(incident_id: str, request: Request, _: str = Depends(deps.ops_token)):
    body = await _body(request)
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise envelope.bad_request(detail="decision must be approve|reject", field="decision")
    result = incidents.decide(incident_id, decision, note=body.get("note"))
    if not result["ok"]:
        if result.get("already"):
            # 첫 결정만 반영된다 — 기존 결정을 함께 돌려준다 (D-02 1.2)
            raise envelope.conflict("ALREADY_DECIDED", "이미 처리된 요청이에요",
                                    extra={"decision": result["already"]})
        raise envelope.not_found("incident")
    return envelope.ok(result)


@router.get("/status")
def status(_: str = Depends(deps.ops_token)):
    return envelope.ok(incidents.status_view())


@router.get("/metrics")
def metrics(_: str = Depends(deps.ops_token)):
    return envelope.ok(incidents.metrics_view())


@router.get("/orders")
def order_list(limit: int = 50, _: str = Depends(deps.ops_token)):
    return envelope.ok(incidents.order_list(_limit(limit)))


@router.get("/orders/{order_id}")
def order_detail(order_id: str, _: str = Depends(deps.ops_token)):
    return envelope.ok(incidents.order_detail(order_id))


@router.post("/faults")
async def fault(request: Request, _: str = Depends(deps.ops_token)):
    body = await _body(request)
    # 화면은 `code` 를 보낸다. D-02 표기 `fault` 도 받는다
    code = body.get("code") or body.get("fault")
    action = body.get("action") or "inject"
    if action not in ("inject", "clear"):
        raise envelope.bad_request(detail="action must be inject|clear", field="action")
    result = incidents.inject(code, action)
    if not result["ok"]:
        if code in incidents.FAULT_TARGETS or action == "clear":
            # 실습 환경 가드 — 404 로 숨기지 않는다 (D-02 API-049)
            raise envelope.ApiFailure(403, "LAB_ONLY", result["user_message"],
                                      detail="ENVIRONMENT is not lab")
        raise envelope.bad_request(result["user_message"], field="code")
    return envelope.ok(result)
