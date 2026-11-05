#!/usr/bin/env bash
# 순차 배포 — 서버(EC2 ~/moa)에서 실행한다. CI deploy 잡이 이 스크립트를 부른다 (PRD 5.4 순차 배포)
#
#   TAG=<커밋 sha> bash scripts/deploy.sh          ECR 에서 받아 교체 (REGISTRY 는 .env)
#   SKIP_PULL=1 bash scripts/deploy.sh             로컬 이미지로 교체 (로컬 시험용)
#   SKIP_PULL=1 FORCE_RECREATE=1 bash scripts/deploy.sh   이미지가 같아도 다시 만든다 (무중단 시험용)
#
# 순서
#   1. 사전 점검(.env) · 옛 단일 스택(프로젝트 moa) 정리 · 네트워크
#   2. 이미지 받기
#   3. healing 멈춤 — 교체 중 컨테이너가 내려가는 것을 장애로 보고 재시작하지 않게 (끝나면 반드시 다시 켠다)
#   4. 공용 스택: db · socket-proxy · gateway (설정 파일은 다시 읽힌다)
#   5. 해석 서비스: backup → primary 한 개씩 (둘이 동시에 내려가지 않게)
#   6. 앱 스택: A 교체 → 게이트웨이에서 A UP 확인 → B 교체 → B UP 확인. A 가 UP 이 안 되면 B 는 건드리지 않는다
#   7. healing 다시 켬 · 오래된 이미지 정리
set -euo pipefail
cd "$(dirname "$0")/.."

CORE=(docker compose -f docker-compose.core.yml -p moa-core)
APP=(docker compose -f docker-compose.app.yml)
GATEWAY=moa-core-gateway-1
SKIP_PULL=${SKIP_PULL:-0}
RECREATE=()
[ "${FORCE_RECREATE:-0}" = "1" ] && RECREATE=(--force-recreate)

log()  { echo "[$(date -u +%H:%M:%S)] $*"; }
fail() { echo "::error::$*" >&2; exit 1; }

# 게이트웨이 상태 페이지에서 app/<a|b> 상태 (UP · DOWN · MAINT · 없음)
gw_state() {
  docker exec "$GATEWAY" wget -qO- "http://127.0.0.1:8404/stats;csv" 2>/dev/null \
    | awk -F, -v s="$1" '$1=="app" && $2==s {print $18}' || true
}

# 게이트웨이 관리 명령 (haproxy.cfg 의 stats socket — 컨테이너 안 127.0.0.1:9999)
gw_cmd() {
  docker exec "$GATEWAY" sh -c "echo '$1' | nc 127.0.0.1 9999" >/dev/null 2>&1 || true
}

wait_gateway_up() {
  local s=$1
  for _ in $(seq 1 30); do
    [ "$(gw_state "$s")" = "UP" ] && return 0
    sleep 2
  done
  return 1
}

