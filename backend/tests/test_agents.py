# 툴을 쓰는 에이전트 — Menu Agent · Validation 보조 검토 (PRD 5.1 · D-11 4.2 · 4.3)
#
# 가짜 해석 서비스가 "툴 부르기 / 결론" 왕복을 돌려주게 하고, 우리 코드가 지키는 것을 고정한다.
#   ① 툴이 돌려준 menu_id 만 후보가 된다  ② 에이전트는 menu_id 를 확정하지 않는다(SC-8)
#   ③ 허용 횟수 · 왕복 상한  ④ 실패하면 규칙 결과 그대로  ⑤ 보조 검토는 판정을 바꾸지 않는다
import json

import pytest

from app import interpreter_client, prompts
from app.contracts import MenuStep, ReviewStep
from app.graph import agents, nodes
from app.services import menu as menu_service

SESSION = {"session_id": "ORD-0001", "brand_id": "starbucks", "menu_version": "mv", "status": "running", "version": 1}
CAT = {
    "by_id": {"sb_001": {"menu_id": "sb_001", "name": "민트 초콜릿 칩 블렌디드", "category": "블렌디드",
                         "base_price": 6300, "trait_tags": ["단맛"]},
              "sb_012": {"menu_id": "sb_012", "name": "카페 라떼", "category": "에스프레소",
                         "base_price": 5000, "trait_tags": []}},
    "menus": [], "alias_index": {}, "options": [],
}
ROW = {"person": "최유나", "menu_text": "민트 초코", "match_text": "민트 초코", "quantity": 1, "menu_id": None,
       "candidates": [], "traits": [], "ambiguous_options": {}, "_message_id": "m3"}


@pytest.fixture(autouse=True)
def fake_menu(monkeypatch):
    monkeypatch.setattr(menu_service, "catalog", lambda *a, **k: CAT)
    monkeypatch.setattr(menu_service, "search", lambda b, v, q, limit=5: [CAT["by_id"]["sb_001"]] if "민트" in q else [])
    monkeypatch.setattr(menu_service, "option_groups", lambda *a, **k: [])


def step(contract, **kw):
    base = {"reason": "r", "action": "finish", "tool": None, "args_json": None}
    base.update({"matches": []} if contract is MenuStep else {"verdicts": []})
    base.update(kw)
    return contract.model_validate(base)


@pytest.fixture
def service(monkeypatch):
    replies, seen = [], []

    def fake(task, messages, context, **k):
        seen.append({"task": task, "context": context})
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(interpreter_client, "interpret", fake)
    return replies, seen


def match(menu_id=None, candidates=(), menu_text=None, custom_request=None):
    return {"item_ref": "i1", "candidates": [{"menu_id": c, "reason_tags": []} for c in candidates],
            "reason": "민트 초코는 민트 초콜릿 칩 블렌디드다", "menu_id": menu_id, "options": [], "unclear": [],
            "menu_text": menu_text, "custom_request": custom_request}


def test_menu_agent_fills_candidates_from_tools_but_never_confirms(service):
    replies, seen = service
    replies += [step(MenuStep, action="call_tool", tool="search_menu", args_json=json.dumps({"query": "민트 초코"})),
                step(MenuStep, matches=[match("sb_001", ["sb_001", "sb_999"])])]
    row, calls = agents.menu_agent(SESSION, ROW, [], route="add", service="primary", trace_id=None)
    assert calls == 2 and row["agent_tools"] == ["search_menu"]
    assert [c["menu_id"] for c in row["candidates"]] == ["sb_001"]          # 툴이 안 돌려준 sb_999 는 버린다
    assert row["menu_id"] is None                                            # 확정하지 않는다 — 담당자가 고른다
    assert row["candidates_by"] == "menu_agent"
    assert seen[0]["task"] == "normalize_menu" and seen[0]["context"]["agent"]["remaining"] == 2


def test_menu_agent_drops_menu_it_never_looked_up(service):
    replies, _ = service
    replies.append(step(MenuStep, matches=[match("sb_012", ["sb_012"])]))   # 툴 없이 기억으로 고름
    row, _ = agents.menu_agent(SESSION, ROW, [], route="add", service="primary", trace_id=None)
    assert row.get("candidates") == [] and "candidates_by" not in row


