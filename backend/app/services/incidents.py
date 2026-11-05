"""운영 대시보드 조회 서비스 — 사건 · 회로 · 지표 · 처리 기록 (O-1 ~ O-6).

이 모듈은 **읽기와 사람의 결정 기록**만 한다. 탐지 · 진단 · 복구 실행은
장애 대응 층(별도 컨테이너 · 순수 파이썬 상태기계)의 몫이다 — D-12 · D-15 범위다.
섞으면 "업무와 함께 죽지 않기"가 깨진다 (D-03 1.2).

쓰기는 `healing_rw` 롤로 한다. 업무 롤(app_rw)은 healing 스키마에 쓸 수 없다 —
권한으로 막혀 있고, 그것이 PRD 5.7 금지 행동의 DB 쪽 구현이다.
"""

from app import config, db, ids

# P-03 7절 장애 코드 7종 → 화면 문구
FAULT_LABEL = {
    "DEP_HTTP_5XX": "주문 해석 오류 응답",
    "DEP_TIMEOUT": "응답 지연",
    "WORKER_DOWN": "처리 프로세스 중단",
    "AGENT_OUTPUT_INVALID": "잘못된 결과 형식",
    "REPEATED_FAILURE": "반복 장애",
    "DB_UNAVAILABLE": "메뉴 저장소 연결 끊김",
    "UNKNOWN": "원인 미확인",
}

STATE_LABEL = {
    "detected": "탐지",
    "recovering": "복구 중",
    "awaiting_approval": "승인 대기",
    "manual_check": "수동 점검",
    "recovered": "복구 성공",
    "failed": "복구 실패",
}

SERVICE_LABEL = {
    "order_interpreter_primary": "주문 해석 1차",
    "order_interpreter_backup": "주문 해석 대체",
    "menu_store": "메뉴 저장소",
    "agent_process": "처리 프로세스",
}

CIRCUIT_STATE_TEXT = {
    "up": "정상",
    "degraded": "느림",
    "down": "중단",
    "circuit_open": "차단",
    "probing": "시험 중",
}

# F-1 ~ F-6 → 주입 대상과 모드 (D-02 6.1)
FAULT_TARGETS = {
    "F-1": ("order_interpreter_primary", "error"),
    "F-2": ("order_interpreter_primary", "delay"),
    "F-3": ("agent_process", "kill"),
    "F-4": ("order_interpreter_primary", "error"),
    "F-5": ("order_interpreter_primary", "invalid"),
    "F-6": ("menu_store", "block"),
}


# --- O-1 사건 목록 · O-4 승인 대기 -------------------------------------------
def incident_list(limit: int = 50) -> dict:
    rows = db.fetch_all(
        "SELECT incident_id, fault_code, status, status_label, detected_at, resolved_at, "
        "       strategy, detection_evidence "
        "  FROM healing.incident "
        " WHERE is_verification_run = false "
        " ORDER BY detected_at DESC LIMIT %s",
        (limit,), role="healing")

    incidents = [{
        "incident_id": row["incident_id"],
        "fault_code": row["fault_code"],
        "state": row["status"],
        "state_text": row["status_label"] or STATE_LABEL.get(row["status"], row["status"]),
        "detected_at_text": _hhmmss(row["detected_at"]),
        "resolved_at_text": _hhmmss(row["resolved_at"]) or "-",
    } for row in rows]

    approvals = [{
        "incident_id": row["incident_id"],
        "summary": FAULT_LABEL.get(row["fault_code"], row["fault_code"]),
        "waiting_text": _waiting_text(row["detected_at"]),
        "recommendation_text": _recommendation(row),
    } for row in rows if row["status"] == "awaiting_approval"]

    # 화면이 한 번의 호출로 둘을 함께 받는다 (screens/ops.py 가 병합해 쓴다)
    return {"incidents": incidents, "approvals": approvals}


