#!/bin/bash
set -euo pipefail
ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env
TS=$(date -u +%Y%m%d_%H%M%S)
cp "$ENV" "${ENV}.bak.pre_memory.${TS}"
# Fail-open temporal: MI de vm-genesis-bc-tf-01 aún no autorizada en Redis data-plane
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/genesis-cognitive-8447/Genesis_v2/.env")
lines = p.read_text(encoding="utf-8").splitlines()
want = {
    "GENESIS_SESSION_BACKEND": "memory",
    "GENESIS_REDIS_REQUIRED": "0",
}
seen=set()
out=[]
for line in lines:
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        out.append(line); continue
    k,v=line.split("=",1)
    k=k.strip()
    if k in want:
        out.append(f"{k}={want[k]}")
        seen.add(k)
    else:
        out.append(line)
for k,v in want.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out)+"\n", encoding="utf-8")
print("ENV_PATCHED_MEMORY")
PY
chmod 600 "$ENV"
chown genesis:genesis "$ENV"
grep -E '^(GENESIS_SESSION_BACKEND|GENESIS_REDIS_REQUIRED|GENESIS_REDIS_AUTH_MODE)=' "$ENV"
systemctl restart genesis-cognitive-8447
sleep 3
systemctl is-active genesis-cognitive-8447 || true
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf --max-time 3 http://127.0.0.1:8447/health >/dev/null; then
    echo HEALTH_OK
    curl -sS --max-time 5 http://127.0.0.1:8447/health
    echo
    curl -sS --max-time 5 -o /dev/null -w 'pruebas_http=%{http_code}\n' http://127.0.0.1:8447/pruebas/
    exit 0
  fi
  sleep 2
done
echo HEALTH_FAIL
journalctl -u genesis-cognitive-8447 -n 40 --no-pager
exit 1
