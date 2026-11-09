# 2026-11-09 사용자 요청 — 디스코드 복사 형식("이름 — 오전 10:23" 머리줄 + 다음 줄 메시지)을 읽는다.
# 이전에는 머리줄까지 `이름 없음` 메시지로 들어가 사람이 갈리지 않았다
from app.services import chat_parse

USER_SAMPLE = ("AIO 2기_이성우 — 오전 10:\n"
               "좋습니다. 저는 딸기 딜라이트 요거트 블렌디드 그란데 한 잔, 얼음은 적게 부탁드려요")


def _pairs(parsed):
    return [(m["sender"], m["text"]) for m in parsed["messages"]]


def test_user_sample_cut_minutes():
    parsed = chat_parse.parse(USER_SAMPLE)
    assert _pairs(parsed) == [("AIO 2기_이성우",
                               "좋습니다. 저는 딸기 딜라이트 요거트 블렌디드 그란데 한 잔, 얼음은 적게 부탁드려요")]
    assert parsed["unreadable_lines"] == []
    assert parsed["summary_text"] == "1명 · 메시지 1개를 읽었어요"


def test_two_people_with_date_forms():
    parsed = chat_parse.parse("AIO 2기_이성우 — 오늘 오전 10:23\n아아 톨 2잔\n"
                              "김민수 — 2026. 11. 9. 오후 2:31\n라떼 그란데 하나")
    assert _pairs(parsed) == [("AIO 2기_이성우", "아아 톨 2잔"), ("김민수", "라떼 그란데 하나")]
    assert parsed["person_count"] == 2


def test_continued_message_with_time_prefix():
    # 같은 사람이 이어 보낸 줄은 "[오전 10:24]본문" 으로 복사된다 — 시각을 이름으로 읽지 않는다
    parsed = chat_parse.parse("이성우 — 오전 10:23\n아아 톨 2잔\n[오전 10:24]하나는 샷 추가\n"
                              "김민수 — 오전 10:25\n라떼 하나")
    assert _pairs(parsed) == [("이성우", "아아 톨 2잔"), ("이성우", "하나는 샷 추가"), ("김민수", "라떼 하나")]


def test_header_without_body_is_skipped():
    parsed = chat_parse.parse("이성우 — 오전 10:23\n김민수 — 오전 10:24\n라떼 하나")
    assert _pairs(parsed) == [("김민수", "라떼 하나")]


def test_trailing_store_request_stays_unreadable():
    parsed = chat_parse.parse("이성우 — 오전 10:23\n아아 톨\n스타벅스로 갈 예정이야")
    assert _pairs(parsed) == [("이성우", "아아 톨")]
    assert [u["text"] for u in parsed["unreadable_lines"]] == ["스타벅스로 갈 예정이야"]


def test_sentence_with_dash_is_not_header():
    # 시각으로 끝나지 않는 대시 문장은 머리줄이 아니다 — 이름 없는 대화로 남는다
    parsed = chat_parse.parse("라떼 — 그란데로 하나\n아아 두 잔")
    assert parsed["people"] == [chat_parse.UNNAMED]


# 2026-11-09 사용자 보고 2 — 본문의 "[성우] …" 때문에 `[이름]` 형식으로 오인돼 나머지 줄이 전부 읽지 못한 줄이 됐고,
# 대시 뒤 공백이 없는 머리줄("이름 —오전 10:07")을 읽지 못했다
REAL_CHAT = """백승주 — 오전 10:03
스타벅스 다녀오려고 하는데 다들 드실거 이야기주세요~
AIO 2기_이성우 — 오전 10:07
[성우]  좋습니다. 저는 딸기 딜라이트 요거트 블렌디드 그란데 한 잔, 얼음은 적게 부탁드려요
AIO 2기_이홍진 —오전 10:07
아이스 바닐라 라떼로 부탁해요, 빨대는 빼주시고 제 개인컵 이용할게요
노곤민우 — 오전 10:10
아아 한 잔!
백승주 — 오전 10:16
저는 민우님과 같은걸로 할게요
백승주 — 오전 10:16
다녀오겠습니다!"""


def test_bracket_in_body_does_not_switch_format():
    parsed = chat_parse.parse(REAL_CHAT)
    assert parsed["unreadable_lines"] == []
    assert parsed["people"] == sorted(["백승주", "AIO 2기_이성우", "AIO 2기_이홍진", "노곤민우"])
    assert parsed["message_count"] == 6
    assert ("AIO 2기_이홍진", "아이스 바닐라 라떼로 부탁해요, 빨대는 빼주시고 제 개인컵 이용할게요") in _pairs(parsed)


def test_short_body_is_not_taken_as_name_in_discord():
    # 디스코드에서는 머리줄만 이름 줄이다 — 이어 보낸 짧은 줄("라떼")을 이름으로 잡지 않는다
    parsed = chat_parse.parse("김민수 — 오전 10:01\n아아 톨\n라떼\n하나 더요\n이지연 — 오전 10:02\n바닐라라떼")
    assert _pairs(parsed) == [("김민수", "아아 톨"), ("김민수", "라떼"), ("김민수", "하나 더요"),
                              ("이지연", "바닐라라떼")]


def test_lines_before_first_header_are_unreadable():
    parsed = chat_parse.parse("스타벅스로 갈 예정이야\n김민수 — 오전 10:01\n아아 톨")
    assert _pairs(parsed) == [("김민수", "아아 톨")]
    assert [u["text"] for u in parsed["unreadable_lines"]] == ["스타벅스로 갈 예정이야"]