def incident_detail(incident_id: str) -> dict | None:
    row = db.fetch_one(
        "SELECT * FROM healing.incident WHERE incident_id = %s", (incident_id,),
        role="healing")
    if not row:
        return None
    attempts = db.fetch_all(
        "SELECT attempt_no, action, wait_ms, tool, tool_args, result, error, "
        "       started_at, ended_at "
        "  FROM healing.recovery_attempt WHERE incident_id = %s ORDER BY attempt_no",
        (incident_id,), role="healing")
    checks = db.fetch_all(
        "SELECT check_name, expected, actual, passed, verdict, verified_at "
        "  FROM healing.verification_result WHERE incident_id = %s ORDER BY check_name",
        (incident_id,), role="healing")
    approval = db.fetch_one(
        "SELECT decision, approver, note, recommendation_text, waiting_sec, decided_at "
        "  FROM healing.approval WHERE incident_id = %s", (incident_id,), role="healing")

    return {
        "incident_id": row["incident_id"],
        "trace_id": row["trace_id"],
        "fault_code": row["fault_code"],
        "fault_label": FAULT_LABEL.get(row["fault_code"], row["fault_code"]),
        "state": row["status"],
        "state_text": row["status_label"] or STATE_LABEL.get(row["status"]),
        "strategy": row["strategy"],
        "timeline": [
            {"key": "injected", "label": "주입", "at_text": _hhmmss(row["injected_at"])},
            {"key": "detected", "label": "탐지", "at_text": _hhmmss(row["detected_at"])},
            {"key": "recovery_started", "label": "복구 시작",
             "at_text": _hhmmss(row["recovery_started_at"])},
            {"key": "resolved", "label": "정상화", "at_text": _hhmmss(row["resolved_at"])},
            {"key": "failed", "label": "실패", "at_text": _hhmmss(row["failed_at"])},
        ],
        "detection": {"metric": row["detection_metric"],
                      "evidence": list(row["detection_evidence"] or [])},
        "diagnosis": {"rule": row["diagnosis_rule"], "reason": row["diagnosis_reason"]},
        "attempts": [{**a, "started_at": _hhmmss(a["started_at"]),
                      "ended_at": _hhmmss(a["ended_at"])} for a in attempts],
        "verification": [{**c, "verified_at": _hhmmss(c["verified_at"])} for c in checks],
        "approval": ({**approval, "decided_at": _hhmmss(approval["decided_at"])}
                     if approval else None),
        "session_id": row["session_id"],
        "checkpoint": row["checkpoint"],
        "paused_ms": row["paused_ms"],
        "elapsed_ms": row["elapsed_ms"],
        "is_false_positive": row["is_false_positive"],
    }


def decide(incident_id: str, decision: str, *, note: str | None = None) -> dict:
    """O-4 승인 · 거부. **첫 결정만 반영된다** — 사건당 1건 (D-07 4.17).

    대기 시간을 `paused_ms` 에 넣는다. 이것이 없으면 운영자가 늦게 승인한 사건의
    MTTR 이 사람 대기 시간을 포함해 SC-3 측정이 오염된다 (D-03 1.4).
    """
    if decision not in ("approve", "reject"):
        raise ValueError(decision)

    row = db.fetch_one(
        "SELECT status, detected_at, recovery_started_at FROM healing.incident "
        " WHERE incident_id = %s", (incident_id,), role="healing")
    if not row:
        return {"ok": False, "user_message": "사건을 찾지 못했어요"}

    existing = db.fetch_one("SELECT decision FROM healing.approval WHERE incident_id = %s",
                            (incident_id,), role="healing")
    if existing:
        # 재요청은 409 다 — 호출자가 그렇게 돌려준다
        return {"ok": False, "already": existing["decision"],
                "user_message": "이미 결정된 사건이에요"}

    with db.transaction(role="healing") as cur:
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM (NOW() - detected_at))::int AS waited "
            "  FROM healing.incident WHERE incident_id = %s", (incident_id,))
        waited = int(cur.fetchone()["waited"] or 0)
        cur.execute(
            "INSERT INTO healing.approval "
            "  (incident_id, decision, approver, note, waiting_sec) "
            "VALUES (%s, %s, '운영자', %s, %s)",
            (incident_id, decision, note, waited))
        # 승인하면 복구가 이어지고, 거부하면 수동 점검으로 넘긴다.
        # 복구 실행은 장애 대응 층이 한다 — 여기서는 상태와 멈춘 시간만 적는다
        next_status = "recovering" if decision == "approve" else "manual_check"
        cur.execute(
            "UPDATE healing.incident "
            "   SET status = %s, status_label = %s, paused_ms = paused_ms + %s, "
            "       escalated_at = CASE WHEN %s = 'manual_check' THEN NOW() ELSE escalated_at END, "
            "       updated_at = NOW() "
            " WHERE incident_id = %s",
            (next_status, STATE_LABEL[next_status], waited * 1000, next_status, incident_id))

    label = "승인함" if decision == "approve" else "거부함"
    return {"ok": True, "user_message": f"{incident_id} {label}", "waiting_sec": waited}