# 컨테이너 안에서 자기 /health 를 부른다 (slim 이미지에는 curl 이 없다)
# "프로세스가 떠서 HTTP 로 답한다"만 본다 — 상태 코드는 따지지 않는다.
#   해석 서비스는 장애 주입(F-1 error 모드)이 켜져 있으면 /health 에 503 을 답한다. 그것도 떠 있는 것이다
#   (주입 해제 · 복구 판단은 healing 몫이고, 배포가 그 때문에 멈추면 앱 스택을 못 띄운 채 끝난다)
wait_http() {
  local name=$1 url=$2
  for _ in $(seq 1 30); do
    docker exec "$name" python -c "
import sys, urllib.request, urllib.error
try:
    urllib.request.urlopen('$url', timeout=2)
except urllib.error.HTTPError:
    pass                      # 4xx · 5xx 도 응답이다
except Exception:
    sys.exit(1)               # 연결 거부 · 시간 초과 = 아직 안 떴다
" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

# 옛 앱 이미지 정리 — 배포마다 커밋 sha 태그 이미지(약 1.3GB)가 남아 디스크가 찬다.
#   `docker image prune` 은 태그 없는 이미지만 지우므로 sha 태그는 여기서 지운다.
#   컨테이너가 쓰는 이미지(지금 버전) + 쓰지 않는 것 중 최신 KEEP_PREVIOUS 벌(되돌리기용)만 남긴다
KEEP_PREVIOUS=${KEEP_PREVIOUS:-1}
cleanup_images() {
  local used repo kept id ref removed=0
  used=$(docker ps -aq | xargs -r docker inspect -f '{{.Image}}' | sed 's/^sha256://' | cut -c1-12 | sort -u)
  for repo in moa-backend moa-frontend; do
    kept=""
    # docker images 는 만든 시각 최신순이다. 같은 이미지에 태그가 여럿(sha · latest)이면 한 벌로 센다
    while read -r id ref; do
      echo "$used" | grep -qx "$id" && continue          # 지금 쓰는 이미지
      echo "$kept" | grep -qw "$id" && continue           # 이미 남기기로 한 이미지의 다른 태그
      if [ "$(echo "$kept" | wc -w)" -lt "$KEEP_PREVIOUS" ]; then kept="$kept $id"; continue; fi
      docker rmi "$ref" >/dev/null 2>&1 && removed=$((removed + 1))
    done < <(docker images --format '{{.ID}} {{.Repository}}:{{.Tag}}' | awk -v r="$repo" '$2 ~ ("(^|/)" r ":") && $2 !~ /:<none>$/')
  done
  log "옛 앱 이미지 ${removed}개 정리 (지금 버전 + 직전 ${KEEP_PREVIOUS}벌 보존) · 디스크 $(df -h / | awk 'NR==2 {print $4}') 남음"
}

on_exit() {
  # 배포가 중간에 실패해도 빼 둔 스택은 되돌리고 healing 은 다시 켠다
  gw_cmd "set server app/a state ready"
  gw_cmd "set server app/b state ready"
  resume_healing
}

resume_healing() {
  if "${CORE[@]}" ps --services --all 2>/dev/null | grep -qx healing; then
    "${CORE[@]}" up -d --no-build --no-deps healing >/dev/null 2>&1 && log "healing 다시 켬" || true
  fi
}

# ---------- 1. 사전 점검 ----------
[ -f .env ] || fail ".env 가 없다 — POSTGRES_PASSWORD · HEALING_RW_PASSWORD 를 넣는다"
for v in POSTGRES_PASSWORD HEALING_RW_PASSWORD; do
  grep -q "^${v}=" .env || fail ".env 에 ${v} 가 없다"
done

old=$(docker ps -aq --filter label=com.docker.compose.project=moa)
if [ -n "$old" ]; then
  log "옛 단일 스택(프로젝트 moa) 컨테이너를 지운다 — 볼륨 moa_pgdata 는 그대로 이어 쓴다 (이번 한 번 화면이 잠깐 끊긴다)"
  docker rm -f $old >/dev/null
fi

bash scripts/init-networks.sh

# ---------- 2. 이미지 ----------
if [ "$SKIP_PULL" != "1" ]; then
  log "이미지 받기 (TAG=${TAG:-latest})"
  "${CORE[@]}" pull -q
  "${APP[@]}" -p moa-a pull -q      # moa-b 도 같은 이미지다
fi

# ---------- 3. healing 멈춤 ----------
trap on_exit EXIT
if [ -n "$("${CORE[@]}" ps -q healing 2>/dev/null)" ]; then
  log "healing 멈춤 (배포 동안)"
  "${CORE[@]}" stop healing >/dev/null
fi

# ---------- 4. 공용 스택 기반 ----------
log "공용 스택: db · socket-proxy · gateway"
"${CORE[@]}" up -d --no-build --wait --wait-timeout 120 db socket-proxy gateway
# 설정 파일(bind mount)만 바뀐 경우 컨테이너가 다시 만들어지지 않으므로 다시 읽게 한다
docker kill -s HUP "$GATEWAY" moa-core-socket-proxy-1 >/dev/null

# ---------- 5. 해석 서비스 — 한 개씩 ----------
for svc in interpreter-backup:8102 interpreter-primary:8101; do
  name=${svc%%:*}; port=${svc##*:}
  log "해석 서비스 교체: $name"
  "${CORE[@]}" up -d --no-build --no-deps "${RECREATE[@]}" "$name" >/dev/null
  wait_http "moa-core-${name}-1" "http://localhost:${port}/health" || fail "$name 이 60초 안에 응답하지 않았다"
done

# ---------- 6. 앱 스택 — A → B 순차 ----------
for s in a b; do
  other=$([ "$s" = a ] && echo b || echo a)
  log "앱 스택 ${s} 교체 (교체 전: a=$(gw_state a) b=$(gw_state b))"
  if [ "$(gw_state "$other")" = "UP" ]; then
    # 교체 전에 게이트웨이에서 먼저 뺀다 — 내려가는 컨테이너로 새 요청이 가지 않게. 열린 연결(WebSocket)은 끊어 다른 스택으로 다시 붙게 한다
    gw_cmd "set server app/${s} state maint"
    gw_cmd "shutdown sessions server app/${s}"
    sleep 1
  else
    log "주의: 다른 스택(${other})이 UP 이 아니다 — 교체 동안 화면이 끊길 수 있다"
  fi
  "${APP[@]}" -p "moa-${s}" up -d --no-build "${RECREATE[@]}" --wait --wait-timeout 180 \
    || fail "앱 스택 ${s} 가 healthy 가 되지 않았다 — 나머지 스택은 교체하지 않는다"
  gw_cmd "set server app/${s} state ready"
  wait_gateway_up "$s" || fail "게이트웨이에서 ${s} 가 60초 안에 UP 이 되지 않았다 — 나머지 스택은 교체하지 않는다"
  log "앱 스택 ${s} UP"
done

# ---------- 7. 마무리 ----------
trap - EXIT
log "healing 켬"
"${CORE[@]}" up -d --no-build --no-deps healing >/dev/null
if [ "$SKIP_PULL" != "1" ]; then
  cleanup_images
  docker image prune -f >/dev/null      # 태그 없는(dangling) 이미지
fi

log "배포 완료 — 게이트웨이 a=$(gw_state a) b=$(gw_state b)"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep '^moa-' | sort
