#!/usr/bin/env bash
# 복제본 장애 주입 (F-3 WORKER_DOWN) — 서버(또는 로컬)에서 실행한다. 장애 실험 25회의 F-3 회차에 쓴다
#
#   bash scripts/fault.sh stop  <a|b> [backend|frontend]   주입: 주입 시각을 기록하고 컨테이너를 멈춘다 (기본 backend)
#   bash scripts/fault.sh start <a|b> [backend|frontend]   수동 복귀: 컨테이너를 다시 켠다 (healing 이 없을 때 · 실험 정리용)
#   bash scripts/fault.sh clear                            열려 있는 F-3 주입 기록을 닫는다 (cleared_at)
#   bash scripts/fault.sh status                           게이트웨이 A/B 상태 · 앱 컨테이너 · 열린 주입
#
# 주입 기록: healing.fault_injection 에 F-3 · agent_process · kill (운영 대시보드 API-049 와 같은 값)
#   MTTD · MTTR 의 시작점(injected_at)이다. 어느 복제본인지는 출력 · 사건 증거로 남긴다
# 복구(재시작)는 healing Recovery Worker 몫이다 — 실험 회차에서는 start 를 쓰지 않는다 (쓰면 수동 개입 회차)
set -euo pipefail

GATEWAY=moa-core-gateway-1
DB=moa-core-db-1
now() { date -u +%Y-%m-%dT%H:%M:%S.%3NZ; }

psql_() { docker exec "$DB" psql -U postgres -tAq -c "$1"; }

gw_states() {
  docker exec "$GATEWAY" wget -qO- "http://127.0.0.1:8404/stats;csv" 2>/dev/null \
    | awk -F, '$1=="app" && ($2=="a"||$2=="b") {printf "%s=%s ", $2, $18}'
}

cmd=${1:-status}
stack=${2:-}
svc=${3:-backend}

target() {
  case "$stack" in a|b) ;; *) echo "스택은 a 또는 b" >&2; exit 2 ;; esac
  case "$svc" in backend|frontend) ;; *) echo "대상은 backend 또는 frontend" >&2; exit 2 ;; esac
  echo "moa-${stack}-${svc}-1"
}

case "$cmd" in
  stop)
    name=$(target)
    id="fi_$(date +%s%N | cut -c1-12)"
    psql_ "INSERT INTO healing.fault_injection (injection_id, fault, action, target, mode, environment)
           VALUES ('$id', 'F-3', 'inject', 'agent_process', 'kill', 'lab')"
    t=$(now)
    docker stop -t 0 "$name" >/dev/null
    echo "주입 $t  F-3  $name 중지  (injection_id=$id)"
    echo "게이트웨이: $(gw_states)"
    ;;
  start)
    name=$(target)
    docker start "$name" >/dev/null
    echo "복귀 $(now)  $name 시작 — 수동 개입"
    ;;
  clear)
    n=$(psql_ "WITH c AS (UPDATE healing.fault_injection SET cleared_at = NOW()
               WHERE fault = 'F-3' AND action = 'inject' AND cleared_at IS NULL RETURNING 1) SELECT count(*) FROM c")
    echo "F-3 주입 기록 ${n}건 닫음"
    ;;
  status)
    echo "게이트웨이: $(gw_states)"
    docker ps -a --filter name='^moa-[ab]-' --format '{{.Names}}\t{{.Status}}' | sort
    echo "열린 주입:"
    psql_ "SELECT injection_id || '  ' || fault || '  ' || target || '  ' || mode || '  ' || injected_at
             FROM healing.fault_injection WHERE action = 'inject' AND cleared_at IS NULL ORDER BY injected_at" \
      | sed 's/^/  /'
    ;;
  *)
    sed -n '2,10p' "$0"; exit 2 ;;
esac
