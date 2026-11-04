# 2026-11-04 사용자 보고 수정분 — #5 옵션 기본값 · #6 답장 반영 · #8 이름 없이 공유 (DB 없이 돈다)
#
# #6 의 "같은 세션에서 두 번째 답장 분석이 500" 은 DB 키 충돌이라 실DB 로 본다(tests/test_live_flow.py).
import datetime

from app.services import chat_parse, projection, share, suggestions
from tests import q03_fakes as F


# --- #5 행에 값이 없는 옵션 묶음은 메뉴 기본값이 골라진 상태 ------------------------------------
def test_unset_option_groups_show_menu_default(monkeypatch):
    F.install(monkeypatch, F.Store())
    groups = {g["option_group"]: g for g in projection.option_choices(
        F.BRAND, F.MENU_VERSION, {"menu_id": "sb_004", "options": {"size": "grande"}})}
    assert groups["size"]["current"] == "그란데"                 # 고른 값은 그대로
    assert groups["ice"]["current"] == "보통"                    # 안 고른 묶음은 기본값
    assert groups["shot"]["current"] == "기본"


def test_ambiguous_size_is_not_filled_with_default(monkeypatch):
    """모호한 사이즈("큰 거")는 고른 것이 아니다 — 기본값으로 채우면 확인 없이 톨이 된다."""
    F.install(monkeypatch, F.Store())
    groups = {g["option_group"]: g for g in projection.option_choices(
        F.BRAND, F.MENU_VERSION,
        {"menu_id": "sb_004", "options": {}, "ambiguous_options": {"size": '"큰 거"'}})}
    assert groups["size"]["current"] is None
    assert groups["ice"]["current"] == "보통"


# --- #6 답장 형식 ------------------------------------------------------------------------------
def test_kakao_pc_time_is_not_part_of_the_message():
    parsed = chat_parse.parse("[이지연] [오후 2:31] 그란데로 바꿔주세요")
    assert [(m["sender"], m["text"]) for m in parsed["messages"]] == [("이지연", "그란데로 바꿔주세요")]


def test_plain_bracket_text_is_kept():
    """시각처럼 생기지 않은 대괄호는 본문이다."""
    parsed = chat_parse.parse("[이지연] [급해요] 그란데로")
    assert parsed["messages"][0]["text"] == "[급해요] 그란데로"


def test_reply_without_sender_says_how_to_paste():
    out = suggestions.analyze({"session_id": "ORD-0001"}, "그란데로 바꿔주세요")
    assert out["suggestions"] == [] and out["found_text"] == suggestions.NO_SENDER_TEXT


# --- #8 이름 없이 공유 -------------------------------------------------------------------------
SHEET = {"brand": {"id": "starbucks"}, "summary": {"people": 3, "cups": 3},
         "totals": {"cups": 3, "estimated_total": 14500},
         "groups": [{"menu_text": "아이스 아메리카노", "options": [{"label": "사이즈", "value": "톨"}],
                     "quantity": 2, "people": ["김민수", "박서연"], "custom_request": None},
                    {"menu_text": "카페 라떼", "options": [], "quantity": 1, "people": ["이지연"],
                     "custom_request": "휘핑 빼주세요"}]}
NOW = datetime.datetime(2026, 11, 4, 11, 0, tzinfo=share.KST)


def test_share_with_names_is_unchanged():
    out = share.view(SHEET, now=NOW)
    assert out["show_names"] is True
    assert "김민수 · 박서연" in out["content"] and "이지연" in out["content"]


def test_share_without_names_keeps_menu_quantity_request_total():
    out = share.view(SHEET, now=NOW, show_names=False)
    text = out["content"]
    for name in ("김민수", "박서연", "이지연"):
        assert name not in text and name not in str(out["card"])
    assert "아이스 아메리카노 톨  x2" in text and "카페 라떼  x1" in text
    assert "요청: 휘핑 빼주세요" in text and "합계 3잔 · 예상 14,500원" in text
    assert "3명" in out["card"]["sub"]                          # 인원 수는 이름이 아니다
