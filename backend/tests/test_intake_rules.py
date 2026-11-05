# 해석 규칙 — 수량 · 사이즈 · 온도 점검 (DB 없이 돈다)
#
# 양방향으로 본다 (CLAUDE.md G-A0): 확인이 필요한 입력은 확인으로 가고,
# **정상 주문은 확인으로 가지 않는다.** 한쪽만 보면 질문을 남발하는 규칙도 통과한다.
import pytest

from app.services import intake, questions
from app.services.text_norm import parse_quantity


def first_item(text, sender="김민수"):
    events = intake.extract_events([{"message_id": "m1", "seq": 1, "sender": sender,
                                     "text": text}], brand_id="starbucks",
                                   menu_version="mv_20261029")
    return events[0]["items"][0]


# --- 수량 ---------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("아아 50잔", 50), ("아아 0잔", 0), ("아아 -1잔", -1), ("아아 세 잔", 3), ("라떼 2개요", 2),
    ("아아 한 잔이요", 1), ("아아요", 1),
])
def test_quantity_is_read_as_written(text, expected):
    # 예전에는 1 ~ 20 으로 잘라 50잔이 20잔, 0잔이 1잔이 됐다
    assert parse_quantity(text) == expected


@pytest.mark.parametrize("text,raw,kept", [
    ("아아 50잔", '"50잔"', 50), ("아아 0잔", '"0잔"', 1), ("아아 -1잔", '"-1잔"', 1),
])
def test_out_of_range_quantity_goes_to_review(text, raw, kept):
    item = first_item(text)
    assert item["ambiguous_options"]["quantity"] == raw
    assert item["quantity"] == kept                 # 저장 가능한 값 (DB CHECK quantity > 0)


@pytest.mark.parametrize("text", ["아아 2잔", "아이스 아메리카노 톨 20잔", "라떼 한 잔"])
def test_normal_quantity_is_not_flagged(text):
    assert "quantity" not in first_item(text)["ambiguous_options"]


def test_flagged_quantity_is_not_split():
    # "50잔, 하나는 샷 추가"를 49 + 1 로 나누면 확인 전 값이 두 행으로 굳는다
    events = intake.extract_events([{"message_id": "m1", "seq": 1, "sender": "a",
                                     "text": "아아 50잔, 하나는 샷 추가요"}],
                                   brand_id="starbucks", menu_version="mv_20261029")
    assert len(events[0]["items"]) == 1


def test_normal_split_still_works():
    events = intake.extract_events([{"message_id": "m1", "seq": 1, "sender": "a",
                                     "text": "아이스 아메리카노 톨 2잔, 하나는 샷 추가요."}],
                                   brand_id="starbucks", menu_version="mv_20261029")
    assert [i["quantity"] for i in events[0]["items"]] == [1, 1]


# --- 사이즈 -------------------------------------------------------------------
@pytest.mark.parametrize("text,raw", [
    ("라떼 중간 사이즈", '"중간 사이즈"'), ("라떼 미디엄", '"미디엄"'), ("라떼 숏", '"숏"'),
    ("라떼 M", '"M"'), ("바닐라라떼 큰 거", '"큰 거"'),
])
def test_ambiguous_size_words(text, raw):
    assert first_item(text)["ambiguous_options"]["size"] == raw


@pytest.mark.parametrize("text", ["라떼 톨", "아아 그란데", "아아", "MD 한정 콜드브루", "라떼 SML"])
def test_clear_or_absent_size_is_not_flagged(text):
    assert "size" not in first_item(text)["ambiguous_options"]


# --- 온도 ---------------------------------------------------------------------
@pytest.mark.parametrize("text,raw", [
    ("따뜻한 아이스 아메리카노 톨", '"따뜻한 아이스"'),
    ("아이스 뜨거운 라떼", '"아이스 뜨거운"'),
    ("핫 아이스티", '"핫 아이스"'),
])
def test_temperature_conflict(text, raw):
    item = first_item(text)
    assert item["ambiguous_options"]["temperature"] == raw
    assert "아이스" not in item["temperature_base"]


@pytest.mark.parametrize("text", ["아이스 아메리카노", "따뜻한 라떼", "뜨아", "아아", "핫초코",
                                  "차가운 라떼"])
def test_single_temperature_is_not_flagged(text):
    assert "temperature" not in first_item(text)["ambiguous_options"]


