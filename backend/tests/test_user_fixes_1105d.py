# 2026-11-05 4차 사용자 보고 3번 — 메뉴판에 없는 메뉴 이름만 말한 주문("나 얼박사!")이 사라졌다
#
# 인원별 정리(consolidate)가 "메뉴판과 무관 + 주문 문형 없음"을 잡담으로 보고 버렸다.
# 그 사람의 다른 주문이 없으면 버리지 않고 확인 필요로 올린다 — 미등록 메뉴를 임의 확정하지 않는다(D-08 · SC-8).
import pytest

from app.services import consolidate
from tests import q03_fakes as F
from tests.test_user_fixes_1105 import rows_after_rules, run_rules


@pytest.fixture
def store():
    return F.Store()


@pytest.mark.parametrize("text", ["나 얼박사!", "저는 얼박사요", "얼박사"])
def test_bare_unregistered_menu_is_a_menu_name(monkeypatch, text):
    monkeypatch.setattr("app.services.brand._dictionary", lambda: [])
    assert consolidate._bare_menu(text) is True, text


@pytest.mark.parametrize("text", ["얼박사?", "네네 스타벅스입니다~", "좋아요", "그래", "넵넵",
                                  "오늘 날씨 좋네요"])
def test_chatter_is_not_a_menu_name(monkeypatch, text):
    monkeypatch.setattr("app.services.brand._dictionary",
                        lambda: [{"_key": "스타벅스", "display_name": "스타벅스"}])
    assert consolidate._bare_menu(text) is False, text


def test_unregistered_menu_person_is_kept_as_needs_review(monkeypatch, store):
    run_rules(monkeypatch, store, ["[민지] 나 얼박사!", "[서연] 저는 카페 라떼 하나 주세요"])
    people = {r["person"]: r for r in store.live()}
    assert set(people) == {"민지", "서연"}, list(people)
    assert people["민지"]["validation_status"] == "needs_review"
    assert people["민지"]["menu_id"] is None            # 메뉴판에 없는 메뉴를 임의로 확정하지 않는다


def test_someone_who_already_ordered_still_drops_chatter(monkeypatch):
    """이미 주문한 사람의 군말은 여전히 항목이 되지 않는다(2차 보고 5 · 7번)."""
    store = rows_after_rules(monkeypatch, ["[이지연 사원] 저는 카페 라떼 하나 주세요",
                                           "[이지연 사원] 넵넵"])
    assert [r["person"] for r in store.live()] == ["이지연 사원"]
