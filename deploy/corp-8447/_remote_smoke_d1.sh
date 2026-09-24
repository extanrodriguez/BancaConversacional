#!/bin/bash
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
for f in \
  src/genesis_cognitive/brain/azure_plan_turn.py \
  src/genesis_cognitive/brain/azure_plan_adapter.py \
  src/genesis_cognitive/demo/contract_inspector_app.py
do
  sed -i 's/\r$//' "$APP/$f"
  echo "OK $f $(sha256sum "$APP/$f" | awk '{print $1}')"
done
CONV="smoke-d1-$(date +%s)"
curl -sS -m 120 -X POST http://127.0.0.1:8447/turn \
  -H 'Content-Type: application/json' \
  --data-binary @- <<EOF | "$APP/.venv/bin/python" -c '
import sys,json,re
d=json.loads(sys.stdin.read())
a=d.get("audit") or {}
app=d.get("app_channel") or {}
st=app.get("status") or d.get("status")
intent=app.get("intent_id") or d.get("intent_id")
trace=str(a.get("decision_trace") or "")[:300]
trace=re.sub(r"\b\d{4,}\b","####",trace)
print("SMOKE", st, intent, "inf", a.get("inference_count"))
print("TRACE", trace)
print("REPLY", re.sub(r"\b\d{4,}\b","####", str(app.get("client_response") or d.get("reply") or d.get("client_response") or "")[:180]))
'
{
  "conversation_id": "$CONV",
  "customer_id": "726588",
  "question": "La tasa de mi préstamo y qué significa"
}
EOF
echo DONE
