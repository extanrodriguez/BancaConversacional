#!/bin/bash
set -euo pipefail
ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env
TS=$(date -u +%Y%m%d_%H%M%S)
cp "$ENV" "$ENV.bak.redis_entra_on.${TS}"

python3 - <<'PY'
from pathlib import Path

p = Path("/opt/genesis-cognitive-8447/Genesis_v2/.env")
want = {
    "GENESIS_SESSION_BACKEND": "redis",
    "GENESIS_REDIS_REQUIRED": "1",
    "GENESIS_REDIS_AUTH_MODE": "entra_managed_identity",
    "GENESIS_REDIS_URL": "rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0",
    "GENESIS_CONV_LOCK_REDIS_URL": "rediss://bsc-cognitive-redis-qa.eastus.redis.azure.net:10000/0",
}
out = []
seen = set()
for line in p.read_text(encoding="utf-8").splitlines():
    stripped = line.lstrip("#").strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        # drop old commented redis url lines; keep other comments/blanks
        if stripped.startswith("GENESIS_REDIS_URL=") or stripped.startswith("GENESIS_CONV_LOCK_REDIS_URL="):
            continue
        out.append(line)
        continue
    k = stripped.split("=", 1)[0].strip()
    if k in want:
        if k in seen:
            continue
        out.append(f"{k}={want[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("ENV_REDIS_ENTRA_ON")
PY

chmod 600 "$ENV"
chown genesis:genesis "$ENV"
echo "=== markers ==="
grep -E '^(GENESIS_SESSION_BACKEND|GENESIS_REDIS_REQUIRED|GENESIS_REDIS_AUTH_MODE|GENESIS_REDIS_URL|GENESIS_CONV_LOCK_REDIS_URL)=' "$ENV" \
  | sed -E 's#(=rediss://).*#\1…#'

systemctl stop genesis-cognitive-8447 || true
sleep 1
fuser -k 8447/tcp 2>/dev/null || true
pkill -9 -f 'run_contract_inspector.py' 2>/dev/null || true
sleep 1
systemctl start genesis-cognitive-8447
sleep 8
systemctl is-active genesis-cognitive-8447 || true

echo "=== health ==="
curl -sS --max-time 10 http://127.0.0.1:8447/health; echo
echo "=== ready/redis ==="
curl -sS --max-time 25 http://127.0.0.1:8447/ready/redis; echo
echo "=== journal ==="
journalctl -u genesis-cognitive-8447 -n 35 --no-pager | tail -n 35
