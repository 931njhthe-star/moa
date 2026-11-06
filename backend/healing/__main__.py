"""Long-running worker entry point for the existing Compose `healing` service."""

import json
import logging
import os
import secrets
import socket
import time
from datetime import datetime, timezone

import httpx
import psycopg

from app import config, db, ids
from app.contracts import TASK_CONTRACTS
from app.interpreter_client import InterpreterError, interpret_resilient
from app.services import incidents, menu, workflows

LOG = logging.getLogger("moa.healing")
WORKER_ID = os.getenv("HOSTNAME") or socket.gethostname()
POLL_SEC = 1.0
LEASE_SEC = 30
F_CODE = {"F-1": "DEP_HTTP_5XX", "F-2": "DEP_TIMEOUT", "F-3": "WORKER_DOWN",
          "F-4": "REPEATED_FAILURE", "F-5": "AGENT_OUTPUT_INVALID", "F-6": "DB_UNAVAILABLE"}
INCIDENT_LABELS = {
    "DEP_HTTP_5XX": "주문 해석 오류 응답", "DEP_TIMEOUT": "응답 지연",
    "WORKER_DOWN": "처리 프로세스 중단", "REPEATED_FAILURE": "반복 장애",
    "AGENT_OUTPUT_INVALID": "잘못된 결과 형식", "DB_UNAVAILABLE": "메뉴 저장소 연결 끊김",
}


def _allowlist() -> list[str]:
    return sorted({v.strip() for v in os.getenv("HEALING_ALLOWLIST", "").split(",") if v.strip()})


def _docker_client() -> httpx.Client:
    host = os.getenv("DOCKER_HOST", "tcp://socket-proxy:2375")
    if host.startswith("tcp://"):
        host = "http://" + host.removeprefix("tcp://")
    return httpx.Client(base_url=host, timeout=4.0)


def _heartbeat() -> None:
    proxy_ok = False
    detail = ""
    try:
        with _docker_client() as client:
            response = client.get("/_ping")
            proxy_ok = response.status_code == 200 and response.text.strip() == "OK"
            if not proxy_ok:
                detail = f"proxy HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        detail = f"proxy {type(exc).__name__}"
    db.execute(
        "INSERT INTO healing.workflow_worker(worker_id,last_seen,proxy_ok,allowlist,detail) "
        "VALUES (%s,NOW(),%s,%s::jsonb,%s) ON CONFLICT(worker_id) DO UPDATE SET "
        "last_seen=NOW(),proxy_ok=EXCLUDED.proxy_ok,allowlist=EXCLUDED.allowlist,detail=EXCLUDED.detail",
        (WORKER_ID, proxy_ok, json.dumps(_allowlist()), detail or None), role="healing")


def _event(run_id: str, kind: str, summary: str, iteration: int | None = None, details: dict | None = None) -> None:
    db.execute("INSERT INTO healing.workflow_event(run_id,iteration_no,event_type,summary,details) "
               "VALUES (%s,%s,%s,%s,%s::jsonb)",
               (run_id, iteration, kind, summary, json.dumps(details or {}, ensure_ascii=False)), role="healing")


def _record_verification(result: dict) -> None:
    incident_id = result.get("incident_id")
    if not incident_id:
        return
    fault = result.get("fault_type")
    check_name = {"F-1": "request_sample", "F-3": "health_consecutive",
                  "F-6": "cache_db_match"}.get(fault, "function_test")
    expected = {"F-1": "5 successful synthetic requests", "F-3": "3 consecutive backend, frontend, and Gateway checks",
                "F-5": "invalid output ends in NEEDS_REVIEW after 3 attempts",
                "F-6": "stale cache checksum matches preloaded checksum"}.get(fault, "fault-specific behavior verified")
    actual = result.get("detail", "")
    expected_safe_outcome = (actual == "NEEDS_REVIEW" or "approval" in actual.lower())
    verification_passed = bool(result.get("passed") or expected_safe_outcome)
    db.execute("INSERT INTO healing.verification_result(incident_id,check_name,expected,actual,passed,verdict) "
               "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(incident_id,check_name) DO UPDATE SET "
               "expected=EXCLUDED.expected,actual=EXCLUDED.actual,passed=EXCLUDED.passed,"
               "verdict=EXCLUDED.verdict,verified_at=NOW()",
               (incident_id, check_name, expected, actual, verification_passed,
                "pass" if verification_passed else "fail"), role="healing")


