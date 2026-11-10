"""Lab-only, single-flight workflow API support for the existing healing worker."""

import json
import secrets
from datetime import datetime, timezone

import httpx
import psycopg

from app import config, db, ids
from app.services import incidents

MAX_STEPS = 20
MAX_REPETITIONS = 10
MAX_INJECTION_SECONDS = 120
FAULT_DEFAULTS = {
    "F-1": ("order_interpreter_primary", "error"),
    "F-2": ("order_interpreter_primary", "delay"),
    "F-3": ("moa-a-backend-1", "kill"),
    "F-4": ("order_interpreter_primary", "error"),
    "F-5": ("order_interpreter_primary", "invalid"),
    "F-6": ("menu_store", "block"),
}
FAULT_LABELS = {
    "F-1": "해석기 HTTP 오류 전환", "F-2": "해석기 지연 전환",
    "F-3": "backend 재시작·복귀", "F-4": "회로 차단·probe",
    "F-5": "출력 검증·재생성", "F-6": "메뉴 캐시 폴백",
}
RECOVERABLE = ("F-1", "F-2", "F-3", "F-5", "F-6")
# 무인 복구율(사람 없이 복구) 집계 대상 — F-4 도 넣는다(2026-11-09 팀 결정, PRD 개정 전 코드 선반영).
# F-4 는 차단 → cooldown → 단일 probe 성공으로 끝나면 사람 없이 복구한 것이다. 승인 대기로 끝나면 승인 칸
GRID_FAULTS = ("F-1", "F-2", "F-3", "F-4", "F-5", "F-6")
ACTIVE_RUN_STATUSES = ("queued", "preflight", "running", "stop_requested", "cleaning")


def templates() -> list[dict]:
    return [{"template_id": code, "fault_type": code, "label": label,
             "default_target": FAULT_DEFAULTS[code][0],
             "default_seconds": 1, "default_repetitions": 1,
             "description": label}
            for code, label in FAULT_LABELS.items()]


def _json(response) -> dict:
    try:
        body = response.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def _why_interpreter(response) -> str:
    """해석기 /health 가 200 이 아닌 이유. 503 은 **주입된 error 모드일 때만** 난다(interpreter/main.py)."""
    mode = _json(response).get("mode")
    if mode == "error":
        return "HTTP 503 · 장애 주입(error 모드)이 남아 있음 → 장애 도구줄 [해제] 후 다시 점검"
    return f"HTTP {response.status_code} · 해석기 로그 확인"


def _why_backend(response) -> str:
    """backend /ready 가 503 인 이유 — DB 연결과 메뉴 사전 적재 중 어느 쪽인가."""
    checks = _json(response).get("checks") or {}
    if checks and not checks.get("db"):
        return f"HTTP {response.status_code} · DB 연결 실패 ({checks.get('db_text') or '-'})"
    if checks and not checks.get("menu_preload"):
        return (f"HTTP {response.status_code} · 메뉴 사전 적재 실패 "
                f"({checks.get('menu_preload_error') or '-'}) → 메뉴 시드 확인")
    return f"HTTP {response.status_code}"


def _why_frontend(response) -> str:
    if response.status_code == 503:
        # HAProxy 503 = 보낼 서버가 없다. 서버 상태는 각 스택 backend /ready 를 따라간다(gateway/haproxy.cfg)
        return "HTTP 503 · Gateway 에 살아 있는 앱 스택 없음 → A/B backend 행 먼저 확인"
    return f"HTTP {response.status_code}"