def test_menu_agent_failure_keeps_rule_result(service):
    replies, _ = service
    replies.append(interpreter_client.InterpreterError("DEP_TIMEOUT", "x", service="primary"))
    rule_row = {**ROW, "candidates": [{"menu_id": "sb_012", "name": "카페 라떼"}]}
    row, calls = agents.menu_agent(SESSION, rule_row, [], route="add", service="primary", trace_id=None)
    assert calls == 1 and row["candidates"] == rule_row["candidates"]


def test_menu_agent_budget_stops_second_search(service):
    replies, _ = service
    call = step(MenuStep, action="call_tool", tool="search_menu", args_json='{"query": "민트"}')
    replies += [call, call]
    row, calls = agents.menu_agent(SESSION, ROW, [], route="add", service="primary", trace_id=None)
    assert calls == 2 and row["agent_tools"] == ["search_menu"]             # add 경로 search_menu 1회 (D-10 5절)


def test_menu_agent_round_limit(service, monkeypatch):
    from app.tools import budget

    monkeypatch.setitem(budget.ROUTE_ALLOWANCE, "add", {"search_menu": 9})
    monkeypatch.setitem(budget.ROUTE_TOTAL, "add", 9)
    replies, seen = service
    replies += [step(MenuStep, action="call_tool", tool="search_menu", args_json='{"query": "민트"}')] * 3
    _, calls = agents.menu_agent(SESSION, ROW, [], route="add", service="primary", trace_id=None)
    assert calls == 3 and [s["context"]["agent"]["remaining"] for s in seen] == [2, 1, 0]


def test_bad_args_json_is_returned_to_llm(service):
    replies, seen = service
    replies += [step(MenuStep, action="call_tool", tool="search_menu", args_json="{not json"),
                step(MenuStep, matches=[match()])]
    row, _ = agents.menu_agent(SESSION, ROW, [], route="add", service="primary", trace_id=None)
    assert "거부됨" in seen[1]["context"]["agent"]["transcript"][0]["result"]
    assert row["agent_tools"] == []                                           # 거부된 호출은 예산을 안 쓴다


@pytest.mark.parametrize("state,row,expect", [
    ({"service": None, "agent_ok": True}, {"menu_id": None}, False),             # 규칙 모드
    ({"service": "primary", "agent_ok": False}, {"menu_id": None}, False),       # 분석 1회 상한 밖
    ({"service": "primary", "agent_ok": True}, {"menu_id": "sb_004"}, False),    # 규칙이 이미 정함
    ({"service": "primary", "agent_ok": True}, {"menu_id": None, "reference": True,
                                                "candidates": [{"menu_id": "sb_004"}]}, False),  # 참조 후보 있음
    ({"service": "primary", "agent_ok": True}, {"menu_id": None}, True),
])
def test_menu_agent_called_only_for_rule_unresolved(state, row, expect):
    assert nodes._needs_menu_agent(row, state) is expect


def test_review_agent_gives_opinion_without_verdict_power(service):
    replies, seen = service
    replies += [step(ReviewStep, action="call_tool", tool="list_order_items", args_json="{}"),
                step(ReviewStep, verdicts=[{"item_id": "ORD-0001-it_01", "evidence_message_ids": ["m2"],
                                            "target_item_ids": ["ORD-0001-it_01", "ORD-0001-it_02"],
                                            "reason": "두 잔 중 어느 쪽인지 대화에 없다. 이지연 5,100원",
                                            "verdict": "unsure"}])]
    import app.tools.order_tools as order_tools

    order_tools.db.fetch_all = lambda *a, **k: []
    row = {"item_id": "ORD-0001-it_01", "person": "김민수", "menu_name": "아이스 아메리카노", "quantity": 1,
           "review_reason_text": "어느 잔을 취소할지 확인해 주세요"}
    opinion, calls = agents.review_agent(SESSION, row, [], route="cancel", service="primary", trace_id=None)
    assert calls == 2 and seen[0]["task"] == "review"
    assert opinion["llm_review_verdict"] is None                              # unsure 는 저장 값 없음(D-07 CHECK)
    assert "5,100원" not in opinion["review_reason_text"]                      # 금액은 사유에 남기지 않는다
    assert "validation_status" not in opinion                                 # 판정 권한 없음


