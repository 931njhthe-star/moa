#!/usr/bin/env bash
# 서버(EC2) 사전 점검 — 아무것도 바꾸지 않고 읽기만 한다. 공용 + 앱 A/B 구성으로 처음 배포하기 전에 돌린다
#
#   bash server-check.sh            (~/moa 에서. CI 가 아직 scripts/ 를 복사하지 않았으면 이 파일만 올려서 실행)
#
# 확인: 메모리 · 스왑, Docker · Compose 버전과 이 구성이 쓰는 기능, ~/moa 의 .env 키, 옛 단일 스택, 8501 사용 여부
set -u
cd ~/moa 2>/dev/null || { echo "XX ~/moa 가 없다"; exit 1; }

ok()   { echo "OK  $*"; }
warn() { echo "!!  $*"; }
bad()  { echo "XX  $*"; FAIL=1; }
FAIL=0

echo "== 메모리"
mem=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
swap=$(awk '/SwapTotal/ {printf "%d", $2/1024}' /proc/meminfo)
avail=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
echo "    전체 ${mem}MB · 지금 쓸 수 있는 ${avail}MB · 스왑 ${swap}MB"
# 컨테이너 10개 유휴 합계 약 360MB(로컬 실측) + 분석 · 화면 세션 여유
if [ "$mem" -lt 1800 ] && [ "$swap" -lt 1000 ]; then
  bad "메모리 2GB 미만에 스왑도 없다 — 스왑 2GB 를 만들거나 인스턴스를 키운다 (README 5단계 안내)"
elif [ "$mem" -lt 1800 ]; then
  warn "메모리 2GB 미만 — 스왑으로 버틴다. 분석이 몰리면 느려질 수 있다"
else
  ok "메모리 충분"
fi

echo "== Docker · Compose"
dv=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || bad "docker 에 접속하지 못한다 (이 사용자가 docker 그룹인가)"
cv=$(docker compose version --short 2>/dev/null) || bad "docker compose 플러그인이 없다"
echo "    docker ${dv:-?} · compose ${cv:-?}"

# 이 구성이 쓰는 compose 기능을 실제로 풀어 본다: env_file required:false · 프로젝트 이름 치환 · mem_limit
t=$(mktemp -d)
cat > "$t/c.yml" <<'EOF'
services:
  x:
    image: busybox
    mem_limit: 32m
    env_file:
      - path: ./none.env
        required: false
networks:
  default:
    name: ${COMPOSE_PROJECT_NAME}_default
    external: true
EOF
if out=$(docker compose -f "$t/c.yml" -p moa-a config 2>&1) && echo "$out" | grep -q "name: moa-a_default"; then
  ok "compose 기능 (env_file required · 프로젝트 이름 치환 · mem_limit)"
else
  bad "compose 가 이 구성을 풀지 못한다 — compose 2.24 이상으로 올린다: $out"
fi
docker compose up --help 2>/dev/null | grep -q -- "--wait" && ok "compose up --wait" || bad "compose up --wait 없음 — compose 를 올린다"
rm -rf "$t"

echo "== ~/moa/.env (값은 출력하지 않는다)"
if [ -f .env ]; then
  for v in POSTGRES_PASSWORD HEALING_RW_PASSWORD REGISTRY; do
    if grep -q "^${v}=." .env; then ok "$v 있음"; else bad "$v 없음 (루트 .env.example 참고)"; fi
  done
  grep -q "^REGISTRY=.*/$" .env || warn "REGISTRY 끝에 / 가 없다 — 이미지 이름이 붙어 버린다"
else
  bad ".env 없음"
fi
if [ -f backend/.env ]; then
  ok "backend/.env 있음"
  if [ -f .env ] && grep -q "^HEALING_RW_PASSWORD=" .env; then
    a=$(grep "^HEALING_RW_PASSWORD=" .env | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//')
    b=$(grep "^HEALING_RW_PASSWORD=" backend/.env | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//')
    [ "$a" = "$b" ] && ok "HEALING_RW_PASSWORD 가 backend/.env 와 같다" || bad "HEALING_RW_PASSWORD 가 backend/.env 와 다르다"
  fi
else
  bad "backend/.env 없음"
fi

echo "== 지금 떠 있는 것"
old=$(docker ps -a --filter label=com.docker.compose.project=moa --format '{{.Names}}' | tr '\n' ' ')
[ -n "$old" ] && warn "옛 단일 스택(moa): ${old}— 첫 deploy.sh 가 지운다(볼륨 유지). 그 한 번은 화면이 잠깐 끊긴다" || ok "옛 단일 스택 없음"
docker volume inspect moa_pgdata >/dev/null 2>&1 && ok "DB 볼륨 moa_pgdata 있음 — 그대로 이어 쓴다" || warn "DB 볼륨 moa_pgdata 없음 — 새 DB 다. 첫 배포 전에 sql/run_sql.py 로 초기화한다"
user=$(docker ps --format '{{.Names}} {{.Ports}}' | grep ':8501->' | awk '{print $1}')
echo "    8501 사용 중: ${user:-없음}"

echo
[ "$FAIL" = 0 ] && echo "점검 통과 — main 에 merge 하면 CI 가 배포한다" || { echo "고칠 것이 있다 (XX 줄)"; exit 1; }
