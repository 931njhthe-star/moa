# 업무 조회 툴 — G-A3 협상 불가 규칙 2개를 DB 없이 고정한다 (D-10)
#
# 실제 DB 로 남의 데이터를 조회해 보는 확인은 tools/g_a3_ownership_check.py 다(결과는 eval/ 의 로그).
# 여기서는 그 성질이 코드 수정으로 조용히 깨지지 않게 막는다.
import pytest

from app import tools
from app.tools import order_tools, pii, registry

CTX = tools.ToolContext(session_id="ORD-0001", brand_id="generic", menu_version="mv_20261029")


# --- 규칙 1 — 식별자를 LLM 인자로 받지 않는다 -----------------------------------------------
def test_no_tool_schema_exposes_identifier_params():
    for schema in tools.schemas():
        params = set(schema["parameters"].get("properties", {}))
        assert not params & registry.FORBIDDEN_ARGS, (schema["name"], params)
        assert schema["parameters"].get("additionalProperties") is False   # 정의 밖 인자 금지


def test_every_tool_says_when_to_use_it():
    for schema in tools.schemas():
        assert schema["description"].endswith("쓴다."), schema["name"]       # "언제 쓰는가" 한 문장


@pytest.mark.parametrize("name,args", [
    ("search_menu", {"query": "라떼", "brand_id": "starbucks"}),
    ("get_order_item", {"item_id": "ORD-0002-it_01", "session_id": "ORD-0002"}),
    ("list_order_items", {"token": "x"}),
    ("get_menu", {"menu_id": "sb_004", "menu_version": "mv_old"}),
])
def test_smuggled_identifier_is_rejected_before_running(name, args, monkeypatch):
    ran = []
    monkeypatch.setitem(registry.TOOLS[name], "fn", lambda *a, **k: ran.append(1) or {})
    with pytest.raises(tools.ToolRejected):
        tools.call(CTX, name, args)
    assert ran == []                                                       # 실행 자체를 하지 않는다


@pytest.mark.parametrize("name,args", [
    ("search_menu", {}), ("search_menu", {"query": ""}), ("search_menu", {"query": "라떼", "limit": 99}),
    ("get_menu", {"menu_id": "../etc"}), ("find_menu_by_traits", {"traits": ["없는태그"]}),
    ("nope", {}),
])
def test_schema_violations_are_rejected(name, args):
    with pytest.raises(tools.ToolRejected):
        tools.call(CTX, name, args)


def test_context_cannot_be_forged_from_dict():
    with pytest.raises(tools.ToolRejected):
        tools.call({"session_id": "ORD-0002"}, "list_order_items", {})


# --- 규칙 2 — 소유권은 조회 안에서 ----------------------------------------------------------
def test_order_queries_carry_session_condition():
    assert "i.session_id = %s" in order_tools._SELECT                      # 쿼리에 박혀 있다


def test_get_order_item_binds_context_session_not_argument(monkeypatch):
    seen = {}

    def fake_fetch_one(sql, params, **k):
        seen.update(sql=sql, params=params)
        return None

    monkeypatch.setattr(order_tools.db, "fetch_one", fake_fetch_one)
    result = tools.call(CTX, "get_order_item", {"item_id": "ORD-0002-it_01"})
    assert result == {"item": None}
    assert seen["params"] == ("ORD-0001", "ORD-0002-it_01")                # 세션은 ctx 에서만 온다


def test_get_menu_from_other_brand_is_empty(monkeypatch):
    from app.services import menu

    cat = {"by_id": {"gn_001": {"name": "아이스 아메리카노", "category": "커피", "base_price": 2500}},
           "menus": [], "alias_index": {}, "options": []}
    monkeypatch.setattr(menu, "catalog", lambda *a, **k: cat)
    monkeypatch.setattr(menu, "option_groups", lambda *a, **k: [])
    assert tools.call(CTX, "get_menu", {"menu_id": "sb_004"}) == {"menu": None, "options": []}
    assert tools.call(CTX, "get_menu", {"menu_id": "gn_001"})["menu"]["name"] == "아이스 아메리카노"


