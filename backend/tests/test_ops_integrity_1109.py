"""운영 대시보드 B "주문 중복 · 유실" — 복구 시험 회차가 SC-5 를 실제로 잰다 (2026-11-09).

종전에는 서버가 `integrity_issue_count` 를 보내지 않아 칸이 늘 `미측정`이었다.
G-A0 양방향 — (a) 손대지 않은 세션이 그대로면 0건 (b) 중복 · 유실 · 세션 소실은 건수로 잡힌다.
여기에 (c) 사용 중이던 세션은 정당한 변경이므로 세지 않고 (d) 비교할 세션이 없으면 0건이 아니라 미측정이다.
"""
from app.services import incidents
from healing import integrity

A = {"items": 2, "digest": "aa"}
B = {"items": 1, "digest": "bb"}


def test_untouched_sessions_that_stay_the_same_count_zero():
    got = integrity.compare({"s1": A, "s2": B}, {"s1": A, "s2": B}, set())
    assert got == {"measured": True, "compared": 2, "skipped": 0, "issues": 0, "changed": []}


def test_duplicate_and_loss_are_counted_by_item_difference():
    after = {"s1": {"items": 3, "digest": "xx"},          # 1건 중복
             "s2": {"items": 0, "digest": "yy"}}          # 1건 유실
    got = integrity.compare({"s1": A, "s2": B}, after, set())
    assert got["issues"] == 2 and set(got["changed"]) == {"s1", "s2"}


def test_same_count_but_changed_content_is_one_issue():
    got = integrity.compare({"s1": A}, {"s1": {"items": 2, "digest": "changed"}}, set())
    assert got["issues"] == 1


def test_a_vanished_session_loses_all_its_items():
    assert integrity.compare({"s1": A}, {}, set())["issues"] == 2


def test_sessions_someone_edited_during_the_trial_are_skipped():
    got = integrity.compare({"s1": A, "s2": B}, {"s1": {"items": 5, "digest": "x"}, "s2": B}, {"s1"})
    assert got["issues"] == 0 and got["compared"] == 1 and got["skipped"] == 1


def test_nothing_to_compare_is_unmeasured_not_zero():
    assert integrity.compare({"s1": A}, {"s1": A}, {"s1"})["measured"] is False
    assert integrity.check({"at": None, "sessions": {}})["measured"] is False
    assert integrity.check(None)["measured"] is False


def test_touched_matches_session_column_or_path():
    rows = [{"session_id": "s1", "path": "/x"}, {"session_id": None, "path": "/api/sessions/s2/edits"}]
    assert integrity.touched(["s1", "s2", "s3"], rows) == {"s1", "s2"}


# --- 서버가 칸을 채운다 — 비교한 회차가 없으면 None(미측정) · 있으면 합 --------------------
def test_metrics_send_none_until_a_trial_compared_something(monkeypatch):
    monkeypatch.setattr(incidents.db, "fetch_one", lambda sql, *a, **k:
                        {"runs": 0, "issues": None, "sessions": None} if "integrity" in sql else {})
    assert incidents.metrics_view()["detail"]["integrity_issue_count"] is None


def test_metrics_send_the_sum_once_measured(monkeypatch):
    monkeypatch.setattr(incidents.db, "fetch_one", lambda sql, *a, **k:
                        {"runs": 3, "issues": 0, "sessions": 12} if "integrity" in sql else {})
    detail = incidents.metrics_view()["detail"]
    assert detail["integrity_issue_count"] == 0 and detail["integrity_runs"] == 3
