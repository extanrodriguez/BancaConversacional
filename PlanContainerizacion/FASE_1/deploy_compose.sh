#!/bin/bash
# Deploy Genesis API con Docker Compose en VM (Fase 1)
# NO modifica genesis-cognitive-8446.service
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/genesis-docker}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
IMAGE_TAG="${IMAGE_TAG:-genesis-api:latest}"

echo "=== Genesis Docker Compose Deploy ==="
echo "Dir: $DEPLOY_DIR"

# 1. Verificar Docker
command -v docker >/dev/null || { echo "ERROR: docker not installed"; exit 1; }
docker compose version >/dev/null || { echo "ERROR: docker compose plugin missing"; exit 1; }

# 2. Safety: 8446 legacy sigue vivo
curl -sS -m 5 http://127.0.0.1:8446/health >/dev/null && echo "8446 OK (legacy)" || echo "WARN: 8446 not responding"

# 3. Pull / load imagen
cd "$DEPLOY_DIR"
if [ -f ".env" ]; then
  echo "Using .env from $DEPLOY_DIR"
else
  echo "ERROR: .env missing in $DEPLOY_DIR"
  exit 1
fi

# Si usas ACR en fase intermedia:
# docker login $ACR_NAME.azurecr.io
# docker pull $ACR_NAME.azurecr.io/genesis-api:$IMAGE_TAG

docker compose -f "$COMPOSE_FILE" pull 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" build --no-cache 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

# 4. Health
sleep 10
PORT=$(grep GENESIS_PORT .env | cut -d= -f2 | tr -d '"' || echo 8445)
curl -sf "http://127.0.0.1:${PORT}/health" | head -c 200
echo ""
echo "=== Deploy complete ==="
docker compose -f "$COMPOSE_FILE" ps
