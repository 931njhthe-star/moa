# 에이전트 런타임 프롬프트 · 계약 — D-11 명세가 코드에 그대로 있는지 (D-14)
#
# 문장의 정본은 D-11 이고, prompts/*.md 는 그 사본이다. 여기서는 "조립이 명세대로인가"를 본다.
# 문장 자체의 품질(경로 정확도)은 테스트가 아니라 측정이다 — tools/d14_prompt_check.py · Q-05.
import json

import pytest

from app import llm, prompts
from app.contracts import TASK_CONTRACTS, OrderEvents

CTX = {"brand_id": "starbucks", "menu_version": "mv_20261029", "menu_as_of": "2026-10-29",
       "session_id": "ORD-0001",
       "existing_items": [{"message_id": "m1", "person": "김민수", "menu_text": "아이스 아메리카노",
                           "quantity": 2, "options": {"size": "톨"}}],
       "prev_messages": [{"message_id": "m1", "sender": "김민수", "text": "아아 톨 2잔이요"}]}
MSGS = [{"message_id": "m2", "sender": "이지연", "text": "저도 같은 걸로요"}]


@pytest.mark.parametrize("name", ["system.md", "classify.md", "menu.md", "review.md", "context_tmpl.md"])
def test_prompt_files_exist(name):
    assert prompts.load(name)


@pytest.mark.parametrize("task,head", [("extract_events", "작업: 단톡방 메시지를 읽고"),
                                       ("normalize_menu", "작업: 주문 항목의 메뉴 표현을"),
                                       ("review", "작업: 규칙이 정하지 못한")])
def test_system_is_common_rules_plus_task_file(task, head):
    system = prompts.system_for(task)
    assert system.startswith("당신은 친구 · 동아리 · 가족이")                 # 공통 7규칙이 앞
    assert head in system
    assert "{" not in system                                               # 가변 값이 없다(캐시 규칙)


def test_every_task_has_a_prompt_and_a_contract():
    assert set(prompts.TASK_PROMPTS) == set(TASK_CONTRACTS)


def test_intake_prompt_has_no_tools_and_menu_prompt_does():
    assert "search_menu" not in prompts.system_for("extract_events")       # Intake 는 메뉴판을 보지 않는다
    assert "search_menu" in prompts.system_for("normalize_menu")


def test_context_sections_are_filled_in_order():
    text = prompts.render_context(CTX, MSGS)
    assert "매장 기준: 스타벅스 메뉴 기준" in text and "메뉴 기준일: 2026-10-29" in text
    lines = text.splitlines()
    assert lines.index("[앞 메시지]") < lines.index("m1 [김민수] 아아 톨 2잔이요") \
        < lines.index("[이번에 해석할 메시지]") < lines.index("m2 [이지연] 저도 같은 걸로요")
    assert "m1 김민수: 아이스 아메리카노 2잔 톨" in lines


def test_context_never_carries_identifiers():
    text = prompts.render_context(CTX, MSGS)
    for raw in ("starbucks", "ORD-0001", "mv_20261029"):                   # 라벨만, 식별자는 없다
        assert raw not in text


def test_empty_sections_say_none():
    text = prompts.render_context({"brand_id": "generic"}, MSGS)
    assert text.count("없음") == 2                                          # 이미 정리된 주문 · 앞 메시지
    assert "일반 카페 메뉴 기준" in text


@pytest.mark.parametrize("task", sorted(TASK_CONTRACTS))
def test_contracts_are_strict_schema_ready(task):
    schema = llm.strict_schema(TASK_CONTRACTS[task].model_json_schema())
    json.dumps(schema)
    assert "additionalProperties" in json.dumps(schema)


def test_order_event_field_order_puts_evidence_before_verdict():
    fields = list(OrderEvents.model_fields["events"].annotation.__args__[0].model_fields)
    assert fields.index("evidence_message_ids") < fields.index("target_message_id") \
        < fields.index("reason") < fields.index("event_type") < fields.index("person")


def test_contracts_have_no_price_fields():
    blob = json.dumps({t: c.model_json_schema() for t, c in TASK_CONTRACTS.items()}, ensure_ascii=False)
    for word in ("price", "amount", "total"):
        assert word not in blob                                            # D-11 금지 2 · 5
