# 2026-11-09 사용자 보고 — 이름이 제 줄에 따로 있는 대화("김민수\n아아 톨 2잔")가 16줄 전부
# `이름 없음` 메시지로 들어가 이름 줄까지 주문으로 읽혔다 (매장 기준과 무관한 파서 결함)
from app.services import chat_parse

STACKED = """김민수
아이스 아메리카노 톨 2잔, 하나는 샷 추가요.
이지연
바닐라라떼 큰 거 얼음 적게요.
박서연
아아 톨 한 잔이요. 빨대는 빼 주시고 개인 텀블러에 담아 주세요, 얼음은 컵 반만 채워 주시면 좋겠어요!
최유나
여기 인기 있는 메뉴 뭐야?
정하준
민트 초코가 유명하대
최유나
그럼 난 그걸로 하나~
김민수
아까 샷 추가한 한 잔 취소할게요.
정하준
나도 민수랑 같은 걸로!
"""


def test_name_on_own_line_is_sender():
    parsed = chat_parse.parse(STACKED)
    assert parsed["message_count"] == 8
    assert parsed["person_count"] == 5
    assert parsed["messages"][0] == {**parsed["messages"][0], "sender": "김민수",
                                     "text": "아이스 아메리카노 톨 2잔, 하나는 샷 추가요."}
    assert chat_parse.UNNAMED not in parsed["people"]
    assert parsed["unreadable_lines"] == []


def test_one_word_message_after_name_is_message():
    parsed = chat_parse.parse("최유나\n민트초코\n정하준\n라떼 하나")
    assert [(m["sender"], m["text"]) for m in parsed["messages"]] == [
        ("최유나", "민트초코"), ("정하준", "라떼 하나")]


def test_trailing_store_request_stays_unreadable():
    parsed = chat_parse.parse("김민수\n아아 톨\n이지연\n라떼\n스타벅스로 갈 예정이야")
    assert parsed["message_count"] == 2
    assert [u["text"] for u in parsed["unreadable_lines"]] == ["스타벅스로 갈 예정이야"]


def test_nameless_chat_still_unnamed():
    parsed = chat_parse.parse("아이스 아메리카노 두 잔\n라떼 한 잔요")
    assert parsed["people"] == [chat_parse.UNNAMED]
