from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    """서비스 생존 확인용 (Day 10 Auto Healing에서 재사용)"""
    return {"status": "ok"}
