# 대리 주문 주문자 확인 — "서연이 것도 라떼"를 참여자 박서연에 **담당자가 맞다고 한 뒤에만** 잇는다 (2026-11-04)
#
# P-03 INT-002 · 평가셋 EV-006 · D-12 10.5. DB 없이 돈다(그래프 전체는 q03_fakes).
# 판정기 양방향(G-A0): 이어야 할 후보를 찾는가 + 이으면 안 되는 것(대명사 · 대화에 없는 사람 · 이름 그대로)을 건드리지 않는가.
import pytest

from app import graph
from app.graph import nodes
from app.services import intake, questions, validation
from tests import q03_fakes as F

PEOPLE = ["김민수", "이지연", "박서연", "최유나", "정하준"]


# --- 규칙 — 앞머리 · 후보 --------------------------------------------------------------------
@pytest.mark.parametrize("text,name", [
    ("서연이 것도 라떼 하나 추가요.", "서연"), ("민수 씨 대신 아아 하나", "민수"), ("지연이꺼 아아 톨", "지연"),
    ("하준 형 것도 아아", "하준"), ("박서연 것도 라떼", "박서연"),
    ("그거 라떼로", None), ("저도 같은 거", None), ("같은 거 하나", None), ("라떼 하나요", None),
])
def test_proxy_phrase(text, name):
    hit = intake.proxy_phrase(text)
    assert (hit[0] if hit else None) == name


@pytest.mark.parametrize("said,people,kind,candidates", [
    ("서연이", PEOPLE, "linked", ["박서연"]),
    ("민수 씨", PEOPLE, "linked", ["김민수"]),
    ("유나 언니", PEOPLE, "linked", ["최유나"]),
    ("박서연", PEOPLE, "exact", ["박서연"]),
    ("서연이", PEOPLE + ["김서연"], "ambiguous", ["박서연", "김서연"]),   # 고르지 않는다
    ("엄마", PEOPLE, "outsider", []),
    ("아이스", PEOPLE, "outsider", []),
])
def test_link_person_finds_candidates_only(said, people, kind, candidates):
    assert intake.link_person(said, people) == (kind, candidates)


# --- N-04 — 후보만 단다 · 주문자는 그대로 ----------------------------------------------------
MSGS = [{"message_id": "m1", "seq": 1, "sender": "박서연", "text": "저는 조금 이따 볼게요"},
        {"message_id": "m2", "seq": 2, "sender": "김민수", "text": "서연이 것도 라떼 하나 추가요."}]


def _event(person, text="서연이 것도 라떼 하나 추가요.", message_id="m2"):
    items = intake.build_items(text, person)
    return {"message_id": message_id, "person": person, "route": "add", "_raw_text": text, "items": items}


def test_llm_proxy_name_gets_a_check_not_a_link():
    event = _event("서연이")                                   # LLM 이 낸 주문자
    nodes._link_persons([event], MSGS)
    item = event["items"][0]
    assert item["person"] == "서연"                            # 확인 전에는 참여자로 바꾸지 않는다(호칭 · 조사만 뗌)
    assert item["person_check"] == {"said": "서연", "candidates": ["박서연"]}
    assert item["match_text"].startswith("라떼")               # 앞머리를 떼야 메뉴가 확정된다


def test_rule_path_reads_proxy_from_the_sentence():
    event = _event("김민수")                                   # 규칙 해석은 발신자를 넣는다
    nodes._link_persons([event], MSGS)
    assert event["items"][0]["person"] == "서연"
    assert event["items"][0]["person_check"]["candidates"] == ["박서연"]


def test_full_name_in_the_sentence_is_not_asked():
    event = _event("김민수", "박서연 것도 라떼 하나요")
    nodes._link_persons([event], MSGS)
    assert event["items"][0]["person"] == "박서연" and not event["items"][0].get("person_check")


def test_llm_full_name_not_in_the_sentence_is_still_asked():
    event = _event("박서연")                                   # LLM 이 성까지 붙여 줬지만 원문은 "서연이"
    nodes._link_persons([event], MSGS)
    assert event["items"][0]["person_check"] == {"said": "서연", "candidates": ["박서연"]}


