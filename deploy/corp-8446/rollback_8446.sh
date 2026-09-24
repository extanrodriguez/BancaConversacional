#!/bin/bash
# Rollback Genesis Cognitive 8446 — NEVER touches 8445
set -e

SERVICE_NAME="genesis-cognitive-8446.service"

echo "=== Genesis 8446 Rollback ==="

# 1. Stop and disable 8446
echo "[1] Stopping $SERVICE_NAME..."
sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true

# 2. Verify 8445 still alive
echo "[2] Verifying 8445..."
curl -sS -m 5 http://127.0.0.1:8445/health || echo "WARNING: 8445 not responding"

# 3. Confirm 8446 is down
echo "[3] Confirming 8446 is down..."
curl -sS -m 3 http://127.0.0.1:8446/health 2>/dev/null && echo "WARNING: 8446 still responding" || echo "  8446 stopped OK"

# 4. Remove unit file (optional)
echo "[4] Removing unit file..."
sudo rm -f /etc/systemd/system/"$SERVICE_NAME"
sudo systemctl daemon-reload

# 5. Keep directory for analysis
echo ""
echo "=== Rollback complete ==="
echo "Directory /opt/genesis-cognitive-8446 preserved for analysis."
echo "8445 service NOT modified."
echo ""
echo "To restore connectivity listener (if needed):"
echo "  sudo systemctl enable --now dev-health-8446.service"
