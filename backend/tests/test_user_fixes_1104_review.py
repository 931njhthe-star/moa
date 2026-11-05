# 2026-11-04 사용자 보고 수정분 — #1 군말 섞인 주문 · #2 버튼 없는 대상 확인 질문 · #3 · #4 채팅으로 질문에 답하기
# (DB 없이 돈다. 실제 DB · LLM 으로 본 전체 흐름 확인은 화면에서 했다)
import pytest

from app import db
from app.graph import nodes
from app.services import edits, intake, questions, sessions
from tests import q03_fakes as F


def _match(text):
    item = intake.build_items(text, "이지연")[0]
    return item, sessions.match_item(item, brand_id=F.BRAND, menu_version=F.MENU_VERSION)


# --- #1 군말 · 웃음 · 공손 어미가 섞여도 메뉴를 확정한다 -------------------------------------------
@pytest.mark.parametrize("text, menu_id", [
    ("오 좋아요 ㅎㅎ 저는 아이스 카페라떼 그란데요!", "sb_003"),
    ("저는 아아 톨이요! 얼음 적게 부탁드려요", "sb_004"),
    ("넵 저 라떼 아이스로 부탁드립니다 ☕️", "sb_003"),
    ("음 아이스 바닐라라떼 해주세요 ㅋㅋ", "sb_006"),
])
def test_chatter_does_not_block_menu(monkeypatch, text, menu_id):
    F.install(monkeypatch, F.Store())
    _, hit = _match(text)
    assert hit.get("menu_id") == menu_id


def test_chatter_keeps_options():
    item = intake.build_items("오 좋아요 ㅎㅎ 저는 아이스 카페라떼 그란데요!", "이지연")[0]
    assert item["options"] == {"size": "grande"}


@pytest.mark.parametrize("text", ["오 헤이즐넛 라떼요 ㅎㅎ", "오트 라떼요", "아몬드 라떼 하나"])
def test_unregistered_modifier_is_still_not_confirmed(monkeypatch, text):
    """군말은 **낱말 단위로만** 뗀다 — "오트"의 "오"가 지워지면 오트 라떼가 조용히 카페 라떼가 된다(SC-8)."""
    F.install(monkeypatch, F.Store())
    _, hit = _match(text)
    assert hit.get("menu_id") is None


def test_ne_jan_is_quantity_not_filler():
    assert intake.build_items("아아 네 잔이요", "이지연")[0]["quantity"] == 4


# --- #2 그 사람의 주문이 하나뿐이면 "어느 주문" 을 묻지 않는다 ----------------------------------
def _target(matched, events, monkeypatch):
    monkeypatch.setattr(nodes, "match_one", lambda item, *a: {**item, "menu_id": item.get("menu_id")})
    state = {"session": F.SESSION, "source": "snapshot", "targets": {"ordered": events},
             "matched": [{"index": i, "k": 0, "row": r} for i, r in matched]}
    return nodes.target_node(state)


def _row(mid, person, menu_id, options=None):
    return {"_message_id": mid, "person": person, "menu_id": menu_id, "menu_name": menu_id,
            "menu_text": menu_id, "options": options or {}, "ambiguous_options": {}, "quantity": 1}


def test_update_on_only_order_is_applied_even_if_llm_unsure(monkeypatch):
    out = _target([(0, _row("m4", "최유나", "sb_004", {"size": "tall"}))],
                  [{"message_id": "m4", "route": "add", "person": "최유나"},
                   {"message_id": "m14", "route": "update", "person": "최유나", "target_unclear": True,
                    "_raw_text": "아 맞다 저 디카페인으로 해주세요!",
                    "items": [{"options": {"bean": "decaf"}}]}], monkeypatch)
    row = out["rows"][0]
    assert row["options"] == {"size": "tall", "bean": "decaf"} and not row.get("_target_unclear_text")


def test_update_with_two_orders_still_asks(monkeypatch):
    out = _target([(0, _row("m1", "최유나", "sb_004")), (1, _row("m2", "최유나", "sb_003"))],
                  [{"message_id": "m1", "route": "add", "person": "최유나"},
                   {"message_id": "m2", "route": "add", "person": "최유나"},
                   {"message_id": "m3", "route": "update", "person": "최유나", "target_unclear": True,
                    "_raw_text": "디카페인으로 해주세요", "items": [{"options": {"bean": "decaf"}}]}],
                  monkeypatch)
    assert any(r.get("_target_unclear_text") for r in out["rows"])


# --- #2 대상 확인 질문에는 언제나 버튼이 있다 ------------------------------------------------------
def _target_question(change_text):
    row = {"item_id": "it_03", "person": "최유나", "menu_id": "sb_004", "menu_name": "아이스 아메리카노",
           "menu_text": "저는 아아 톨이요", "review_reason": "ambiguous_target"}
    return questions.build(row, session_id="ORD-0001", brand_id=F.BRAND, menu_version=F.MENU_VERSION,
                           seq=2, change_text=change_text)