def test_tool_call_is_logged(monkeypatch):
    from app import logging_setup

    events = []
    monkeypatch.setattr(logging_setup, "log", lambda event, **f: events.append((event, f)))
    monkeypatch.setattr(order_tools.db, "fetch_all", lambda *a, **k: [])
    tools.call(CTX, "list_order_items", {})
    assert events and events[0][0] == "tool_call" and events[0][1]["tool"] == "list_order_items"


# --- PII 마스킹 — 가릴 것은 가리고, 주문 문장은 건드리지 않는다 (양방향) --------------------------
@pytest.mark.parametrize("text,kind", [
    ("010-1234-5678로 연락 주세요", "전화번호"), ("01012345678", "전화번호"),
    ("카드 1234-5678-9012-3456", "카드번호"), ("a.b@example.com 로 보내줘", "이메일"),
    ("국민 123-45-678901 로 입금", "계좌번호"), ("010 1234 5678 이에요", "전화번호"),
])
def test_pii_is_masked(text, kind):
    masked, found = pii.mask_pii(text)
    assert kind in found and "가림" in masked


@pytest.mark.parametrize("text", ["아이스 아메리카노 톨 2잔", "샷 2번 추가", "그란데 3잔이요 얼음 적게",
                                  "11월 3일 오후 2시 픽업", "2026-11-03 픽업", "10-20-30 잔씩"])
def test_order_text_is_not_masked(text):
    assert pii.mask_pii(text) == (text, [])


def test_mask_payload_keeps_ids_and_masks_nested_text():
    payload = {"messages": [{"message_id": "m-010-1234-5678", "text": "010-1234-5678"}],
               "context": {"brand_id": "starbucks", "items": [{"custom_request": "a.b@example.com"}]}}
    masked, found = pii.mask_payload(payload)
    assert masked["messages"][0]["message_id"] == "m-010-1234-5678"       # 식별자 키는 건드리지 않는다
    assert masked["messages"][0]["text"] == "[전화번호 가림]"
    assert masked["context"]["items"][0]["custom_request"] == "[이메일 가림]"
    assert sorted(found) == ["이메일", "전화번호"]
    assert payload["messages"][0]["text"] == "010-1234-5678"                # 원본을 바꾸지 않는다


# --- 경로별 호출 허용 (D-10 5절 · D-13) — 넘으면 실행하지 않는다 -----------------------------------
@pytest.fixture
def fake_tools(monkeypatch):
    ran = []
    for name in registry.TOOLS:
        monkeypatch.setitem(registry.TOOLS[name], "fn",
                            lambda ctx, _n=name, **k: ran.append(_n) or {"menus": [], "items": []})
    return ran


@pytest.mark.parametrize("route", ["ignore", "confirm"])
def test_ignore_and_confirm_allow_zero_tools(route, fake_tools):
    budget = tools.ToolBudget(agent="menu", route=route)
    with pytest.raises(tools.ToolBudgetExceeded):
        tools.call(CTX, "search_menu", {"query": "라떼"}, budget=budget)
    assert fake_tools == []


def test_intake_agent_has_no_tools(fake_tools):
    with pytest.raises(tools.ToolBudgetExceeded):
        tools.call(CTX, "search_menu", {"query": "라떼"}, budget=tools.ToolBudget(agent="intake", route="add"))
    assert fake_tools == []


def test_agent_permission_is_checked(fake_tools):
    # Menu Agent 는 주문 항목을 보지 않는다 — 대상 연결은 Validation 보조 검토의 일이다
    with pytest.raises(tools.ToolBudgetExceeded):
        tools.call(CTX, "list_order_items", {}, budget=tools.ToolBudget(agent="menu", route="update"))
    tools.call(CTX, "list_order_items", {}, budget=tools.ToolBudget(agent="validation", route="update"))
    assert fake_tools == ["list_order_items"]


def test_add_allows_each_menu_tool_once_up_to_three(fake_tools):
    from app.tools import menu_tools

    budget = tools.ToolBudget(agent="menu", route="add")
    tools.call(CTX, "search_menu", {"query": "라떼"}, budget=budget)
    with pytest.raises(tools.ToolBudgetExceeded):                          # 같은 툴 두 번째
        tools.call(CTX, "search_menu", {"query": "라테"}, budget=budget)
    tools.call(CTX, "find_menu_by_traits", {"traits": [menu_tools.TRAITS[0]]}, budget=budget)
    tools.call(CTX, "get_menu", {"menu_id": "gn_001"}, budget=budget)
    assert budget.used == ["search_menu", "find_menu_by_traits", "get_menu"]
    assert fake_tools == budget.used                                        # 거부된 호출은 실행 0


