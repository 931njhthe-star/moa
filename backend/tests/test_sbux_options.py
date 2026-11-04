# 스타벅스 메뉴별 옵션 5종 (2026-11-04 · 스타벅스_메뉴별_옵션정리.xlsx)
#
# 스타벅스는 size · ice · shot · bean · cup 만 메뉴판 옵션이고, 공통 행 없이 메뉴마다 적는다.
# 메뉴에 그 종류가 없는 옵션(두유 · 시럽 · 따뜻한 메뉴의 얼음)은 기타 요청으로 옮긴다.
# 양방향으로 본다 — 옮겨야 할 것은 옮기고, 남겨야 할 것(종류는 있고 값만 막힌 것)은 남긴다.
import pytest

from app.services import intake, menu, sessions


def opt(menu_id, group, value, price=0, default=False):
    return {"option_id": f"{menu_id}_{group}_{value}", "menu_id": menu_id, "category": None,
            "option_group": group, "option_value": value, "value_label": value,
            "extra_price": price, "is_default": default}


def rows(menu_id, groups, sizes=("tall", "grande", "venti")):
    values = {"size": [(s, {"grande": 600, "venti": 1000}.get(s, 0), s == "tall") for s in sizes],
              "ice": [("none", 0, False), ("less", 0, False), ("normal", 0, True), ("more", 0, False)],
              "shot": [("base", 0, True), ("extra", 600, False)],
              "bean": [("signature", 0, True), ("blonde", 0, False), ("decaf", 300, False)],
              "cup": [("none", 0, True), ("personal", 0, False)]}
    return [opt(menu_id, g, v, p, d) for g in groups for v, p, d in values[g]]


CAT = {
    "by_id": {"sb_004": {"menu_id": "sb_004", "name": "아이스 아메리카노", "category": "에스프레소"},
              "sb_011": {"menu_id": "sb_011", "name": "아메리카노", "category": "에스프레소"},
              "sb_018": {"menu_id": "sb_018", "name": "에스프레소", "category": "에스프레소"},
              "sb_002": {"menu_id": "sb_002", "name": "자바 칩 프라푸치노", "category": "블렌디드"},
              "sb_023": {"menu_id": "sb_023", "name": "아이스 얼 그레이 티", "category": "티"}},
    "menus": [], "alias_index": {},
    "options": (rows("sb_004", ["size", "ice", "shot", "bean", "cup"])
                + rows("sb_011", ["size", "shot", "bean", "cup"])
                + rows("sb_018", ["shot", "bean", "cup"], sizes=())
                + rows("sb_002", ["size", "ice", "cup"])
                + rows("sb_023", ["size", "ice", "cup"], sizes=("tall", "venti"))),
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(menu, "catalog", lambda *a, **k: CAT)


def groups(menu_id):
    return {g["option_group"] for g in menu.option_groups("starbucks", "mv", menu_id)}


# --- 메뉴마다 다른 옵션 종류 ------------------------------------------------------
def test_each_menu_shows_only_its_groups():
    assert groups("sb_004") == {"size", "ice", "shot", "bean", "cup"}
    assert groups("sb_011") == {"size", "shot", "bean", "cup"}          # 따뜻한 메뉴에 얼음 없음
    assert groups("sb_002") == {"size", "ice", "cup"}                   # 블렌디드에 샷 · 원두 없음
    assert groups("sb_018") == {"shot", "bean", "cup"}                  # 에스프레소는 사이즈 선택 없음


def test_menu_sizes_follow_the_sheet():
    assert menu.is_valid_option("starbucks", "mv", "size", "venti", menu_id="sb_023")
    assert not menu.is_valid_option("starbucks", "mv", "size", "grande", menu_id="sb_023")


def test_decaf_costs_300():
    assert menu.option_extra_price("starbucks", "mv", {"bean": "decaf"}, menu_id="sb_004") == 300


def test_undecided_menu_checks_against_the_union():
    """공통 행이 없어도 메뉴를 고르기 전의 "벤티" · "샷 추가"는 옵션 오류가 아니다."""
    assert menu.is_valid_option("starbucks", "mv", "size", "venti", menu_id=None)
    assert menu.is_valid_option("starbucks", "mv", "ice", "none", menu_id=None)
    assert not menu.is_valid_option("starbucks", "mv", "milk", "soy", menu_id=None)


# --- 기타 요청으로 옮기기 ---------------------------------------------------------
def test_unoffered_groups_move_and_offered_stay():
    kept, moved = menu.split_unoffered("starbucks", "mv",
                                       {"size": "grande", "milk": "soy", "ice": "less"}, "sb_011")
    assert kept == {"size": "grande"}
    assert moved == {"milk": "soy", "ice": "less"}


def test_blocked_value_in_an_offered_group_is_not_moved():
    """종류는 있는데 값이 막힌 것(얼 그레이 그란데)은 옮기지 않는다 — 사이즈 질문이 잡는다."""
    kept, moved = menu.split_unoffered("starbucks", "mv", {"size": "grande"}, "sb_023")
    assert kept == {"size": "grande"} and moved == {}


def test_nothing_moves_before_the_menu_is_known():
    kept, moved = menu.split_unoffered("starbucks", "mv", {"milk": "soy"}, None)
    assert kept == {"milk": "soy"} and moved == {}


def test_spec_checks_moves_soy_milk_into_custom_request_with_the_original_words():
    item = intake.build_items("아이스 아메리카노 오트밀크로 해주세요", "박서연")[0]
    item = {**item, "menu_id": "sb_004"}
    out = sessions._spec_checks(item, brand_id="starbucks", menu_version="mv")
    assert "milk" not in out["options"]
    assert out["custom_request"] == "오트밀크"


def test_moved_word_is_not_repeated_in_custom_request():
    assert intake.move_to_custom("두유로 바꿔 주세요", {"milk": "soy"}) == "두유로 바꿔 주세요"
    assert intake.move_to_custom(None, {"syrup": "add"}) == "시럽 추가"
    assert intake.move_to_custom("빨대 빼 주세요", {"milk": "oat"}) == "빨대 빼 주세요, 오트 우유"


# --- 새 옵션 읽기 ------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [
    ("아아 얼음 빼고 주세요", {"ice": "none"}),
    ("아아 얼음 없이", {"ice": "none"}),
    ("아아 얼음 적게", {"ice": "less"}),
    ("디카페인 라떼", {"bean": "decaf"}),
    ("1/2 디카페인 라떼", {"bean": "half_decaf"}),
    ("블론드 아메리카노", {"bean": "blonde"}),
    ("아아 개인컵에 주세요", {"cup": "personal"}),
    ("아아 텀블러로", {"cup": "personal"}),
])
def test_new_option_rules(text, expected):
    assert intake._options(text) == expected


