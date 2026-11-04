"""전문가 루프 — 에이전트가 툴을 부르며 일하고 보고한다 (교안코드규약 4.7 · D-10 5.1).

교안 `run_specialist` 와 같은 규약 3개를 지킨다.
  1 툴 설명(description)이 LLM 에게 가는 설명이다 — `tools.schemas()` 가 낸다
  2 **왕복 상한** — `config.MAX_TOOL_ROUNDS`(3)
  3 **호출한 툴 이름을 반환한다** — 계측 없이는 "툴을 안 불렀다 · 너무 많이 불렀다"를 알 수 없다

교안과 다른 점 — LLM 을 이 파일이 직접 부르지 않는다. 한 왕복을 하는 `step` 을 호출부(D-15 노드)가 넘긴다.
LLM 은 주문 해석 서비스(DEP-001) 너머에 있고, 전송 방식이 바뀌어도 루프 · 상한 · 계측은 여기 하나다.

    step(transcript) -> {"tool_calls": [{"name": ..., "args": {...}}, ...]}   툴을 더 부른다
                     -> {"final": {...}}                                    보고로 끝낸다
"""

from dataclasses import dataclass, field
from typing import Callable

from app import config
from app.tools.budget import ToolBudget, ToolBudgetExceeded
from app.tools.registry import ToolContext, ToolRejected, call


@dataclass
class SpecialistResult:
    """`final` 이 None 이면 보고가 없다 — 호출부는 그 항목을 확인 필요로 넘긴다."""

    final: dict | None
    used: list[str] = field(default_factory=list)
    stop: str = "done"          # done · budget_exceeded · round_limit


def run_specialist(ctx: ToolContext, budget: ToolBudget, request: dict,
                   step: Callable[[list[dict]], dict]) -> SpecialistResult:
    transcript: list[dict] = [{"request": request}]
    for _ in range(config.MAX_TOOL_ROUNDS):          # 툴 왕복은 최대 3번
        reply = step(transcript) or {}
        calls = reply.get("tool_calls") or []
        if not calls:
            return SpecialistResult(reply.get("final"), list(budget.used), "done")
        results = []
        for tc in calls:
            try:
                result = call(ctx, tc.get("name", ""), tc.get("args"), budget=budget)
            except ToolBudgetExceeded:
                # 허용을 넘으면 더 묻지 않는다 — 사람이 고른다(D-10 5절)
                return SpecialistResult(None, list(budget.used), "budget_exceeded")
            except ToolRejected as exc:
                # 스키마 위반 · 식별자 끼워 넣기 — 실행하지 않았고, 그 사실을 LLM 에 돌려준다
                result = {"error": str(exc)}
            results.append({"name": tc.get("name"), "result": result})
        transcript.append({"tool_calls": calls, "results": results})
    return SpecialistResult(None, list(budget.used), "round_limit")
