#!/usr/bin/env bash
# 이중화 배포 시험 DEP-1 ~ 5 (PRD 9.2 · 기획서 산출물 "배포 및 장애 복구 보고서") — 서버(또는 로컬)에서 실행한다
#
#   bash scripts/dep-test.sh                      DEP-1 ~ 4 (앱 스택 A 를 잠깐 멈췄다 켠다 — B 가 받는다)
#   bash scripts/dep-test.sh --with-session       DEP-5 까지 (시험 세션 1개를 만든다 · 해석 서비스 호출이 생긴다)
#   bash scripts/dep-test.sh > dep-result.md      결과표를 파일로
#
#   DEP-1 매니페스트 · 시크릿   공개 포트 · 메모리 제한 · restart 정책 · docker.sock · 이미지에 비밀값 없음
#   DEP-2 탐색 · 분산           A/B UP · round-robin · 쿠키 고정 · 스택 격리 · WebSocket
#   DEP-3 A/B 장애 전환         A backend · A frontend 를 멈춰 감지 · 전환 시간(SC-12 각 15초), 그동안 실패 요청 수
#   DEP-4 부분 장애 · 복귀      해석 서비스 장애(F-1)에 스택이 빠지지 않는다 · 복귀한 스택이 다시 트래픽을 받는다
#   DEP-5 사용자 상태           A 에서 만든 세션을 A 가 죽은 뒤 B 가 같은 내용으로 이어 준다 · 중복 0건
#
# 전제: 공용 + A + B 가 모두 떠 있고 healthy (아니면 "배포 구성 실패"로 따로 보고한다 — PRD 9.2)
set -uo pipefail

GATEWAY=moa-core-gateway-1
DB=moa-core-db-1
PROBE=moa-core-healing-1          # moa_core 안에서 두 backend 를 부를 수 있는 컨테이너 (python · httpx 있음)
URL=${GATEWAY_URL:-http://localhost:8501}
LIMIT=15                          # SC-12 감지 · 전환 각 15초
WITH_SESSION=0; [ "${1:-}" = "--with-session" ] && WITH_SESSION=1

RESULTS=()
FAILED=0
record() {  # id 항목 결과(PASS/FAIL/SKIP) 근거
  RESULTS+=("| $1 | $2 | $3 | $4 |")
  [ "$3" = "FAIL" ] && FAILED=1
  echo "  [$3] $1 $2 — $4" >&2
}
now() { date +%s.%N; }
el()  { awk -v a="$1" -v b="$2" 'BEGIN{printf "%.1f", b-a}'; }
le()  { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a<=b)}'; }

gw_state() {
  docker exec "$GATEWAY" wget -qO- "http://127.0.0.1:8404/stats;csv" 2>/dev/null \
    | awk -F, -v s="$1" '$1=="app" && $2==s {print $18}'
}
# 게이트웨이로 요청 1건 → 응답한 스택(a/b) · 실패면 "x"
served() {  # $1 = 쿠키 스택(a/b) 또는 빈 값
  local out code ck
  out=$(curl -s -D - -o /dev/null -w '%{http_code}' --max-time 3 ${1:+-b MOA_STACK=$1} "$URL/_stcore/health" | tr -d '\r')
  code=${out##*$'\n'}
  [ "$code" = "200" ] || { echo x; return; }
  ck=$(echo "$out" | awk -F'[=;]' 'tolower($0) ~ /^set-cookie: moa_stack=/ {print $2}')
  echo "${ck:-$1}"
}
wait_state() {  # $1 스택 $2 원하는 상태(UP / notUP) $3 최대 초 → 걸린 시각(now) 출력, 실패 시 빈 값
  local end=$(( $(date +%s) + $3 )) st
  while [ "$(date +%s)" -le "$end" ]; do
    st=$(gw_state "$1")
    if { [ "$2" = UP ] && [ "$st" = UP ]; } || { [ "$2" = notUP ] && [ -n "$st" ] && [ "$st" != UP ]; }; then
      now; return 0
    fi
    sleep 0.2
  done
  return 1
}
# 배경 요청: 0.2초마다 쿠키 a · 쿠키 없음 요청을 보내 실패 수를 센다
probe_start() { PROBE_LOG=$(mktemp); ( while [ -f "$PROBE_LOG" ]; do echo "a $(served a)" >> "$PROBE_LOG"; echo "- $(served '')" >> "$PROBE_LOG"; sleep 0.2; done ) & PROBE_PID=$!; }
probe_stop()  { local f=$PROBE_LOG; PROBE_LOG=""; sleep 0.5; kill "$PROBE_PID" 2>/dev/null; wait "$PROBE_PID" 2>/dev/null
                PROBE_TOTAL=$(wc -l < "$f"); PROBE_FAIL=$(grep -c ' x$' "$f"); rm -f "$f"; }

echo "이중화 배포 시험 시작 $(date -u +%Y-%m-%dT%H:%M:%SZ) · 대상 $URL" >&2

# ---------- 전제 ----------
pre_ok=1
for c in $GATEWAY $DB moa-core-socket-proxy-1 moa-a-backend-1 moa-a-frontend-1 moa-b-backend-1 moa-b-frontend-1 $PROBE; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = true ] || { echo "전제 실패: $c 가 떠 있지 않다" >&2; pre_ok=0; }
done
[ "$(gw_state a)" = UP ] && [ "$(gw_state b)" = UP ] || { echo "전제 실패: 게이트웨이 a=$(gw_state a) b=$(gw_state b)" >&2; pre_ok=0; }
[ "$pre_ok" = 1 ] || { echo "| 전제 | 공용 + A + B healthy | FAIL | 배포 구성 실패로 보고 (PRD 9.2) |"; exit 2; }

