"""도구줄(T1)과 복구 시험(T2)의 경계 — 운영 서버에서 둘을 함께 쓸 때 (2026-11-09).

1. T1 [해제] 가 시험 주입(run_id 있음)까지 닫아 시험 회차의 장애가 중간에 풀렸다.
2. 화면은 `status.trial_holding` 이 있을 때만 T1 을 잠그는데 서버가 그 값을 보내지 않아
   시험 중에도 같은 해석기에 장애를 겹쳐 넣을 수 있었다. 8501 · 8502 화면은 서로를 모르므로
   서버도 시험 중 도구줄 주입을 거절한다(409 TRIAL_ACTIVE).

양방향으로 잠근다 — 시험이 있으면 막고(a), 없으면 막지 않는다(b).
"""
import pytest

from app.services import incidents


class _Cur:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchall(self):
        return []


class _Tx:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return _Cur(self.log)

    def __exit__(self, *exc):
        return False


@pytest.fixture
def lab(monkeypatch):
    state = {"sql": [], "run": None}
    monkeypatch.setattr(incidents.config, "ENVIRONMENT", "lab")
    monkeypatch.setattr(incidents.db, "transaction", lambda role="app": _Tx(state["sql"]))
    monkeypatch.setattr(incidents.db, "fetch_one", lambda *a, **k: state["run"])
    return state


# --- 1. [해제] 는 도구줄 주입만 닫는다 -------------------------------------------------
def test_clear_leaves_trial_injections_alone(lab):
    assert incidents.inject(None, "clear")["ok"] is True
    sql = lab["sql"][0][0]
    assert "UPDATE healing.fault_injection" in sql and "run_id IS NULL" in sql


# --- 2. 시험 중이면 대상을 알리고 도구줄 주입을 거절한다 --------------------------------
def test_status_names_the_target_a_trial_is_injecting(lab):
    lab["run"] = {"cases": [{"target": "order_interpreter_primary"}], "current_iteration": 1,
                  "injected": "order_interpreter_backup"}
    assert incidents.trial_holding() == "주문 해석 대체"


def test_between_iterations_the_current_case_target_is_held(lab):
    lab["run"] = {"cases": [{"target": "moa-a-backend-1"}, {"target": "moa-b-backend-1"}],
                  "current_iteration": 2, "injected": None}
    assert incidents.trial_holding() == "앱 B 처리 프로세스"


def test_a_queued_run_without_progress_holds_its_first_case(lab):
    lab["run"] = {"cases": [{"target": "menu_store"}], "current_iteration": 0, "injected": None}
    assert incidents.trial_holding() == "메뉴 저장소"


def test_toolbar_injection_is_refused_while_a_trial_runs(lab):
    lab["run"] = {"cases": [{"target": "order_interpreter_primary"}], "current_iteration": 1,
                  "injected": "order_interpreter_primary"}
    result = incidents.inject("F-1")
    assert result["ok"] is False and result["busy"] is True
    assert lab["sql"] == []                         # 주입 행을 쓰지 않았다


def test_toolbar_injection_goes_through_without_a_trial(lab):
    """(b) 반대 방향 — 시험이 없으면 막지 않는다. 막기만 확인하면 항상 막는 구현도 통과한다."""
    assert incidents.trial_holding() is None
    result = incidents.inject("F-1")
    assert result["ok"] is True and result["target"] == "order_interpreter_primary"
    assert "INSERT INTO healing.fault_injection" in lab["sql"][0][0]


def test_an_unreadable_trial_table_does_not_lock(monkeypatch):
    def boom(*a, **k):
        raise incidents.db.DbUnavailable("down")
    monkeypatch.setattr(incidents.db, "fetch_one", boom)
    assert incidents.trial_holding() is None


# --- API 층 — 시험 중 거절은 409 이고 실습 환경 거절(403)과 섞이지 않는다 ---------------
def test_api_answers_409_while_a_trial_runs(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import deps
    from app.main import app

    monkeypatch.setattr(incidents, "inject", lambda code, action="inject": {
        "ok": False, "busy": True, "user_message": "복구 시험이 주문 해석 1차를 쓰고 있어요"})
    app.dependency_overrides[deps.ops_token] = lambda: "t"
    try:
        res = TestClient(app).post("/api/ops/faults", json={"code": "F-1", "action": "inject"})
    finally:
        app.dependency_overrides.pop(deps.ops_token, None)
    assert res.status_code == 409
    assert "TRIAL_ACTIVE" in res.text
