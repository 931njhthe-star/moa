# 상품 소개문 서비스 — Day 6에서 만든 FastAPI 서비스 (Day 8 CI/CD의 대상)
# 앱 생성과 라우터 등록만 한다. 경로는 app/api, 로직은 app/services에 있다
from fastapi import FastAPI

from app.api import check, health

app = FastAPI(title="상품 소개문 서비스")

app.include_router(health.router)
app.include_router(check.router)