def test_agent_prompt_has_tools_and_no_identifiers():
    text = prompts.render_agent({"brand_id": "starbucks", "session_id": "ORD-0001",
                                 "agent": {"items": [{"item_ref": "i1", "summary": "민트 초코"}],
                                           "tools": [{"name": "search_menu", "description": "d", "params": "query"}],
                                           "transcript": [], "remaining": 2}},
                                [{"message_id": "m1", "sender": "최유나", "text": "그럼 난 그걸로"}])
    assert "search_menu" in text and "남은 툴 왕복: 2번" in text and "스타벅스 메뉴 기준" in text
    assert "ORD-0001" not in text and "starbucks" not in text


# --- 요청 나누기 (2026-11-04 · D-11 v1.2 menu.md 규칙 7 · 8) -------------------------------------
# LLM 은 원문을 (메뉴 부분, 요청 부분)으로 나누기만 하고, 메뉴는 규칙이 다시 맞춘다. 양방향으로 본다.
ORIGINAL = "아이스 라떼 바닐라빈 파우더 조금 뿌려 주세요"


def test_split_is_accepted_when_both_parts_come_from_the_original():
    got = agents.request_split(ORIGINAL, match(menu_text="아이스 라떼", custom_request="바닐라빈 파우더 조금 뿌려 주세요"))
    assert got == {"menu_text": "아이스 라떼", "custom_request": "바닐라빈 파우더 조금 뿌려 주세요"}


@pytest.mark.parametrize("menu_text, custom", [
    ("아이스 카페 라떼", "바닐라빈 파우더 조금"),        # 메뉴 부분을 메뉴판 이름으로 고쳐 썼다 — 원문에 없다
    ("아이스 라떼", "시나몬 파우더 조금"),               # 요청 부분을 지어냈다
    ("라떼", "헤이즐넛"),                                # 맛 이름만 뗐다 — 요청이 아니라 다른 메뉴다(규칙 8)
    ("아이스 라떼", None),                               # 한쪽이 비었다
])
def test_split_is_rejected(menu_text, custom):
    original = "헤이즐넛 라떼" if custom == "헤이즐넛" else ORIGINAL
    assert agents.request_split(original, match(menu_text=menu_text, custom_request=custom)) is None


def test_split_menu_is_confirmed_by_rules_and_request_is_kept(monkeypatch):
    def fake_match_one(item, *a):
        hit = item["match_text"] == "아이스 라떼"
        return {**item, "menu_id": "sb_003" if hit else None, "candidates": []}

    monkeypatch.setattr(nodes, "match_one", fake_match_one)
    row = {"menu_id": None, "custom_request": None, "agent_tools": ["search_menu"],
           "llm_split": {"menu_text": "아이스 라떼", "custom_request": "바닐라빈 파우더 조금"}}
    out = nodes._retry_with_split(row, {"match_text": ORIGINAL}, {"event": {}, "events": [], "index": 0,
                                                                  "session": SESSION})
    assert out["menu_id"] == "sb_003" and out["matched_by"] == "rule_after_llm_split"
    assert out["custom_request"] == "바닐라빈 파우더 조금"


def test_split_that_rules_still_cannot_match_keeps_the_request(monkeypatch):
    monkeypatch.setattr(nodes, "match_one", lambda item, *a: {**item, "menu_id": None})
    row = {"menu_id": None, "custom_request": None, "candidates": [{"menu_id": "sb_003"}],
           "llm_split": {"menu_text": "라떼 비슷한 거", "custom_request": "파우더 조금"}}
    out = nodes._retry_with_split(row, {}, {"event": {}, "events": [], "index": 0, "session": SESSION})
    assert out["menu_id"] is None and out["candidates"] == [{"menu_id": "sb_003"}]   # 에이전트 후보 그대로
    assert out["custom_request"] == "파우더 조금"                                     # 요청은 남는다
