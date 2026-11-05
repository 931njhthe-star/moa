# 2026-11-05 5차 사용자 보고 — ORD-0023(스타벅스 · 40메시지) 실측에서 나온 것. DB 없이 돈다
#
# 1 [다른 메뉴]가 20개로 잘렸다          2 주문 아닌 말이 확인 질문이 됐다("네네 변경 내용까지 확인했습니다~",
#                                          "일단 10잔으로 확인되네요", "혹시 저도 시켜도 되나요?", "ㅋㅋㅋㅋ 저도 고민되네요")
# 3 [대화 보기]가 엉뚱한 메시지를 보였다  4 "우유 오트밀크로 바꿔주세요"가 메뉴를 아메리카노로 바꾸고 failed 로 만들었다
# 5 모델이 빠뜨린 메시지를 규칙이 주문으로 채웠다
import pytest

from app.graph import nodes
from app.services import consolidate, intake
from app.services import menu as menu_service
from tests import q03_fakes as F
from tests.test_user_fixes_1105 import install_wide, run_rules

MILK = {"menu_id": "sb_027", "brand_id": F.BRAND, "menu_version": F.MENU_VERSION,
        "category": "기타 제조 음료", "name": "우유", "base_price": 3800, "trait_tags": ["카페인없음"]}
AMERICANO = {"menu_id": "sb_011", "brand_id": F.BRAND, "menu_version": F.MENU_VERSION,
             "category": "에스프레소", "name": "아메리카노", "base_price": 4500, "trait_tags": ["따뜻한"]}


@pytest.fixture
def store():
    return F.Store()


def run_with_milk_menu(monkeypatch, store, lines):
    """메뉴판에 "우유" · "아메리카노"가 있는 스타벅스 — 실제 시드와 같은 조건."""
    from app import graph
    from app.services.text_norm import normalize

    F.no_interpreter(monkeypatch)
    install_wide(monkeypatch, store, messages=F.chat(lines))
    cat = menu_service._CACHE[(F.BRAND, F.MENU_VERSION)]
    menus = list(cat["menus"]) + [MILK, AMERICANO]
    alias_index = {k: list(v) for k, v in cat["alias_index"].items()}
    for m in (MILK, AMERICANO):
        alias_index.setdefault(normalize(m["name"]), []).append(m["menu_id"])
    monkeypatch.setitem(menu_service._CACHE, (F.BRAND, F.MENU_VERSION),
                        {**cat, "menus": menus, "by_id": {m["menu_id"]: m for m in menus},
                         "alias_index": alias_index})
    return graph.run("snapshot", dict(F.SESSION), trace_id="tr_1105e")


# --- 1 메뉴 찾기는 전부 ---------------------------------------------------------------------
def test_menu_search_returns_every_menu_by_default(monkeypatch, store):
    install_wide(monkeypatch, store)
    cat = menu_service._CACHE[(F.BRAND, F.MENU_VERSION)]
    many = [{**F.MENUS[0], "menu_id": f"sb_x{i}", "name": f"테스트 음료 {i}"} for i in range(30)]
    monkeypatch.setitem(menu_service._CACHE, (F.BRAND, F.MENU_VERSION),
                        {**cat, "menus": list(cat["menus"]) + many,
                         "by_id": {**cat["by_id"], **{m["menu_id"]: m for m in many}}})
    assert len(menu_service.search(F.BRAND, F.MENU_VERSION, "")) == len(cat["menus"]) + 30
    assert len(menu_service.search(F.BRAND, F.MENU_VERSION, "", limit=5)) == 5     # 툴 호출은 그대로 5개


# --- 2 주문 아닌 말 ------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["일단 10잔으로 확인되네요! 최종 주문서 정리해서 공유하겠습니다~",
                                  "총 8잔이죠?", "모두 5잔 맞나요"])
def test_tally_is_not_an_order_pattern(text):
    assert intake.order_pattern(text) is False, text


def test_quantity_orders_are_still_orders():
    assert intake.order_pattern("아이스 아메리카노 2잔 주세요") is True
    assert intake.order_pattern("라떼 한 잔이요") is True


@pytest.mark.parametrize("chatter", [
    "[김민수 과장] 네네 변경 내용까지 확인했습니다~",
    "[김민수 과장] 일단 10잔으로 확인되네요! 최종 주문서 정리해서 공유하겠습니다~",
    "[김민수 과장] 다들 변경이 많으시네요 ㅋㅋ 주문 넣기 전에 한번 정리해야겠어요",
    "[강민호 사원] 혹시 저도 시켜도 되나요? ㅎㅎ",
])
def test_chatter_never_becomes_an_item(monkeypatch, store, chatter):
    run_rules(monkeypatch, store, ["[이지은 대리] 저는 아이스 카페라떼 그란데로 부탁드려요~", chatter])
    assert [r["person"] for r in store.live()] == ["이지은 대리"], \
        [(r["person"], r["menu_text"]) for r in store.live()]


def test_me_too_from_someone_who_already_ordered_is_not_another_cup(monkeypatch, store):
    run_rules(monkeypatch, store, ["[최서연 주임] 저도 아아 하나요 ㅋㅋ 근데 저는 그란데로요",
                                   "[최서연 주임] ㅋㅋㅋㅋ 저도 고민되네요"])
    assert len(store.live()) == 1


def test_asking_permission_with_a_menu_is_still_an_order(monkeypatch, store):
    run_rules(monkeypatch, store, ["[강민호 사원] 저도 아이스 카페라떼 시켜도 되나요?"])
    assert [r["person"] for r in store.live()] == ["강민호 사원"]


