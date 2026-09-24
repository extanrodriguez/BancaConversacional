#!/usr/bin/env bash
# Liberar :8448 y levantar contenedores Genesis
set -euo pipefail
ROOT="/opt/genesis-cognitive-8448/Genesis_v2"
cd "$ROOT"

# Matar http.server residual u otros listeners en 8448 (excepto docker-proxy)
for pid in $(ss -lptn 'sport = :8448' 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u); do
  cmd=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null || true)
  echo "Found PID $pid :: $cmd"
  if echo "$cmd" | grep -qiE 'http.server|python3 -m http'; then
    echo "Killing $pid"
    kill "$pid" || kill -9 "$pid" || true
  fi
done
sleep 1

# Si el contenedor existe pero no publicó puerto, recrear
docker compose -f deploy/corp-8448/docker-compose.yml down || true
docker compose -f deploy/corp-8448/docker-compose.yml up -d --remove-orphans
sleep 8
echo "=== health ==="
curl -sf -m 8 http://127.0.0.1:8448/health
echo
echo "=== pruebas ==="
curl -sf -m 5 -o /dev/null -w "http=%{http_code}\n" http://127.0.0.1:8448/pruebas
docker ps --filter name=genesis --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