def test_target_question_with_change_has_apply_and_keep(monkeypatch):
    F.install(monkeypatch, F.Store())
    q = _target_question("아 맞다 저 디카페인으로 해주세요!")
    assert q["question_text"] == '최유나 님 "아 맞다 저 디카페인으로 해주세요"는 아이스 아메리카노 주문을 말하는 건가요?'
    assert [o["value"] for o in q["options"]] == [questions.TARGET_APPLY, questions.TARGET_KEEP]
    assert q["options"][0]["change_text"] == "아 맞다 저 디카페인으로 해주세요!"


def test_target_question_names_options_to_tell_cups_apart(monkeypatch):
    """같은 메뉴 두 잔이 후보면 질문이 똑같아진다 — 옵션을 붙여 어느 잔인지 보이게 한다."""
    F.install(monkeypatch, F.Store())
    row = {"item_id": "it_02", "person": "김민수", "menu_id": "sb_004", "menu_name": "아이스 아메리카노",
           "options": {"size": "tall", "shot": "extra"}, "review_reason": "ambiguous_target"}
    q = questions.build(row, session_id="ORD-0001", brand_id=F.BRAND, menu_version=F.MENU_VERSION,
                        seq=1, change_text="하나는 디카페인으로 바꿔주세요")
    assert "아이스 아메리카노(톨 · 샷 추가) 주문을" in q["question_text"]


def test_target_question_without_change_still_has_a_button(monkeypatch):
    F.install(monkeypatch, F.Store())
    assert [o["value"] for o in _target_question(None)["options"]] == [questions.TARGET_KEEP]


# --- #3 · #4 채팅 문장 → 열린 질문의 답 -----------------------------------------------------------
@pytest.fixture
def people(monkeypatch):
    F.install(monkeypatch, F.Store())
    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None, **k:
                        [{"person": p} for p in ("최유나", "박서연", "이지연")])


def _q(reason, options, person="이지연", ambiguous=None):
    return {"reason": reason, "options": options, "person": person, "ambiguous_options": ambiguous or {}}


MENU_OPTIONS = [{"value": "아이스 카페 라떼", "label": "아이스 카페 라떼"}]


@pytest.mark.parametrize("said, value", [
    ("아이스아메리카노", "아이스 아메리카노"),          # 보고 3 — 이름 없는 메뉴 이름
    ("아이스 카페 라떼로 해주세요", "아이스 카페 라떼"),   # 버튼 라벨을 그대로
    ("그냥 아아로 할게요", "아이스 아메리카노"),
    ("라떼 차갑게요", "아이스 카페 라떼"),               # 온도 단서로 아이스 판
])
def test_menu_question_reads_menu_from_chat(people, said, value):
    assert edits._text_answer(F.SESSION, _q("unregistered_menu", MENU_OPTIONS), said) == value


def test_other_persons_name_is_not_an_answer(people):
    """"박서연 라떼로"는 박서연 주문 수정이다 — 지금 질문(이지연)의 답으로 가로채지 않는다."""
    with pytest.raises(edits.NotApplicable):
        edits._text_answer(F.SESSION, _q("unregistered_menu", MENU_OPTIONS), "박서연 님 라떼로 바꿔줘")


def test_unrelated_chat_is_not_an_answer(people):
    with pytest.raises(edits.NotApplicable):
        edits._text_answer(F.SESSION, _q("unregistered_menu", MENU_OPTIONS), "고마워요")


def test_size_and_quantity_from_chat(people):
    sizes = [{"value": "tall", "label": "톨"}, {"value": "grande", "label": "그란데"}]
    assert edits._text_answer(F.SESSION, _q("ambiguous_spec", sizes, ambiguous={"size": '"큰 거"'}),
                              "그란데로 해주세요") == "grande"
    qty = [{"value": "1", "label": "1잔"}, {"value": "2", "label": "2잔"}]
    assert edits._text_answer(F.SESSION, _q("ambiguous_spec", qty, ambiguous={"quantity": "0잔"}),
                              "3잔이요") == "3"


def test_target_question_yes_no_from_chat(people):
    options = [{"value": questions.TARGET_APPLY, "label": "네, 바꿔 주세요"},
               {"value": questions.TARGET_KEEP, "label": "아니에요, 그대로 둘게요"}]
    q = _q("ambiguous_target", options, person="최유나")
    assert edits._text_answer(F.SESSION, q, "네 맞아요") == questions.TARGET_APPLY
    assert edits._text_answer(F.SESSION, q, "아니요 그대로요") == questions.TARGET_KEEP
    assert edits._text_answer(F.SESSION, q, "아이스 카페 라떼로 바꿀게요") == "아이스 카페 라떼"   # 보고 4
