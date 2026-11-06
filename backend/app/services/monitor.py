"""상시 감시 — 업무 층이 남긴 메트릭을 읽어 **실제 장애 사건**을 만든다 (PRD 5.6.1 · FR-013).

지금까지 `healing.incident` 는 장애 시험 워크플로 안에서만 만들어졌다(`is_verification_run=true`).
운영 중 저절로 난 장애는 탐지도 기록도 되지 않아 대시보드 E 블록과 지표 뷰가 비어 있었다.

경계(PRD 5.3 v1.1): 요청 안 복구(재시도 · 대체 전환 · 폴백)는 업무 층이 이미 했다.
여기서 하는 일은 **사건을 만들고 증거를 묶는 것**이고, 프로세스 수준 조치와 검증은 healing 워커가 한다.

판정 조건은 PRD 5.6.1 정본이다.

    dep_5xx_ratio      5xx 연속 2회      -> DEP_HTTP_5XX
    timeout_count      호출 5초 초과 1회  -> DEP_TIMEOUT
    schema_error_rate  스키마 실패 1회    -> AGENT_OUTPUT_INVALID

`dep_latency_ms` 는 추세용이라 그것만으로는 사건이 되지 않는다 — 넘은 호출은 `timeout_count` 로 따로 남는다.
"""

import secrets

from app import db

# metric_key -> (장애 코드, 사건이 되는 최소 관측 수, 사람이 읽는 이름)
_RULES = {
    "dep_5xx_ratio": ("DEP_HTTP_5XX", 2, "주문 해석 오류 응답"),
    "timeout_count": ("DEP_TIMEOUT", 1, "응답 지연"),
    "schema_error_rate": ("AGENT_OUTPUT_INVALID", 1, "잘못된 결과 형식"),
    # 처리되지 않은 예외 1회로 사건이 된다 (PRD 5.6.1 에이전트 실행 FT-02)
    "agent_error_count": ("AGENT_EXCEPTION", 1, "처리 중 예외"),
}
# F-3(agent_error_count · restart_count)과 F-6(db_connection_error · slow_query_count)은
# 수집 훅이 들어오는 단계에서 함께 넣는다. 수집이 없는 규칙을 미리 두면 사건이 만들어지지 않거나,
# 만들어져도 닫을 검증 경로가 없어 열린 채 쌓인다

# 아직 닫히지 않은 사건 — 같은 장애가 열려 있으면 새로 만들지 않고 증거만 쌓는다(PRD 5.6.1 Monitor 책임)
_OPEN_STATUSES = ("detected", "recovering", "awaiting_approval", "manual_check")

WINDOW_SEC = 60


def pending_signals(window_sec: int = WINDOW_SEC) -> list[dict]:
    """사건이 될 만한 관측 묶음. 이미 사건에 묶인 행과 열린 사건은 제외한다."""
    rows = db.fetch_all(
        "SELECT id,metric_key,target,value,breached,measured_at,trace_id "
        "  FROM healing.runtime_metric m "
        " WHERE breached = true AND incident_id IS NULL "
        "   AND measured_at > NOW() - (%s * INTERVAL '1 second') "
        # 장애 시험 구간의 관측은 실제 사건이 아니다. 시험 주입에만 run_id 가 있다 —
        # 섞으면 SC-4 무인 복구율과 사건 수가 오염된다(R-14 측정 오염과 같은 종류).
        # 주입 구간과 **겹치는 동안의** 관측만 뺀다 — 주입 전후의 실제 장애는 그대로 사건이 된다
        "   AND NOT EXISTS (SELECT 1 FROM healing.fault_injection fi "
        "                    WHERE fi.run_id IS NOT NULL AND fi.target = m.target "
        "                      AND m.measured_at >= fi.injected_at "
        "                      AND (fi.cleared_at IS NULL OR m.measured_at <= fi.cleared_at)) "
        " ORDER BY measured_at, id", (window_sec,), role="healing")

    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        rule = _RULES.get(row["metric_key"])
        if not rule:
            continue                                   # 추세 메트릭(dep_latency_ms 등)은 사건 재료가 아니다
        grouped.setdefault((rule[0], row["target"]), []).append(row)

    signals = []
    for (fault_code, target), group in grouped.items():
        # 같은 장애 코드로 묶되 최소 관측 수는 메트릭마다 다르다 — 가장 느슨한 것을 쓴다
        need = min(_RULES[r["metric_key"]][1] for r in group)
        if len(group) < need:
            continue
        if _open_incident_count(fault_code, target):
            continue
        label = _RULES[group[0]["metric_key"]][2]
        signals.append({
            "fault_code": fault_code, "target": target, "label": label,
            "metric_key": group[0]["metric_key"],
            "metric_ids": [r["id"] for r in group],
            "detected_at": group[0]["measured_at"],
            "trace_id": next((r["trace_id"] for r in group if r["trace_id"]), None),
            "evidence": [f"{r['metric_key']}={r['value']}" for r in group],
        })
    return signals


def _open_incident_count(fault_code: str, target: str) -> int:
    row = db.fetch_one(
        "SELECT COUNT(*) AS n FROM healing.incident "
        " WHERE fault_code = %s AND status = ANY(%s) AND is_verification_run = false",
        (fault_code, list(_OPEN_STATUSES)), role="healing")
    return (row or {}).get("n", 0)