def test_cancel_total_is_two(fake_tools):
    budget = tools.ToolBudget(agent="validation", route="cancel")
    tools.call(CTX, "list_order_items", {}, budget=budget)
    tools.call(CTX, "get_order_item", {"item_id": "ORD-0001-it_01"}, budget=budget)
    with pytest.raises(tools.ToolBudgetExceeded):
        tools.call(CTX, "get_menu", {"menu_id": "gn_001"}, budget=budget)
    assert len(fake_tools) == 2


def test_schema_rejection_does_not_spend_budget(fake_tools):
    budget = tools.ToolBudget(agent="menu", route="add")
    with pytest.raises(tools.ToolRejected):
        tools.call(CTX, "search_menu", {"query": "라떼", "brand_id": "starbucks"}, budget=budget)
    assert budget.used == []
    tools.call(CTX, "search_menu", {"query": "라떼"}, budget=budget)          # 정상 호출은 아직 된다
    assert budget.used == ["search_menu"]


# --- 전문가 루프 (교안코드규약 4.7) — 왕복 상한 · 호출한 툴 이름 반환 --------------------------------
def test_loop_returns_final_and_used_tools(fake_tools):
    replies = iter([{"tool_calls": [{"name": "search_menu", "args": {"query": "라떼"}}]},
                    {"final": {"menu_id": None}}])
    result = tools.run_specialist(CTX, tools.ToolBudget(agent="menu", route="add"),
                                  {"menu_text": "라떼"}, lambda t: next(replies))
    assert (result.final, result.used, result.stop) == ({"menu_id": None}, ["search_menu"], "done")


def test_loop_without_tools_uses_zero(fake_tools):
    result = tools.run_specialist(CTX, tools.ToolBudget(agent="menu", route="add"), {},
                                  lambda t: {"final": {"ok": True}})
    assert result.used == [] and result.stop == "done" and fake_tools == []


def test_loop_stops_at_round_limit(monkeypatch, fake_tools):
    from app import config
    from app.tools import budget as budget_mod

    # 예산을 넉넉히 줘도 왕복 상한(3)에서 멈춘다 — 상한이 예산과 따로 동작하는지 본다
    monkeypatch.setitem(budget_mod.ROUTE_ALLOWANCE, "add", {"get_menu": 99})
    monkeypatch.setitem(budget_mod.ROUTE_TOTAL, "add", 99)
    calls = []

    def step(transcript):
        calls.append(1)
        return {"tool_calls": [{"name": "get_menu", "args": {"menu_id": "gn_001"}}]}

    result = tools.run_specialist(CTX, tools.ToolBudget(agent="menu", route="add"), {}, step)
    assert result.stop == "round_limit" and result.final is None
    assert len(calls) == config.MAX_TOOL_ROUNDS == 3


def test_loop_stops_when_budget_exceeded(fake_tools):
    def step(transcript):
        return {"tool_calls": [{"name": "search_menu", "args": {"query": "라떼"}}]}

    result = tools.run_specialist(CTX, tools.ToolBudget(agent="menu", route="add"), {}, step)
    assert result.stop == "budget_exceeded" and result.final is None
    assert result.used == ["search_menu"]                                    # 두 번째는 실행 안 됨


def test_loop_returns_rejection_to_llm_instead_of_running(fake_tools):
    seen = []

    def step(transcript):
        seen.append(transcript[-1])
        if len(seen) == 1:
            return {"tool_calls": [{"name": "get_order_item",
                                    "args": {"item_id": "x", "session_id": "ORD-0002"}}]}
        return {"final": {}}

    result = tools.run_specialist(CTX, tools.ToolBudget(agent="validation", route="update"), {}, step)
    assert "error" in seen[1]["results"][0]["result"]                       # 거부 사유가 LLM 에 돌아간다
    assert result.used == [] and fake_tools == []