def _http_check(name: str, url: str, timeout: float = 3.0,
                headers: dict[str, str] | None = None, explain=None) -> dict:
    """200 이면 정상. 아니면 **원인과 해결**을 detail 에 적는다 — "HTTP 503" 만으로는 운영자가 움직일 수 없다."""
    try:
        response = httpx.get(url, timeout=timeout, headers=headers)
    except httpx.HTTPError as exc:
        return {"name": name, "ready": False,
                "detail": f"연결할 수 없음 ({type(exc).__name__}) → 컨테이너 기동 여부 확인"}
    if response.status_code == 200:
        return {"name": name, "ready": True, "detail": "정상"}
    detail = explain(response) if explain else f"HTTP {response.status_code}"
    return {"name": name, "ready": False, "detail": detail}


def _leftover_injections() -> dict:
    """해제되지 않은 장애 주입. 남아 있으면 해석기 /health 가 503 이고 새 시험의 측정이 오염된다."""
    try:
        rows = db.fetch_all(
            "SELECT fi.fault, fi.target, fi.mode, fi.run_id, r.status AS run_status "
            "  FROM healing.fault_injection fi "
            "  LEFT JOIN healing.workflow_run r ON r.run_id = fi.run_id "
            " WHERE fi.action = 'inject' AND fi.cleared_at IS NULL ORDER BY fi.injected_at",
            role="healing")
    except (db.DbUnavailable, psycopg.Error) as exc:
        return {"name": "남은 장애 주입", "ready": False,
                "detail": f"주입 상태 확인 실패 ({type(exc).__name__})"}
    if not rows:
        return {"name": "남은 장애 주입", "ready": True, "detail": "없음"}
    listed = ", ".join(f"{r['fault']}→{r['target']}({r['mode']})" for r in rows[:3])
    more = f" 외 {len(rows) - 3}건" if len(rows) > 3 else ""
    if any(r["run_id"] is None for r in rows):
        how = "장애 도구줄 [해제] 후 다시 점검"
    elif any(r["run_status"] in ACTIVE_RUN_STATUSES for r in rows):
        how = "진행 중인 복구 시험이 끝난 뒤 다시 점검"
    else:
        # 끝난 시험이 정리하지 못한 주입 — healing worker 가 다음 순회에 닫는다(_clear_orphan_injections)
        how = "끝난 시험의 정리 누락 · healing worker 가 몇 초 안에 정리 → 다시 점검 (계속 남으면 healing 로그 확인)"
    return {"name": "남은 장애 주입", "ready": False, "detail": f"{listed}{more} → {how}"}