@pytest.mark.parametrize("text,key", [("차가운 라떼", "아이스 라떼"), ("시원한 바닐라라떼", "아이스 바닐라라떼"),
                                      ("ice 라떼", "아이스 라떼")])
def test_cold_words_read_as_iced(text, key):
    # 바꾸지 않으면 별칭 "라떼"(따뜻한 카페 라떼)에 걸려 반대 온도로 확정된다
    assert intake._menu_text(text) == key


def test_hot_choco_alias_untouched():
    assert intake._menu_text("핫초코 한 잔") == "핫초코"


# --- 질문 문구 · 버튼 (사유는 ambiguous_spec 하나) -----------------------------
def _question(ambiguous, **extra):
    item = {"item_id": "ORD-1-it_01", "person": "김민수", "menu_name": "아이스 아메리카노",
            "menu_text": "아아 50잔", "menu_id": "sb_004", "review_reason": "ambiguous_spec",
            "ambiguous_options": ambiguous, **extra}
    return questions.build(item, session_id="ORD-1", brand_id="starbucks",
                           menu_version="mv_20261029", seq=1)


def test_quantity_question_offers_said_value_first():
    q = _question({"quantity": '"50잔"'})
    assert q["reason"] == "ambiguous_spec"
    assert q["question_text"] == '김민수 님 아이스 아메리카노 수량이 "50잔"로 적혀 있어요. 몇 잔인가요?'
    assert [o["value"] for o in q["options"]] == ["50", "1", "2"]


def test_zero_quantity_question_does_not_offer_zero():
    q = _question({"quantity": '"0잔"'})
    assert [o["value"] for o in q["options"]] == ["1", "2", "3"]


def test_temperature_question_lists_both_menus():
    q = _question({"temperature": '"따뜻한 아이스"', "quantity": '"50잔"'},
                  temperature_candidates=[{"menu_id": "sb_011", "name": "아메리카노"},
                                          {"menu_id": "sb_004", "name": "아이스 아메리카노"}])
    assert "따뜻한 것과 아이스" in q["question_text"]           # 온도가 수량보다 먼저
    assert [o["label"] for o in q["options"]] == ["아메리카노", "아이스 아메리카노"]


def test_spec_order():
    assert questions.spec_key({"quantity": "x", "size": "y"}) == "size"
    assert questions.spec_key({}) is None


# --- 답한 뒤 안내 문구 — 내부 값이 아니라 버튼 이름 (F-013 · D-05 확인에서 발견) ----------------
@pytest.mark.parametrize("value,label,expected", [
    ("tall", "톨", "이지연 님 주문을 톨로 했어요."),
    ("3", "3잔", "이지연 님 주문을 3잔으로 했어요."),
    ("민트 초콜릿 칩 블렌디드", "민트 초콜릿 칩 블렌디드", "이지연 님 주문을 민트 초콜릿 칩 블렌디드로 했어요."),
])
def test_applied_text_uses_label(value, label, expected):
    from app.services.edits import _applied_text

    text = _applied_text({"options": [{"value": value, "label": label}]}, value, "이지연")
    assert text == expected
    if value.isascii() and value.isalpha():
        assert value not in text                            # "tall로 했어요" 가 다시 나오지 않는다


# --- U-15 측정 도구 자기 검증 (G-A0) — 판정기가 오답 확정 · 미등록 확정을 실제로 잡는가 --------------
def test_u15_judge_self_check():
    # 측정 도구는 평가 기록과 함께 저장소 밖에서 관리한다 — 없으면 건너뛴다(서비스 코드는 이 도구에 기대지 않는다)
    self_check = pytest.importorskip("tools.u15_measure").self_check

    assert self_check() == []


# --- D-09 메뉴 매칭 규칙 — 가짜 메뉴판으로 (DB 없이) ------------------------------------------
@pytest.fixture
def fake_menu(monkeypatch):
    from app.services import menu
    from app.services.text_norm import normalize

    menus = [{"menu_id": "m_hot", "name": "카페 라떼", "base_price": 5000, "category": "c", "trait_tags": []},
             {"menu_id": "m_ice", "name": "아이스 카페 라떼", "base_price": 5000, "category": "c", "trait_tags": []},
             {"menu_id": "m_brew", "name": "콜드 브루", "base_price": 4900, "category": "c", "trait_tags": []}]
    alias_index = {}
    for m in menus:
        alias_index.setdefault(normalize(m["name"]), []).append(m["menu_id"])
    for alias, mid in (("라떼", "m_hot"), ("아이스라떼", "m_ice"), ("콜드브루", "m_brew")):
        alias_index.setdefault(normalize(alias), []).append(mid)
    cat = {"menus": menus, "by_id": {m["menu_id"]: m for m in menus}, "alias_index": alias_index,
           "options": [], "store_words": ["스타벅스", "카페"]}
    monkeypatch.setattr(menu, "catalog", lambda *a, **k: cat)
    return menu


