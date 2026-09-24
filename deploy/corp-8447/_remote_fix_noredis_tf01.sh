#!/bin/bash
set -euo pipefail
ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env
TS=$(date -u +%Y%m%d_%H%M%S)
cp "$ENV" "$ENV.bak.noredis.${TS}"

python3 - <<'PY'
from pathlib import Path
p = Path("/opt/genesis-cognitive-8447/Genesis_v2/.env")
want = {
    "GENESIS_SESSION_BACKEND": "memory",
    "GENESIS_REDIS_REQUIRED": "0",
    "GENESIS_REDIS_AUTH_MODE": "url",
}
out = []
seen = set()
for line in p.read_text(encoding="utf-8").splitlines():
    if line.startswith("GENESIS_REDIS_URL=") or line.startswith("GENESIS_CONV_LOCK_REDIS_URL="):
        if not line.startswith("#"):
            out.append("#" + line)
        else:
            out.append(line)
        continue
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k in want:
        out.append(f"{k}={want[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("ENV_OK")
PY
chmod 600 "$ENV"
chown genesis:genesis "$ENV"
grep -E '^(#)?GENESIS_(SESSION_BACKEND|REDIS_|CONV_LOCK)' "$ENV" | sed -E 's/(=).*/\1…/'

systemctl stop genesis-cognitive-8447 || true
sleep 1
# force-kill hung uvicorn if still listening
fuser -k 8447/tcp 2>/dev/null || true
pkill -9 -f 'run_contract_inspector.py' 2>/dev/null || true
sleep 1
systemctl start genesis-cognitive-8447
sleep 5
systemctl is-active genesis-cognitive-8447 || true
ss -lntp | grep 8447 || true
curl -sS --max-time 8 http://127.0.0.1:8447/health; echo
curl -sS --max-time 8 -o /dev/null -w 'pruebas=%{http_code}\n' http://127.0.0.1:8447/pruebas/
journalctl -u genesis-cognitive-8447 -n 25 --no-pager | tail -n 25
