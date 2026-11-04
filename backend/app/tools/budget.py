"""경로별 툴 호출 허용 — D-10 5절 표를 코드 상수로 옮긴 것 (D-13).

두 겹으로 막는다.
  1 **에이전트 권한** — 어느 에이전트가 어떤 툴을 쓸 수 있는가. Intake 는 0개(메뉴판을 보지 않는다 — D-10 1절)
  2 **경로 허용 횟수** — 그 이벤트의 경로(`route`)에서 툴마다 몇 번, 합계 몇 번까지인가

예산은 **항목 하나 · 에이전트 호출 한 번**마다 새로 만든다(D-12 1.3 — 이전 항목의 사용량이 새지 않게).
넘으면 `ToolBudgetExceeded` — 호출부는 루프를 멈추고 그 항목을 확인 필요로 넘긴다(재시도하지 않는다).
"""

from dataclasses import dataclass, field

# 에이전트별 쓸 수 있는 툴 (D-10 1절 "쓰는 에이전트" 열 · D-11 4.2 · 4.3)
AGENT_TOOLS = {
    "intake": frozenset(),
    "menu": frozenset({"search_menu", "find_menu_by_traits", "get_menu"}),
    "validation": frozenset({"list_order_items", "get_order_item", "get_menu"}),
}

# 경로별 툴마다 허용 횟수 (D-10 5절). 표에 없는 툴은 그 경로에서 0회다
ROUTE_ALLOWANCE = {
    "add": {"search_menu": 1, "find_menu_by_traits": 1, "get_menu": 1},
    "update": {"list_order_items": 1, "get_order_item": 1, "search_menu": 1},
    "cancel": {"list_order_items": 1, "get_order_item": 1},
    "confirm": {},
    "ignore": {},
}

# 경로별 합계 상한 (D-10 5절 "최대 N")
ROUTE_TOTAL = {"add": 3, "update": 3, "cancel": 2, "confirm": 0, "ignore": 0}


class ToolBudgetExceeded(RuntimeError):
    """허용 횟수를 넘었다 — 실행하지 않았다. 루프를 멈추고 항목을 확인 필요로 넘긴다."""

    def __init__(self, reason: str, *, tool: str, route: str, agent: str):
        super().__init__(reason)
        self.tool, self.route, self.agent = tool, route, agent


@dataclass
class ToolBudget:
    """항목 하나 · 에이전트 호출 한 번의 툴 사용량. `used` 는 호출한 툴 이름 순서 그대로다(교안 4.7 규약 3)."""

    agent: str
    route: str
    used: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.agent not in AGENT_TOOLS:
            raise ValueError(f"모르는 에이전트: {self.agent}")
        if self.route not in ROUTE_ALLOWANCE:
            raise ValueError(f"모르는 경로: {self.route}")

    def check(self, tool: str) -> None:
        """실행 전에 부른다. 권한 · 툴별 횟수 · 합계 순으로 본다."""
        if tool not in AGENT_TOOLS[self.agent]:
            raise ToolBudgetExceeded(f"{self.agent} 에이전트는 {tool} 을 쓰지 않는다",
                                     tool=tool, route=self.route, agent=self.agent)
        if self.used.count(tool) >= ROUTE_ALLOWANCE[self.route].get(tool, 0):
            raise ToolBudgetExceeded(f"{self.route} 경로의 {tool} 허용 횟수를 넘었다",
                                     tool=tool, route=self.route, agent=self.agent)
        if len(self.used) >= ROUTE_TOTAL[self.route]:
            raise ToolBudgetExceeded(f"{self.route} 경로의 툴 호출 합계 {ROUTE_TOTAL[self.route]}회를 넘었다",
                                     tool=tool, route=self.route, agent=self.agent)

    def record(self, tool: str) -> None:
        self.used.append(tool)
