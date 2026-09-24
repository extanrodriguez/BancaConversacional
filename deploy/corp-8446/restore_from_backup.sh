#!/bin/bash
# Restaura la última copia de Genesis_v2 desde backups/
set -euo pipefail

BACKUP_ROOT="/opt/genesis-cognitive-8446/backups"
DEPLOY_PARENT="/opt/genesis-cognitive-8446"
SERVICE_NAME="genesis-cognitive-8446.service"

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ]; then
    if [ -f "$BACKUP_ROOT/LATEST.txt" ]; then
        ARCHIVE=$(head -1 "$BACKUP_ROOT/LATEST.txt")
    else
        ARCHIVE=$(ls -t "$BACKUP_ROOT"/genesis_v2_*.tar.gz 2>/dev/null | head -1 || true)
    fi
fi

if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "ERROR: no se encontró backup en $BACKUP_ROOT"
    exit 1
fi

echo "=== Restaurando desde $ARCHIVE ==="
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true

ENV_BACKUP=""
if [ -f "$DEPLOY_PARENT/Genesis_v2/.env" ]; then
    ENV_BACKUP=$(mktemp)
    cp "$DEPLOY_PARENT/Genesis_v2/.env" "$ENV_BACKUP"
fi

sudo rm -rf "$DEPLOY_PARENT/Genesis_v2"
sudo tar -xzf "$ARCHIVE" -C "$DEPLOY_PARENT"
sudo chown -R genesis:genesis "$DEPLOY_PARENT/Genesis_v2"

if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" "$DEPLOY_PARENT/Genesis_v2/.env"
    rm -f "$ENV_BACKUP"
    sudo chown genesis:genesis "$DEPLOY_PARENT/Genesis_v2/.env"
    sudo chmod 600 "$DEPLOY_PARENT/Genesis_v2/.env"
fi

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sleep 5
curl -sf http://127.0.0.1:8446/health && echo ""
echo "=== Restore complete ==="