def preflight(*, mode: str = "quick", fault_type: str = "F-1", target: str | None = None) -> dict:
    """Check prerequisites without writing an injection or mutating app data."""
    checks = [{"name": "lab 환경", "ready": config.ENVIRONMENT == "lab",
               "detail": "실습 환경" if config.ENVIRONMENT == "lab" else "ENVIRONMENT=lab에서만 실행 가능"}]
    if config.db_configured():
        health = db.health()
        checks.append({"name": "DB 연결", "ready": health["state"] == "connected",
                       "detail": health["text"]})
        try:
            rows = db.fetch_all(
                "SELECT to_regclass('healing.workflow_run') AS run_table, "
                "to_regclass('healing.workflow_worker') AS worker_table", role="healing")
            schema_ok = bool(rows and rows[0]["run_table"] and rows[0]["worker_table"])
            checks.append({"name": "workflow 스키마", "ready": schema_ok,
                           "detail": "준비됨" if schema_ok else "backend/sql/15_schema_workflows.sql 적용 필요"})
            worker = db.fetch_one(
                "SELECT worker_id, last_seen, proxy_ok, allowlist "
                "FROM healing.workflow_worker ORDER BY last_seen DESC LIMIT 1", role="healing")
            fresh = bool(worker and (datetime.now(timezone.utc) - worker["last_seen"]).total_seconds() <= 15)
            checks.append({"name": "healing worker", "ready": fresh,
                           "detail": "실행 중" if fresh else "worker heartbeat 없음"})
            allowlist = worker.get("allowlist") if worker else []
            proxy_ready = fresh and bool(worker and worker["proxy_ok"])
            checks.append({"name": "Docker proxy·allowlist", "ready": proxy_ready,
                           "detail": "연결·허용목록 확인" if proxy_ready else "worker proxy 확인 또는 allowlist 미준비"})
            backend_allowlist_ok = all(name in (allowlist or []) for name in ("moa-a-backend-1", "moa-b-backend-1"))
            checks.append({"name": "backend allowlist", "ready": fresh and backend_allowlist_ok,
                           "detail": "A/B allowed" if fresh and backend_allowlist_ok else "A/B backend missing from allowlist"})
        except (db.DbUnavailable, psycopg.Error) as exc:
            checks.append({"name": "workflow 스키마", "ready": False,
                           "detail": f"스키마/worker 상태 확인 실패 ({type(exc).__name__})"})
            allowlist = []
        checks.append(_leftover_injections())
    else:
        checks.extend([
            {"name": "DB 연결", "ready": False, "detail": "DATABASE_URL 미설정"},
            {"name": "workflow 스키마", "ready": False, "detail": "DB 연결 필요"},
            {"name": "healing worker", "ready": False, "detail": "DB 연결 필요"},
            {"name": "Docker proxy·allowlist", "ready": False, "detail": "DB 연결 필요"},
        ])
        allowlist = []

    checks.append(_http_check("Gateway", "http://gateway:8404/stats;csv"))
    for role in ("primary", "backup"):
        url = {"primary": config.ORDER_INTERPRETER_PRIMARY_URL,
               "backup": config.ORDER_INTERPRETER_BACKUP_URL}[role]
        checks.append(_http_check(f"interpreter {role}", f"{url}/health", explain=_why_interpreter) if url else
                      {"name": f"interpreter {role}", "ready": False, "detail": "주소 미설정"})

    for letter in ("a", "b"):
        name = f"moa-{letter}-backend-1"
        checks.append(_http_check(f"{letter.upper()} backend", f"http://{name}:8000/ready",
                                  explain=_why_backend))
        # Frontends intentionally stay on their isolated A/B networks, so the
        # ops backend cannot resolve their container DNS names. Probe each one
        # through the shared Gateway using its sticky routing cookie instead.
        checks.append(_http_check(
            f"{letter.upper()} frontend", "http://gateway:8501/_stcore/health",
            headers={"Cookie": f"MOA_STACK={letter}"}, explain=_why_frontend,
        ))
    if fault_type == "F-3" and target:
        checks.append({"name": "F-3 allowlisted target", "ready": target in allowlist,
                       "detail": "allowlisted" if target in allowlist else "target missing from worker allowlist"})
    return {"ready": bool(checks) and all(c["ready"] for c in checks), "checks": checks,
            "environment": config.ENVIRONMENT, "checked_at": datetime.now(timezone.utc).isoformat()}


def build_cases(*, mode: str, fault_type: str, target: str | None,
                repetitions: int, injection_seconds: int) -> list[dict]:
    if mode not in ("quick", "full", "custom"):
        raise ValueError("mode는 quick, full, custom 중 하나여야 합니다")
    if fault_type not in FAULT_DEFAULTS:
        raise ValueError("지원하지 않는 장애 유형입니다")
    if not 1 <= repetitions <= MAX_REPETITIONS:
        raise ValueError(f"반복 횟수는 1~{MAX_REPETITIONS}회여야 합니다")
    if not 1 <= injection_seconds <= MAX_INJECTION_SECONDS:
        raise ValueError(f"주입 시간은 1~{MAX_INJECTION_SECONDS}초여야 합니다")
    if mode == "quick":
        repetitions = 1
    if mode == "full":
        cases = []
        for code in GRID_FAULTS:
            for ix in range(5):
                default_target, _ = FAULT_DEFAULTS[code]
                case_target = (f"moa-{'a' if ix % 2 == 0 else 'b'}-backend-1"
                               if code == "F-3" else default_target)
                cases.append({"fault_type": code, "target": case_target,
                              "seconds": injection_seconds})
        return cases

    default_target, _ = FAULT_DEFAULTS[fault_type]
    chosen = target or default_target
    if fault_type in ("F-1", "F-2", "F-4", "F-5") and chosen not in (
            "order_interpreter_primary", "order_interpreter_backup"):
        raise ValueError("해석기 장애 대상은 primary 또는 backup이어야 합니다")
    if fault_type == "F-3" and chosen not in ("moa-a-backend-1", "moa-b-backend-1"):
        raise ValueError("F-3 대상은 허용목록 backend A 또는 B여야 합니다")
    if fault_type == "F-6" and chosen != "menu_store":
        raise ValueError("F-6 대상은 menu_store여야 합니다")
    return [{"fault_type": fault_type, "target": chosen, "seconds": injection_seconds}
            for _ in range(repetitions)]


