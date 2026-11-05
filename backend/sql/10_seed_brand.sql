-- =====================================================================
-- 10_seed_brand.sql — 매장 기준 판별 사전 (D-07 4.11 brand_alias · F-024)
--
-- 판별에 LLM 을 쓰지 않는다 (FR-030 · llm_calls: 0). 이 테이블 조회가 판별의 전부다.
-- 같은 매장의 별칭은 1종으로 센다 — resolved_brand_id 가 같으면 한 종류다 (PRD 2.4.1).
--
-- ★ 범위는 PRD U-17 에서 확정한다. 아래는 프론트엔드 모의(moa/mock.py _STORE_WORDS)와
--   PRD 2.4.1 의 예시를 옮긴 **잠정 사전**이다. U-17 확정 시 이 파일을 교체한다.
-- =====================================================================
INSERT INTO app.brand_alias (alias, resolved_brand_id, kind, display_name) VALUES
  -- 지원 매장 (starbucks)
  ('스타벅스',    'starbucks', 'supported',    '스타벅스'),
  ('스벅',        'starbucks', 'supported',    '스타벅스'),
  ('스타벅스커피','starbucks', 'supported',    '스타벅스'),
  ('starbucks',   'starbucks', 'supported',    '스타벅스'),
  ('sbux',        'starbucks', 'supported',    '스타벅스'),

  -- 일반 카페 표현 (generic_expr)
  ('일반카페',    'generic',   'generic_expr', '일반 카페'),
  ('일반 카페',   'generic',   'generic_expr', '일반 카페'),
  ('동네카페',    'generic',   'generic_expr', '일반 카페'),
  ('개인카페',    'generic',   'generic_expr', '일반 카페'),
  ('카페',        'generic',   'generic_expr', '일반 카페'),

  -- 미지원 브랜드 — generic 으로 처리하고 안내 문구에 이름을 쓴다 (PRD 2.4.1 1-3)
  ('메가커피',    'generic',   'unsupported',  '메가커피'),
  ('메가',        'generic',   'unsupported',  '메가커피'),
  ('이디야',      'generic',   'unsupported',  '이디야'),
  ('투썸',        'generic',   'unsupported',  '투썸플레이스'),
  ('투썸플레이스','generic',   'unsupported',  '투썸플레이스'),
  ('컴포즈',      'generic',   'unsupported',  '컴포즈커피'),
  ('컴포즈커피',  'generic',   'unsupported',  '컴포즈커피'),
  ('빽다방',      'generic',   'unsupported',  '빽다방'),
  ('커피빈',      'generic',   'unsupported',  '커피빈'),
  ('폴바셋',      'generic',   'unsupported',  '폴바셋'),
  ('할리스',      'generic',   'unsupported',  '할리스'),
  ('탐앤탐스',    'generic',   'unsupported',  '탐앤탐스'),
  ('더벤티',      'generic',   'unsupported',  '더벤티'),
  ('매머드',      'generic',   'unsupported',  '매머드커피'),
  ('매머드커피',  'generic',   'unsupported',  '매머드커피'),
  -- 공차 — PRD 2.4.1 · 8.1 #24 "스벅 갈까 공차 갈까" 되묻기 사례 (v1.9 · U-17)
  ('공차',        'generic',   'unsupported',  '공차')
ON CONFLICT (alias) DO UPDATE
   SET resolved_brand_id = EXCLUDED.resolved_brand_id,
       kind              = EXCLUDED.kind,
       display_name      = EXCLUDED.display_name;