@pytest.mark.parametrize("text", ["헤이즐넛 라떼", "딸기 라떼", "바닐라 크림 콜드브루"])
def test_strict_match_does_not_confirm_unknown_modifier(fake_menu, text):
    strict = fake_menu.match("b", "v", text, strict=True)
    assert strict["menu_id"] is None and strict["candidates"]          # 묻는다 — 후보는 준다
    assert fake_menu.match("b", "v", text)["menu_id"]                  # 채팅 수정 경로(기본)는 예전대로


@pytest.mark.parametrize("text,expected", [
    ("라떼 큰 거", "m_hot"), ("라떼 하나", "m_hot"), ("아이스 라떼", "m_ice"), ("콜드브루 그란데로", "m_brew"),
    ("스타벅스 라떼", "m_hot"), ("스타벅스에서 콜드브루", "m_brew"),          # 매장 이름은 수식어가 아니다
])
def test_strict_match_keeps_explained_leftovers(fake_menu, text, expected):
    from app.services import intake

    assert fake_menu.match("b", "v", intake._menu_text(text), strict=True)["menu_id"] == expected


@pytest.mark.parametrize("hint,start,expected", [
    ("ice", "m_hot", "m_ice"), ("hot", "m_ice", "m_hot"), (None, "m_hot", "m_hot"),
    ("hot", "m_brew", "m_brew"),                                       # 다른 판이 없으면 그대로
])
def test_with_temperature(fake_menu, hint, start, expected):
    cat = fake_menu.catalog()
    hit = fake_menu._hit(cat, start)
    assert fake_menu.with_temperature("b", "v", hit, hint)["menu_id"] == expected


@pytest.mark.parametrize("text,hint", [
    ("바닐라라떼 큰 거 얼음 적게요", "ice"), ("아메리카노 아이스로", "ice"), ("따뜻한 라떼", "hot"),
    ("라떼 하나", None), ("따뜻한 아이스 아메리카노", None),
])
def test_temperature_hint(text, hint):
    assert first_item(text)["temperature_hint"] == hint


@pytest.mark.parametrize("raw,key", [("카페 라테", "카페라떼"), ("카라멜마끼아또", "카라멜마키아토"),
                                     ("카페라떼", "카페라떼")])
def test_spelling_variants_normalize(raw, key):
    from app.services.text_norm import normalize

    assert normalize(raw) == key


def test_particle_i_is_kept():
    from app.services import intake

    assert intake._menu_text("차이 라떼") == "차이 라떼"               # "차 라떼"가 되지 않는다


# --- 참조가 가리키는 사람 (2026-11-03) ----------------------------------------
def test_reference_picks_the_named_person():
    """"민수랑 같은 걸로"는 김민수의 주문을 가리킨다 — 바로 앞 잡담이 아니다."""
    from app.services.sessions import _named_person

    events = [{"person": "김민수"}, {"person": "최유나"}, {"person": "정하준"}]
    assert _named_person("나도 민수랑 같은 걸로!", events) == "김민수"
    assert _named_person("김민수랑 같은 거요", events) == "김민수"


def test_reference_without_a_name_is_not_narrowed():
    """"그걸로 하나"는 사람을 가리키지 않는다 — 앞선 대화 전체에서 찾아야 한다."""
    from app.services.sessions import _named_person

    events = [{"person": "김민수"}, {"person": "정하준"}]
    assert _named_person("그럼 난 그걸로 하나~", events) is None


def test_reference_source_is_quoted_short_with_the_right_particle():
    """근거는 첫 구절만 인용하고, 조사는 받침에 따라 `로` · `으로`로 갈린다."""
    from app.services.questions import _source_clause

    # "2잔" 은 받침이 있다 → `으로` (`2잔로` 가 질문에 나가면 안 된다)
    assert _source_clause("아이스 아메리카노 톨 2잔, 하나는 샷 추가요.") == '"아이스 아메리카노 톨 2잔"으로'
    assert _source_clause("민트 초코가 유명하대") == '"민트 초코가 유명하대"로'
    assert _source_clause(None) == "앞선 대화로"