def open_incident(signal: dict) -> str:
    """사건을 만들고 쓴 관측을 묶는다. 주입이 아니라 실제 장애이므로 `injected_at` 은 두지 않는다."""
    incident_id = "INC-" + secrets.token_hex(6).upper()
    trace_id = signal.get("trace_id") or f"tr_{secrets.token_hex(6).upper()}"
    db.execute(
        "INSERT INTO healing.incident(incident_id,trace_id,fault_code,status,status_label,"
        "detected_at,detection_metric,detection_evidence,is_verification_run) "
        "VALUES (%s,%s,%s,'detected',%s,%s,%s,%s,false)",
        (incident_id, trace_id, signal["fault_code"], signal["label"],
         signal["detected_at"], signal["metric_key"], signal["evidence"]), role="healing")
    # 쓴 행에 사건을 묶어 둔다 — 안 하면 다음 순회에서 같은 관측을 또 세어 사건이 쏟아진다
    db.execute("UPDATE healing.runtime_metric SET incident_id = %s WHERE id = ANY(%s)",
               (incident_id, signal["metric_ids"]), role="healing")
    return incident_id



def close_incident(incident_id: str, *, recovered: bool, manual_check: bool = False) -> None:
    """사건을 닫는다. 칸 이름은 `healing.incident` 그대로다 — `recovered_at` 은 없다.

    복구 완료는 `resolved_at`, 자동 복구 실패는 `failed_at` + `escalated_at` 이다.
    `recovery_started_at` 은 처음 값을 지킨다 — MTTR 구간이 뒤로 밀리면 안 된다.

    `manual_check` 는 담당자 확인으로 넘긴 경우다 — F-5 가 NEEDS_REVIEW 로 끝나는 것은
    안전한 기대 결과이지 복구도 실패도 아니다. 복구 시각 · 실패 시각을 지어내지 않는다.
    """
    if manual_check:
        db.execute("UPDATE healing.incident SET status='manual_check',status_label=%s,"
                   "recovery_started_at=COALESCE(recovery_started_at,detected_at),"
                   "escalated_at=NOW() WHERE incident_id=%s",
                   ("담당자 확인 필요", incident_id), role="healing")
        return
    if recovered:
        db.execute("UPDATE healing.incident SET status='recovered',status_label=%s,"
                   "recovery_started_at=COALESCE(recovery_started_at,detected_at),"
                   "resolved_at=NOW() WHERE incident_id=%s",
                   ("정상 복구", incident_id), role="healing")
        return
    db.execute("UPDATE healing.incident SET status='failed',status_label=%s,"
               "recovery_started_at=COALESCE(recovery_started_at,detected_at),"
               "failed_at=NOW(),escalated_at=NOW() WHERE incident_id=%s",
               ("자동 복구 실패", incident_id), role="healing")


# --- 폴링으로 직접 관측한 장애 (F-3) ----------------------------------------------------------
# 사건을 만드는 입구가 둘이다. 메트릭을 세는 pending_signals 와, 헬스체크처럼 **직접 관측**하는 이쪽.
# 둘 다 Monitor 역할이고, 중복 방지 기준(열린 사건)도 같다.
def open_incident_for(fault_code: str, target: str, *, label: str, detection_metric: str,
                      evidence: list[str], trace_id: str | None = None) -> str | None:
    """직접 관측한 장애의 사건. 같은 장애가 이미 열려 있으면 만들지 않고 None 을 돌려준다."""
    if _open_incident_count(fault_code, target):
        return None
    incident_id = "INC-" + secrets.token_hex(6).upper()
    db.execute(
        "INSERT INTO healing.incident(incident_id,trace_id,fault_code,status,status_label,"
        "detection_metric,detection_evidence,is_verification_run) "
        "VALUES (%s,%s,%s,'detected',%s,%s,%s,false)",
        (incident_id, trace_id or f"tr_{secrets.token_hex(6).upper()}", fault_code, label,
         detection_metric, evidence), role="healing")
    return incident_id


def test_injection_active(target: str) -> bool:
    """이 대상에 **시험 주입**이 걸려 있는가. 시험 주입에만 run_id 가 있다.

    걸려 있으면 상시 감시는 비켜선다 — 시험이 만든 장애를 실제 사건으로 또 세면
    SC-4 무인 복구율이 오염되고, 시험이 복구하는 중에 둘이 같이 재시작할 수도 있다.
    """
    row = db.fetch_one(
        "SELECT COUNT(*) AS n FROM healing.fault_injection "
        " WHERE target = %s AND action = 'inject' AND run_id IS NOT NULL AND cleared_at IS NULL",
        (target,), role="healing")
    return bool((row or {}).get("n", 0))


# 재시작 상한 (PRD 5.6 F-3 "같은 세션 재실행 1회 · 10분 내 재시작 2회")
# 상한이 없으면 올라오지 않는 컨테이너를 영원히 재시작한다 — 폭주 방어의 일부다.
RESTART_LIMIT = 2
RESTART_WINDOW_SEC = 600


def restart_allowed(stamps: list[float], *, now: float) -> bool:
    """최근 창 안의 재시작 수가 상한 미만인가. 넘으면 사람에게 넘긴다(에스컬레이션)."""
    recent = [t for t in stamps if now - t < RESTART_WINDOW_SEC]
    return len(recent) < RESTART_LIMIT

# 자동 복구가 가능한 장애 (PRD 5.6 복구정책)
#
# AGENT_EXCEPTION 의 정책은 "요청 단위로 잡아 마지막 체크포인트부터 1회 재실행"이지만
# 업무 층에 그 재실행이 아직 없다. 자동 복구했다고 적으면 거짓이고 SC-4 무인 복구율이
# 부풀려지므로, 기록만 하고 담당자 확인(manual_check)으로 넘긴다.
AUTO_RECOVERABLE = frozenset({"DEP_HTTP_5XX", "DEP_TIMEOUT", "AGENT_OUTPUT_INVALID",
                              "WORKER_DOWN", "DB_UNAVAILABLE"})
