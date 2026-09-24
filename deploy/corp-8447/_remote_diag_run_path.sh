#!/bin/bash
set -euo pipefail
APP=/opt/genesis-cognitive-8447/Genesis_v2
PY=$APP/.venv/bin/python
cd "$APP"
export PYTHONPATH=$APP/src
while IFS= read -r line; do
  case "$line" in GENESIS_*|AZURE_*)
    key="${line%%=*}"; val="${line#*=}"; val="${val%\"}"; val="${val#\"}"; export "$key=$val" || true ;;
  esac
done < <(grep -E '^(GENESIS_|AZURE_)' .env | head -100 || true)

"$PY" - <<'PY'
import traceback, asyncio
from genesis_cognitive.brain.azure_plan_turn import run_azure_plan_path, build_turn_envelope
from genesis_cognitive.context.redis_session_store import build_session_store
from genesis_cognitive.context.reactive_store import SessionState
from genesis_cognitive.demo.contract_inspector_app import create_app
from genesis_cognitive.validation.input_validator import InputValidator
from genesis_cognitive.model_input.model_input_builder import ModelInputBuilder
from genesis_cognitive.context.context_assembler import ContextAssembler
from genesis_cognitive.context.adapters.in_memory_conversation_context import InMemoryConversationContextProvider
from genesis_cognitive.context.adapters.in_memory_portfolio_context import InMemoryPortfolioContextProvider
from genesis_cognitive.context.adapters.in_memory_pending_operation_context import InMemoryPendingOperationContextProvider
from genesis_cognitive.context.adapters.in_memory_capability_context import InMemoryCapabilityContextProvider
from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
from unittest.mock import AsyncMock, MagicMock
from genesis_cognitive.errors.cognitive_errors import InvalidModelOutputError
import time

store = build_session_store()
snap = store.get_snapshot("726588")
sess = store.get_session("diag-attr") or SessionState(customer_id="726588", snapshot=snap)
if store.get_session("diag-attr") is None:
    try:
        store.put_session("diag-attr", sess)
    except Exception as e:
        print("put_session", type(e), e)

resolver = MagicMock()
resolver.resolve_full = AsyncMock(side_effect=InvalidModelOutputError())

async def main():
    try:
        out = await run_azure_plan_path(
            question="La tasa de mi préstamo y qué significa",
            safe_question="La tasa de mi préstamo y qué significa",
            session_state=sess,
            history=[],
            customer_snapshot=snap,
            resolver=resolver,
            model_input_builder=ModelInputBuilder(),
            context_assembler=ContextAssembler(
                InMemoryConversationContextProvider(),
                InMemoryPortfolioContextProvider(data={}),
                InMemoryPendingOperationContextProvider(),
                InMemoryCapabilityContextProvider(CapabilityCatalog()),
            ),
            input_validator=InputValidator(),
            conv_id="diag-attr",
            customer_id="726588",
            turn_number=1,
            azure_model="test",
            prompt_version="test",
            request_start=time.perf_counter(),
        )
        print("OK status", out.get("status"), "route", (out.get("decision_trace") or [{}])[0].get("output",{}).get("route_source"))
        print("text", (out.get("client_response") or "")[:160])
    except Exception:
        traceback.print_exc()

asyncio.run(main())
PY
echo DONE
