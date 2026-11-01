from fastapi import APIRouter

from app.schemas import CheckRequest, CheckResponse
from app.services.checker import check_rules

router = APIRouter()


@router.post("/check", response_model=CheckResponse)
def check(req: CheckRequest):
    """소개문이 작성 규칙을 지켰는지 검사한다."""
    violations = check_rules(req.text, {"name": req.name, "price": req.price})
    return {"passed": not violations, "violations": violations}