def test_option_words_are_stripped_from_the_menu_text():
    """옵션 말이 메뉴 표현에 남으면 엄격 매칭이 미등록으로 본다("디카페인" + 아메리카노)."""
    assert intake._menu_text("디카페인 아메리카노") == "아메리카노"
    assert intake._menu_text("아아 텀블러로") == "아아"


# --- 메뉴판이 커지면서 생긴 오매칭 (2026-11-04 · Q-02 EV-045) -----------------------
def test_one_letter_reply_does_not_confirm_a_menu(monkeypatch):
    """"네~"가 레모"네"이드의 일부로 걸려 딸기 아사이 레모네이드로 자동 확정됐다."""
    cat = {"by_id": {"sb_x": {"menu_id": "sb_x", "name": "딸기 아사이 레모네이드", "base_price": 6100,
                              "category": "리프레셔", "trait_tags": []}},
           "alias_index": {"딸기아사이레모네이드": ["sb_x"]}, "menus": [], "options": []}
    monkeypatch.setattr(menu, "catalog", lambda *a, **k: cat)
    assert menu.match("starbucks", "mv", "네~", strict=True)["menu_id"] is None
    assert menu.match("starbucks", "mv", "레모네", strict=True)["menu_id"] == "sb_x"   # 두 글자 이상은 그대로


