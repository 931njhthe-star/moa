-- =====================================================================
-- 90_cleanup.sql — 보존 정리 (D-07 7.3 · PRD U-07)
--   실행 주체: 수동 또는 CI 작업. 자동 스케줄러를 만들지 않는다 (3일 범위)
--   메뉴 · 별칭 · 옵션 · 브랜드 사전은 시드 데이터이므로 지우지 않는다
-- =====================================================================

-- 세션과 그 하위 (snapshot · message · order_event · order_item · 질문 · 이력 · 정산 · 공유): CASCADE
DELETE FROM app.order_session WHERE updated_at < NOW() - INTERVAL '14 days';

-- FK가 없는 이력 2종은 따로 지운다
DELETE FROM app.request_history WHERE created_at < NOW() - INTERVAL '14 days';
DELETE FROM app.llm_history     WHERE created_at < NOW() - INTERVAL '14 days';

-- 멱등 키는 10분 (D-02 1.2)
DELETE FROM app.idempotency_key WHERE expires_at < NOW();

-- 사건과 그 하위: 14일
DELETE FROM healing.incident        WHERE detected_at < NOW() - INTERVAL '14 days';
DELETE FROM healing.fault_injection WHERE injected_at < NOW() - INTERVAL '14 days';

-- 메트릭은 24시간. 단 사건으로 승격된 행은 14일 유지 (D-07 4.20)
DELETE FROM healing.runtime_metric
 WHERE incident_id IS NULL AND measured_at < NOW() - INTERVAL '24 hours';
DELETE FROM healing.runtime_metric
 WHERE incident_id IS NOT NULL AND measured_at < NOW() - INTERVAL '14 days';
