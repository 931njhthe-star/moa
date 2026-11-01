# API 입출력 형식 — 프론트엔드(Streamlit)와 주고받는 데이터의 약속
from pydantic import BaseModel


class CheckRequest(BaseModel):
    text: str
    name: str
    price: str


class CheckResponse(BaseModel):
    passed: bool
    violations: list[str]
