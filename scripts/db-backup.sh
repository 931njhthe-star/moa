#!/usr/bin/env bash
# DB 백업 · 복원 — 서버(또는 로컬)에서 실행한다. DB 는 EC2 볼륨 moa_pgdata 하나뿐이라 백업이 없으면 되돌릴 방법이 없다
#
#   bash scripts/db-backup.sh                  백업: ~/moa/backups/moa_<UTC시각>.dump (pg_dump 사용자 지정 형식 · 압축)
#   bash scripts/db-backup.sh list             백업 목록
#   bash scripts/db-backup.sh restore <파일>   복원: 앱 스택 A · B 를 멈추고 덮어쓴 뒤 다시 켠다 (확인 문구를 입력해야 진행)
#
#   KEEP=14 (기본) 최근 14개만 남긴다. deploy.sh 가 배포마다 먼저 한 번 부른다
#   정기 백업이 필요하면 crontab: 0 18 * * * cd ~/moa && bash scripts/db-backup.sh >> backups/backup.log 2>&1  (03:00 KST)
#
# 백업 대상: postgres DB 전체(app · healing · langgraph 스키마 · 롤 권한 포함 객체). 롤 자체(app_rw · healing_rw)는
#   sql/run_sql.py 가 .env 비밀번호로 다시 만든다 — 덤프에 비밀번호를 담지 않는다
set -euo pipefail
cd "$(dirname "$0")/.."

DB=moa-core-db-1
DIR=backups
KEEP=${KEEP:-14}
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { echo "::error::$*" >&2; exit 1; }

[ "$(docker inspect -f '{{.State.Running}}' "$DB" 2>/dev/null)" = true ] || fail "$DB 가 떠 있지 않다"
mkdir -p "$DIR"

case "${1:-backup}" in
  backup)
    f="$DIR/moa_$(date -u +%Y%m%dT%H%M%SZ).dump"
    # 컨테이너 안에서 덤프 → 표준 출력으로 받아 호스트 파일에 쓴다 (컨테이너에 파일을 남기지 않는다)
    docker exec "$DB" pg_dump -U postgres -d postgres -Fc --no-owner > "$f.part" || { rm -f "$f.part"; fail "pg_dump 실패"; }
    mv "$f.part" "$f"
    # 덤프가 읽히는지 확인 — 목차를 못 읽으면 깨진 백업이다
    docker exec -i "$DB" pg_restore -l < "$f" >/dev/null || { rm -f "$f"; fail "백업 파일 검증 실패 — 지웠다"; }
    rows=$(docker exec "$DB" psql -U postgres -tAq -c "SELECT (SELECT count(*) FROM app.order_session) || ' 세션 · ' || (SELECT count(*) FROM app.order_item) || ' 주문 항목 · ' || (SELECT count(*) FROM healing.incident) || ' 사건'" 2>/dev/null || echo "?")
    log "백업 $f ($(du -h "$f" | cut -f1) · $rows)"
    # 오래된 것부터 지운다
    ls -1t "$DIR"/moa_*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; log "오래된 백업 지움 $old"; done
    ;;
  list)
    ls -lh "$DIR"/moa_*.dump 2>/dev/null | awk '{print $5, $9}' || echo "백업 없음"
    ;;
  restore)
    f=${2:-}
    [ -f "$f" ] || fail "백업 파일이 없다: $f (bash scripts/db-backup.sh list)"
    echo "!! $f 로 DB 를 덮어쓴다. 지금 DB 의 주문 · 사건 기록은 사라진다 (복원 전에 지금 상태를 한 번 더 백업한다)."
    read -r -p "계속하려면 '복원' 을 입력: " answer
    [ "$answer" = "복원" ] || fail "취소"
    bash "$0" backup
    log "앱 스택 A · B · healing 멈춤 (복원 동안 DB 를 쓰지 않게)"
    docker stop moa-a-backend-1 moa-b-backend-1 moa-core-healing-1 >/dev/null 2>&1 || true
    docker exec -i "$DB" pg_restore -U postgres -d postgres --clean --if-exists --no-owner < "$f" \
      || log "pg_restore 경고가 있다 — 위 메시지 확인"
    log "복원 끝 — 다시 켠다"
    docker start moa-a-backend-1 moa-b-backend-1 moa-core-healing-1 >/dev/null
    log "backend · healing 시작 — 게이트웨이 재등록까지 몇 초 걸린다 (bash scripts/fault.sh status)"
    ;;
  *)
    sed -n '2,12p' "$0"; exit 2 ;;
esac
