import pytest

from app import config
from app.services import workflows


def test_quick_workflow_is_one_bounded_case():
    cases = workflows.build_cases(mode="quick", fault_type="F-1", target=None,
                                  repetitions=10, injection_seconds=120)
    assert len(cases) == 1
    assert cases[0] == {"fault_type": "F-1", "target": "order_interpreter_primary", "seconds": 120}


def test_full_workflow_has_25_cases_and_alternates_backend_targets():
    cases = workflows.build_cases(mode="full", fault_type="F-1", target=None,
                                  repetitions=1, injection_seconds=1)
    assert len(cases) == 25
    f3_targets = [case["target"] for case in cases if case["fault_type"] == "F-3"]
    assert f3_targets == ["moa-a-backend-1", "moa-b-backend-1", "moa-a-backend-1",
                          "moa-b-backend-1", "moa-a-backend-1"]


@pytest.mark.parametrize("fault_type,target", [
    ("F-1", "moa-a-backend-1"),
    ("F-3", "order_interpreter_primary"),
    ("F-6", "moa-a-backend-1"),
])
def test_custom_workflow_rejects_wrong_target(fault_type, target):
    with pytest.raises(ValueError):
        workflows.build_cases(mode="custom", fault_type=fault_type, target=target,
                               repetitions=1, injection_seconds=1)


def test_workflow_start_is_blocked_outside_lab_before_database_access(monkeypatch):
    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    monkeypatch.setattr(workflows.db, "transaction", lambda **_: pytest.fail("DB must not be touched"))
    with pytest.raises(PermissionError):
        workflows.create_run(mode="quick", fault_type="F-1", target=None,
                             repetitions=1, injection_seconds=1)


@pytest.mark.parametrize("repetitions,seconds", [(0, 1), (11, 1), (1, 0), (1, 121)])
def test_workflow_limits_are_enforced(repetitions, seconds):
    with pytest.raises(ValueError):
        workflows.build_cases(mode="custom", fault_type="F-2", target=None,
                              repetitions=repetitions, injection_seconds=seconds)


# --- D 장애 시험 결과 격자 (운영 대시보드 블록 D) ---------------------------------------------
# 유형별 최신 5회차를 모아 `moa/ops_view.trial_summary` 가 먹는 모양으로 바꾼다.
# 칸의 초는 PRD R-20 이 정본으로 정한 SC-3 기준 `recovered_at - injected_at`(= mttd + mttr)이다.
# dev 의 mttr_ms 는 탐지 기준이라 비정본이며, `mttr_sec` 로 따로 함께 내보낸다.
GRID_ROWS = [
    # F-1 — 2회차분. 가장 오래된 것이 1회 칸으로 간다
    {"fault_type": "F-1", "status": "PASS", "mttd_ms": 3000, "mttr_ms": 38000},
    {"fault_type": "F-1", "status": "FAIL", "mttd_ms": 2000, "mttr_ms": None},
    # F-2 — 사람 개입으로 끝난 두 종류. 분모에는 남고 분자에서 빠진다
    {"fault_type": "F-2", "status": "AWAITING_APPROVAL", "mttd_ms": 1000, "mttr_ms": 9000},
    {"fault_type": "F-2", "status": "NEEDS_REVIEW", "mttd_ms": 1000, "mttr_ms": 5000},
    # F-3 — 분모 밖 둘
    {"fault_type": "F-3", "status": "INVALID", "mttd_ms": None, "mttr_ms": None},
    {"fault_type": "F-3", "status": "running", "mttd_ms": None, "mttr_ms": None},
    {"fault_type": "F-3", "status": "queued", "mttd_ms": None, "mttr_ms": None},
    # F-4 — 분모 25회 밖. 별도 줄로 빠진다
    {"fault_type": "F-4", "status": "PASS", "mttd_ms": 1000, "mttr_ms": 60000},
    {"fault_type": "F-4", "status": "FAIL", "mttd_ms": 1000, "mttr_ms": None},
    {"fault_type": "F-4", "status": "AWAITING_APPROVAL", "mttd_ms": 1000, "mttr_ms": 61000},
]


def _grid(monkeypatch, rows):
    seen = {}

    def fake_fetch_all(sql, params=None, *, role="app"):
        seen["sql"], seen["params"], seen["role"] = sql, params, role
        return [dict(r) for r in rows]

    monkeypatch.setattr(workflows.db, "fetch_all", fake_fetch_all)
    return workflows.trials_grid(), seen


def test_trials_grid_maps_each_status_to_its_dashboard_cell(monkeypatch):
    grid, _ = _grid(monkeypatch, GRID_ROWS)
    by_fault = {row["fault"]: row for row in grid["rows"]}

    assert [c["result"] for c in by_fault["F-1"]["cells"]] == ["auto", "failed"]
    # 사람 개입(승인 대기 · 확인 필요)은 "승인 · 수동" 칸이다 — 분모에 남고 분자에서 빠진다(PRD 565행)
    assert [c["result"] for c in by_fault["F-2"]["cells"]] == ["approved", "approved"]
    assert [c["result"] for c in by_fault["F-3"]["cells"]] == ["invalid", "running", "pending"]


def test_trials_grid_cell_seconds_are_injected_to_recovered(monkeypatch):
    grid, _ = _grid(monkeypatch, GRID_ROWS)
    cell = {row["fault"]: row for row in grid["rows"]}["F-1"]["cells"][0]
    assert cell["sec"] == 41        # (3000 + 38000) / 1000 — SC-3 정본
    assert cell["mttr_sec"] == 38   # 탐지 기준(비정본) 은 별도 값으로만 둔다 (R-20)
    # 시각이 없는 회차는 초를 지어내지 않는다
    assert {row["fault"]: row for row in grid["rows"]}["F-3"]["cells"][0]["sec"] is None


def test_trials_grid_keeps_f4_in_its_own_row_outside_the_denominator(monkeypatch):
    grid, _ = _grid(monkeypatch, GRID_ROWS)
    assert "F-4" not in [row["fault"] for row in grid["rows"]]
    # 안전 전환 여부만 본다 — 차단 후 승인 대기도 전환이 일어난 것이다(F-4 기대 결과)
    assert [c["result"] for c in grid["f4"]["cells"]] == ["switched", "not_switched", "switched"]


def test_trials_grid_covers_every_recoverable_fault_and_sc4_denominator(monkeypatch):
    grid, _ = _grid(monkeypatch, GRID_ROWS)
    # 데이터가 없는 유형도 줄은 둔다 — 격자에 구멍이 나면 "안 한 것"과 "줄이 빠진 것"을 구분할 수 없다
    assert [row["fault"] for row in grid["rows"]] == ["F-1", "F-2", "F-3", "F-5", "F-6"]
    assert grid["rows"][3]["cells"] == [] and grid["rows"][4]["cells"] == []
    assert grid["total_runs"] == 25        # F-1 · F-2 · F-3 · F-5 · F-6 각 5회 (SC-4 분모 · F-4 제외)


def test_trials_grid_with_no_history_is_empty_not_an_empty_grid(monkeypatch):
    grid, _ = _grid(monkeypatch, [])
    # ops_view.trial_summary 는 rows 가 비면 None 을 돌려 "아직 없음" 안내를 띄운다
    assert grid["rows"] == [] and grid["f4"] is None


def test_trials_grid_asks_the_healing_role_for_the_latest_five_per_fault(monkeypatch):
    _, seen = _grid(monkeypatch, GRID_ROWS)
    assert seen["role"] == "healing"
    assert 5 in (seen["params"] or ())