def create_run(*, mode: str, fault_type: str, target: str | None,
               repetitions: int, injection_seconds: int, idempotency_key: str | None = None) -> dict:
    if config.ENVIRONMENT != "lab":
        raise PermissionError("장애 시험은 ENVIRONMENT=lab에서만 실행할 수 있습니다")
    cases = build_cases(mode=mode, fault_type=fault_type, target=target,
                        repetitions=repetitions, injection_seconds=injection_seconds)
    if (mode != "full" and len(cases) > MAX_STEPS) or (mode == "full" and len(cases) != 5 * len(GRID_FAULTS)):
        raise ValueError("workflow 단계 상한을 초과했습니다")
    check = preflight(mode=mode, fault_type=fault_type, target=target)
    if not check["ready"]:
        return {"ready": False, "preflight": check}
    run_id = "run_" + secrets.token_hex(8)
    try:
        with db.transaction(role="healing") as cur:
            cur.execute(
                "INSERT INTO healing.workflow_run "
                "(run_id, mode, template_id, environment, cases, total_iterations, "
                " idempotency_key, preflight) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING run_id",
                (run_id, mode, fault_type if mode != "full" else f"full-{len(cases)}", config.ENVIRONMENT,
                 json.dumps(cases), len(cases), idempotency_key, json.dumps(check)))
            row = cur.fetchone()
            if row is None and idempotency_key:
                cur.execute("SELECT run_id FROM healing.workflow_run WHERE idempotency_key=%s",
                            (idempotency_key,))
                row = cur.fetchone()
                return get_run(row["run_id"])
            cur.execute(
                "INSERT INTO healing.workflow_event(run_id,event_type,summary,details) "
                "VALUES (%s,'queued','사전 점검 통과, 실행 대기',%s::jsonb)",
                (run_id, json.dumps({"case_count": len(cases)})))
    except psycopg.errors.UniqueViolation as exc:
        raise RuntimeError("이미 실행 중인 workflow가 있습니다") from exc
    return get_run(run_id)


def get_run(run_id: str) -> dict | None:
    row = db.fetch_one("SELECT * FROM healing.workflow_run WHERE run_id=%s", (run_id,), role="healing")
    if not row:
        return None
    iterations = db.fetch_all(
        "SELECT iteration_no,fault_type,target,status,phase,injection_id,incident_id,"
        "synthetic_requests,result,started_at,finished_at,mttd_ms,mttr_ms "
        "FROM healing.workflow_iteration WHERE run_id=%s ORDER BY iteration_no",
        (run_id,), role="healing")
    events = db.fetch_all(
        "SELECT event_type,summary,details,created_at FROM healing.workflow_event "
        "WHERE run_id=%s ORDER BY event_id DESC LIMIT 500", (run_id,), role="healing")
    return {**row, "iterations": iterations, "events": list(reversed(events))}


