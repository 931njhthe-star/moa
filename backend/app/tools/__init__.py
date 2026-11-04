"""업무 조회 툴 — 에이전트(LLM)가 고르고, 우리 코드가 실행한다 (D-10 툴스키마정의서 · G-A3).

협상 불가 규칙 2개
  1 사용자 · 세션 식별자를 LLM 인자로 받지 않는다 — `ToolContext` 는 세션 행에서만 만들고,
    LLM 이 넘긴 인자에 식별자(session_id · brand_id · menu_version · token …)가 있으면 **실행하지 않는다**
  2 소유권은 툴 코드 안에서 검증한다 — 조회 쿼리 자체에 세션 · 매장 조건이 붙는다.
    남의 레코드 ID 를 넣으면 **빈 결과**다(존재 여부를 알려주지 않는다 — D-02 1.1 과 같은 원칙)

모두 **조회 전용**이다. 쓰기는 담당자 조작(API-021 ~ 032)만 한다 — 열어준 만큼 위험하다.
D-13 완성분
  - `budget.py` 경로별 호출 허용 횟수(D-10 5절) · 에이전트별 툴 권한
  - `loop.py`   전문가 루프 — 왕복 상한 3 · 호출한 툴 이름 반환(교안코드규약 4.7)
  - `pii.py`    LLM 으로 나가는 요청 본문 전체 가림(`mask_payload`) — 툴 반환 칸 가림은 D-10 초판 그대로
소유권 검증(`order_tools._SELECT` 의 세션 조건 · `menu_tools` 의 매장 조건)은 D-10 초판에서 바꾸지 않았다.
"""

from app.tools.budget import ToolBudget, ToolBudgetExceeded
from app.tools.loop import SpecialistResult, run_specialist
from app.tools.registry import ToolContext, ToolRejected, call, context_from_session, schemas

__all__ = ["SpecialistResult", "ToolBudget", "ToolBudgetExceeded", "ToolContext", "ToolRejected",
           "call", "context_from_session", "run_specialist", "schemas"]
