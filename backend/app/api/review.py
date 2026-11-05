"""검토 · 수정 — API-020 ~ 026 (SCR-002).

쓰기는 전부 deps.write 를 지난다 — If-Match 409 · 되돌리기 422 · 멱등 재시도가 한 곳에 있다.
"""

from fastapi import APIRouter, Depends, Request

from app import envelope
from app.api import deps
from app.services import edits, evidence, questions
from app.services import menu as menu_service

router = APIRouter(prefix="/api")


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise envelope.bad_request(detail="body is not json")
    if not isinstance(body, dict):
        raise envelope.bad_request(detail="body must be an object")
    return body


def _required_text(body: dict, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise envelope.bad_request(detail=f"{field} is required", field=field)
    return value


@router.get("/sessions/{session_id}/questions")
def get_questions(session: dict = Depends(deps.session_of)):
    # 확인 필요 항목에 열린 질문이 없으면 먼저 메운다 — 큐 0 과 확인 필요 0 이 같은 뜻이어야 한다(보고 10번)
    questions.reconcile(session)
    return envelope.ok(questions.projection(session["session_id"]))


@router.post("/sessions/{session_id}/questions/{question_id}/answer")
async def answer_question(question_id: str, request: Request,
                          session: dict = Depends(deps.session_of),
                          version: int | None = Depends(deps.expected_version)):
    body = await _body(request)
    # 화면은 `answer` 를 보낸다(버튼 값). D-02 예시의 `value` 도 받는다.
    # `text` 는 질문이 열려 있을 때 채팅으로 친 문장이다 — 서버가 답으로 읽고, 못 읽으면 422(화면이 채팅 수정으로 넘긴다)
    answer = body.get("answer") if body.get("answer") is not None else body.get("value")
    text = body.get("text")
    if answer is None and isinstance(text, str) and text.strip():
        data = deps.write(lambda: edits.answer_from_text(session, question_id, text,
                                                         expected_version=version),
                          key=request.headers.get("Idempotency-Key"),
                          endpoint="question-answer", session_id=session["session_id"])
        return envelope.ok(data)
    if not isinstance(answer, str) or not answer.strip():
        raise envelope.bad_request(detail="answer is required", field="answer")
    data = deps.write(lambda: edits.answer_question(session, question_id, answer,
                                                    expected_version=version),
                      key=request.headers.get("Idempotency-Key"),
                      endpoint="question-answer", session_id=session["session_id"])
    return envelope.ok(data)


@router.post("/sessions/{session_id}/messages")
async def post_message(request: Request, session: dict = Depends(deps.session_of),
                       version: int | None = Depends(deps.expected_version)):
    text = _required_text(await _body(request), "text")
    data = deps.write(lambda: edits.interpret_message(session, text, expected_version=version),
                      key=request.headers.get("Idempotency-Key"),
                      endpoint="messages", session_id=session["session_id"])
    return envelope.ok(data)


@router.patch("/sessions/{session_id}/items/{item_id}")
async def patch_item(item_id: str, request: Request, session: dict = Depends(deps.session_of),
                     version: int | None = Depends(deps.expected_version)):
    body = await _body(request)
    if not body:
        raise envelope.bad_request(detail="no fields to change")
    data = deps.write(lambda: edits.patch_item(session, item_id, body, expected_version=version),
                      key=request.headers.get("Idempotency-Key"),
                      endpoint="patch-item", session_id=session["session_id"])
    return envelope.ok(data)


@router.post("/sessions/{session_id}/undo")
async def undo(request: Request, session: dict = Depends(deps.session_of)):
    undo_token = _required_text(await _body(request), "undo_token")
    data = deps.write(lambda: edits.undo(session, undo_token),
                      key=request.headers.get("Idempotency-Key"),
                      endpoint="undo", session_id=session["session_id"])
    return envelope.ok(data)


@router.get("/sessions/{session_id}/evidence")
def get_evidence(item_id: str | None = None, question_id: str | None = None,
                 session: dict = Depends(deps.session_of)):
    session_id = session["session_id"]
    if item_id:
        return envelope.ok(evidence.for_item(session_id, item_id))
    if question_id:
        return envelope.ok(evidence.for_question(session_id, question_id))
    return envelope.ok(evidence.all_messages(session_id))


@router.get("/menus/search")
def search_menus(q: str = "", session: dict = Depends(deps.session_by_token)):
    """매장 기준은 요청으로 받지 않고 세션에서 주입한다 (G-A3 협상 불가 ①)."""
    return envelope.ok(menu_service.search_view(session["brand_id"], session["menu_version"],
                                                q.strip()))