def list_runs(limit: int = 20) -> list[dict]:
    rows = db.fetch_all(
        "SELECT run_id,mode,template_id,status,phase,current_iteration,total_iterations,"
        "created_at,started_at,finished_at,summary FROM healing.workflow_run "
        "ORDER BY created_at DESC LIMIT %s", (max(1, min(limit, 100)),), role="healing")
    return rows


def request_stop(run_id: str) -> dict | None:
    with db.transaction(role="healing") as cur:
        cur.execute(
            "UPDATE healing.workflow_run SET cancel_requested=true,status='stop_requested',"
            "phase='stop_requested',updated_at=NOW() WHERE run_id=%s "
            "AND status IN ('queued','preflight','running','stop_requested','cleaning') RETURNING run_id",
            (run_id,))
        row = cur.fetchone()
        if row:
            cur.execute("INSERT INTO healing.workflow_event(run_id,event_type,summary) "
                        "VALUES (%s,'stop_requested','중지 요청. 합성 요청을 멈추고 장애를 정리합니다')",
                        (run_id,))
    return get_run(run_id) if row else None


def export_run(run_id: str) -> dict | None:
    data = get_run(run_id)
    if not data:
        return None
    # Keep export deliberately bounded to this run; environment secrets are never selected.
    return {"run": {k: data[k] for k in ("run_id","mode","template_id","status","phase",
                                             "total_iterations","current_iteration","summary",
                                             "created_at","started_at","finished_at")},
            "iterations": data["iterations"], "events": data["events"]}

# --- D 장애 시험 결과 격자 (운영 대시보드 블록 D · PRD 5.6.1) ---------------------------------
# 유형별 **최신 5회차**를 여러 run 에 걸쳐 모아 `moa/ops_view.trial_summary` 가 먹는 모양으로 낸다.
# 빠른 확인(quick)을 여러 번 돌려도 격자가 채워지게 하려고 run 하나로 묶지 않는다(2026-11-06 결정).
TRIALS_PER_FAULT = 5

# status -> 칸. 어휘는 ops_view.trial_summary 가 정한 것이다
#   auto      사람 없이 복구  분자 · 분모
#   approved  승인 · 수동     분모만 — 사람이 개입해 끝난 회차는 분모에 남기고 실패로 센다(PRD 5.6.1)
#   failed    실패           분모만
#   invalid   무효           분모 밖 — 주입 도구 오류 · 준비 실패
#   running   진행 중        분모 밖 (아직 안 한 회차는 pending)
# NEEDS_REVIEW 는 사람이 승인한 것이 아니라 담당자 확인으로 **넘긴** 것이다(F-5 의 PRD 기대 결과).
# 종전에는 "승인"과 같은 칸으로 그려 F-5 가 늘 승인받은 것처럼 보였다(2026-11-09)
_CELL_BY_STATUS = {"PASS": "auto", "AWAITING_APPROVAL": "approved", "NEEDS_REVIEW": "review",
                   "FAIL": "failed", "INVALID": "invalid", "running": "running", "queued": "pending"}
# F-4 는 종전에 안전 전환 여부만 보는 별도 줄(분모 밖)이었다. 2026-11-09 부터 다른 유형과 같은
# 칸 규칙으로 무인 복구율에 넣는다 — probe 성공(PASS)은 자동, 승인 대기는 승인 칸


def _trial_cell(row: dict) -> dict:
    """칸 하나 — 초는 SC-3 정본 `recovered_at - injected_at` 이다.

    healing 이 적는 mttr_ms 는 **탐지 기준**(`검증 통과 - 탐지`)이라 SC-3 과 다르다(PRD R-20).
    R-20 의 해소 지침대로 정본은 주입 기준(mttd + mttr)으로 내고, 탐지 기준은 `mttr_sec` 로 따로 둔다 —
    한 칸에서 두 정의가 섞이면 60초 목표 초과 판정이 조용히 틀린다.
    """
    mttd, mttr = row.get("mttd_ms"), row.get("mttr_ms")
    total_ms = None if mttr is None else (mttd or 0) + mttr
    # F-5 는 NEEDS_REVIEW 로 끝나는 것이 기대 결과라 성공 칸이다(2026-11-09 팀 결정).
    # healing 은 이제 PASS 로 적지만, 그 전에 NEEDS_REVIEW 로 저장된 회차도 같은 칸에 넣는다
    status = row.get("status")
    if row.get("fault_type") == "F-5" and status == "NEEDS_REVIEW":
        status = "PASS"
    return {"result": _CELL_BY_STATUS.get(status, "pending"),
            "sec": None if total_ms is None else round(total_ms / 1000),
            "mttr_sec": None if mttr is None else round(mttr / 1000)}


