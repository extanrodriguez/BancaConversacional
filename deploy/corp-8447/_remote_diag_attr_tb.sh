#!/bin/bash
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
# Patch logger temporarily to print traceback for next failure; restore after
PY=$APP/src/genesis_cognitive/demo/contract_inspector_app.py
sudo cp -a "$PY" /tmp/contract_inspector_app.py.bak_attrdiag
sudo python3 - <<'PY'
from pathlib import Path
p = Path("/opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive/demo/contract_inspector_app.py")
t = p.read_text(encoding="utf-8")
old = '''                    import logging as _log_v4
                    _log_v4.getLogger("genesis.brain").warning(
                        "azure_plan_path_failed: %s", type(_v4_exc).__name__,
                    )'''
new = '''                    import logging as _log_v4
                    import traceback as _tb_v4
                    _log_v4.getLogger("genesis.brain").warning(
                        "azure_plan_path_failed: %s msg=%s\\n%s",
                        type(_v4_exc).__name__,
                        str(_v4_exc)[:300],
                        _tb_v4.format_exc(),
                    )'''
if old not in t:
    # try already-patched or alternate
    if "format_exc" in t and "azure_plan_path_failed" in t:
        print("ALREADY_PATCHED")
    else:
        print("PATTERN_MISSING")
        # show nearby
        idx = t.find("azure_plan_path_failed")
        print(repr(t[idx-80:idx+200]))
        raise SystemExit(2)
else:
    p.write_text(t.replace(old, new, 1), encoding="utf-8")
    print("PATCHED_LOGGER")
PY
sudo systemctl restart genesis-cognitive-8447
sleep 4
curl -sS -m 20 http://127.0.0.1:8447/ready/redis | head -c 200; echo
CONV="diag-attr-$(date +%s)"
echo "POST /turn conv=$CONV"
RESP=$(curl -sS -m 120 -X POST http://127.0.0.1:8447/turn \
  -H 'Content-Type: application/json' \
  -d "{\"conversation_id\":\"$CONV\",\"customer_id\":\"726588\",\"question\":\"La tasa de mi préstamo y qué significa\"}")
echo "$RESP" | /opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python -c '
import sys,json,re
d=json.loads(sys.stdin.read())
print("keys", sorted(d.keys())[:30])
print("status", d.get("status"), "intent", d.get("intent_id") or d.get("intent"))
print("inf", d.get("inference_count"))
dt=d.get("decision_trace")
print("dt_type", type(dt).__name__, "len", len(dt) if isinstance(dt,list) else None)
if isinstance(dt, list) and dt:
  out=dt[0].get("output") if isinstance(dt[0], dict) else dt[0]
  s=re.sub(r"\b\d{4,}\b","####", str(out)[:800])
  print("out0", s)
'
echo "=== JOURNAL ==="
sudo journalctl -u genesis-cognitive-8447 --since "1 min ago" --no-pager \
  | grep -A40 "azure_plan_path_failed" | head -80
# restore original logger body but KEEP traceback logging (we want it) — leave patched
echo DONE
