#!/usr/bin/env bash
# Deploy Genesis Cognitive as Docker containers on port 8448 (parallel to systemd 8446/8447).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/corp-8448/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
TARGET_DIR="/opt/genesis-cognitive-8448"

echo "=== Genesis 8448 Container Deploy ==="
echo "Repo: $ROOT_DIR"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: missing $COMPOSE_FILE"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f /opt/genesis-cognitive-8447/Genesis_v2/.env ]]; then
    echo "Heredando .env desde 8447..."
    cp /opt/genesis-cognitive-8447/Genesis_v2/.env "$ENV_FILE"
  elif [[ -f /opt/genesis-cognitive-8446/Genesis_v2/.env ]]; then
    echo "Heredando .env desde 8446..."
    cp /opt/genesis-cognitive-8446/Genesis_v2/.env "$ENV_FILE"
  else
    echo "ERROR: no hay .env"
    exit 1
  fi
fi

# Asegurar puerto 8448 en .env (compose force ENV anyway)
grep -q '^GENESIS_PORT=' "$ENV_FILE" && sed -i 's/^GENESIS_PORT=.*/GENESIS_PORT=8448/' "$ENV_FILE" || echo 'GENESIS_PORT=8448' >> "$ENV_FILE"

mkdir -p "$TARGET_DIR"
# Mirror compose into opt for ops clarity
cp -a "$ROOT_DIR/deploy/corp-8448" "$TARGET_DIR/"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker no instalado en la VM"
  exit 1
fi

cd "$ROOT_DIR"
echo "[1] docker compose build..."
docker compose -f deploy/corp-8448/docker-compose.yml build

echo "[2] docker compose up..."
docker compose -f deploy/corp-8448/docker-compose.yml up -d --remove-orphans

echo "[3] Health check..."
sleep 5
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf -m 5 http://127.0.0.1:8448/health >/tmp/genesis8448_health.json; then
    cat /tmp/genesis8448_health.json
    echo
    echo "[4] /pruebas..."
    curl -sf -m 5 -o /dev/null -w "pruebas_http=%{http_code}\n" http://127.0.0.1:8448/pruebas || true
    echo "=== Deploy 8448 complete ==="
    echo "URL: http://<IP>:8448/pruebas"
    exit 0
  fi
  echo "  waiting health... ($i)"
  sleep 3
done

echo "ERROR: health check failed"
docker compose -f deploy/corp-8448/docker-compose.yml ps || true
docker compose -f deploy/corp-8448/docker-compose.yml logs --tail=80 api || true
exit 1
