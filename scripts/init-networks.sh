#!/bin/sh
# 공용 · 앱 스택이 함께 쓰는 Docker 네트워크를 미리 만든다 (처음 한 번 · 여러 번 실행해도 안전)
#   moa_core       공용 스택(db · interpreter · gateway · healing) + 각 앱 스택 backend
#   moa-a_default  앱 스택 A 전용 (+ gateway)
#   moa-b_default  앱 스택 B 전용 (+ gateway)
# compose 파일은 세 네트워크를 external 로 참조한다 — 게이트웨이가 앱 스택보다 먼저 떠도 붙을 수 있게
set -eu
for net in moa_core moa-a_default moa-b_default; do
  if docker network inspect "$net" >/dev/null 2>&1; then
    echo "있음: $net"
  else
    docker network create "$net" >/dev/null
    echo "만듦: $net"
  fi
done