# --- 기타 요청 옵션 표현 (시럽 · 우유 · 휘핑·드리즐 · 기타 열) ------------------------------------
@pytest.mark.parametrize("text, menu_text, custom", [
    ("아이스 라떼 저지방 우유로", "아이스 라떼", "저지방 우유로"),
    ("아이스 라떼 헤이즐넛 시럽 넣어주세요", "아이스 라떼", "헤이즐넛 시럽 넣어주세요"),
    ("아이스 라떼 휘핑 많이", "아이스 라떼", "휘핑 많이"),
    ("바닐라 라떼 시럽 두 펌프만", "바닐라 라떼", "시럽 두 펌프만"),
    ("아이스 카페 모카 초코 드리즐 추가", "아이스 카페 모카", "초코 드리즐 추가"),
    ("아이스 라떼 우유 많이", "아이스 라떼", "우유 많이"),
])
def test_request_phrases_leave_the_menu_and_go_to_custom_request(text, menu_text, custom):
    item = intake.build_items(text, "김민수")[0]
    assert item["match_text"] == menu_text
    assert item["custom_request"] == custom


def test_menu_words_alone_are_not_requests():
    """"우유" · "바닐라"처럼 메뉴 이름에 들어가는 말은 혼자서는 요청이 아니다."""
    assert intake.request_phrases("우유 하나요") == []
    assert intake.request_phrases("바닐라 라떼 주세요") == []
    assert intake.build_items("헤이즐넛 라떼", "김민수")[0]["custom_request"] is None


def test_option_rule_phrase_is_not_duplicated_into_custom_request():
    item = intake.build_items("아이스 라떼 시럽 추가", "김민수")[0]
    assert item["options"] == {"syrup": "add"} and item["custom_request"] is None


def test_request_with_remove_word_is_not_a_cancel():
    """"휘핑 빼 주세요"의 `빼 주`는 취소 신호와 같은 글자다 — 주문 추가로 읽어야 한다."""
    assert intake.classify("아이스 라떼 휘핑 빼 주세요") == "add"


# --- 행 편집 버튼 (API-020 option_choices · API-023) ---------------------------------------------
from app.services import projection  # noqa: E402


def test_row_editor_shows_only_the_menus_groups_in_fixed_order():
    choices = projection.option_choices("starbucks", "mv", {"menu_id": "sb_004", "options": {"size": "tall"}})
    assert [c["option_group"] for c in choices] == ["size", "ice", "shot", "bean", "cup"]
    ice = next(c for c in choices if c["option_group"] == "ice")
    assert [x["value"] for x in ice["choices"]] == ["none", "less", "normal", "more"]
    hot = projection.option_choices("starbucks", "mv", {"menu_id": "sb_011", "options": {}})
    assert [c["option_group"] for c in hot] == ["size", "shot", "bean", "cup"]          # 따뜻한 메뉴에 얼음 없음
    espresso = projection.option_choices("starbucks", "mv", {"menu_id": "sb_018", "options": {}})
    assert "size" not in [c["option_group"] for c in espresso]


def test_row_editor_hides_options_until_the_menu_is_known():
    assert projection.option_choices("starbucks", "mv", {"menu_id": None, "options": {}}) == []


def test_saved_values_from_the_editor_pass_the_server_whitelist():
    """화면이 보내는 `{option_group: value}`를 서버가 받는다 — 라벨("그란데")은 거절된다."""
    choices = projection.option_choices("starbucks", "mv", {"menu_id": "sb_004", "options": {}})
    for group in choices:
        for pair in group["choices"]:
            assert menu.is_valid_option("starbucks", "mv", group["option_group"], pair["value"], menu_id="sb_004")
    assert not menu.is_valid_option("starbucks", "mv", "사이즈", "그란데", menu_id="sb_004")


# --- 전체 흐름 확인에서 나온 결함 (2026-11-04) ----------------------------------------------------
@pytest.mark.parametrize("llm_custom, expected", [
    ("샷 추가요", None),                                   # 옵션(shot)으로 이미 읽었다 — 겹치지 않는다
    ("두유로 디카페인이요", None),                         # 두유는 분석 경로가 원문 조각으로 다시 넣는다
    ("개인컵이요", None),
    ("바닐라빈 파우더 조금 뿌려 주세요", "바닐라빈 파우더 조금 뿌려 주세요"),   # 옵션이 아닌 요청은 그대로
    ("휘핑 많이, 샷 추가", "휘핑 많이"),
])
def test_llm_custom_request_drops_menu_option_words(llm_custom, expected):
    assert intake.without_option_words(llm_custom) == expected


