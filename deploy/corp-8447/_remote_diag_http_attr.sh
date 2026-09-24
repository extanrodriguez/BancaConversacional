#!/bin/bash
set -euo pipefail
# Capture recent AttributeError from cognitive service after one POST /turn
CONV="diag-attr-$(date +%s)"
curl -sS -m 90 -X POST http://127.0.0.1:8447/turn \
  -H 'Content-Type: application/json' \
  -d "{\"conversation_id\":\"$CONV\",\"customer_id\":\"726588\",\"question\":\"La tasa de mi préstamo y qué significa\"}" \
  | /opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python -c '
import sys,json,re
raw=sys.stdin.read()
try:
  d=json.loads(raw)
except Exception:
  print("RAW", raw[:300]); raise
trace=str((d.get("decision_trace") or [{}])[0])
trace=re.sub(r"\b\d{4,}\b","####",trace)
print("status", d.get("status"), "intent", d.get("intent_id"), "inf", d.get("inference_count"))
print("trace", trace[:500])
'
echo "=== journal AttributeError (last 40 matching) ==="
sudo journalctl -u genesis-cognitive-8447 --since "2 min ago" --no-pager 2>/dev/null \
  | grep -E "AttributeError|azure_plan_path_failed|Traceback|Error" \
  | tail -40 || true
echo DONE