# ---------- DEP-1 매니페스트 · 시크릿 ----------
echo "DEP-1 매니페스트 · 시크릿" >&2
pub=$(docker ps --filter name='^moa-' --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0:|\[::\]:' | awk '{print $1}' | sort -u | tr '\n' ' ')
[ "$pub" = "$GATEWAY " ] && record DEP-1 "밖으로 열린 포트는 게이트웨이뿐" PASS "${pub}" \
                        || record DEP-1 "밖으로 열린 포트는 게이트웨이뿐" FAIL "공개: ${pub:-없음}"
nolimit=$(for c in $(docker ps --filter name='^moa-' --format '{{.Names}}'); do
  [ "$(docker inspect -f '{{.HostConfig.Memory}}' "$c")" = 0 ] && echo -n "$c "; done)
[ -z "$nolimit" ] && record DEP-1 "모든 컨테이너 메모리 제한" PASS "$(docker ps --filter name='^moa-' -q | wc -l)개" \
                  || record DEP-1 "모든 컨테이너 메모리 제한" FAIL "없음: $nolimit"
bad=""
for c in moa-a-backend-1 moa-b-backend-1 moa-core-interpreter-primary-1; do
  [ "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$c")" = no ] || bad+="$c "; done
for c in moa-a-frontend-1 moa-b-frontend-1 moa-core-interpreter-backup-1 $GATEWAY $DB; do
  [ "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$c")" = unless-stopped ] || bad+="$c "; done
[ -z "$bad" ] && record DEP-1 "restart 정책 (주입 대상 no · 나머지 unless-stopped)" PASS "R-14" \
              || record DEP-1 "restart 정책" FAIL "다름: $bad"
sock=$(for c in $(docker ps --filter name='^moa-' --format '{{.Names}}'); do
  docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' "$c" | grep -q docker.sock && echo -n "$c "; done)
ctl_internal=$(docker network inspect -f '{{.Internal}}' moa-core_ctl 2>/dev/null)
proxy_nets=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' moa-core-socket-proxy-1)
[ "$sock" = "moa-core-socket-proxy-1 " ] && [ "$ctl_internal" = true ] && [ "$proxy_nets" = "moa-core_ctl " ] \
  && record DEP-1 "docker.sock 은 socket-proxy 만 · 내부망 ctl 전용" PASS "ctl internal=$ctl_internal" \
  || record DEP-1 "docker.sock 은 socket-proxy 만" FAIL "마운트: $sock · 프록시 망: $proxy_nets · internal=$ctl_internal"
leak=""
for img in $(docker inspect -f '{{.Config.Image}}' moa-a-backend-1 moa-a-frontend-1 | sort -u); do
  docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$img" \
    | grep -qiE '^[A-Z_]*(PASSWORD|API_KEY|SECRET)=.+' && leak+="$img "; done
[ -z "$leak" ] && record DEP-1 "이미지에 비밀값 없음 (실행 시 .env 로만)" PASS "backend · frontend 이미지 Env 검사" \
               || record DEP-1 "이미지에 비밀값 없음" FAIL "$leak"

# ---------- DEP-2 탐색 · 분산 ----------
echo "DEP-2 탐색 · 분산" >&2
record DEP-2 "게이트웨이가 두 스택을 찾음" PASS "a=$(gw_state a) b=$(gw_state b)"
na=0; nb=0; nx=0
for _ in $(seq 1 20); do case $(served '') in a) na=$((na+1));; b) nb=$((nb+1));; *) nx=$((nx+1));; esac; done
[ "$na" -ge 8 ] && [ "$nb" -ge 8 ] && [ "$nx" = 0 ] && record DEP-2 "쿠키 없는 요청 20건 분산" PASS "a $na · b $nb" \
                                                   || record DEP-2 "쿠키 없는 요청 20건 분산" FAIL "a $na · b $nb · 실패 $nx"
