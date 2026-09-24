# -*- coding: utf-8 -*-
"""Ejecuta POST /turn local con inferencia Azure REAL, contexto sintético y KB local.

No simula respuestas del modelo. Redis remoto queda pendiente (sesión en memoria).
Azure Search remoto: se consulta readiness; retrieval de turno usa KB local.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / "Test_local" / ".env.local")
except ImportError:
    pass

# Dependencias de sesión: memoria (Redis QA inalcanzable). No tocar red/Azure.
os.environ["GENESIS_SESSION_BACKEND"] = "memory"
os.environ.pop("GENESIS_REDIS_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ["GENESIS_REDIS_REQUIRED"] = "0"
os.environ["GENESIS_SEMANTIC_MODE"] = "azure_plan"
os.environ["GENESIS_AZURE_BRAIN"] = "1"
os.environ.setdefault("GENESIS_FAQ_PATH", str(ROOT / "data" / "kb_faq_vf01.json"))
# Conocimiento local (paquete potenciación / azure_mejora)
kb_pkg = ROOT / "works" / "insumos" / "BSC_Potenciacion_Lunes"
if kb_pkg.is_dir():
    os.environ["GENESIS_KB_PACKAGE_ROOT"] = str(kb_pkg)

OUT_DIR = ROOT / "works" / "azure_mejora" / "probe_turn_real"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CUSTOMER = "726588"
PORTFOLIO = ROOT / "data" / "lab_portfolios" / "qa_726588_contract_demo.json"


def _sanitize(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    if not isinstance(obj, str):
        return obj
    s = obj
    s = re.sub(r"(?i)((?:api[_-]?key|token|password|secret|authorization)\"\s*:\s*\")[^\"]*", r"\1***", s)
    return s


def _build_app():
    from agent_framework import Agent
    from agent_framework.openai import OpenAIChatCompletionClient

    from genesis_cognitive.agents.agent_framework_turn_resolver import (
        AgentFrameworkTurnResolver,
    )
    from genesis_cognitive.agents.model_cognitive_result import ModelSemanticProposal
    from genesis_cognitive.agents.semantic_verifier import SemanticVerifier
    from genesis_cognitive.context.adapters.in_memory_capability_context import (
        InMemoryCapabilityContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_conversation_context import (
        InMemoryConversationContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_pending_operation_context import (
        InMemoryPendingOperationContextProvider,
    )
    from genesis_cognitive.context.adapters.in_memory_portfolio_context import (
        InMemoryPortfolioContextProvider,
    )
    from genesis_cognitive.context.context_assembler import ContextAssembler
    from genesis_cognitive.context.context_types import PortfolioContext
    from genesis_cognitive.context.reactive_store import ReactiveSessionStore
    from genesis_cognitive.context.types import PortfolioProduct, PortfolioSnapshot
    from genesis_cognitive.decision.capability_catalog import CapabilityCatalog
    from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
    from genesis_cognitive.demo.contract_inspector_app import create_app
    from genesis_cognitive.enums import FreshnessState, OperationalState
    from genesis_cognitive.model_input.model_input_builder import ModelInputBuilder
    from genesis_cognitive.prompts.prompt_registry import PromptRegistry
    from genesis_cognitive.router.domain_classifier import (
        BusinessClassifier,
        OodClassifier,
        OwnProductClassifier,
    )
    from genesis_cognitive.router.final_response_agent import FinalResponseAgent
    from genesis_cognitive.router.product_classifiers import (
        ProductMutationClassifier,
        ProductReadClassifier,
    )
    from genesis_cognitive.validation.input_validator import InputValidator

    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key or not endpoint:
        raise RuntimeError("AZURE_OPENAI_API_KEY/ENDPOINT required")

    registry = PromptRegistry(ROOT / "prompts", ROOT / "schemas")
    pv = registry.get_current("turn-decision-agent")
    instructions = (
        f"{pv.instructions.role}\n\n"
        "Objectives:\n" + "\n".join(f"- {o}" for o in pv.instructions.objectives) + "\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in pv.instructions.prohibitions)
    )

    client = OpenAIChatCompletionClient(
        model=deployment,
        azure_endpoint=endpoint,
        api_version=api_version,
        api_key=api_key,
    )
    agent: Agent[ModelSemanticProposal] = Agent(
        client, instructions=instructions, name="GenesisIntentEntityAgent"
    )

    verifier_pv = registry.get_current("semantic-verifier-agent")
    verifier_instructions = (
        f"{verifier_pv.instructions.role}\n\n"
        "Objectives:\n" + "\n".join(f"- {o}" for o in verifier_pv.instructions.objectives) + "\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in verifier_pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in verifier_pv.instructions.prohibitions)
    )
    verifier = SemanticVerifier(
        Agent(client, instructions=verifier_instructions, name="GenesisSemanticVerifierAgent")
    )
    resolver = AgentFrameworkTurnResolver(agent, verifier=verifier)  # type: ignore[arg-type]

    def _clf(prompt_id: str, name: str, Cls):
        p = registry.get_current(prompt_id)
        instr = f"{p.instructions.role}\n\nRules:\n" + "\n".join(f"- {r}" for r in p.instructions.rules)
        return Cls(Agent(client, instructions=instr, name=name))

    own_classifier = _clf("domain-own-product", "DomainOwnProduct", OwnProductClassifier)
    business_classifier = _clf("domain-business", "DomainBusiness", BusinessClassifier)
    ood_classifier = _clf("domain-ood", "DomainOod", OodClassifier)
    product_read_clf = _clf("product-read", "ProductRead", ProductReadClassifier)
    product_mutation_clf = _clf("product-mutation", "ProductMutation", ProductMutationClassifier)

    final_pv = registry.get_current("final-response")
    final_instr = (
        f"{final_pv.instructions.role}\n\n"
        "Rules:\n" + "\n".join(f"- {r}" for r in final_pv.instructions.rules) + "\n\n"
        "Prohibitions:\n" + "\n".join(f"- {p}" for p in final_pv.instructions.prohibitions)
    )
    final_response_agent = FinalResponseAgent(
        Agent(client, instructions=final_instr, name="FinalResponse")
    )

    now = datetime.now(tz=UTC)
    portfolio_data = {
        "demo-customer": PortfolioContext(
            snapshot=PortfolioSnapshot(
                version="probe-v1",
                generated_at=now,
                fresh_until=now + timedelta(minutes=30),
                freshness_state=FreshnessState.FRESH,
                products=(
                    PortfolioProduct(
                        product_ref="COR001",
                        product_type="CHECKING",
                        label="Cuenta corriente",
                        alias="cuenta principal",
                        currency="DOP",
                        operational_state=OperationalState.ACTIVE,
                        recent_balance=Decimal("12500.75"),
                        known_reserved_amount=Decimal("500.00"),
                        balance_as_of=now,
                    ),
                ),
            )
        )
    }
    store = ReactiveSessionStore()
    store.backend_name = "memory"  # type: ignore[attr-defined]

    app = create_app(
        resolver=resolver,
        gate=SemanticContractGate(),
        input_validator=InputValidator(),
        context_assembler=ContextAssembler(
            InMemoryConversationContextProvider(),
            InMemoryPortfolioContextProvider(data=portfolio_data),
            InMemoryPendingOperationContextProvider(),
            InMemoryCapabilityContextProvider(CapabilityCatalog()),
        ),
        model_input_builder=ModelInputBuilder(),
        azure_model=deployment,
        prompt_version=pv.prompt_version,
        db_path=None,
        session_store=store,
        domain_classifiers=(own_classifier, business_classifier, ood_classifier),
        product_classifiers=(product_read_clf, product_mutation_clf),
        final_response_agent=final_response_agent,
    )
    return app, deployment, endpoint


def _extract(data: dict) -> dict:
    app = data.get("app_channel") if isinstance(data.get("app_channel"), dict) else {}
    audit = data.get("audit") if isinstance(data.get("audit"), dict) else {}
    trace = audit.get("decision_trace") or data.get("decision_trace") or []
    return {
        "status": app.get("status") or data.get("status"),
        "intent_id": app.get("intent_id") or data.get("intent_id"),
        "reply": (app.get("message") or data.get("reply") or data.get("message") or "")[:500],
        "brain_source": audit.get("brain_source") or data.get("brain_source"),
        "inference_count": audit.get("inference_count") or data.get("inference_count"),
        "decision_trace_head": (trace[0] if isinstance(trace, list) and trace else None),
        "provider": audit.get("provider") or data.get("provider"),
        "deployment": audit.get("deployment") or data.get("deployment"),
        "audit_keys": sorted(audit.keys()) if audit else [],
    }


def main() -> int:
    from fastapi.testclient import TestClient

    print("Building app with REAL Azure OpenAI…")
    app, deployment, endpoint = _build_app()
    print("deployment:", deployment)
    print("endpoint host:", endpoint.split("//")[-1][:48])

    envelope = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    context = {"data": envelope}  # products at top level → orchestrator shape
    conv = f"probe-real-{uuid.uuid4().hex[:12]}"

    questions = [
        # Paráfrasis abierta → debe invocar resolve_full (modelo real), no shortcut
        "Oye, se me vence algo pronto? Dime si tengo que pagar algún préstamo o tarjeta en estos días y cuánto.",
        # Conocimiento local / institucional
        "Qué significa el saldo disponible en una cuenta de ahorros?",
    ]

    results: dict = {
        "mode": {
            "GENESIS_SEMANTIC_MODE": os.environ.get("GENESIS_SEMANTIC_MODE"),
            "GENESIS_AZURE_BRAIN": os.environ.get("GENESIS_AZURE_BRAIN"),
            "GENESIS_SESSION_BACKEND": os.environ.get("GENESIS_SESSION_BACKEND"),
            "GENESIS_KB_PACKAGE_ROOT": os.environ.get("GENESIS_KB_PACKAGE_ROOT"),
            "deployment": deployment,
            "endpoint_host": endpoint.split("//")[-1],
            "portfolio": str(PORTFOLIO.name),
            "customer_id": CUSTOMER,
            "conversation_id": conv,
            "context_source": "lab_synthetic",
            "session_store": "memory_SIMULATED",
            "redis_qa": "UNREACHABLE_PENDING",
            "azure_search_remote": "REAL_REACHABLE_but_turn_uses_local_kb",
            "interpretation": "REAL_AZURE_MODEL",
        },
        "turns": [],
    }

    with TestClient(app, raise_server_exceptions=True) as client:
        t0 = time.perf_counter()
        r0 = client.post(
            "/turn",
            json={
                "question": None,
                "customer_id": CUSTOMER,
                "conversation_id": conv,
                "context_info": True,
                "context_op": "load",
                "context": context,
            },
        )
        load_ms = int((time.perf_counter() - t0) * 1000)
        load_body = r0.json() if r0.headers.get("content-type", "").startswith("application/json") else {"raw": r0.text[:300]}
        results["context_load"] = {
            "http": r0.status_code,
            "ms": load_ms,
            "status": load_body.get("status") if isinstance(load_body, dict) else None,
        }
        print("context_load", r0.status_code, load_body.get("status") if isinstance(load_body, dict) else load_body)
        if r0.status_code != 200:
            (OUT_DIR / "turn_real_result.json").write_text(
                json.dumps(_sanitize(results), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return 1

        for q in questions:
            print("--- /turn ---", q[:80])
            t1 = time.perf_counter()
            try:
                resp = client.post(
                    "/turn",
                    json={
                        "question": q,
                        "customer_id": CUSTOMER,
                        "conversation_id": conv,
                        "context_info": False,
                    },
                    timeout=180.0,
                )
                ms = int((time.perf_counter() - t1) * 1000)
                body = resp.json()
                extracted = _extract(body)
                entry = {
                    "question": q,
                    "http": resp.status_code,
                    "client_ms": ms,
                    "extracted": extracted,
                    "simulated_reply": False,
                    "model_path": "azure_plan.resolve_full" if extracted.get("inference_count") else "unknown",
                }
                print(
                    "http",
                    resp.status_code,
                    "ms",
                    ms,
                    "brain",
                    extracted.get("brain_source"),
                    "inf",
                    extracted.get("inference_count"),
                    "intent",
                    extracted.get("intent_id"),
                )
                print("reply:", (extracted.get("reply") or "")[:180])
            except Exception as exc:
                entry = {
                    "question": q,
                    "http": 0,
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:400],
                    "simulated_reply": False,
                }
                print("FAIL", type(exc).__name__, str(exc)[:300])
            results["turns"].append(entry)

    out = OUT_DIR / "turn_real_result.json"
    out.write_text(json.dumps(_sanitize(results), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)

    # Éxito si al menos un turno 200 con inference_count>0 o brain_source real
    ok = False
    for t in results["turns"]:
        ex = t.get("extracted") or {}
        inf = ex.get("inference_count")
        src = str(ex.get("brain_source") or "")
        if t.get("http") == 200 and (
            (isinstance(inf, int) and inf > 0)
            or src in ("resolve_full", "azure_plan", "azure_structured")
            or "azure" in src.lower()
            or "resolve" in src.lower()
        ):
            ok = True
            break
        # También OK si hay reply real y no error
        if t.get("http") == 200 and (ex.get("reply") or "").strip():
            ok = True
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