# --- O-3 지금 상태 ------------------------------------------------------------
def status_view() -> dict:
    rows = db.fetch_all(
        "SELECT dependency_key, state, consecutive_failures, cache_fallback_active, "
        "       is_active_route, healthy_streak, probe_at, cooldown_until, updated_at "
        "  FROM healing.circuit_state ORDER BY dependency_key", role="healing")

    services = []
    for row in rows:
        if row["dependency_key"] == "agent_process":
            continue        # 화면 O-3 은 의존 서비스 3개만 보여준다
        services.append({
            "name": SERVICE_LABEL.get(row["dependency_key"], row["dependency_key"]),
            "key": row["dependency_key"],
            "state": _ui_state(row),
            "state_text": _state_text(row),
            "active": bool(row["is_active_route"]),
            "healthy_streak": row["healthy_streak"],
        })

    active = next((r["dependency_key"] for r in rows if r["is_active_route"]), None)
    latest = max((r["updated_at"] for r in rows), default=None)
    return {
        "updated_at_text": _hhmmss(latest) or "-",
        "environment_label": "실습 환경" if config.ENVIRONMENT == "lab" else config.ENVIRONMENT,
        "services": services,
        "active_interpreter": active,
        "cache_fallback_active": any(r["cache_fallback_active"] for r in rows),
    }


def _ui_state(row: dict) -> str:
    """화면이 색으로 쓰는 값. circuit_open 은 `blocked` 로 보낸다."""
    return {"circuit_open": "blocked", "probing": "probing", "down": "down",
            "degraded": "degraded"}.get(row["state"], "up")


def _state_text(row: dict) -> str:
    base = CIRCUIT_STATE_TEXT.get(row["state"], row["state"])
    if row["state"] == "circuit_open" and row["probe_at"]:
        seconds = _seconds_until(row["probe_at"])
        if seconds is not None and seconds > 0:
            return f"차단 · {seconds}초 후 시험"
    if row["cache_fallback_active"]:
        return f"{base} · 캐시 폴백"
    return base


# --- O-5 지표 ----------------------------------------------------------------
def metrics_view() -> dict:
    row = db.fetch_one("SELECT * FROM healing.v_metrics", role="healing") or {}
    detail = {
        "mttd_sec": _num(row.get("mttd_sec")),
        "mttr_sec": _num(row.get("mttr_sec")),
        "recovery_success_rate": _num(row.get("recovery_success_rate")),
        "escalation_count": int(row.get("escalation_count") or 0),
        "false_positive_rate": _num(row.get("false_positive_rate")),
        "avg_attempts": _num(row.get("avg_attempts")),
        "incident_count": int(row.get("incident_count") or 0),
    }
    return {
        # 0% 와 "측정값 없음"을 구분한다 — 뷰가 0건일 때 NULL 을 돌려주는 이유다
        "metrics": [
            {"label": "MTTD", "value_text": _sec_text(detail["mttd_sec"])},
            {"label": "MTTR", "value_text": _sec_text(detail["mttr_sec"])},
            {"label": "성공률", "value_text": _pct_text(detail["recovery_success_rate"])},
            {"label": "에스컬레이션", "value_text": str(detail["escalation_count"])},
        ],
        "detail": detail,
    }


# --- O-6 주문 처리 기록 -------------------------------------------------------
def order_list(limit: int = 50) -> dict:
    rows = db.fetch_all(
        "SELECT s.session_id, s.brand_id, s.status, s.completed_at, "
        "       (SELECT COUNT(*) FROM app.change_log c WHERE c.session_id = s.session_id) "
        "         AS change_count, "
        "       (SELECT COUNT(*) FROM app.change_log c WHERE c.session_id = s.session_id "
        "          AND c.method = 'auto_recovery') AS recovery_count "
        "  FROM app.order_session s "
        " WHERE s.is_verification = false "
        " ORDER BY s.updated_at DESC LIMIT %s", (limit,))
    return {"orders": [{
        "order_id": row["session_id"],
        "brand_label": "스타벅스" if row["brand_id"] == "starbucks" else "일반 카페",
        "state_text": "주문 확정" if row["status"] == "completed" else "확인 받는 중",
        "confirmed_at_text": _hhmm(row["completed_at"]) or "-",
        "change_count_text": f'{row["change_count"]}건',
        "recovery_count_text": f'{row["recovery_count"]}건',
    } for row in rows]}


