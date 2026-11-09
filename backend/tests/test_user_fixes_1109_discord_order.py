"""2026-11-09 사용자 보고 — 디스코드 단체 주문 대화에서 주문이 사라지고 남의 메뉴가 조용히 확정됐다.

실측(로컬 규칙 경로 · 운영 스택은 해석 서비스 DEP_TIMEOUT 으로 같은 규칙 경로로 떨어졌다):

    이홍진  "아이스 바닐라 라떼로 부탁해요, 빨대는 빼주시고 제 개인컵 이용할게요"   -> cancel (주문 사라짐)
    노곤민우 "아아 큰걸로요,  빨대는 빼 주시고 개인 텀블러에 담아 주세요"          -> cancel (주문 사라짐)
    백승주  "초코가 유명하대요" → 노지훈 "그럼 난 그걸로 하나 부탁해요"            -> 딸기 딜라이트 톨 자동 확정
    백승주  "저는 민우님과 같은걸로 할게요"                                     -> 딸기 딜라이트 톨 자동 확정
    백승주  "스타벅스 다녀오려고 하는데 다들 드실거 이야기주세요~"               -> 주문으로 보고 질문

원인 5가지와 고친 곳은 각 테스트의 설명을 본다. 메뉴판이 필요한 것은 MOA_LIVE_DB=1 에서만 돈다.
"""
import os

import pytest

from app import config
from app.services import intake, sessions

HONGJIN = "아이스 바닐라 라떼로 부탁해요, 빨대는 빼주시고 제 개인컵 이용할게요"
MINWOO = "아아 큰걸로요,  빨대는 빼 주시고 개인 텀블러에 담아 주세요"


# --- 1. 한 문장 안의 기타 요청 구절이 주문을 지우고 취소로 분류했다 ---------------------------------
@pytest.mark.parametrize("text", [HONGJIN, MINWOO])
def test_order_with_request_clause_is_add_not_cancel(text):
    assert intake.classify(text) == "add"


def test_request_clause_leaves_menu_and_moves_to_custom_request():
    item = intake.build_items(HONGJIN, "AIO 2기_이홍진")[0]
    assert item["match_text"] == "아이스 바닐라 라떼"
    assert item["custom_request"] == "빨대는 빼주시고 제 개인컵 이용할게요"


def test_whole_request_sentence_is_still_not_an_order():
    # 요청만 있는 문장은 예전처럼 분류에서 빠진다 — 쉼표 구절로 바꿔도 이 동작은 그대로다
    assert intake.order_text("빨대는 빼 주세요") == "빨대는 빼 주세요"     # 남은 것이 없으면 원문
    assert intake.classify("아아 톨, 빨대 빼 주세요") == "add"


# --- 4. "큰걸로"는 사이즈를 고른 것이 아니다 — 기본 사이즈로 채우지 않고 묻는다 ----------------------
@pytest.mark.parametrize("text", ["아아 큰걸로요", "아아 큰 걸로 주세요", "라떼 작은걸로", "아아 큰 사이즈"])
def test_big_or_small_without_size_name_is_ambiguous(text):
    assert "size" in intake.build_items(text, "x")[0]["ambiguous_options"]


# --- 5. 주문을 받으려는 말은 주문이 아니다 ---------------------------------------------------------
@pytest.mark.parametrize("text", ["스타벅스 다녀오려고 하는데 다들 드실거 이야기주세요~",
                                  "드실 분 얘기해 주세요", "마실 거 말씀해주세요"])
def test_collecting_orders_is_not_an_order(text):
    assert intake.classify(text) == "ignore"
    assert not intake.order_pattern(text)


def test_own_order_with_please_is_still_an_order():
    assert intake.classify("아이스 아메리카노 톨 주세요") == "add"


# --- 3. 닉네임 · 소속이 붙은 이름도 가리킬 수 있다 ----------------------------------------------------
EVENTS = [{"message_id": "m1", "person": "노곤민우"},
          {"message_id": "m2", "person": "AIO 2기_이홍진"},
          {"message_id": "m3", "person": "김민수"}]


@pytest.mark.parametrize("said, who", [("저는 민우님과 같은걸로 할게요", "노곤민우"),
                                       ("홍진님이랑 같은 거요", "AIO 2기_이홍진"),
                                       ("나도 민수랑 같은 걸로", "김민수")])
def test_named_person_from_nickname(said, who):
    assert sessions._named_person(said, EVENTS) == who


def test_name_tokens_skip_single_letters():
    assert all(len(t) >= 2 for t in sessions._name_tokens("AIO 2기_이"))


# --- 2. 맛 낱말을 가리킨 참조 주문 — 남의 메뉴로 확정하지 않고 그 맛의 메뉴들을 후보로 묻는다 ----------
live = pytest.mark.skipif(os.getenv("MOA_LIVE_DB") != "1", reason="메뉴 사전을 실제로 읽어야 한다(MOA_LIVE_DB=1)")

CHAT = [
    {"message_id": "m1", "person": "AIO 2기_이성우",
     "_raw_text": "[성우]  좋습니다. 저는 딸기 딜라이트 요거트 블렌디드 그란데 한 잔이요"},
    {"message_id": "m2", "person": "노곤민우", "_raw_text": MINWOO},
    {"message_id": "m3", "person": "AIO 2기_노지훈", "_raw_text": "여기 인기 있는 메뉴 뭐예요?"},
    {"message_id": "m4", "person": "백승주", "_raw_text": "초코가 유명하대요"},
    {"message_id": "m5", "person": "AIO 2기_노지훈", "_raw_text": "그럼 난 그걸로 하나 부탁해요"},
    {"message_id": "m6", "person": "백승주", "_raw_text": "저는 민우님과 같은걸로 할게요"},
]


@live
def test_reference_to_flavor_offers_flavor_menus():
    got = sessions._referenced_menus(CHAT, 4, brand_id="starbucks", menu_version=config.MENU_VERSION)
    names = [g["name"] for g in got]
    assert len(got) > 1, names                                     # 둘 이상 — 자동 확정되지 않는다
    assert "딸기 딜라이트 요거트 블렌디드" not in names, names
    assert all("초콜릿" in g["trait_tags"] for g in got), got
    assert {g["source_message_id"] for g in got} == {"m4"}


@live
def test_reference_to_named_nickname_takes_that_persons_menu():
    got = sessions._referenced_menus(CHAT, 5, brand_id="starbucks", menu_version=config.MENU_VERSION)
    assert [(g["name"], g["source_message_id"]) for g in got] == [("아이스 아메리카노", "m2")]


@live
def test_unavailable_flavor_menu_still_resolves_to_nothing():
    # 11/07 방어가 그대로인지 — "민트 초코"는 스타벅스 기준에 없다. 초콜릿 메뉴로 바꿔 내놓지 않는다
    chat = CHAT[:3] + [{"message_id": "m4", "person": "백승주", "_raw_text": "민트 초코가 유명하대"}] + CHAT[4:5]
    assert sessions._referenced_menus(chat, 4, brand_id="starbucks", menu_version=config.MENU_VERSION) == []
