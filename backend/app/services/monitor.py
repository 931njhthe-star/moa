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
        "  FROM healing.runtime_metric "
        " WHERE breached = true AND incident_id IS NULL "
        "   AND measured_at > NOW() - (%s * INTERVAL '1 second') "
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



def close_incident(incident_id: str, *, recovered: bool) -> None:
    """사건을 닫는다. 칸 이름은 `healing.incident` 그대로다 — `recovered_at` 은 없다.

    복구 완료는 `resolved_at`, 자동 복구 실패는 `failed_at` + `escalated_at` 이다.
    `recovery_started_at` 은 처음 값을 지킨다 — MTTR 구간이 뒤로 밀리면 안 된다.
    """
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