def _update_run(run_id: str, *, status: str | None = None, phase: str | None = None,
                iteration: int | None = None, summary: dict | None = None) -> None:
    db.execute("UPDATE healing.workflow_run SET status=COALESCE(%s,status),phase=COALESCE(%s,phase),"
               "current_iteration=COALESCE(%s,current_iteration),summary=COALESCE(%s::jsonb,summary),"
               "updated_at=NOW(), started_at=COALESCE(started_at,CASE WHEN %s='running' THEN NOW() END),"
               "finished_at=CASE WHEN %s IN ('completed','stopped','failed','needs_operator_action','invalid') "
               "THEN NOW() ELSE finished_at END WHERE run_id=%s",
               (status, phase, iteration, json.dumps(summary) if summary is not None else None,
                status, status, run_id), role="healing")


def _cancelled(run_id: str) -> bool:
    row = db.fetch_one("SELECT cancel_requested FROM healing.workflow_run WHERE run_id=%s",
                       (run_id,), role="healing")
    return bool(row and row["cancel_requested"])


def _sleep_or_stop(run_id: str, seconds: float) -> bool:
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        if _cancelled(run_id):
            return True
        time.sleep(min(0.5, deadline - time.monotonic()))
    return _cancelled(run_id)


def _claim() -> dict | None:
    with db.transaction(role="healing") as cur:
        # A dead worker's lease is never replayed blindly: end its injections and surface operator action.
        cur.execute("SELECT run_id FROM healing.workflow_lease WHERE lease_name='active' "
                    "AND lease_until < NOW() FOR UPDATE")
        expired = cur.fetchone()
        if expired:
            stale_id = expired["run_id"]
            cur.execute("SELECT target,fault,mode FROM healing.fault_injection "
                        "WHERE run_id=%s AND action='inject' AND cleared_at IS NULL", (stale_id,))
            stale_injections = cur.fetchall()
            restart_failures = []
            for injection in stale_injections:
                if injection["fault"] == "F-3" and injection["mode"] == "kill":
                    recovered, detail = _docker_action(injection["target"], "restart")
                    if not recovered:
                        restart_failures.append(detail)
            cur.execute("UPDATE healing.fault_injection SET cleared_at=COALESCE(cleared_at,NOW()) "
                        "WHERE run_id=%s AND action='inject' AND cleared_at IS NULL", (stale_id,))
            cur.execute("UPDATE healing.workflow_run SET status='needs_operator_action',phase='cleanup',"
                        "finished_at=NOW(),updated_at=NOW() WHERE run_id=%s "
                        "AND status IN ('running','stop_requested','cleaning')", (stale_id,))
            summary = "expired lease cleanup; operator verification required"
            if restart_failures:
                summary += "; backend restart failed: " + ",".join(restart_failures)
            cur.execute("INSERT INTO healing.workflow_event(run_id,event_type,summary) "
                        "VALUES (%s,'lease_recovered',%s)", (stale_id, summary))
            cur.execute("DELETE FROM healing.workflow_lease WHERE lease_name='active'")
        cur.execute("SELECT run_id FROM healing.workflow_run WHERE status='queued' "
                    "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        run_id = row["run_id"]
        cur.execute("UPDATE healing.workflow_run SET status='running',phase='preflight',started_at=NOW(),updated_at=NOW() "
                    "WHERE run_id=%s AND status='queued' RETURNING *", (run_id,))
        run = cur.fetchone()
        if not run:
            return None
        cur.execute("INSERT INTO healing.workflow_lease(lease_name,run_id,worker_id,lease_until) "
                    "VALUES ('active',%s,%s,NOW() + (%s * INTERVAL '1 second')) "
                    "ON CONFLICT(lease_name) DO UPDATE SET run_id=EXCLUDED.run_id,worker_id=EXCLUDED.worker_id,"
                    "lease_until=EXCLUDED.lease_until,updated_at=NOW()",
                    (run_id, WORKER_ID, LEASE_SEC))
        return run


def _renew_lease(run_id: str) -> None:
    db.execute("UPDATE healing.workflow_lease SET lease_until=NOW() + (%s * INTERVAL '1 second'),updated_at=NOW() "
               "WHERE lease_name='active' AND run_id=%s AND worker_id=%s",
               (LEASE_SEC, run_id, WORKER_ID), role="healing")


def _inject(run_id: str, no: int, fault: str, target: str, mode: str) -> str:
    injection_id = ids.injection_id()
    with db.transaction(role="healing") as cur:
        cur.execute("INSERT INTO healing.fault_injection "
                    "(injection_id,fault,action,target,mode,environment,run_id,iteration_no) "
                    "VALUES (%s,%s,'inject',%s,%s,'lab',%s,%s)",
                    (injection_id, fault, target, mode, run_id, no))
        cur.execute("UPDATE healing.workflow_iteration SET status='running',phase='injecting',"
                    "injection_id=%s,started_at=NOW() WHERE run_id=%s AND iteration_no=%s",
                    (injection_id, run_id, no))
        cur.execute("UPDATE healing.workflow_run SET phase='injecting',current_iteration=%s,updated_at=NOW() "
                    "WHERE run_id=%s", (no, run_id))
    _event(run_id, "injection_started", f"{fault} 장애 주입", no,
           {"injection_id": injection_id, "target": target, "mode": mode})
    return injection_id


def _clear(run_id: str, injection_id: str) -> bool:
    db.execute("UPDATE healing.fault_injection SET cleared_at=COALESCE(cleared_at,NOW()) "
               "WHERE injection_id=%s AND run_id=%s AND action='inject'",
               (injection_id, run_id), role="healing")
    row = db.fetch_one("SELECT cleared_at FROM healing.fault_injection WHERE injection_id=%s AND run_id=%s",
                       (injection_id, run_id), role="healing")
    return bool(row and row["cleared_at"])


def _create_incident(run_id: str, iteration: int, fault: str, injection_id: str,
                     evidence: str) -> str:
    incident_id = "INC-WF-" + secrets.token_hex(6).upper()
    code = F_CODE[fault]
    trace_id = f"tr_{secrets.token_hex(6).upper()}"
    db.execute("INSERT INTO healing.incident(incident_id,trace_id,fault_code,status,status_label,"
               "injected_at,detected_at,detection_metric,detection_evidence,is_verification_run,run_id) "
               "SELECT %s,%s,%s,'detected',%s,injected_at,NOW(),'workflow_signal',ARRAY[%s],true,%s "
               "FROM healing.fault_injection WHERE injection_id=%s",
               (incident_id, trace_id, code, INCIDENT_LABELS[code], evidence, run_id, injection_id), role="healing")
    db.execute("UPDATE healing.workflow_iteration SET incident_id=%s WHERE run_id=%s AND iteration_no=%s",
               (incident_id, run_id, iteration), role="healing")
    db.execute("UPDATE healing.fault_injection SET incident_id=%s WHERE injection_id=%s AND run_id=%s",
               (incident_id, injection_id, run_id), role="healing")
    return incident_id


def _service_for(target: str) -> str:
    return "backup" if target.endswith("backup") else "primary"


def _probe_circuit(target: str, run_id: str, incident_id: str) -> tuple[bool, str]:
    service = _service_for(target)
    key = f"order_interpreter_{service}"
    row = db.fetch_one(
        "UPDATE healing.circuit_state SET state='probing',updated_at=NOW() "
        "WHERE dependency_key=%s AND state='circuit_open' AND cooldown_until<=NOW() "
        "RETURNING dependency_key", (key,), role="healing")
    if not row:
        return False, "cooldown 또는 circuit_open 상태가 준비되지 않아 probe하지 않았습니다"
    url = config.ORDER_INTERPRETER_BACKUP_URL if service == "backup" else config.ORDER_INTERPRETER_PRIMARY_URL
    try:
        response = httpx.get(f"{url}/health", timeout=2.0)
        success = response.status_code == 200
    except httpx.HTTPError:
        success = False
    if success:
        db.execute("UPDATE healing.circuit_state SET state='up',consecutive_failures=0,"
                   "cooldown_until=NULL,healthy_streak=0,updated_at=NOW() WHERE dependency_key=%s",
                   (key,), role="healing")
        return True, "단일 probe 성공; circuit을 up으로 복귀했습니다"
    db.execute("UPDATE healing.circuit_state SET state='down',cooldown_until=NULL,updated_at=NOW() "
               "WHERE dependency_key=%s", (key,), role="healing")
    db.execute("UPDATE healing.incident SET fault_code='REPEATED_FAILURE',status='awaiting_approval',"
               "status_label='승인 대기',detection_metric='circuit_probe',"
               "detection_evidence=ARRAY['cooldown 후 단일 probe 실패'],strategy='escalate',updated_at=NOW() "
               "WHERE incident_id=%s AND run_id=%s", (incident_id, run_id), role="healing")
    return False, f"probe 실패; 자동 재시도 없이 승인 대기 사건 {incident_id}을 만들었습니다"


def _synthetic_interpreter_request(fault: str, target: str, samples: int,
                                  run_id: str, attempt_observer=None) -> tuple[bool, str, int]:
    success = 0
    errors: list[str] = []
    for index in range(samples):
        context = {"brand_id": "generic", "menu_version": config.MENU_VERSION}
        attempts = 1 + config.MAX_REGENERATE if fault == "F-5" else 1
        for attempt in range(attempts):
            try:
                interpret_resilient(
                    "extract_events", [{"message_id": f"synthetic-{run_id}-{index}", "order": index + 1,
                                        "sender": "lab-run", "text": "iced americano one"}],
                    context, service=_service_for(target), trace_id=f"workflow-{run_id}-{fault}-{index}-{attempt}",
                    session_id=None, attempt_observer=attempt_observer)
                success += 1
                break
            except InterpreterError as exc:
                errors.append(exc.fault_code)
                if fault == "F-5" and exc.fault_code == "AGENT_OUTPUT_INVALID":
                    if attempt + 1 < attempts:
                        context["validation_feedback"] = {
                            "error": exc.fault_code, "attempt": attempt + 1,
                            "instruction": "Regenerate complete output matching the required schema.",
                        }
                        continue
                    return False, "NEEDS_REVIEW", success
                break
        if success <= index:
            break
    return success == samples, ",".join(errors) or "synthetic_request_ok", success

def _docker_action(target: str, action: str) -> tuple[bool, str]:
    if target not in _allowlist() or target not in ("moa-a-backend-1", "moa-b-backend-1"):
        return False, "target is not in healing allowlist"
    try:
        with _docker_client() as client:
            response = client.post(f"/containers/{target}/{action}", params={"t": 2})
            if response.status_code not in (204, 304):
                return False, f"Docker {action} HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"Docker proxy {type(exc).__name__}"
    return True, f"Docker {action} accepted"


def _restart_backend(target: str, run_id: str, seconds: int, attempt_observer=None) -> tuple[bool, str, int | None]:
    started = time.monotonic()
    action_started = time.monotonic()
    stopped, detail = _docker_action(target, "stop")
    if attempt_observer:
        attempt_observer({"action": "backend 중지 요청", "outcome": "성공" if stopped else "실패",
                          "duration_ms": int((time.monotonic() - action_started) * 1000)})
    if not stopped:
        return False, detail, None
    down_deadline = time.monotonic() + 10
    observed_down = False
    gateway_down = False
    detected_ms = None
    letter = "a" if target.startswith("moa-a-") else "b"
    while time.monotonic() < down_deadline:
        try:
            httpx.get(f"http://{target}:8000/ready", timeout=0.5)
        except httpx.HTTPError:
            observed_down = True
        try:
            stats = httpx.get(os.getenv("GATEWAY_STATS_URL", "http://gateway:8404/stats;csv"), timeout=1.0)
            gateway_down = any(line.startswith(f"chk_{letter},backend,") and "DOWN" in line
                               for line in stats.text.splitlines())
        except httpx.HTTPError:
            pass
        if observed_down and gateway_down:
            detected_ms = int((time.monotonic() - started) * 1000)
            break
        if _cancelled(run_id):
            break
        time.sleep(0.5)
    cancelled = _sleep_or_stop(run_id, max(0, seconds - (time.monotonic() - started)))
    # Restart is unconditional after an accepted stop, including cancellation.
    action_started = time.monotonic()
    restarted, restart_detail = _docker_action(target, "restart")
    if attempt_observer:
        attempt_observer({"action": "backend 재시작 요청", "outcome": "성공" if restarted else "실패",
                          "duration_ms": int((time.monotonic() - action_started) * 1000)})
    if not restarted:
        return False, f"backend stopped but restart failed: {restart_detail}", detected_ms

    verification_started = time.monotonic()
    verification_polls = 0
    deadline = time.monotonic() + 30
    consecutive = 0
    while time.monotonic() < deadline:
        verification_polls += 1
        try:
            backend = httpx.get(f"http://{target}:8000/ready", timeout=1.0)
            frontend = httpx.get(f"http://moa-{letter}-frontend-1:8501/_stcore/health", timeout=1.0)
            stats = httpx.get(os.getenv("GATEWAY_STATS_URL", "http://gateway:8404/stats;csv"), timeout=1.0)
            gateway_up = any(line.startswith(f"chk_{letter},backend,") and "UP" in line
                             for line in stats.text.splitlines())
            consecutive = consecutive + 1 if backend.status_code == 200 and frontend.status_code == 200 and gateway_up else 0
            if consecutive >= 3:
                passed = observed_down and gateway_down and not cancelled
                if attempt_observer:
                    attempt_observer({"action": "backend·frontend·Gateway 독립 확인",
                                      "outcome": "성공" if passed else "예상과 다름",
                                      "poll_count": verification_polls,
                                      "duration_ms": int((time.monotonic() - verification_started) * 1000)})
                return passed, "3 consecutive backend/frontend/Gateway checks passed; exclusion observed=" + str(gateway_down), detected_ms
        except httpx.HTTPError:
            consecutive = 0
        time.sleep(2)
    if attempt_observer:
        attempt_observer({"action": "backend·frontend·Gateway 독립 확인",
                          "outcome": "시간 초과", "poll_count": verification_polls,
                          "duration_ms": int((time.monotonic() - verification_started) * 1000)})
    return False, "backend/frontend independent verification failed within 30 seconds", detected_ms

def _execute_case(run_id: str, no: int, case: dict) -> dict:
    fault, target, seconds = case["fault_type"], case["target"], int(case["seconds"])
    default_target, mode = workflows.FAULT_DEFAULTS[fault]
    if fault == "F-3":
        mode = "kill"
    elif fault == "F-6":
        mode = "block"
    elif target == "order_interpreter_backup":
        mode = {"F-1": "error", "F-2": "delay", "F-4": "error", "F-5": "invalid"}[fault]

    preloaded_checksum = None
    if fault == "F-6":
        # Warm this exact brand/version cache before injecting the menu read fault.
        preloaded_checksum = menu.catalog("generic", config.MENU_VERSION).get("checksum")
    attempts: list[dict] = []
    first_fault_at: float | None = None      # 장애를 **처음 관측한** 시각 (MTTD 의 끝점)

    def record_attempt(item: dict) -> None:
        nonlocal first_fault_at
        entry = dict(item)
        entry["request_attempt_no"] = entry.get("attempt_no")
        entry["attempt_no"] = len(attempts) + 1
        attempts.append(entry)
        if first_fault_at is None and entry.get("outcome") == "실패":
            first_fault_at = time.monotonic()
        _event(run_id, "recovery_attempt",
               f"시도 {entry.get('attempt_no')}: "
               f"{entry.get('service') or entry.get('action') or '해석 요청'} · "
               f"{entry.get('outcome') or entry.get('result') or '기록'}", no, entry)

    injection_id = _inject(run_id, no, fault, target, mode)
    start = time.monotonic()
    _update_run(run_id, phase="detecting", iteration=no)
    detected_at = None
    verdict, detail, request_count = False, "미검증", 0
    incident_id = None
    try:
        if fault == "F-3":
            _update_run(run_id, phase="recovering", iteration=no)
            ok, detail, detect_offset_ms = _restart_backend(target, run_id, seconds, record_attempt)
            _update_run(run_id, phase="verifying", iteration=no)
            if ok:
                function_ok, function_detail, request_count = _synthetic_interpreter_request(
                    fault, target, 1, run_id, record_attempt)
                ok = ok and function_ok
                detail += f"; synthetic function check: {function_detail}"
            verdict = ok
            detected_at = start + detect_offset_ms / 1000 if detect_offset_ms is not None else time.monotonic()
            incident_id = _create_incident(run_id, no, fault, injection_id, detail)
        elif fault == "F-6":
            from app.services.menu import catalog

            try:
                attempt_started = time.monotonic()
                recovered = catalog("generic", config.MENU_VERSION)
                verdict = bool(recovered.get("stale") and recovered.get("checksum") == preloaded_checksum)
                record_attempt({"action": "동일 버전 캐시 조회", "outcome": "성공" if verdict else "예상과 다름",
                                "duration_ms": int((time.monotonic() - attempt_started) * 1000)})
                detail = "동일 브랜드·버전 캐시 stale fallback" if verdict else "메뉴 조회 fault가 적용되지 않음"
            except db.DbUnavailable as exc:
                detail = f"cache fallback 실패: {type(exc).__name__}"
            detected_at = time.monotonic()
            incident_id = _create_incident(run_id, no, fault, injection_id, detail)
        else:
            # F-4 needs three observations to exercise the breaker; F-1 verifies five synthetic reads.
            _update_run(run_id, phase="recovering", iteration=no)
            samples = 3 if fault == "F-4" else 5 if fault == "F-1" else 1
            verdict, detail, request_count = _synthetic_interpreter_request(fault, target, samples, run_id, record_attempt)
            _update_run(run_id, phase="verifying", iteration=no)
            # 탐지 시각은 **첫 관측 실패**다. 복구 관측이 다 끝난 뒤에 찍으면 MTTD 가 복구 시간까지
            # 흡수해 과대해지고 MTTR 이 0 에 가까워진다 — 실측 2026-11-06: mttd 12,611ms · mttr 13ms.
            # SC-3(복구 60초)이 늘 통과하는 거짓 합격이 되므로 판정이 무의미해진다.
            # 실패를 한 번도 관측하지 못했으면(대체 경로로 바로 성공) 지금을 쓴다 — 그 회차는
            # 애초에 1차 장애를 거치지 않았다는 뜻이고, attempts 기록에 그 사실이 남는다
            detected_at = first_fault_at or time.monotonic()
            incident_id = _create_incident(run_id, no, fault, injection_id, detail)
            if fault == "F-4":
                _clear(run_id, injection_id)
                _update_run(run_id, phase="cooldown_probe", iteration=no)
                if _sleep_or_stop(run_id, max(0, 60 - (time.monotonic() - start))):
                    verdict, detail = False, "중지 요청으로 cooldown/probe를 중단했습니다"
                else:
                    probe_started = time.monotonic()
                    probe_ok, probe_detail = _probe_circuit(target, run_id, incident_id)
                    record_attempt({"action": "cooldown 후 단일 probe",
                                    "outcome": "성공" if probe_ok else "승인 대기/실패",
                                    "duration_ms": int((time.monotonic() - probe_started) * 1000)})
                    verdict = verdict and probe_ok
                    detail = f"{detail}; {probe_detail}"
            if fault == "F-5" and detail == "NEEDS_REVIEW":
                verdict = True  # Safe manual-review outcome is the expected F-5 test result.
        recovery_verified_at = time.monotonic()
        mttd_ms = int(max(0, (detected_at or recovery_verified_at) - start) * 1000)
        mttr_ms = int(max(0, recovery_verified_at - (detected_at or start)) * 1000)
        if _sleep_or_stop(run_id, max(0, seconds - (recovery_verified_at - start))):
            verdict, detail = False, "중지 요청으로 회차 종료"
        expected = {
            "F-1": "오류 감지 → 반대 해석기로 전환 → 합성 요청 5건 확인",
            "F-2": "5초 초과 지연 감지 → 대체 해석기 전환 → 총 15초 이내 응답",
            "F-3": "backend 제외 → 재시작 → backend/frontend/Gateway 연속 확인",
            "F-4": "3회 실패 → 60초 차단 → 단일 probe 또는 승인 대기",
            "F-5": "최대 3회 생성·검증 → 필요 시 NEEDS_REVIEW",
            "F-6": "동일 버전·checksum 캐시 폴백",
        }[fault]
        steps = [
            {"name": "장애 감지와 사건 기록", "expected": "주입한 장애를 감지하고 사건을 기록",
             "actual": "사건 기록됨" if incident_id else "사건 기록 없음",
             "duration_ms": mttd_ms, "status": "PASS" if incident_id else "FAIL"},
            {"name": "복구 시도와 독립 확인", "expected": expected, "actual": detail,
             "duration_ms": mttr_ms, "status": "PASS" if verdict else "FAIL"},
        ]
        return {"fault_type": fault, "target": target, "injection_id": injection_id,
                "incident_id": incident_id, "passed": verdict, "detail": detail,
                "synthetic_requests": request_count, "mttd_ms": mttd_ms, "mttr_ms": mttr_ms,
                "attempts": attempts, "steps": steps}
    finally:
        cleanup_started = time.monotonic()
        cleared = _clear(run_id, injection_id)
        _event(run_id, "injection_cleared" if cleared else "cleanup_failed",
               "주입 해제 확인" if cleared else "주입 해제를 확인하지 못함", no,
               {"injection_id": injection_id, "duration_ms": int((time.monotonic() - cleanup_started) * 1000),
                "status": "PASS" if cleared else "FAIL"})


def _run(run: dict) -> None:
    run_id = run["run_id"]
    cases = run["cases"]
    if isinstance(cases, str):
        cases = json.loads(cases)
    results = []
    try:
        _update_run(run_id, status="running", phase="preflight")
        first = cases[0]
        check = workflows.preflight(mode=run["mode"], fault_type=first["fault_type"],
                                    target=first["target"])
        if not check.get("ready"):
            summary = {"preflight_ready": False, "checks": check.get("checks", []),
                       "pass": 0, "fail": 0, "total": len(cases)}
            _update_run(run_id, status="invalid", phase="preflight", summary=summary)
            _event(run_id, "preflight_failed", "실행 전 점검 실패. 장애를 주입하지 않았습니다", details=summary)
            return
        for no, case in enumerate(cases, start=1):
            _renew_lease(run_id)
            if _cancelled(run_id):
                break
            fault, target = case["fault_type"], case["target"]
            db.execute("INSERT INTO healing.workflow_iteration(run_id,iteration_no,fault_type,target,status,phase) "
                       "VALUES (%s,%s,%s,%s,'queued','queued') ON CONFLICT DO NOTHING",
                       (run_id, no, fault, target), role="healing")
            _update_run(run_id, phase="fault_injection", iteration=no)
            _event(run_id, "iteration_started", f"{no}/{len(cases)}회차 · {fault} 시작", no,
                   {"target": target})
            try:
                result = _execute_case(run_id, no, case)
            except Exception as exc:  # worker must always attempt cleanup and keep the run auditable
                result = {"fault_type": fault, "target": target, "passed": False,
                          "detail": f"실행 오류: {type(exc).__name__}"}
                LOG.exception("workflow iteration failed run_id=%s iteration=%s", run_id, no)
            _record_verification(result)
            iteration_status = "PASS" if result.get("passed") else "FAIL"
            if result.get("detail") == "NEEDS_REVIEW":
                iteration_status = "NEEDS_REVIEW"
            elif ("approval" in (result.get("detail") or "").lower()
                  or "승인 대기" in (result.get("detail") or "")):
                iteration_status = "AWAITING_APPROVAL"
            result["status"] = iteration_status
            results.append(result)
            db.execute("UPDATE healing.workflow_iteration SET status=%s,phase='verified',incident_id=%s,"
                       "synthetic_requests=%s,result=%s::jsonb,finished_at=NOW(),mttd_ms=%s,mttr_ms=%s "
                       "WHERE run_id=%s AND iteration_no=%s",
                       (iteration_status, result.get("incident_id"), result.get("synthetic_requests", 0),
                        json.dumps(result, ensure_ascii=False), result.get("mttd_ms"), result.get("mttr_ms"),
                        run_id, no), role="healing")
            _event(run_id, "iteration_result", f"{no}/{len(cases)}회차 · {iteration_status}", no,
                   {"detail": result.get("detail"), "incident_id": result.get("incident_id")})
            _renew_lease(run_id)

        db.execute("UPDATE healing.fault_injection SET cleared_at=COALESCE(cleared_at,NOW()) "
                   "WHERE run_id=%s AND action='inject' AND cleared_at IS NULL", (run_id,), role="healing")
        uncleared = db.fetch_one("SELECT COUNT(*) AS n FROM healing.fault_injection "
                                 "WHERE run_id=%s AND action='inject' AND cleared_at IS NULL",
                                 (run_id,), role="healing")["n"]
        if uncleared:
            final_status = "needs_operator_action"
        elif _cancelled(run_id):
            final_status = "stopped"
        else:
            final_status = "completed"  # Means injection workflow ended, never recovery success.
        statuses = [r.get("status") or ("PASS" if r.get("passed") else "FAIL") for r in results]
        mttd_values = [r["mttd_ms"] for r in results if r.get("mttd_ms") is not None]
        mttr_values = [r["mttr_ms"] for r in results if r.get("mttr_ms") is not None]
        summary = {"pass": sum(1 for value in statuses if value == "PASS"),
                   "fail": sum(1 for value in statuses if value == "FAIL"),
                   "needs_review": sum(1 for value in statuses if value == "NEEDS_REVIEW"),
                   "awaiting_approval": sum(1 for value in statuses if value == "AWAITING_APPROVAL"),
                   "invalid": sum(1 for value in statuses if value == "INVALID"),
                   "total": len(cases), "completed_iterations": len(results),
                   "avg_mttd_ms": round(sum(mttd_values) / len(mttd_values)) if mttd_values else None,
                   "avg_mttr_ms": round(sum(mttr_values) / len(mttr_values)) if mttr_values else None}
        _update_run(run_id, status=final_status, phase="cleanup", summary=summary)
        _event(run_id, "run_finished", f"workflow {final_status}", details=summary)
    except Exception:
        LOG.exception("workflow run failed run_id=%s", run_id)
        try:
            db.execute("UPDATE healing.fault_injection SET cleared_at=COALESCE(cleared_at,NOW()) "
                       "WHERE run_id=%s AND action='inject' AND cleared_at IS NULL", (run_id,), role="healing")
            _update_run(run_id, status="failed", phase="cleanup")
            _event(run_id, "run_failed", "실행 중 오류. 남은 주입을 정리했습니다")
        except Exception:
            LOG.exception("workflow emergency cleanup failed run_id=%s", run_id)
    finally:
        db.execute("DELETE FROM healing.workflow_lease WHERE lease_name='active' AND run_id=%s AND worker_id=%s",
                   (run_id, WORKER_ID), role="healing")


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    if config.ENVIRONMENT != "lab" and os.getenv("HEALING_ENABLE_PRODUCTION_RECOVERY", "0") != "1":
        LOG.warning("lab workflow runner disabled outside ENVIRONMENT=lab")
    while True:
        try:
            _heartbeat()
            run = _claim() if config.ENVIRONMENT == "lab" else None
            if run:
                _run(run)
            else:
                time.sleep(POLL_SEC)
        except (db.DbUnavailable, psycopg.Error):
            LOG.exception("worker database operation failed")
            time.sleep(2)
        except Exception:
            LOG.exception("worker loop failed")
            time.sleep(2)


if __name__ == "__main__":
    main()
