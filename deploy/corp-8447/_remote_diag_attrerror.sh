#!/bin/bash
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
PY=$APP/.venv/bin/python
cd "$APP"
export PYTHONPATH=$APP/src
# load env selectively
while IFS= read -r line; do
  case "$line" in
    GENESIS_*|AZURE_*)
      key="${line%%=*}"; val="${line#*=}"
      val="${val%\"}"; val="${val#\"}"
      export "$key=$val" || true
      ;;
  esac
done < <(grep -E '^(GENESIS_|AZURE_)' .env | head -80 || true)

"$PY" - <<'PY'
import traceback, asyncio, os
os.environ.setdefault("GENESIS_SEMANTIC_MODE", "azure_plan")
from genesis_cognitive.brain.azure_plan_turn import run_azure_plan_path
from genesis_cognitive.context.redis_session_store import build_session_store
from genesis_cognitive.context.reactive_store import SessionState

# Minimal: invoke interpret repair path only
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.brain.plan_executor import execute_turn_plan

store = build_session_store()
snap = store.get_snapshot("726588")
print("snap", None if snap is None else len(snap.products))
sess = SessionState(customer_id="726588", snapshot=snap)
try:
    plan = interpret_turn_plan("La tasa de mi préstamo y qué significa", sess, snapshot=snap)
    print("plan_tasks", len(plan.tasks), "source", plan.source)
    plan.source = "repair:test"
    pex = execute_turn_plan(plan, snap, "La tasa de mi préstamo y qué significa", session=sess)
    print("pex", pex.status, (pex.text or "")[:120])
except Exception:
    traceback.print_exc()
PY
echo DONE