# --- 3 근거 메시지 ------------------------------------------------------------------------
def test_evidence_always_contains_the_events_own_message():
    messages = [{"message_id": "m1", "seq": 1, "sender": "김민수", "text": "드실 메뉴 남겨주세요"},
                {"message_id": "m2", "seq": 2, "sender": "이지은", "text": "아이스 카페라떼 그란데요"}]
    events = [{"message_id": "m2", "event_type": "add", "person": "이지은", "is_reference": False,
               "evidence_message_ids": ["m1"], "items": []},
              {"message_id": "m2", "event_type": "add", "person": "이지은", "is_reference": True,
               "evidence_message_ids": ["m1"], "items": []}]
    out = intake.from_contract(events, messages, known_ids={"m1", "m2"})
    assert out[0]["evidence_message_ids"] == ["m2"]            # 참조가 아니면 자기 메시지만
    assert out[-1]["evidence_message_ids"] == ["m1", "m2"]     # 참조면 앞 메시지 + 자기 메시지


# --- 4 옵션만 바꾸는 변경 -------------------------------------------------------------------
def test_milk_change_keeps_the_menu_and_moves_milk_to_request(monkeypatch, store):
    run_with_milk_menu(monkeypatch, store, [
        "[이지은 대리] 저는 아이스 카페라떼 그란데로 부탁드려요~",
        "[박준혁 사원] 아 제 아메리카노 샷 하나 추가해주세요!",
        "[이지은 대리] 저도 변경 하나만요~ 우유 오트밀크로 바꿔주세요",
    ])
    row = next(r for r in store.live() if r["person"] == "이지은 대리")
    assert row["menu_id"] == "sb_003", row                    # 아이스 카페 라떼 그대로
    assert "milk" not in (row.get("options") or {}), row      # 매장에 없는 옵션은 옵션에 남지 않는다
    assert "오트" in (row.get("custom_request") or ""), row
    assert row["validation_status"] != "failed", row


@pytest.mark.parametrize("menu_id, text, options, expected", [
    ("sb_006", "아이스 바닐라라떼로 바꿔주세요", {}, True),          # 메뉴를 말했다
    ("sb_003", "라떼로 바꿔줘", {}, True),                             # 온도만 다른 판은 같은 메뉴
    ("sb_011", "저도 변경 하나만요~ 우유 오트밀크로 바꿔주세요", {"milk": "oat"}, False),   # 남의 메뉴(참조)
    ("sb_027", "저도 변경 하나만요~ 우유 오트밀크로 바꿔주세요", {"milk": "oat"}, False),   # 우유 옵션의 "우유"
])
def test_change_menu_only_when_the_sentence_names_it(monkeypatch, store, menu_id, text, options, expected):
    run_with_milk_menu(monkeypatch, store, ["[이지은 대리] 아이스 카페라떼요"])
    assert nodes._names_menu(menu_id, text, options, F.BRAND, F.MENU_VERSION) is expected


# --- 5 모델이 빠뜨린 메시지 ------------------------------------------------------------------
def test_rule_filled_events_without_menu_are_demoted(monkeypatch, store):
    install_wide(monkeypatch, store)
    filled = intake.extract_events(
        [{"message_id": "m7", "seq": 7, "sender": "강민호", "text": "혹시 저도 시켜도 되나요? ㅎㅎ"},
         {"message_id": "m24", "seq": 24, "sender": "최서연", "text": "ㅋㅋㅋㅋ 저도 고민되네요"},
         {"message_id": "m32", "seq": 32, "sender": "한유진", "text": "저희 팀장님도 하나 부탁하신대요!"},
         {"message_id": "m9", "seq": 9, "sender": "강민호", "text": "아이스 카페라떼 그란데요!"}],
        brand_id=F.BRAND, menu_version=F.MENU_VERSION)
    monkeypatch.setattr("app.services.brand._dictionary", lambda: [])
    nodes._demote_unsupported(filled, dict(F.SESSION))
    assert {e["message_id"]: e["event_type"] for e in filled} == {
        "m7": "ignore", "m24": "ignore", "m32": "ignore", "m9": "add"}


def test_bare_menu_name_survives_demotion(monkeypatch, store):
    """"나 얼박사!"는 모델이 빠뜨려도 확인 필요로 남는다(4차 보고 3번과 같은 기준)."""
    install_wide(monkeypatch, store)
    monkeypatch.setattr("app.services.brand._dictionary", lambda: [])
    filled = intake.extract_events([{"message_id": "m1", "seq": 1, "sender": "민지", "text": "나 얼박사!"}],
                                   brand_id=F.BRAND, menu_version=F.MENU_VERSION)
    before = filled[0]["event_type"]
    assert before == "add", filled[0]                       # 규칙은 주문으로 읽는다
    nodes._demote_unsupported(filled, dict(F.SESSION))
    assert filled[0]["event_type"] == "add"                  # 강등하지 않는다


# --- 덧: 서비스 · 운영 비밀번호에 한글이 섞여도 500 이 아니다 ------------------------------------
def test_non_ascii_password_is_just_wrong(monkeypatch):
    from app import config
    from app.services import ops_auth
    monkeypatch.setattr(config, "OPS_DASHBOARD_PASSWORD", "secret-123")
    assert ops_auth.login("비밀번호 # 주석") is None
    assert ops_auth.login("secret-123") is not None
