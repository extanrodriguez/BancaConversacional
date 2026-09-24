#!/bin/bash
# Deploy Genesis Cognitive 8447 — NO modifica 8445 ni 8446
set -euo pipefail

DEPLOY_DIR="/opt/genesis-cognitive-8447/Genesis_v2"
DEPLOY_PARENT="/opt/genesis-cognitive-8447"
BACKUP_ROOT="/opt/genesis-cognitive-8447/backups"
SERVICE_NAME="genesis-cognitive-8447.service"
LEGACY_8446="/opt/genesis-cognitive-8446/Genesis_v2"
VENV="$DEPLOY_DIR/.venv"
PYTHON="python3.12"
ZIP_FILE="/tmp/genesis_corp_8447.zip"
PORT=8447
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)

echo "=== Genesis 8447 Deploy (paralelo a 8446) ==="
echo "Target: $DEPLOY_DIR"

# 0. Backup instalación 8447 si existe
if [ -d "$DEPLOY_DIR" ] && [ -n "$(ls -A "$DEPLOY_DIR" 2>/dev/null || true)" ]; then
    echo "[0] Backup versión 8447 actual..."
    sudo mkdir -p "$BACKUP_ROOT"
    sudo tar -czf "$BACKUP_ROOT/genesis_v2_${TIMESTAMP}.tar.gz" \
        -C "$DEPLOY_PARENT" --exclude='Genesis_v2/.venv' Genesis_v2
    sudo chown genesis:genesis "$BACKUP_ROOT/genesis_v2_${TIMESTAMP}.tar.gz"
    echo "  Backup: $BACKUP_ROOT/genesis_v2_${TIMESTAMP}.tar.gz"
fi

if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: $PYTHON not found."
    exit 1
fi

echo "[1] Verificando 8446 legacy (no se modifica)..."
curl -sS -m 5 http://127.0.0.1:8446/health >/dev/null && echo "  8446 OK (intacto)" || echo "  WARN: 8446 no responde"

ENV_BACKUP=""
if [ -f "$DEPLOY_DIR/.env" ]; then
    ENV_BACKUP=$(mktemp)
    cp "$DEPLOY_DIR/.env" "$ENV_BACKUP"
elif [ -f "$LEGACY_8446/.env" ]; then
    echo "[2] Primera instalación 8447 — copiando .env desde 8446"
    ENV_BACKUP=$(mktemp)
    cp "$LEGACY_8446/.env" "$ENV_BACKUP"
fi

echo "[3] Preparando directorio..."
sudo mkdir -p "$DEPLOY_DIR"
sudo chown -R genesis:genesis "$DEPLOY_PARENT"

if [ ! -f "$ZIP_FILE" ]; then
    echo "ERROR: $ZIP_FILE not found"
    exit 1
fi

echo "[4] Extrayendo paquete..."
cd "$DEPLOY_DIR"
unzip -oq "$ZIP_FILE"

