# 메뉴별 옵션 — 허용 검증 · 추가금 · 화면 버튼 · 기본값이 같은 범위 규칙을 쓴다
#
# 범위: 매장 공통 < 분류 < 메뉴. 옵션 종류마다 가장 구체적인 범위의 행만 쓴다(menu.applicable_options).
# 양방향으로 본다 — 허용돼야 할 것은 허용되고(공통 행), 막혀야 할 것은 막힌다(분류 · 메뉴 범위의 덮어쓰기).
import pytest

from app.services import menu, settlement, validation


def opt(option_id, group, value, price=0, *, menu_id=None, category=None, default=False):
    return {"option_id": option_id, "menu_id": menu_id, "category": category, "option_group": group,
            "option_value": value, "value_label": value, "extra_price": price, "is_default": default}


CAT = {
    "by_id": {"sb_001": {"menu_id": "sb_001", "name": "아메리카노", "category": "커피", "base_price": 4700},
              "sb_010": {"menu_id": "sb_010", "name": "자몽 허니 블랙 티", "category": "티", "base_price": 5700},
              "sb_020": {"menu_id": "sb_020", "name": "카페 라떼", "category": "커피", "base_price": 5000},
              "sb_030": {"menu_id": "sb_030", "name": "에스프레소", "category": "커피", "base_price": 4000}},
    "menus": [], "alias_index": {},
    "options": [
        opt("size_tall", "size", "tall", 0, default=True), opt("size_grande", "size", "grande", 600),
        opt("size_venti", "size", "venti", 1000),
        opt("shot_base", "shot", "base", 0, default=True), opt("shot_extra", "shot", "extra", 600),
        opt("milk_normal", "milk", "normal", 0, default=True), opt("milk_oat", "milk", "oat", 800),
        # 티 분류 — 샷은 기본만(샷 추가 불가)
        opt("tea_shot_base", "shot", "base", 0, category="티", default=True),
        # 카페 라떼 — 오트 우유 추가금이 다르다
        opt("latte_milk_normal", "milk", "normal", 0, menu_id="sb_020", default=True),
        opt("latte_milk_oat", "milk", "oat", 500, menu_id="sb_020"),
        # 에스프레소 — 사이즈는 솔로 하나뿐이고 그것이 기본
        opt("esp_size_solo", "size", "solo", 0, menu_id="sb_030", default=True),
    ],
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(menu, "catalog", lambda *a, **k: CAT)


def valid(group, value, menu_id):
    return menu.is_valid_option("starbucks", "mv", group, value, menu_id=menu_id)


def test_common_options_apply_to_every_menu():
    assert valid("shot", "extra", "sb_001") and valid("size", "venti", "sb_001")


def test_category_scope_blocks_an_option():
    assert not valid("shot", "extra", "sb_010")                            # 티에 샷 추가 불가
    assert valid("shot", "base", "sb_010")
    assert valid("size", "venti", "sb_010")                                # 다른 종류는 공통 그대로


def test_menu_scope_overrides_price():
    extra = lambda m: menu.option_extra_price("starbucks", "mv", {"milk": "oat"}, menu_id=m)  # noqa: E731
    assert extra("sb_020") == 500 and extra("sb_001") == 800


def test_menu_scope_replaces_sizes_and_default():
    assert not valid("size", "tall", "sb_030") and valid("size", "solo", "sb_030")
    assert menu.default_option("starbucks", "mv", "size", menu_id="sb_030") == "solo"
    assert menu.default_option("starbucks", "mv", "size", menu_id="sb_001") == "tall"


def test_buttons_follow_the_same_scope():
    groups = {g["option_group"]: [v["option_value"] for v in g["values"]]
              for g in menu.option_groups("starbucks", "mv", "sb_010")}
    assert groups["shot"] == ["base"] and groups["size"] == ["tall", "grande", "venti"]


def test_unknown_menu_sees_only_common_rows():
    assert valid("shot", "extra", None) and not valid("size", "solo", None)


def test_validation_fails_an_option_the_menu_does_not_allow():
    item = {"menu_id": "sb_010", "options": {"shot": "extra"}, "quantity": 1, "ambiguous_options": {}}
    assert validation.validate_item(item, brand_id="starbucks", menu_version="mv")["rule_verdict"] == "failed"
    ok = {**item, "menu_id": "sb_001"}
    assert validation.validate_item(ok, brand_id="starbucks", menu_version="mv")["rule_verdict"] == "passed"


def test_price_uses_the_menu_scope():
    item = {"menu_id": "sb_020", "options": {"size": "grande", "milk": "oat"}, "quantity": 2,
            "ambiguous_options": {}}
    assert settlement.item_price(item, brand_id="starbucks", menu_version="mv") == (6100, 12200)


# --- 참조 표현과 확인 필요 (2026-11-03) ---------------------------------------
def test_reference_flag_does_not_hold_a_resolved_menu():
    """메뉴가 그 메시지 자체로 확정됐으면 참조 표현이 섞여 있어도 확인 필요로 올리지 않는다.

    박서연 "아아 톨 한 잔이요"는 별칭으로 아이스 아메리카노가 확정되는데, LLM Intake 가
    그 메시지를 참조로 표시하면 확인 필요가 붙었다. 그러면 왼쪽 패널에는 아이스 아메리카노가
    들어가 있는데 질문은 앞선 대화 후보를 들고 "메뉴를 골라 주세요"라고 물어 화면이 어긋난다.
    """
    item = {"menu_id": "sb_001", "options": {"size": "tall"}, "quantity": 1,
            "ambiguous_options": {}, "reference": True}
    verdict = validation.validate_item(item, brand_id="starbucks", menu_version="mv")
    assert verdict["rule_verdict"] == "passed", verdict
    assert verdict["review_reason"] is None


def test_reference_without_a_menu_is_still_asked():
    """진짜 참조("그걸로 하나")는 메뉴가 안 정해진다 — 그때는 담당자에게 넘긴다."""
    item = {"menu_id": None, "options": {}, "quantity": 1, "ambiguous_options": {},
            "reference": True, "match_reason": "reference_menu"}
    verdict = validation.validate_item(item, brand_id="starbucks", menu_version="mv")
    assert verdict["validation_status"] == "needs_review"
    assert verdict["review_reason"] == "reference_menu"
