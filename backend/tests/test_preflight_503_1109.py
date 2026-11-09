# 2026-11-09 보고 — 운영 대시보드 장애 시험 환경점검이 "HTTP 503" 으로 막혀 시험을 못 돌린다
#
# 1) 503 행이 원인 · 해결을 말한다 (해석기 주입 모드 · backend DB/메뉴 적재 · Gateway 서버 없음)
# 2) "남은 장애 주입" 행 — 해제 방법을 주입 주인(도구줄 · 진행 중 시험 · 끝난 시험)에 맞춰 안내한다
# 3) 끝난 시험이 남긴 주입은 healing worker 가 닫는다 — 환경점검 교착 방지
#
# 판정기 자기 검증(G-A0): 정상 200 은 ready=True · "정상"으로, 503 은 ready=False 로 갈리는지 함께 본다.
import httpx
import pytest

from app.services import workflows


def _resp(status, body=None):
    return httpx.Response(status, json=body if body is not None else {},
                          request=httpx.Request("GET", "http://x"))


def _check(monkeypatch, response, explain):
    monkeypatch.setattr(workflows.httpx, "get", lambda *a, **k: response)
    return workflows._http_check("x", "http://x", explain=explain)


def test_ok_stays_ok(monkeypatch):
    got = _check(monkeypatch, _resp(200, {"status": "ok"}), workflows._why_interpreter)
    assert got == {"name": "x", "ready": True, "detail": "정상"}


def test_interpreter_503_names_the_leftover_injection(monkeypatch):
    got = _check(monkeypatch, _resp(503, {"status": "down", "mode": "error"}), workflows._why_interpreter)
    assert got["ready"] is False
    assert "장애 주입" in got["detail"] and "[해제]" in got["detail"]


@pytest.mark.parametrize("checks,expect", [
    ({"db": False, "db_text": "연결 실패 (OperationalError)", "menu_preload": False}, "DB 연결 실패"),
    ({"db": True, "menu_preload": False, "menu_preload_error": "DbUnavailable"}, "메뉴 사전 적재 실패"),
])
def test_backend_ready_503_says_which_part_failed(monkeypatch, checks, expect):
    got = _check(monkeypatch, _resp(503, {"status": "not_ready", "checks": checks}), workflows._why_backend)
    assert got["ready"] is False and expect in got["detail"]


def test_gateway_503_points_to_backends(monkeypatch):
    got = _check(monkeypatch, httpx.Response(503, text="<html>No server is available</html>",
                                             request=httpx.Request("GET", "http://x")),
                 workflows._why_frontend)
    assert got["ready"] is False and "backend" in got["detail"]


def test_connection_error_is_not_ready(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(workflows.httpx, "get", boom)
    got = workflows._http_check("x", "http://x")
    assert got["ready"] is False and "ConnectError" in got["detail"]


@pytest.mark.parametrize("rows,ready,hint", [
    ([], True, "없음"),
    ([{"fault": "F-1", "target": "order_interpreter_primary", "mode": "error",
       "run_id": None, "run_status": None}], False, "[해제]"),
    ([{"fault": "F-1", "target": "order_interpreter_primary", "mode": "error",
       "run_id": "WF-1", "run_status": "running"}], False, "진행 중"),
    ([{"fault": "F-1", "target": "order_interpreter_primary", "mode": "error",
       "run_id": "WF-1", "run_status": "failed"}], False, "healing worker"),
])
def test_leftover_injection_row(monkeypatch, rows, ready, hint):
    monkeypatch.setattr(workflows.db, "fetch_all", lambda *a, **k: rows)
    got = workflows._leftover_injections()
    assert got["ready"] is ready and hint in got["detail"]


def test_worker_clears_only_finished_run_injections(monkeypatch):
    import healing.__main__ as worker

    seen = {"sql": None, "cleared": [], "restarted": []}

    def fetch_all(sql, params=None, *, role="app"):
        seen["sql"] = sql
        return [{"injection_id": "fi_1", "run_id": "WF-1", "fault": "F-1",
                 "target": "order_interpreter_primary", "mode": "error"},
                {"injection_id": "fi_2", "run_id": "WF-1", "fault": "F-3",
                 "target": "moa-a-backend-1", "mode": "kill"}]

    monkeypatch.setattr(worker.db, "fetch_all", fetch_all)
    monkeypatch.setattr(worker.db, "execute", lambda sql, params=None, **k: seen["cleared"].append(params[0]))
    monkeypatch.setattr(worker, "_docker_action",
                        lambda target, action: (seen["restarted"].append(target), (True, "ok"))[1])
    monkeypatch.setattr(worker, "_event", lambda *a, **k: None)

    worker._clear_orphan_injections()
    # 진행 중 시험은 건드리지 않는다
    assert "NOT IN ('queued','preflight','running','stop_requested','cleaning')" in seen["sql"]
    assert seen["cleared"] == ["fi_1", "fi_2"]
    assert seen["restarted"] == ["moa-a-backend-1"]          # F-3 는 재시작 먼저


def test_worker_keeps_f3_record_open_when_restart_fails(monkeypatch):
    import healing.__main__ as worker

    cleared = []
    monkeypatch.setattr(worker.db, "fetch_all", lambda *a, **k: [
        {"injection_id": "fi_2", "run_id": "WF-1", "fault": "F-3", "target": "moa-a-backend-1", "mode": "kill"}])
    monkeypatch.setattr(worker.db, "execute", lambda sql, params=None, **k: cleared.append(params[0]))
    monkeypatch.setattr(worker, "_docker_action", lambda *a: (False, "proxy down"))
    monkeypatch.setattr(worker, "_event", lambda *a, **k: None)
    worker._clear_orphan_injections()
    assert cleared == []          # 꺼진 컨테이너를 "정리됨"으로 숨기지 않는다
