#!/bin/bash
# Backup de Genesis_v2 antes de deploy — preserva .env por separado
set -euo pipefail

DEPLOY_DIR="/opt/genesis-cognitive-8446/Genesis_v2"
BACKUP_ROOT="/opt/genesis-cognitive-8446/backups"
TIMESTAMP="${1:-$(date -u +%Y%m%d_%H%M%S)}"

echo "=== Genesis 8446 Backup ($TIMESTAMP) ==="

if [ ! -d "$DEPLOY_DIR" ] || [ -z "$(ls -A "$DEPLOY_DIR" 2>/dev/null || true)" ]; then
    echo "No hay instalación previa en $DEPLOY_DIR — backup omitido."
    exit 0
fi

sudo mkdir -p "$BACKUP_ROOT"
sudo chown genesis:genesis "$BACKUP_ROOT"

if systemctl is-active --quiet genesis-cognitive-8446.service 2>/dev/null; then
    echo "[1] Deteniendo servicio para backup consistente..."
    sudo systemctl stop genesis-cognitive-8446.service
    RESTART_AFTER=1
else
    RESTART_AFTER=0
fi

if [ -f "$DEPLOY_DIR/.env" ]; then
    echo "[2] Respaldo .env..."
    sudo cp -a "$DEPLOY_DIR/.env" "$BACKUP_ROOT/.env.$TIMESTAMP"
    sudo chown genesis:genesis "$BACKUP_ROOT/.env.$TIMESTAMP"
    sudo chmod 600 "$BACKUP_ROOT/.env.$TIMESTAMP"
fi

ARCHIVE="$BACKUP_ROOT/genesis_v2_${TIMESTAMP}.tar.gz"
echo "[3] Creando $ARCHIVE ..."
sudo tar -czf "$ARCHIVE" \
    -C /opt/genesis-cognitive-8446 \
    --exclude='Genesis_v2/.venv' \
    --exclude='Genesis_v2/**/__pycache__' \
    --exclude='Genesis_v2/**/*.pyc' \
    Genesis_v2

sudo chown genesis:genesis "$ARCHIVE"
echo "Backup OK: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

LATEST_LINK="$BACKUP_ROOT/LATEST.txt"
echo "$ARCHIVE" | sudo tee "$LATEST_LINK" >/dev/null
echo ".env backup: $BACKUP_ROOT/.env.$TIMESTAMP" | sudo tee -a "$LATEST_LINK" >/dev/null

if [ "$RESTART_AFTER" -eq 1 ]; then
    echo "[4] Reiniciando servicio previo..."
    sudo systemctl start genesis-cognitive-8446.service || true
fi

echo "=== Backup complete ==="
