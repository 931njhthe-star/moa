-- =====================================================================
-- 12_seed_menu_generic.sql — 일반 카페 기준 메뉴 (D-07 4.11 · 8절)
--
-- ★ 금액은 **시연용 기준가**다 (PRD 2.4). 특정 매장의 실제 가격이 아니다.
--   PRD U-13 확정 시 이 파일을 교체한다.
--
-- 매장 간 용어 충돌 1건 — 사이즈 용어가 스타벅스와 다르다 (레귤러 · 라지, U-13 요건)
-- =====================================================================

INSERT INTO app.menu (menu_id, brand_id, menu_version, category, name, base_price, trait_tags) VALUES
  ('gn_001', 'generic', 'mv_20261029', '커피', '아이스 아메리카노',  3000, '{}'),
  ('gn_002', 'generic', 'mv_20261029', '커피', '아메리카노',         2500, '{"따뜻한"}'),
  ('gn_003', 'generic', 'mv_20261029', '커피', '아이스 카페 라떼',   3500, '{"고소한"}'),
  ('gn_004', 'generic', 'mv_20261029', '커피', '카페 라떼',          3500, '{"고소한","따뜻한"}'),
  ('gn_005', 'generic', 'mv_20261029', '커피', '아이스 바닐라라떼',  4000, '{"단맛"}'),
  ('gn_006', 'generic', 'mv_20261029', '커피', '아이스 카페 모카',   4200, '{"단맛","초콜릿"}'),
  ('gn_007', 'generic', 'mv_20261029', '커피', '카라멜 마키아토',    4300, '{"단맛"}'),
  ('gn_008', 'generic', 'mv_20261029', '커피', '콜드 브루',          3800, '{}'),
  ('gn_009', 'generic', 'mv_20261029', '티',   '아이스 녹차',        3500, '{"티"}'),
  ('gn_010', 'generic', 'mv_20261029', '티',   '유자차',             4000, '{"티","과일","카페인없음"}'),
  ('gn_011', 'generic', 'mv_20261029', '티',   '아이스티',           3500, '{"티","단맛"}'),
  ('gn_012', 'generic', 'mv_20261029', '기타', '아이스 초콜릿',      4000, '{"단맛","초콜릿","카페인없음"}'),
  ('gn_013', 'generic', 'mv_20261029', '기타', '민트 초코 프라페',   4800, '{"단맛","초콜릿","카페인없음"}'),
  ('gn_014', 'generic', 'mv_20261029', '기타', '딸기 스무디',        5000, '{"단맛","과일","카페인없음"}'),
  ('gn_015', 'generic', 'mv_20261029', '기타', '녹차 라떼',          4300, '{"티","단맛"}'),
  ('gn_016', 'generic', 'mv_20261029', '기타', '우유',               2500, '{"카페인없음"}')
ON CONFLICT (brand_id, menu_version, name) DO UPDATE
   SET base_price = EXCLUDED.base_price, trait_tags = EXCLUDED.trait_tags;

INSERT INTO app.menu_alias (alias, menu_id, brand_id) VALUES
  ('아아',             'gn_001', 'generic'),
  ('아이스아메',       'gn_001', 'generic'),
  ('아이스아메리카노', 'gn_001', 'generic'),
  ('아메',             'gn_002', 'generic'),
  ('아메리카노',       'gn_002', 'generic'),
  ('뜨아',             'gn_002', 'generic'),
  ('아라',             'gn_003', 'generic'),
  ('아이스라떼',       'gn_003', 'generic'),
  ('라떼',             'gn_004', 'generic'),
  ('카페라떼',         'gn_004', 'generic'),
  ('바라떼',           'gn_005', 'generic'),
  ('아바라',           'gn_005', 'generic'),
  ('바닐라라떼',       'gn_005', 'generic'),
  ('모카',             'gn_006', 'generic'),
  ('카라멜마키아토',   'gn_007', 'generic'),
  ('카마',             'gn_007', 'generic'),
  ('콜드브루',         'gn_008', 'generic'),
  ('녹차',             'gn_009', 'generic'),
  ('유자차',           'gn_010', 'generic'),
  ('아이스티',         'gn_011', 'generic'),
  ('복숭아아이스티',   'gn_011', 'generic'),
  ('핫초코',           'gn_012', 'generic'),
  ('아이스초콜릿',     'gn_012', 'generic'),
  ('민트초코',         'gn_013', 'generic'),
  ('민초',             'gn_013', 'generic'),
  ('딸기스무디',       'gn_014', 'generic'),
  ('녹차라떼',         'gn_015', 'generic'),
  ('그린티라떼',       'gn_015', 'generic'),
  ('우유',             'gn_016', 'generic')
ON CONFLICT (alias, menu_id) DO NOTHING;

-- 사이즈 용어가 스타벅스와 다르다 — 같은 option_group 에 다른 value_label (U-13 용어 충돌)
INSERT INTO app.menu_option (option_id, menu_id, category, brand_id, option_group, option_value, value_label, extra_price, is_default) VALUES
  ('gn_opt_size_regular', NULL, NULL, 'generic', 'size',  'regular', '레귤러',    0,   true),
  ('gn_opt_size_large',   NULL, NULL, 'generic', 'size',  'large',   '라지',      500, false),
  ('gn_opt_ice_none',     NULL, NULL, 'generic', 'ice',   'none',    '없이',      0,   false),
  ('gn_opt_ice_less',     NULL, NULL, 'generic', 'ice',   'less',    '적게',      0,   false),
  ('gn_opt_ice_normal',   NULL, NULL, 'generic', 'ice',   'normal',  '보통',      0,   true),
  ('gn_opt_ice_more',     NULL, NULL, 'generic', 'ice',   'more',    '많이',      0,   false),
  ('gn_opt_shot_base',    NULL, NULL, 'generic', 'shot',  'base',    '기본',      0,   true),
  ('gn_opt_shot_extra',   NULL, NULL, 'generic', 'shot',  'extra',   '샷 추가',   500, false),
  ('gn_opt_syrup_none',   NULL, NULL, 'generic', 'syrup', 'none',    '없음',      0,   true),
  ('gn_opt_syrup_add',    NULL, NULL, 'generic', 'syrup', 'add',     '시럽 추가', 0,   false),
  ('gn_opt_milk_normal',  NULL, NULL, 'generic', 'milk',  'normal',  '일반 우유', 0,   true),
  ('gn_opt_milk_soy',     NULL, NULL, 'generic', 'milk',  'soy',     '두유',      500, false)
ON CONFLICT (option_id) DO UPDATE
   SET extra_price = EXCLUDED.extra_price, value_label = EXCLUDED.value_label;
