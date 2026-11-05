# 2026-11-05 3차 사용자 보고 — 한 잔 더 · 맞장구 · 누락 채우기 · 제안 게이트 (DB 없이)
#
# 1 정리하기 버튼 · 2 분석 지연 · 3 패널 순번 은 화면 · 측정 쪽이라 여기 없다
#   (화면: frontend/tests/test_user_fixes_1105c_screens.py · 측정: 보고서 본문)
import pytest

from app.services import consolidate
from tests import q03_fakes as F
from tests.test_user_fixes_1105 import _llm_item, only_row, run_rules, run_with_llm


@pytest.fixture
def store():
    return F.Store()


# --- "한 잔 더"는 추가, "그 잔의 사양"은 변경 ------------------------------------------------
def test_one_more_cup_is_added_even_when_the_llm_says_update(monkeypatch, store):
    """LLM 이 update 로 봐도 **안 시킨 메뉴를 더 말하면** 한 잔 더다 — 앞 주문을 덮어쓰지 않는다."""
    out = run_with_llm(monkeypatch, store, [
        "[김민수 대리] 아이스 아메리카노 톨 하나요",
        "[김민수 대리] 아 저 카페 라떼도 하나 추가요",
    ], [("m1", "add", [_llm_item("아이스 아메리카노 톨")]),
        ("m2", "update", [_llm_item("카페 라떼")])])

    assert [e["route"] for e in out["targets"]["ordered"]] == ["add", "add"]
    menus = sorted(r["menu_name"] for r in store.live())
    assert menus == ["아이스 아메리카노", "카페 라떼"], menus


def test_option_change_on_the_same_menu_is_still_an_update(monkeypatch, store):
    """"아까 그 라떼에 샷 하나 더" — 말한 메뉴가 이미 시킨 그 메뉴면 변경이다."""
    out = run_with_llm(monkeypatch, store, [
        "[정하준 대리] 저는 아이스 바닐라라떼 하나요",
        "[정하준 대리] 아까 바닐라라떼 주문했는데 샷 하나 더 추가해주세요",
    ], [("m1", "add", [_llm_item("아이스 바닐라라떼")]),
        ("m2", "update", [_llm_item("바닐라라떼 샷 추가", option_texts=["shot=extra"])])])

    assert [e["route"] for e in out["targets"]["ordered"]] == ["add", "update"]
    row = only_row(store)
    assert row["menu_name"] == "아이스 바닐라라떼" and row["options"].get("shot") == "extra"


@pytest.mark.parametrize("text, mine, expected", [
    ("아 저 카페 라떼도 하나 추가요", set(), True),
    ("카페 라떼 하나 더 주세요", set(), True),
    ("아까 라떼 주문했는데 샷 하나 더 추가해주세요", {"sb_012"}, False),   # 이미 시킨 메뉴
    ("라떼 말고 아아로 바꿔주세요", set(), False),                        # 바꿈 말이 있으면 변경
    ("그냥 하나 더 주세요", set(), False),                               # 메뉴를 말하지 않았다
])
def test_one_more_rule(monkeypatch, text, mine, expected):
    from app.services import menu as menu_service

    monkeypatch.setitem(menu_service._CACHE, (F.BRAND, F.MENU_VERSION), F.catalog())
    assert consolidate._is_one_more({}, text, mine, brand_id=F.BRAND,
                                    menu_version=F.MENU_VERSION) is expected


# --- 맞장구 재확인 (3차 보고 4번) ------------------------------------------------------------
def test_ack_from_the_llm_is_dropped_too(monkeypatch, store):
    """규칙뿐 아니라 LLM 이 "넵"에 항목을 붙여 와도 항목이 되지 않는다."""
    out = run_with_llm(monkeypatch, store, [
        "[이지연 사원] 저는 카페 라떼 하나 주세요",
        "[김민수 대리] 넵",
    ], [("m1", "add", [_llm_item("카페 라떼")]),
        ("m2", "add", [_llm_item("넵")])])

    assert [e["route"] for e in out["targets"]["ordered"]] == ["add", "ignore"]
    assert [r["person"] for r in store.live()] == ["이지연 사원"]


# --- 누락 채우기 (3차 보고 2번 · 지연) --------------------------------------------------------
def test_missing_message_is_filled_without_extra_calls(monkeypatch, store):
    """모델이 빠뜨린 메시지는 규칙으로 채운다 — 묶음 재생성(호출 3배)을 하지 않는다."""
    out = run_with_llm(monkeypatch, store, [
        "[이지연 사원] 저는 카페 라떼 하나 주세요",
        "[김민수 대리] 아이스 아메리카노 톨 하나요",
    ], [("m1", "add", [_llm_item("카페 라떼")])])          # m2 를 빠뜨린 응답

    assert out.get("llm_calls") == 1, out.get("llm_calls")
    menus = sorted(r["menu_name"] for r in store.live())
    assert menus == ["아이스 아메리카노", "카페 라떼"], menus
