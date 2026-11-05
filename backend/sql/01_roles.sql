-- =====================================================================
-- 01_roles.sql — 접속 롤 2개와 권한 (D-07 2.1)
--   app_rw      : app R/W · langgraph R/W · healing 읽기만
--   healing_rw  : healing R/W · app 읽기만
-- 비밀번호는 psql 변수로 받는다 :  psql -v app_pw=... -v healing_pw=...
-- =====================================================================

-- 롤 (이미 있으면 비밀번호만 갱신한다 — 재실행 가능하게)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
    CREATE ROLE app_rw LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'healing_rw') THEN
    CREATE ROLE healing_rw LOGIN;
  END IF;
END $$;

ALTER ROLE app_rw     PASSWORD :'app_pw';
ALTER ROLE healing_rw PASSWORD :'healing_pw';

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS healing;
CREATE SCHEMA IF NOT EXISTS langgraph;

-- 기본이 차단: PUBLIC 권한을 먼저 회수한다
REVOKE ALL ON SCHEMA app, healing, langgraph FROM PUBLIC;

-- ---------- app_rw ----------
GRANT USAGE  ON SCHEMA app, langgraph               TO app_rw;
GRANT USAGE  ON SCHEMA healing                      TO app_rw;
-- ★ langgraph 테이블은 라이브러리가 만든다(D-07 D-7). USAGE 만으로는 CREATE TABLE 이 안 되므로
--   체크포인터를 켜는 증분 3(D-15)에서 조용히 깨진다. D-07 2.1 SQL 에 빠져 있던 한 줄이다.
GRANT CREATE ON SCHEMA langgraph                    TO app_rw;
GRANT ALL    ON ALL TABLES IN SCHEMA app, langgraph TO app_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA healing        TO app_rw;   -- 사건은 읽기만
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app  TO app_rw;   -- BIGSERIAL 이력 2종

-- ---------- healing_rw ----------
GRANT USAGE  ON SCHEMA healing                      TO healing_rw;
GRANT USAGE  ON SCHEMA app                          TO healing_rw;
GRANT ALL    ON ALL TABLES IN SCHEMA healing        TO healing_rw;
GRANT SELECT ON ALL TABLES IN SCHEMA app            TO healing_rw;  -- 주문은 읽기만
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA healing TO healing_rw;

-- ---------- 앞으로 만들 테이블에도 같은 권한이 붙게 한다 ----------
-- 이것이 없으면 D-08 이후 생성분(menu_chunk 등)에 권한이 없어 런타임에만 오류가 난다
ALTER DEFAULT PRIVILEGES IN SCHEMA app, langgraph GRANT ALL            ON TABLES    TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app            GRANT USAGE, SELECT  ON SEQUENCES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA healing        GRANT SELECT         ON TABLES    TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA healing        GRANT ALL            ON TABLES    TO healing_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA healing        GRANT USAGE, SELECT  ON SEQUENCES TO healing_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app            GRANT SELECT         ON TABLES    TO healing_rw;
