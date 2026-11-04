"""툴 등록 · 실행 · 검사 — LLM 은 이름과 인자를 낼 뿐, 실행 · 주입 · 소유권 검증은 여기서 한다.

호출부(D-15 의 에이전트 노드)는 `call(ctx, name, args, budget=...)` 하나만 쓴다 — 보통은 `loop.run_specialist` 를 거친다.
`ctx` 는 `context_from_session(세션 행)` 으로만 만든다 — LLM 응답에서 만들 방법이 없다.
`budget` 은 경로별 호출 허용(D-10 5절 · `budget.py`). 에이전트 노드에서 부를 때는 반드시 넘긴다.
"""

import re
import time
from dataclasses import dataclass

from app import logging_setup
from app.tools import menu_tools, order_tools
from app.tools.budget import ToolBudget

# LLM 인자로 절대 받지 않는 이름 — 세션에서만 주입한다 (G-A3 ①)
FORBIDDEN_ARGS = frozenset({
    "session_id", "brand_id", "brand", "menu_version", "token", "session_token",
    "token_hash", "user_id", "owner", "trace_id",
})


@dataclass(frozen=True)
class ToolContext:
    """툴 실행 맥락. **세션 행에서만** 만든다 — 담당자 토큰으로 이미 소유권을 확인한 세션이다."""

    session_id: str
    brand_id: str
    menu_version: str


def context_from_session(session: dict) -> ToolContext:
    return ToolContext(session_id=session["session_id"], brand_id=session["brand_id"],
                       menu_version=session["menu_version"])


class ToolRejected(ValueError):
    """인자가 스키마에 맞지 않는다 — 실행하지 않았다. 호출부는 툴 오류로 LLM 에 돌려준다."""


# 툴 정의 — description 이 LLM 이 툴을 고르는 유일한 근거다("언제 이 툴을 쓰는가" 한 문장)
TOOLS = {
    "search_menu": {
        "id": "TOOL-001",
        "description": "메시지의 메뉴 표현(이름 · 줄임말 · 별칭)에 맞는 메뉴 후보를 찾을 때 쓴다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["query"],
                       "properties": {
                           "query": {"type": "string", "minLength": 1, "maxLength": 60,
                                     "description": "메뉴 표현 원문. 예: 아아, 바닐라라떼"},
                           "limit": {"type": "integer", "minimum": 1, "maximum": 5,
                                     "description": "후보 수 상한. 기본 5"}}},
        "fn": menu_tools.search_menu,
    },
    "find_menu_by_traits": {
        "id": "TOOL-002",
        "description": "메뉴 이름 없이 취향만 말했을 때(달달한 거 · 카페인 없는 거) 특성으로 후보를 정렬해 찾을 때 쓴다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["traits"],
                       "properties": {
                           "traits": {"type": "array", "minItems": 1, "maxItems": 3,
                                      "items": {"type": "string", "enum": menu_tools.TRAITS},
                                      "description": "특성 태그"}}},
        "fn": menu_tools.find_menu_by_traits,
    },
    "get_menu": {
        "id": "TOOL-003",
        "description": "후보 메뉴 하나의 사이즈 · 옵션 · 가격을 확인해 사양이 메뉴판에 있는지 볼 때 쓴다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["menu_id"],
                       "properties": {
                           "menu_id": {"type": "string", "pattern": r"^[a-z]{2}_[0-9]{3}$",
                                       "description": "search_menu 가 돌려준 menu_id"}}},
        "fn": menu_tools.get_menu,
    },
    "get_order_item": {
        "id": "TOOL-004",
        "description": "수정 · 취소 메시지가 가리키는 주문 항목 하나의 지금 내용을 확인할 때 쓴다.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["item_id"],
                       "properties": {
                           "item_id": {"type": "string", "maxLength": 40,
                                       "description": "list_order_items 가 돌려준 item_id"}}},
        "fn": order_tools.get_order_item,
    },
    "list_order_items": {
        "id": "TOOL-005",
        "description": "이 대화의 주문 항목 전체를 훑어 수정 · 취소 대상을 고를 때 쓴다.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
        "fn": order_tools.list_order_items,
    },
}


def schemas() -> list[dict]:
    """LLM 에 넘기는 툴 목록 — 이름 · 설명 · 파라미터만. 식별자 파라미터는 하나도 없다."""
    return [{"name": name, "description": spec["description"], "parameters": spec["parameters"]}
            for name, spec in TOOLS.items()]


def call(ctx: ToolContext, name: str, args: dict | None = None, *,
         budget: ToolBudget | None = None) -> dict:
    """툴 실행. 검사 → 허용 횟수 → 실행(세션 주입) → tool_call 로그.

    인자 문제는 ToolRejected(실행 안 함 · LLM 에 돌려줌), 허용 초과는 ToolBudgetExceeded(실행 안 함 · 루프 중단).
    """
    if not isinstance(ctx, ToolContext):
        raise ToolRejected("ToolContext 는 세션에서만 만든다")
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolRejected(f"모르는 툴: {name}")
    args = dict(args or {})
    _check(spec["parameters"], args, name)
    if budget is not None:
        budget.check(name)          # 실행 전 — 넘으면 DB 를 건드리지 않는다

    started = time.perf_counter()
    result = spec["fn"](ctx, **args)
    if budget is not None:
        budget.record(name)
    logging_setup.log("tool_call", tool=name, session_id=ctx.session_id,
                      agent=budget.agent if budget else None, route=budget.route if budget else None,
                      duration_ms=int((time.perf_counter() - started) * 1000),
                      result=_size(result))
    return result


def _check(schema: dict, args: dict, name: str) -> None:
    """스키마 검사 — 식별자 인자는 이름만으로 거부한다(스키마에 없더라도 명시적으로)."""
    smuggled = sorted(FORBIDDEN_ARGS & set(args))
    if smuggled:
        raise ToolRejected(f"{name}: 식별자는 인자로 받지 않는다 — {smuggled}")
    props = schema.get("properties", {})
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise ToolRejected(f"{name}: 정의되지 않은 인자 {unknown}")
    missing = [key for key in schema.get("required", []) if key not in args]
    if missing:
        raise ToolRejected(f"{name}: 필수 인자 없음 {missing}")
    for key, value in args.items():
        rule = props[key]
        kind = rule.get("type")
        if kind == "string":
            if not isinstance(value, str) or len(value) < rule.get("minLength", 0) \
                    or len(value) > rule.get("maxLength", 10_000):
                raise ToolRejected(f"{name}.{key}: 문자열 길이 위반")
            if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
                raise ToolRejected(f"{name}.{key}: 형식 위반")
        elif kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not rule.get("minimum", value) <= value <= rule.get("maximum", value):
                raise ToolRejected(f"{name}.{key}: 정수 범위 위반")
        elif kind == "array":
            allowed = rule.get("items", {}).get("enum")
            if not isinstance(value, list) or not rule.get("minItems", 0) <= len(value) \
                    <= rule.get("maxItems", 100) or (allowed and any(v not in allowed for v in value)):
                raise ToolRejected(f"{name}.{key}: 목록 위반")


def _size(result: dict) -> str:
    for key in ("menus", "items"):
        if key in result:
            return f"{key}={len(result[key])}"
    return "found" if result.get("menu") or result.get("item") else "empty"
