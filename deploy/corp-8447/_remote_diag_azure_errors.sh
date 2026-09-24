#!/bin/bash
set -euo pipefail
echo "=== JOURNAL azure_plan ==="
sudo journalctl -u genesis-cognitive-8447 --since "10 min ago" --no-pager | grep -iE 'azure_plan|InvalidModel|PROVIDER|error_stage|turn_plan' | tail -40 || true
echo "=== SAMPLE_TURN ==="
curl -sS -m 90 -X POST http://127.0.0.1:8447/turn \
  -H 'Content-Type: application/json' \
  -d '{"question":"La tasa de mi préstamo y qué significa","conversation_id":"diag-d1-'$(date +%s)'","customer_id":"726588"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); a=d.get('audit') or {}; print('status', (d.get('app_channel') or d).get('status')); print('inf', a.get('inference_count')); print('trace', str(a.get('decision_trace') or d.get('decision_trace'))[:600])"
echo DONE