def test_menu_change_fits_the_size_to_the_new_menu():
    from app.services import edits
    assert edits.fit_size("starbucks", "mv", {"size": "grande", "ice": "less"}, "sb_023") == {"ice": "less", "size": "tall"}
    assert edits.fit_size("starbucks", "mv", {"size": "venti"}, "sb_023") == {"size": "venti"}      # 있으면 그대로
    assert edits.fit_size("starbucks", "mv", {"size": "tall", "shot": "extra"}, "sb_018") == {"shot": "extra"}  # 사이즈 없는 메뉴
    assert edits.fit_size("starbucks", "mv", {"ice": "less"}, "sb_023") == {"ice": "less"}           # 사이즈 미지정은 그대로


def test_failed_rows_are_flagged_for_review():
    row = {"item_id": "i1", "person": "김", "menu_id": "sb_004", "menu_name": "아이스 아메리카노", "menu_text": "",
           "options": {}, "ambiguous_options": {}, "custom_request": None, "quantity": 1, "estimated_price": None,
           "validation_status": "failed", "review_reason_text": "옵션을 다시 골라 주세요", "changed": False}
    session = {"session_id": "S", "brand_id": "starbucks", "menu_version": "mv"}
    assert projection.item_rows(session, [row])[0]["needs_review"] is True
    passed = {**row, "validation_status": "passed"}
    assert projection.item_rows(session, [passed])[0]["needs_review"] is False


def test_options_are_shown_in_fixed_order():
    block = projection.options_block("starbucks", "mv", {"cup": "personal", "ice": "less", "size": "venti"}, {})
    assert [b["label"] for b in block] == ["사이즈", "얼음", "개인컵"]


def test_cafe_inside_menu_words_is_not_a_store():
    from app.services import brand
    dictionary = [{"_key": "스타벅스", "resolved_brand_id": "starbucks", "display_name": "스타벅스"},
                  {"_key": "카페", "resolved_brand_id": "generic", "display_name": "카페"},
                  {"_key": "일반카페", "resolved_brand_id": "generic", "display_name": "일반 카페"}]
    dictionary.sort(key=lambda r: -len(r["_key"]))
    names = lambda t: [h["display_name"] for h in brand._find(t, dictionary)]  # noqa: E731
    assert names("스타벅스 가서 아이스 카페 라떼 마실래") == ["스타벅스"]
    assert names("디카페인으로 바꿔줘") == [] and names("카페 모카 하나") == []
    assert names("일반 카페로 해줘") == ["일반 카페"]                       # 진짜 매장 표현은 그대로
    assert names("동네 카페에서 사올게") == ["카페"]


def test_share_time_is_korean_time():
    from app.services import share
    assert share._now_kst().utcoffset().total_seconds() == 9 * 3600


@pytest.mark.parametrize("llm_custom, expected", [
    ("하나는 샷 추가", None),
    ("휘핑 많이, 하나는 샷 추가", "휘핑 많이"),
])
def test_llm_custom_request_drops_quantity_leftovers(llm_custom, expected):
    assert intake.without_option_words(llm_custom) == expected


@pytest.mark.parametrize("draft, expected", [
    # LLM 이 요청을 option_texts 와 custom_request 로 쪼개 넣었다 — 원문 구간 그대로 합친다
    ({"option_texts": ["바닐라빈 파우더 조금"], "custom_request": "뿌려 주세요"}, "바닐라빈 파우더 조금 뿌려 주세요"),
    ({"option_texts": [], "custom_request": "바닐라빈 파우더 조금 뿌려 주세요"}, "바닐라빈 파우더 조금 뿌려 주세요"),
    ({"option_texts": ["얼음 적게", "샷 추가"], "custom_request": None}, None),       # 메뉴판 옵션은 옵션 몫
])
def test_llm_request_keeps_option_texts_the_rules_cannot_read(draft, expected):
    text = "아이스 라떼 바닐라빈 파우더 조금 뿌려 주세요 얼음 적게 샷 추가"
    assert intake.llm_request(text, draft) == expected


@pytest.mark.parametrize("word, josa", [("에스프레소 디카페인", "으로"), ("아이스 카페 라떼 (톨)", "로"),
                                        ("망고 바나나 블렌디드 (그란데)", "로"), ("3잔", "으로")])
def test_chat_edit_notice_particle(word, josa):
    from app.services import edits
    assert edits._ro(word) == josa
