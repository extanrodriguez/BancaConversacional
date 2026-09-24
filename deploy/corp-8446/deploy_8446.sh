#!/bin/bash
# Deploy Genesis Cognitive 8446 — NEVER touches 8445
set -euo pipefail

DEPLOY_DIR="/opt/genesis-cognitive-8446/Genesis_v2"
SERVICE_NAME="genesis-cognitive-8446.service"
VENV="$DEPLOY_DIR/.venv"
PYTHON="python3.12"
ZIP_FILE="/tmp/genesis_corp_8446.zip"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)

echo "=== Genesis 8446 Deploy ==="
echo "Target: $DEPLOY_DIR"

# 0. Backup instalación actual
if [ -f "$DEPLOY_DIR/deploy/corp-8446/backup_before_deploy.sh" ]; then
    echo "[0] Backup versión actual..."
    bash "$DEPLOY_DIR/deploy/corp-8446/backup_before_deploy.sh" "$TIMESTAMP"
elif [ -d "$DEPLOY_DIR" ] && [ -n "$(ls -A "$DEPLOY_DIR" 2>/dev/null || true)" ]; then
    echo "[0] Backup inline (script no encontrado)..."
    sudo mkdir -p /opt/genesis-cognitive-8446/backups
    sudo tar -czf "/opt/genesis-cognitive-8446/backups/genesis_v2_${TIMESTAMP}.tar.gz" \
        -C /opt/genesis-cognitive-8446 --exclude='Genesis_v2/.venv' Genesis_v2 || true
fi

# 1. Verify python3.12 exists
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: $PYTHON not found. Install Python 3.12 first."
    exit 1
fi

# 2. Verify 8445 is alive (safety — never deploy if 8445 is down)
echo "[1] Checking 8445..."
curl -sS -m 5 http://127.0.0.1:8445/health >/dev/null || { echo "ERROR: 8445 not alive. Aborting."; exit 1; }
echo "  8445 OK"

# 3. Preserve .env before extract
ENV_BACKUP=""
if [ -f "$DEPLOY_DIR/.env" ]; then
    ENV_BACKUP=$(mktemp)
    cp "$DEPLOY_DIR/.env" "$ENV_BACKUP"
    echo "[2] .env preservado temporalmente"
fi

# 4. Disable temporary listener if present
echo "[3] Disabling dev-health-8446 if active..."
sudo systemctl disable --now dev-health-8446.service 2>/dev/null || true

# 5. Create directory structure
echo "[4] Creating $DEPLOY_DIR..."
sudo mkdir -p "$DEPLOY_DIR"
sudo chown -R genesis:genesis /opt/genesis-cognitive-8446

# 6. Unzip package
echo "[5] Extracting package..."
if [ ! -f "$ZIP_FILE" ]; then
    echo "ERROR: $ZIP_FILE not found"
    exit 1
fi
cd "$DEPLOY_DIR"
unzip -oq "$ZIP_FILE"

# 7. Restore .env
if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" "$DEPLOY_DIR/.env"
    rm -f "$ENV_BACKUP"
    chmod 600 "$DEPLOY_DIR/.env"
    chown genesis:genesis "$DEPLOY_DIR/.env"
    echo "[6] .env restaurado"
elif [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "WARNING: .env not found — copiar desde deploy/corp-8446/.env.example"
fi

# 8. Fix line endings
find . -name "*.py" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
find . -name "*.txt" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
find . -name "*.json" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
find . -name "*.toml" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
find . -name "*.sh" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
chmod +x deploy/corp-8446/*.sh 2>/dev/null || true

# 9. Create venv + install deps
echo "[7] Creating venv and installing dependencies..."
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
grep -v '^-e' requirements.runtime.txt > /tmp/_req_runtime_clean.txt 2>/dev/null || cp requirements.runtime.txt /tmp/_req_runtime_clean.txt
"$VENV/bin/pip" install -r /tmp/_req_runtime_clean.txt -q
"$VENV/bin/pip" install -e . -q

# 10. Verify critical imports
echo "[8] Verifying imports..."
"$VENV/bin/python" -c "
import fastapi
import httpx
import azure.identity
import azure.search.documents
import openai
import pypdf
print('ALL_IMPORTS_OK')
"

# 11. Verify pruebas UI present
if [ ! -f "$DEPLOY_DIR/src/genesis_cognitive/demo/pruebas_ui/index.html" ]; then
    echo "ERROR: pruebas_ui/index.html missing in package"
    exit 1
fi
echo "[9] pruebas_ui OK"

# 12. Set ownership
sudo chown -R genesis:genesis "$DEPLOY_DIR"

# 13. Install systemd unit
echo "[10] Installing systemd unit..."
sudo cp deploy/corp-8446/genesis-cognitive-8446.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "[11] Waiting for health..."
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf -m 3 http://127.0.0.1:8446/health >/dev/null; then
        echo "  8446 health OK"
        break
    fi
    sleep 2
    if [ "$i" -eq 10 ]; then
        echo "ERROR: 8446 health check failed"
        sudo journalctl -u "$SERVICE_NAME" -n 40 --no-pager
        exit 1
    fi
done

# 14. Verify /pruebas static
if curl -sf -m 5 http://127.0.0.1:8446/pruebas/ | head -c 80 | grep -qi html; then
    echo "[12] /pruebas UI OK"
else
    echo "WARNING: /pruebas no respondió HTML — revisar logs"
fi

curl -sS -m 5 http://127.0.0.1:8445/health >/dev/null && echo "[13] 8445 still OK"

echo ""
echo "=== Deploy complete ==="
echo "  API:     http://127.0.0.1:8446/health"
echo "  Pruebas: http://<IP-publica>:8446/pruebas"
echo "  Backup:  /opt/genesis-cognitive-8446/backups/"
echo ""
echo "Rollback: sudo bash $DEPLOY_DIR/deploy/corp-8446/restore_from_backup.sh"