if [ -n "$ENV_BACKUP" ] && [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" "$DEPLOY_DIR/.env"
    rm -f "$ENV_BACKUP"
    chmod 600 "$DEPLOY_DIR/.env"
    chown genesis:genesis "$DEPLOY_DIR/.env"
    # Asegurar puerto 8447 + env Fase 1 (FAQ overlay / no escalación institucional)
    if grep -q '^GENESIS_PORT=' "$DEPLOY_DIR/.env"; then
        sed -i 's/^GENESIS_PORT=.*/GENESIS_PORT=8447/' "$DEPLOY_DIR/.env"
    else
        echo "GENESIS_PORT=8447" >> "$DEPLOY_DIR/.env"
    fi
    _ensure_env() {
        local key="$1" val="$2"
        if grep -q "^${key}=" "$DEPLOY_DIR/.env"; then
            sed -i "s|^${key}=.*|${key}=${val}|" "$DEPLOY_DIR/.env"
        else
            echo "${key}=${val}" >> "$DEPLOY_DIR/.env"
        fi
    }
    _ensure_env GENESIS_HOST "0.0.0.0"
    _ensure_env GENESIS_PORT "8447"
    _ensure_env GENESIS_FAQ_PATH "/opt/genesis-cognitive-8447/Genesis_v2/data/kb_faq_vf01.json"
    _ensure_env GENESIS_FAQ_OVERLAY_PATH "/opt/genesis-cognitive-8447/Genesis_v2/data/kb_faq_overlay_fase1.json"
    _ensure_env GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL "1"
    _ensure_env GENESIS_FAQ_INSTITUTIONAL_MIN_SCORE "0.65"
    _ensure_env GENESIS_SNAPSHOT_TTL_S "session"
    _ensure_env GENESIS_SESSION_TTL_S "1800"
    # Foundry KB + índice vectorial alineado al agente PoC
    _ensure_env AZURE_SEARCH_INDEX "bsc-kb-conocimiento"
    _ensure_env GENESIS_FOUNDRY_KB_AGENT "1"
    _ensure_env GENESIS_FOUNDRY_PROJECT_ENDPOINT "https://foundry-bsc-genesis-dev.services.ai.azure.com/api/projects/genesis-rag-poc"
    _ensure_env GENESIS_FOUNDRY_KB_AGENT_NAME "genesis-kb-agent-poc"
    _ensure_env GENESIS_FOUNDRY_KB_AGENT_VERSION "5"
    # P0/P1: puerta confianza + cache Foundry (ON en QA 8447)
    _ensure_env GENESIS_KB_CONFIDENCE_GATE "1"
    _ensure_env GENESIS_FAQ_HIGH_SCORE "0.90"
    _ensure_env GENESIS_FAQ_GRAY_MIN "0.55"
    _ensure_env GENESIS_FAQ_GRAY_MAX "0.85"
    _ensure_env GENESIS_FOUNDRY_CACHE "1"
    _ensure_env GENESIS_FOUNDRY_CACHE_TTL_S "86400"
    _ensure_env GENESIS_FOUNDRY_CACHE_DIR "/opt/genesis-cognitive-8447/Genesis_v2/data/cache/foundry_kb"
    # Azure Intent Brain — hechos solo snapshot/KB
    _ensure_env GENESIS_AZURE_BRAIN "1"
    _ensure_env GENESIS_AZURE_DRAFT "1"
    # Foundry product tools — OFF por defecto (rollback = flag 0)
    _ensure_env GENESIS_FOUNDRY_PRODUCT_TOOLS "0"
    # Limpiar cache Foundry en cada deploy QA (evita entradas envenenadas)
    rm -rf /opt/genesis-cognitive-8447/Genesis_v2/data/cache/foundry_kb 2>/dev/null || true
    mkdir -p /opt/genesis-cognitive-8447/Genesis_v2/data/cache/foundry_kb
    chown -R genesis:genesis /opt/genesis-cognitive-8447/Genesis_v2/data/cache 2>/dev/null || true
    echo "[5] .env listo (8447 + FAQ + Foundry + Azure Brain + gate + cache)"
elif [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "ERROR: .env no encontrado. Copiar desde 8446 o deploy/corp-8447/.env.example"
    exit 1
fi

find . -name "*.py" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
find . -name "*.sh" -exec sed -i 's/\r$//' {} \; 2>/dev/null || true
chmod +x deploy/corp-8447/*.sh deploy/corp-8446/*.sh 2>/dev/null || true

echo "[6] venv + dependencias..."
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
grep -v '^-e' requirements.runtime.txt > /tmp/_req_runtime_clean.txt
"$VENV/bin/pip" install -r /tmp/_req_runtime_clean.txt -q
"$VENV/bin/pip" install -e . -q

echo "[7] Verificando imports..."
"$VENV/bin/python" -c "import fastapi, httpx, openai; print('ALL_IMPORTS_OK')"

if [ ! -f "$DEPLOY_DIR/src/genesis_cognitive/demo/pruebas_ui/index.html" ]; then
    echo "ERROR: pruebas_ui missing"
    exit 1
fi

sudo chown -R genesis:genesis "$DEPLOY_DIR"

echo "[8] systemd $SERVICE_NAME..."
sudo cp deploy/corp-8447/genesis-cognitive-8447.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "[9] Health check :$PORT ..."
for i in $(seq 1 10); do
    if curl -sf -m 3 "http://127.0.0.1:${PORT}/health" >/dev/null; then
        echo "  8447 health OK"
        break
    fi
    sleep 2
    if [ "$i" -eq 10 ]; then
        sudo journalctl -u "$SERVICE_NAME" -n 40 --no-pager
        exit 1
    fi
done

curl -sf -m 5 "http://127.0.0.1:${PORT}/pruebas/" | head -c 80 | grep -qi html && echo "[10] /pruebas OK"
PRIV_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -n "$PRIV_IP" ]; then
    curl -sf -m 5 "http://${PRIV_IP}:${PORT}/health" >/dev/null \
      && echo "[11] private ${PRIV_IP}:${PORT} health OK" \
      || echo "[11] WARN: private ${PRIV_IP}:${PORT} no respondió"
fi
curl -sS -m 5 http://127.0.0.1:8446/health >/dev/null && echo "[12] 8446 sigue OK (no modificado)"

echo ""
echo "=== Deploy 8447 complete ==="
echo "  Publica:  http://20.127.25.24:${PORT}/pruebas"
if [ -n "$PRIV_IP" ]; then
    echo "  Privada:  http://${PRIV_IP}:${PORT}/pruebas"
fi
echo "  (GENESIS_HOST=0.0.0.0 → escucha en ambas IPs)"
echo "  8446 legacy intacto en :8446"