def trials_grid(per_fault: int = TRIALS_PER_FAULT) -> dict:
    """유형별 최신 N회차 격자. 모양은 `{"total_runs", "rows": [{"fault", "cells"}], "f4"}`.

    기록이 아예 없으면 `rows` 를 비워 둔다 — ops_view 가 그때 "아직 없음" 안내를 띄운다.
    하나라도 있으면 집계 대상 6종(F-1 ~ F-6)의 줄을 모두 둔다. 격자에 구멍이 나면 보는 사람이
    "아직 안 한 유형"과 "줄이 빠진 유형"을 구분할 수 없다.
    """
    rows = db.fetch_all(
        "SELECT fault_type,status,mttd_ms,mttr_ms FROM ("
        " SELECT i.fault_type,i.status,i.mttd_ms,i.mttr_ms,"
        "        ROW_NUMBER() OVER (PARTITION BY i.fault_type"
        "          ORDER BY COALESCE(i.finished_at,i.started_at) DESC NULLS LAST,"
        "                   i.run_id DESC, i.iteration_no DESC) AS rn"
        "   FROM healing.workflow_iteration i) t"
        " WHERE rn <= %s ORDER BY fault_type, rn DESC", (per_fault,), role="healing")
    total_runs = per_fault * len(GRID_FAULTS)
    if not rows:
        return {"total_runs": total_runs, "rows": [], "f4": None, "latest_run": None}
    by_fault: dict[str, list[dict]] = {}
    for row in rows:
        by_fault.setdefault(row["fault_type"], []).append(row)
    grid = [{"fault": fault, "cells": [_trial_cell(r) for r in by_fault.get(fault, [])]}
            for fault in GRID_FAULTS]
    # "f4" 별도 줄은 더 내지 않는다(F-4 가 rows 에 들어갔다). 키는 화면 호환을 위해 None 으로 둔다
    return {"total_runs": total_runs, "rows": grid, "f4": None, "latest_run": _latest_run()}


def _latest_run() -> dict | None:
    """격자 위에 적을 최신 실행 — 실행 ID와 예상 흐름 일치 수.

    "25회 중 몇 회를 했는가"만으로는 **어느 실행의 숫자인지** 알 수 없어 캡처가 증빙이 되지 않는다.
    일치는 `PASS`(예상대로 통과) ÷ 판정이 난 회차다. 진행 중 · 대기 회차는 분모에서 뺀다.
    """
    try:
        row = db.fetch_one(
            "SELECT run_id, summary FROM healing.workflow_run ORDER BY created_at DESC LIMIT 1",
            role="healing")
    except (db.DbUnavailable, psycopg.Error):
        return None     # 실행 이름을 못 읽었다고 격자를 통째로 비우지 않는다
    if not row:
        return None
    summary = row.get("summary") or {}
    ok = int(summary.get("pass") or 0)
    valid = ok + int(summary.get("fail") or 0) + int(summary.get("needs_review") or 0)         + int(summary.get("awaiting_approval") or 0)
    return {"run_id": row["run_id"], "ok": ok, "valid": valid,
            "avg_mttd_ms": summary.get("avg_mttd_ms"), "avg_mttr_ms": summary.get("avg_mttr_ms")}
