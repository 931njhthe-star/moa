-- =====================================================================
-- 14_seed_demo.sql — 시연 · 검수용 사건 데이터 3건씩 (healing 스키마)
--
-- ★ 이 파일은 **시연용**이다. 운영 배포에서 돌리지 않는다.
--   업무 데이터(세션 · 주문)는 서비스 계층이 만들어야 정합성이 맞으므로
--   SQL 로 넣지 않는다 — `tools/seed_demo.py` 가 파이프라인을 태워 만든다.
--
-- healing 쪽은 Monitor · Recovery · Verification(별도 컨테이너 · D-12 · D-15)이
-- 아직 없어 사건이 생기지 않는다. 운영 대시보드 O-1 ~ O-5 와 v_metrics 를
-- 눈으로 확인하려면 이 시드가 필요하다.
--
-- 소유 롤: healing_rw (app_rw 는 이 스키마에 쓸 수 없다 — D-07 2.1)
-- =====================================================================

-- 기존 시연 데이터를 지우고 다시 넣는다 (재실행 가능)
DELETE FROM healing.incident        WHERE incident_id LIKE 'INC-9%';
DELETE FROM healing.fault_injection WHERE injection_id LIKE 'fi_demo%';
DELETE FROM healing.runtime_metric  WHERE trace_id LIKE 'tr_DEMO%';

-- --------------------------------------------------------------------
-- 장애 주입 3건 — 주입이 사건보다 **먼저** 일어난다 (MTTD 시작점)
-- --------------------------------------------------------------------
INSERT INTO healing.fault_injection
  (injection_id, fault, action, target, mode, injected_at, cleared_at, incident_id, environment)
VALUES
  ('fi_demo_001', 'F-2', 'inject', 'order_interpreter_primary', 'delay',
   NOW() - INTERVAL '38 minutes', NOW() - INTERVAL '30 minutes', 'INC-9001', 'lab'),
  ('fi_demo_002', 'F-3', 'inject', 'agent_process', 'kill',
   NOW() - INTERVAL '22 minutes', NOW() - INTERVAL '20 minutes', 'INC-9002', 'lab'),
  ('fi_demo_003', 'F-6', 'inject', 'menu_store', 'block',
   NOW() - INTERVAL '12 minutes', NOW() - INTERVAL '10 minutes', 'INC-9003', 'lab');

-- --------------------------------------------------------------------
-- 사건 3건 — 상태를 서로 다르게 둔다
--   INC-9001 승인 대기 (O-4 가 비어 있지 않게)
--   INC-9002 복구 성공 (MTTD · MTTR 이 계산되게)
--   INC-9003 복구 성공 · 캐시 폴백 (F-6 reconnect_cache)
-- --------------------------------------------------------------------
INSERT INTO healing.incident
  (incident_id, trace_id, fault_code, status, status_label,
   injected_at, detected_at, recovery_started_at, resolved_at, escalated_at, paused_ms,
   detection_metric, detection_evidence, diagnosis_rule, diagnosis_reason, strategy,
   attempt_count, session_id, checkpoint, elapsed_ms, is_false_positive)
VALUES
  ('INC-9001', 'tr_DEMO0001', 'DEP_TIMEOUT', 'awaiting_approval', '승인 대기',
   NOW() - INTERVAL '38 minutes', NOW() - INTERVAL '37 minutes',
   NOW() - INTERVAL '36 minutes', NULL, NULL, 0,
   'dep_latency_ms', '{"타임아웃 ×3","대체 경로 5xx"}',
   'R-02', '연속 2회 호출 제한시간 초과', 'escalate',
   3, NULL, 'chat_read', NULL, false),

  ('INC-9002', 'tr_DEMO0002', 'WORKER_DOWN', 'recovered', '복구 성공',
   NOW() - INTERVAL '22 minutes', NOW() - INTERVAL '21 minutes',
   NOW() - INTERVAL '21 minutes', NOW() - INTERVAL '20 minutes', NULL, 0,
   'checkpoint_age_sec', '{"체크포인트 72초 미갱신"}',
   'R-03', '처리 프로세스 응답 없음', 'restart_resume',
   1, NULL, 'menu_matched', 69000, false),

  ('INC-9003', 'tr_DEMO0003', 'DB_UNAVAILABLE', 'recovered', '복구 성공 · 캐시 폴백',
   NOW() - INTERVAL '12 minutes', NOW() - INTERVAL '11 minutes',
   NOW() - INTERVAL '11 minutes', NOW() - INTERVAL '10 minutes', NULL, 0,
   'db_query_p95_ms', '{"쿼리 2초 초과","연결 오류 2회"}',
   'R-06', '메뉴 저장소 연결 오류 연속 2회', 'reconnect_cache',
   2, NULL, 'menu_matched', 54000, false);

-- --------------------------------------------------------------------
-- 복구 시도 — 사건당 시도 수가 attempt_count 와 맞아야 한다
-- 대기 셈 규약: N회 시도 = 대기 N-1회 (D-03 1.4)
-- --------------------------------------------------------------------
INSERT INTO healing.recovery_attempt
  (incident_id, attempt_no, action, wait_ms, tool, tool_args, result, error,
   started_at, ended_at)