def order_detail(session_id: str) -> dict:
    from app.services import changes

    shares = db.fetch_all("SELECT shared_at, method FROM app.share_history WHERE session_id = %s "
                          " ORDER BY shared_at", (session_id,))
    return {"order_id": session_id, "changes": changes.history(session_id),
            "share_history": [{"at_text": _hhmm(r["shared_at"]), "method": r["method"],
                               "method_text": SHARE_METHOD_LABEL.get(r["method"], r["method"])}
                              for r in shares]}


SHARE_METHOD_LABEL = {"copy_text": "텍스트 복사", "save_image": "이미지 저장"}


# --- API-049 장애 주입 --------------------------------------------------------
def inject(code: str | None, action: str = "inject") -> dict:
    """실습 전용. `lab` 환경에서만 받는다 (D-07 4.18 environment 가드).

    주입과 사건을 별개 테이블에 둔다 — 주입이 사건보다 **먼저** 일어나고,
    탐지되지 않은 주입(오탐률의 분모)을 기록할 곳이 필요하다.
    """
    if config.ENVIRONMENT != "lab":
        return {"ok": False, "user_message": "실습 환경에서만 쓸 수 있어요"}

    if action == "clear":
        with db.transaction(role="healing") as cur:
            cur.execute(
                "UPDATE healing.fault_injection SET cleared_at = NOW() "
                " WHERE cleared_at IS NULL AND action = 'inject' RETURNING injection_id")
            cleared = cur.fetchall()
        return {"ok": True, "user_message": "장애를 해제했어요", "cleared": len(cleared)}

    if code not in FAULT_TARGETS:
        return {"ok": False, "user_message": "모르는 장애 코드예요"}

    target, mode = FAULT_TARGETS[code]
    injection_id = ids.injection_id()
    with db.transaction(role="healing") as cur:
        cur.execute(
            "INSERT INTO healing.fault_injection "
            "  (injection_id, fault, action, target, mode, environment) "
            "VALUES (%s, %s, 'inject', %s, %s, %s)",
            (injection_id, code, target, mode, config.ENVIRONMENT))
    return {"ok": True, "user_message": f"{code} 주입했어요",
            "injection_id": injection_id, "target": target, "mode": mode}


def active_injections() -> list[dict]:
    """지금 주입 중인 장애. 모의 주문 해석 서비스와 메뉴 조회가 이것을 읽는다."""
    return db.fetch_all(
        "SELECT injection_id, fault, target, mode, injected_at "
        "  FROM healing.fault_injection "
        " WHERE action = 'inject' AND cleared_at IS NULL ORDER BY injected_at",
        role="healing")


# --- 표시 보조 ---------------------------------------------------------------
def _hhmmss(value) -> str | None:
    return value.strftime("%H:%M:%S") if value else None


def _hhmm(value) -> str | None:
    return value.strftime("%H:%M") if value else None


def _waiting_text(detected_at) -> str:
    import datetime

    if not detected_at:
        return "-"
    delta = datetime.datetime.now(detected_at.tzinfo) - detected_at
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes}분째 대기" if minutes else "방금"


def _seconds_until(value) -> int | None:
    import datetime

    if not value:
        return None
    return int((value - datetime.datetime.now(value.tzinfo)).total_seconds())


def _recommendation(row: dict) -> str:
    evidence = list(row["detection_evidence"] or [])
    tail = f' · 증거 {len(evidence)}건 ({", ".join(evidence)})' if evidence else ""
    return f"추천: 수동 점검 후 재개{tail}"


def _num(value):
    return None if value is None else round(float(value), 2)


def _sec_text(value) -> str:
    return "-" if value is None else f"{value:g}s"


def _pct_text(value) -> str:
    return "-" if value is None else f"{round(value * 100)}%"
