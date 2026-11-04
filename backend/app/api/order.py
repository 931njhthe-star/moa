"""주문서 · 공유 — API-030 ~ 034 (SCR-005).

공유 가능 조건 판정은 서버가 한다. 화면이 버튼을 막고 있어도 완료 기록 전에 다시 본다.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response

from app import envelope
from app.api import deps
from app.api.review import _body, _required_text
from app.services import completion, order_sheet, share, suggestions

router = APIRouter(prefix="/api")


@router.get("/sessions/{session_id}/order-sheet")
def get_order_sheet(session: dict = Depends(deps.session_of)):
    data = order_sheet.view(session)
    data["shared"] = completion.shared_state(session["session_id"])
    data["pending_suggestions"] = suggestions.pending_count(session["session_id"])
    return envelope.ok(data)


@router.post("/sessions/{session_id}/replies/analyze")
async def analyze_replies(request: Request, session: dict = Depends(deps.session_of)):
    raw_text = _required_text(await _body(request), "raw_text")
    data = deps.write(lambda: suggestions.analyze(session, raw_text),
                      key=request.headers.get("Idempotency-Key"),
                      endpoint="replies-analyze", session_id=session["session_id"])
    return envelope.ok(data)


@router.post("/sessions/{session_id}/suggestions/{suggestion_id}/decision")
async def decide_suggestion(suggestion_id: str, request: Request,
                            session: dict = Depends(deps.session_of),
                            version: int | None = Depends(deps.expected_version)):
    decision = (await _body(request)).get("decision")
    if decision not in ("apply", "ignore"):
        raise envelope.bad_request(detail="decision must be apply|ignore", field="decision")
    data = deps.write(lambda: suggestions.decide(session, suggestion_id, decision,
                                                 expected_version=version),
                      key=request.headers.get("Idempotency-Key"),
                      endpoint="suggestion-decision", session_id=session["session_id"])
    data["pending_count"] = suggestions.pending_count(session["session_id"])
    return envelope.ok(data)


def _shareable_sheet(session: dict) -> dict:
    gate = order_sheet.can_share(session["session_id"])
    if not gate["can_share"]:
        raise envelope.conflict("SHARE_BLOCKED",
                                gate["blocked_reason_text"] or "아직 공유할 수 없어요")
    return order_sheet.view(session)


@router.get("/sessions/{session_id}/share")
def get_share(format: str = "text", names: bool = True, session: dict = Depends(deps.session_of)):
    """names=false 면 이름 없이 메뉴 · 수량 · 요청 · 합계만 (2026-11-04 · 사용자 요청 #8). 기본은 이름 표시."""
    if format not in ("text", "image"):
        raise envelope.bad_request(detail="format must be text|image", field="format")
    sheet = _shareable_sheet(session)
    if format == "image":
        # PNG 는 **포장(envelope)에 넣지 않는다** — 본문이 그림이다. 화면은 바이트를 그대로 받는다.
        # 폰트가 없어 그릴 수 없으면 오류로 답한다(JSON 을 PNG 로 착각하지 않게)
        if not share.share_image.available():
            raise envelope.unprocessable("IMAGE_UNAVAILABLE", share.IMAGE_UNAVAILABLE_TEXT)
        filename = share.image_filename(sheet["brand"]["id"])
        return Response(
            content=share.render_image(sheet, show_names=names), media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"',
                     "Cache-Control": "no-store"})
    return envelope.ok(share.view(sheet, fmt=format, show_names=names))


@router.post("/sessions/{session_id}/share/complete")
async def complete_share(request: Request, session: dict = Depends(deps.session_of)):
    method = (await _body(request)).get("method")
    if method not in completion.METHODS:
        raise envelope.bad_request(detail="method must be copy_text|save_image", field="method")
    try:
        data = completion.complete(session, method)
    except completion.NotShareable as exc:
        raise envelope.conflict("SHARE_BLOCKED", exc.reason)
    return envelope.ok(data)
