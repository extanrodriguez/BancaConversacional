#!/bin/bash
set -euo pipefail
BASE=/opt/genesis-cognitive-8447/Genesis_v2
sed -i 's/\r$//' \
  "$BASE/src/genesis_cognitive/brain/azure_plan_turn.py" \
  "$BASE/src/genesis_cognitive/brain/azure_plan_adapter.py" \
  "$BASE/src/genesis_cognitive/brain/plan_interpreter.py" \
  "$BASE/src/genesis_cognitive/brain/plan_executor.py" \
  "$BASE/src/genesis_cognitive/context/app_channel.py" \
  "$BASE/src/genesis_cognitive/demo/contract_inspector_app.py"
sudo systemctl restart genesis-cognitive-8447
sleep 5
systemctl is-active genesis-cognitive-8447
curl -sS -m 10 http://127.0.0.1:8447/ready/redis | head -c 140; echo
