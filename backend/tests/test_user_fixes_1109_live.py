# 2026-11-09 사용자 보고 — 성 없이 이름만 불러 채팅으로 바꾸기 (실제 DB · MOA_LIVE_DB=1)
#
#   MOA_LIVE_DB=1 ../.venv/Scripts/python.exe -m pytest -q tests/test_user_fixes_1109_live.py
#
# "서연이는 따뜻한 아메리카노로 변경" — 박서연이 세션에 있는데 "어느 주문을 말하는지 찾지 못했어요".
# 대상 찾기가 **전체 이름이 문장에 있을 때만** 사람을 알아봤다.
import os

import pytest

from tests.test_user_fixes_1105f_live import _menu_of, _rows, _say, _start, live  # noqa: F401

pytestmark = pytest.mark.skipif(os.getenv("MOA_LIVE_DB") != "1",
                                reason="MOA_LIVE_DB=1 일 때만 실제 DB 로 돈다")

PEOPLE = [
    "[박서연] 아이스 아메리카노 톨 한 잔이요",
    "[김민수] 아이스 아메리카노 톨 한 잔이요",
    "[이지연] 아이스 카페 라떼 톨 한 잔이요",
]


@pytest.mark.parametrize("text", ["서연이는 따뜻한 아메리카노로 변경",
                                  "서연 카페 라떼로 바꿔줘"])
def test_given_name_only_finds_the_person(live, text):
    client, made = live
    sid, token = _start(client, made, PEOPLE)
    _, before = _rows(client, sid, token)
    res, data = _say(client, sid, token, text)
    assert res.status_code == 200, data
    assert data["kind"] == "applied", data
    assert "박서연" in data["text"], data
    _, rows = _rows(client, sid, token)
    assert _menu_of(rows, "김민수") == _menu_of(before, "김민수"), rows     # 남의 잔은 그대로
    assert _menu_of(rows, "박서연") != _menu_of(before, "박서연"), rows


def test_given_name_does_not_match_inside_another_word(live):
    """'지연'은 '이지연'의 이름이지만 '지연되다'의 일부로 읽히면 안 된다 — 앞뒤 글자가 한글이면 아니다."""
    client, made = live
    sid, token = _start(client, made, PEOPLE)
    res, data = _say(client, sid, token, "주문지연돼서 카페 라떼로 바꿔줘")
    assert data.get("kind") != "applied" or "이지연" not in data.get("text", ""), data