stick=0; for _ in $(seq 1 10); do [ "$(served b)" = b ] && stick=$((stick+1)); done
[ "$stick" = 10 ] && record DEP-2 "쿠키 고정 (MOA_STACK=b 10건)" PASS "10/10 b" || record DEP-2 "쿠키 고정" FAIL "$stick/10"
iso=$(docker exec moa-a-frontend-1 python -c "
import socket
def ip(h):
    try: return socket.gethostbyname(h)
    except OSError: return '-'
print(ip('backend'), ip('db'), ip('moa-b-backend-1'), ip('socket-proxy'))")
a_be=$(docker inspect -f '{{(index .NetworkSettings.Networks "moa-a_default").IPAddress}}' moa-a-backend-1)
[ "$iso" = "$a_be - - -" ] && record DEP-2 "스택 격리 (A 화면 → A backend 만)" PASS "backend=$a_be · db/B/proxy 안 보임" \
                           || record DEP-2 "스택 격리" FAIL "A 화면에서: $iso (A backend $a_be)"
ws=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" "$URL/_stcore/stream")
[ "$ws" = 101 ] && record DEP-2 "WebSocket 전달" PASS "101" || record DEP-2 "WebSocket 전달" FAIL "$ws"

# ---------- DEP-3 A/B 장애 전환 ----------
dep3() {  # $1 = backend | frontend
  local c="moa-a-$1-1" t0 td ts tr
  probe_start; sleep 1
  t0=$(now); docker stop -t 0 "$c" >/dev/null
  td=$(wait_state a notUP 30)
  ts=""; local end=$(( $(date +%s) + 30 ))
  while [ "$(date +%s)" -le "$end" ]; do [ "$(served a)" = b ] && { ts=$(now); break; }; sleep 0.2; done
  docker start "$c" >/dev/null; tr=$(now)
  local tu; tu=$(wait_state a UP 60)
  probe_stop
  local d s u
  d=$([ -n "$td" ] && el "$t0" "$td" || echo "-"); s=$([ -n "$ts" ] && el "$t0" "$ts" || echo "-"); u=$([ -n "$tu" ] && el "$tr" "$tu" || echo "-")
  if [ -n "$td" ] && [ -n "$ts" ] && le "$d" $LIMIT && le "$s" $LIMIT; then
    record DEP-3 "A $1 중지 → 감지 · 전환" PASS "감지 ${d}초 · 고정 사용자 B 로 ${s}초 · 실패 요청 ${PROBE_FAIL}/${PROBE_TOTAL}"
  else
    record DEP-3 "A $1 중지 → 감지 · 전환" FAIL "감지 ${d}초 · 전환 ${s}초 (기준 ${LIMIT}초) · 실패 ${PROBE_FAIL}/${PROBE_TOTAL}"
  fi
  [ -n "$tu" ] && record DEP-4 "A $1 재시작 → 재등록" PASS "${u}초 뒤 UP" \
               || record DEP-4 "A $1 재시작 → 재등록" FAIL "60초 안에 UP 안 됨"
}
echo "DEP-3 A/B 장애 전환 · DEP-4 복귀" >&2
dep3 backend
dep3 frontend
na=0; for _ in $(seq 1 10); do [ "$(served '')" = a ] && na=$((na+1)); done
[ "$na" -ge 3 ] && record DEP-4 "복귀한 A 가 다시 트래픽을 받음" PASS "쿠키 없는 10건 중 a ${na}건" \
                || record DEP-4 "복귀한 A 가 다시 트래픽을 받음" FAIL "a ${na}/10"

# ---------- DEP-4 부분 장애 (의존 서비스) ----------
echo "DEP-4 부분 장애" >&2
active=$(docker exec "$DB" psql -U postgres -tAq -c "SELECT count(*) FROM healing.fault_injection
          WHERE target='order_interpreter_primary' AND mode='error' AND action='inject' AND cleared_at IS NULL")
mine=""
if [ "$active" = 0 ]; then
  mine="fi_dep4_$(date +%s)"
  docker exec "$DB" psql -U postgres -tAq -c "INSERT INTO healing.fault_injection (injection_id, fault, action, target, mode, environment)
          VALUES ('$mine','F-1','inject','order_interpreter_primary','error','lab')" >/dev/null
  sleep 8                                 # 해석 서비스 주입 상태 캐시 + 게이트웨이 점검 2회 이상
fi
sa=$(gw_state a); sb=$(gw_state b)
[ "$sa" = UP ] && [ "$sb" = UP ] \
  && record DEP-4 "해석 서비스 1차 장애(F-1)에 스택이 빠지지 않음" PASS "a=$sa b=$sb ($([ -n "$mine" ] && echo '시험 주입' || echo '이미 켜진 주입 사용'))" \
  || record DEP-4 "해석 서비스 1차 장애(F-1)에 스택이 빠지지 않음" FAIL "a=$sa b=$sb"
[ -n "$mine" ] && docker exec "$DB" psql -U postgres -tAq -c "UPDATE healing.fault_injection SET cleared_at=NOW() WHERE injection_id='$mine'" >/dev/null

# ---------- DEP-5 사용자 상태 ----------
if [ "$WITH_SESSION" = 1 ]; then
  echo "DEP-5 사용자 상태 (시험 세션 생성)" >&2
  wait_state a UP 60 >/dev/null
  out=$(docker exec -i "$PROBE" python - <<'EOF'
import httpx, time, json, sys
A, B = "http://moa-a-backend-1:8000/api", "http://moa-b-backend-1:8000/api"
c = httpx.Client(timeout=30)
raw = c.get(f"{A}/sample-conversation").json()["data"]["raw_text"]
r = c.post(f"{A}/sessions", json={"raw_text": raw, "source": "sample"}).json()["data"]
sid, tok = r["session_id"], r["session_token"]
h = {"X-Session-Token": tok}
for _ in range(120):                                   # 분석이 끝날 때까지 (최대 120초)
    p = c.get(f"{A}/sessions/{sid}/progress", headers=h).json()["data"]
    if str(p.get("status", "")).upper() not in ("PENDING", "RUNNING"):
        break
    time.sleep(1)
a = c.get(f"{A}/sessions/{sid}", headers=h).json()["data"]
print(json.dumps({"sid": sid, "tok": tok, "status": a.get("status"), "rows": a.get("rows")}, ensure_ascii=False))
EOF
)
  sid=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin)['sid'])" 2>/dev/null || echo "$out" | sed -n 's/.*"sid": "\([^"]*\)".*/\1/p')
  if [ -z "$sid" ]; then
    record DEP-5 "A 에서 세션 생성" FAIL "$(echo "$out" | tail -1 | cut -c1-120)"
  else
    before=$(docker exec "$DB" psql -U postgres -tAq -c "SELECT count(*) FROM app.order_item WHERE session_id='$sid'" 2>/dev/null)
    docker stop -t 0 moa-a-backend-1 >/dev/null
    res=$(docker exec -i "$PROBE" python - "$out" <<'EOF'
import httpx, json, sys
s = json.loads(sys.argv[1])
b = httpx.get(f"http://moa-b-backend-1:8000/api/sessions/{s['sid']}", headers={"X-Session-Token": s["tok"]}, timeout=10)
d = b.json().get("data") or {}
same = d.get("rows") == s["rows"] and d.get("status") == s["status"]
print(f"{b.status_code} {'같음' if same else '다름'} status={d.get('status')} 항목={len(d.get('rows') or [])}")
EOF
)
    after=$(docker exec "$DB" psql -U postgres -tAq -c "SELECT count(*) FROM app.order_item WHERE session_id='$sid'" 2>/dev/null)
    docker start moa-a-backend-1 >/dev/null; wait_state a UP 60 >/dev/null
    case "$res" in "200 같음"*) record DEP-5 "A 중지 뒤 B 가 같은 세션을 이어 줌" PASS "$res · 세션 $sid";;
                   *)           record DEP-5 "A 중지 뒤 B 가 같은 세션을 이어 줌" FAIL "$res";; esac
    [ "$before" = "$after" ] && record DEP-5 "전환 전후 주문 항목 중복 · 유실 0건" PASS "${before}건 → ${after}건" \
                             || record DEP-5 "전환 전후 주문 항목 중복 · 유실 0건" FAIL "${before}건 → ${after}건"
  fi
else
  record DEP-5 "사용자 상태" SKIP "--with-session 으로 실행 (시험 세션 · 해석 서비스 호출이 생긴다)"
fi

# ---------- 결과 ----------
echo "## 이중화 배포 시험 결과 — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo
echo "대상 \`$URL\` · 호스트 \`$(hostname)\` · 앱 이미지 \`$(docker inspect -f '{{.Config.Image}}' moa-a-backend-1 | sed 's#.*/##')\`"
echo
echo "| ID | 항목 | 결과 | 근거 |"
echo "| --- | --- | --- | --- |"
printf '%s\n' "${RESULTS[@]}"
echo
echo "최종 상태: 게이트웨이 a=$(gw_state a) b=$(gw_state b)"
exit $FAILED
