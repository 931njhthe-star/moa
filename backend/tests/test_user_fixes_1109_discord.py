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
