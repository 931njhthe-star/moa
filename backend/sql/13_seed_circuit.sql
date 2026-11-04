-- =====================================================================
-- 13_seed_circuit.sql — circuit_state 초기 4행 (D-07 8절)
--   상태 조회가 빈 결과를 받지 않게 한다 · 활성 경로 초기값은 1차만 true (FR-016)
--   채우는 단계: D-04
-- =====================================================================
INSERT INTO healing.circuit_state
  (dependency_key, state, consecutive_failures, cache_fallback_active, is_active_route, healthy_streak)
VALUES
  ('order_interpreter_primary', 'up', 0, false, true,  0),   -- 활성 경로는 1차 하나만
  ('order_interpreter_backup',  'up', 0, false, false, 0),
  ('menu_store',                'up', 0, false, false, 0),
  ('agent_process',             'up', 0, false, false, 0)
ON CONFLICT (dependency_key) DO NOTHING;