@pytest.mark.parametrize("person,text", [
    ("김민수", "아이스 거 말고 라떼로"),      # 이름처럼 생겼지만 참여자가 아니다
    ("김민수", "라떼 하나 추가요"),           # 대리 주문 아님
])
def test_non_proxy_messages_are_untouched(person, text):
    event = _event(person, text)
    before = [dict(i) for i in event["items"]]
    nodes._link_persons([event], MSGS)
    assert event["items"] == before


def test_honorific_is_not_shown_twice():
    event = _event("민수 씨", "민수 씨 대신 아아 하나")
    nodes._link_persons([event], MSGS)
    assert event["items"][0]["person_check"] == {"said": "민수", "candidates": ["김민수"]}


def test_outsider_named_by_llm_stays_without_question():
    event = _event("엄마", "엄마 거 라떼 하나")
    nodes._link_persons([event], MSGS)
    item = event["items"][0]
    assert item["person"] == "엄마" and not item.get("person_check")
    assert item["match_text"].startswith("라떼")


# --- N-07 · 질문 -----------------------------------------------------------------------------
def test_person_check_is_needs_review_and_asked_last():
    row = {"menu_id": "sb_012", "options": {}, "person_check": {"said": "서연이", "candidates": ["박서연"]}}
    assert validation.validate_item(row, brand_id="starbucks", menu_version="mv_20261029")["review_reason"] \
        == "ambiguous_person"
    both = validation._primary(["ambiguous_person", "unregistered_menu"])
    assert both == "unregistered_menu"                         # 메뉴부터 — 주문자는 후속 질문으로


def test_question_offers_candidate_and_keep_as_is():
    built = questions.build({"item_id": "i1", "person": "서연이", "menu_name": "카페 라떼",
                             "review_reason": "ambiguous_person",
                             "person_check": {"said": "서연이", "candidates": ["박서연"]}},
                            session_id="ORD-0001", brand_id="starbucks", menu_version="mv_20261029", seq=1)
    assert built["question_text"] == '"서연이" 님의 카페 라떼 주문이에요. 박서연 님 주문이 맞나요?'
    assert [o["value"] for o in built["options"]] == ["박서연", "서연이"]
    assert built["options"][0]["label"] == "박서연 님 맞아요"


def test_question_with_two_candidates_does_not_pick():
    built = questions.build({"item_id": "i1", "person": "서연이", "menu_name": "카페 라떼",
                             "review_reason": "ambiguous_person",
                             "person_check": {"said": "서연이", "candidates": ["박서연", "김서연"]}},
                            session_id="ORD-0001", brand_id="starbucks", menu_version="mv_20261029", seq=1)
    assert built["question_text"].endswith("누구 주문인가요?")
    assert [o["value"] for o in built["options"]] == ["박서연", "김서연", "서연이"]


# --- 그래프 전체 (규칙 해석 · DB 가짜) -------------------------------------------------------
def test_graph_proxy_order_menu_confirmed_person_pending(monkeypatch):
    store = F.Store()
    F.no_interpreter(monkeypatch)
    F.install(monkeypatch, store, messages=F.chat(["[박서연] 저는 조금 이따 볼게요",
                                                  "[김민수] 서연이 것도 라떼 하나 추가요."]))
    graph.run("snapshot", dict(F.SESSION), trace_id="tr_proxy")
    proxy = [r for r in store.live() if r["menu_id"] == "sb_012"]
    assert len(proxy) == 1                                     # 앞머리를 떼서 카페 라떼로 확정됐다
    assert proxy[0]["person"] == "서연"                        # 주문자는 아직 바꾸지 않았다
    assert proxy[0]["validation_status"] == "needs_review"
    assert proxy[0]["review_reason"] == "ambiguous_person"
    assert store.events[1]["items"][0]["person_check"]["candidates"] == ["박서연"]   # 재개 저장본에도 남는다