VALUES
  ('INC-9001', 1, 'retry', 0, 'call_interpreter',
   '{"service":"primary","timeout_ms":8000}'::jsonb, 'timeout', '제한시간 초과',
   NOW() - INTERVAL '36 minutes', NOW() - INTERVAL '36 minutes'),
  ('INC-9001', 2, 'switch_backup', 1000, 'switch_route',
   '{"from":"order_interpreter_primary","to":"order_interpreter_backup"}'::jsonb,
   'fail', '대체 경로 5xx', NOW() - INTERVAL '36 minutes', NOW() - INTERVAL '35 minutes'),
  ('INC-9001', 3, 'probe', 2000, 'health_probe',
   '{"target":"order_interpreter_backup"}'::jsonb, 'fail', '응답 없음',
   NOW() - INTERVAL '35 minutes', NOW() - INTERVAL '35 minutes'),

  ('INC-9002', 1, 'restart', 0, 'restart_container',
   '{"target":"agent","restart_policy":"no"}'::jsonb, 'ok', NULL,
   NOW() - INTERVAL '21 minutes', NOW() - INTERVAL '20 minutes'),

  ('INC-9003', 1, 'reconnect', 0, 'reconnect_db',
   '{"backoff_ms":1000,"attempt":1}'::jsonb, 'fail', '연결 거부',
   NOW() - INTERVAL '11 minutes', NOW() - INTERVAL '11 minutes'),
  ('INC-9003', 2, 'cache_fallback', 1000, 'use_menu_cache',
   '{"menu_version":"mv_20261029","read_only":true}'::jsonb, 'ok', NULL,
   NOW() - INTERVAL '11 minutes', NOW() - INTERVAL '10 minutes');

-- --------------------------------------------------------------------
-- 복구 검증 — 항목별로 행을 나눈다. 모든 항목이 passed 일 때만 verdict='pass'
-- --------------------------------------------------------------------
INSERT INTO healing.verification_result
  (incident_id, check_name, expected, actual, passed, verdict, verified_at)
VALUES
  ('INC-9002', 'health_consecutive', '연속 3회 정상', '3회 정상', true, 'pass',
   NOW() - INTERVAL '20 minutes'),
  ('INC-9002', 'request_sample',     '실패 0건',      '0건',     true, 'pass',
   NOW() - INTERVAL '20 minutes'),
  ('INC-9002', 'integrity',          '합계 일치',     '일치',    true, 'pass',
   NOW() - INTERVAL '20 minutes'),

  ('INC-9003', 'cache_db_match',     '캐시 == DB',    '일치',    true, 'pass',
   NOW() - INTERVAL '10 minutes'),
  ('INC-9003', 'baseline_latency',   '기준 지연 이내', '1.2초',   true, 'pass',
   NOW() - INTERVAL '10 minutes'),
  ('INC-9003', 'function_test',      '메뉴 조회 성공', '성공',    true, 'pass',
   NOW() - INTERVAL '10 minutes');

-- --------------------------------------------------------------------
-- Monitor 메트릭 — 사건이 되지 않은 행도 넣는다 (오탐률 분모 후보)
-- --------------------------------------------------------------------
INSERT INTO healing.runtime_metric
  (metric_key, target, value, threshold, breached, incident_id, trace_id, measured_at)
VALUES
  ('dep_latency_ms',   'order_interpreter_primary', 8200, 5000, true,  'INC-9001',
   'tr_DEMO0001', NOW() - INTERVAL '37 minutes'),
  ('checkpoint_age_sec','agent_process',              72,   60, true,  'INC-9002',
   'tr_DEMO0002', NOW() - INTERVAL '21 minutes'),
  ('db_query_p95_ms',  'menu_store',                2400, 2000, true,  'INC-9003',
   'tr_DEMO0003', NOW() - INTERVAL '11 minutes'),
  -- 기준을 넘었지만 냉각시간이라 사건이 되지 않은 행 (incident_id IS NULL)
  ('dep_5xx_ratio',    'order_interpreter_primary',  0.12, 0.10, true,  NULL,
   'tr_DEMO0004', NOW() - INTERVAL '9 minutes'),
  -- 평상시 값
  ('dep_latency_ms',   'order_interpreter_primary',  420, 5000, false, NULL,
   'tr_DEMO0005', NOW() - INTERVAL '3 minutes'),
  ('db_query_p95_ms',  'menu_store',                 180, 2000, false, NULL,
   'tr_DEMO0006', NOW() - INTERVAL '2 minutes');

-- --------------------------------------------------------------------
-- 회로 상태 — INC-9001 이 승인 대기라 1차가 차단된 상태로 둔다
-- 활성 경로는 정확히 하나여야 한다 (uq_active_route). 1차 -> 대체로 옮긴다
-- --------------------------------------------------------------------
UPDATE healing.circuit_state
   SET state = 'up', is_active_route = false, consecutive_failures = 0,
       opened_at = NULL, probe_at = NULL, healthy_streak = 0, updated_at = NOW()
 WHERE dependency_key IN ('order_interpreter_primary', 'order_interpreter_backup');

UPDATE healing.circuit_state
   SET state = 'circuit_open', consecutive_failures = 3,
       opened_at = NOW() - INTERVAL '36 minutes',
       probe_at = NOW() + INTERVAL '42 seconds',
       healthy_streak = 0, updated_at = NOW()
 WHERE dependency_key = 'order_interpreter_primary';

UPDATE healing.circuit_state
   SET state = 'up', is_active_route = true, healthy_streak = 5, updated_at = NOW()
 WHERE dependency_key = 'order_interpreter_backup';

UPDATE healing.circuit_state
   SET state = 'up', cache_fallback_active = false, healthy_streak = 8, updated_at = NOW()
 WHERE dependency_key = 'menu_store';
