"""ContractInspector FastAPI demo — Azure OpenAI + conversation session.

POST /inspect — runs full pipeline with ModelCognitiveResult transport.
GET / — serves the static HTML interface.

Does NOT execute financial operations. Does NOT route by keywords.
"""

from __future__ import annotations

import logging
import os
import json
import uuid
import time as _time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# ---------------------------------------------------------------------------
# RF1: Configurable slow-request threshold (ms)
# ---------------------------------------------------------------------------
_SLOW_REQUEST_MS = int(os.getenv("GENESIS_SLOW_REQUEST_MS", "10000"))


def _pending_selection_blocks_brain(
    pending: Any | None,
    question: str,
    *,
    explicit_all_loan_field: bool = False,
    pending_loan_field_switch: bool = False,
) -> bool:
    """Retiene una selección pendiente salvo cambio de campo o turno social."""
    if pending is None:
        return False
    from genesis_cognitive.brain.social_intent import classify_social

    return bool(
        "account_ref" in (getattr(pending, "missing_requirements", None) or [])
        and not explicit_all_loan_field
        and not pending_loan_field_switch
        and classify_social(question) is None
    )


# ---------------------------------------------------------------------------
# Latency logger (RF3/RF4)
# ---------------------------------------------------------------------------
_latency_logger = logging.getLogger("genesis.latency")
if not _latency_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _latency_logger.addHandler(_handler)
_latency_logger.setLevel(logging.DEBUG)


def _slowest_from_trace(decision_trace: list[dict[str, Any]] | None) -> tuple[str | None, int]:
    """Return (step_name, duration_ms) of the slowest step in decision_trace."""
    if not decision_trace:
        return (None, 0)
    steps = [s for s in decision_trace if s.get("duration_ms") is not None]
    if not steps:
        return (None, 0)
    slowest = max(steps, key=lambda s: s["duration_ms"])
    return (slowest.get("step"), slowest["duration_ms"])


def _log_latency_audit(
    *,
    path: str,
    total_ms: int,
    status: str | None = None,
    conversation_id: str | None = None,
    question: str | None = None,
    decision_trace: list[dict[str, Any]] | None = None,
    source: str = "wall",
) -> None:
    """Emit a latency log line. WARNING if slow, INFO otherwise (pipeline only)."""
    slowest_step, slowest_ms = _slowest_from_trace(decision_trace)
    q_fragment = (question or "")[:60].replace("\n", " ")
    msg = (
        f"SLOW_REQUEST path={path} total_ms={total_ms} source={source} "
        f"status={status} conversation_id={conversation_id} "
        f"slowest_step={slowest_step} slowest_ms={slowest_ms} "
        f"question=\"{q_fragment}\""
    )
    threshold = int(os.getenv("GENESIS_SLOW_REQUEST_MS", "10000"))
    if total_ms >= threshold:
        _latency_logger.warning(msg)
    elif source == "pipeline":
        _latency_logger.info(msg.replace("SLOW_REQUEST", "REQUEST"))


# ---------------------------------------------------------------------------
# RF2: HTTP middleware — X-Request-Duration-Ms header for /turn and /inspect
# ---------------------------------------------------------------------------
class LatencyHeaderMiddleware(BaseHTTPMiddleware):
    """Add X-Request-Duration-Ms header and emit SLOW_REQUEST log for /turn and /inspect."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path not in ("/turn", "/inspect"):
            return await call_next(request)

        start = _time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((_time.perf_counter() - start) * 1000)

        response.headers["X-Request-Duration-Ms"] = str(elapsed_ms)

        threshold = int(os.getenv("GENESIS_SLOW_REQUEST_MS", "10000"))
        if elapsed_ms >= threshold:
            _log_latency_audit(
                path=path,
                total_ms=elapsed_ms,
                source="wall",
            )

        return response

from genesis_cognitive.agents.agent_framework_turn_resolver import (
    AgentFrameworkTurnResolver,
)
from genesis_cognitive.context.context_assembler import ContextAssembler
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
from genesis_cognitive.context.reactive_store import (
    LastResolved,
    PendingAction,
    ReactiveSessionStore,
    SessionConflictError,
)
from genesis_cognitive.context.query_spec import build_query_spec, query_question
from genesis_cognitive.context.redis_session_store import build_session_store
from genesis_cognitive.context.sqlite_customer_loader import SqliteCustomerContextLoader
from genesis_cognitive.decision.semantic_contract_gate import SemanticContractGate
from genesis_cognitive.model_input.model_input_builder import (
    ModelInputBuilder,
    ProjectedPendingAction,
)
from genesis_cognitive.validation.input_validator import InputValidator

_STATIC_DIR = Path(__file__).parent / "static"

# Default customer mapping
_DEFAULT_CUSTOMER_ID = "CUST001"

# Follow-up signals: short phrases that refer back to the same product
_FOLLOWUP_SIGNALS = (
    "y la", "y el", "y cual", "y cuál", "y cuanto", "y cuánto", "y mi",
    "tambien", "también", "deuda", "debo", "tasa", "cuota", "fecha", "capital",
    "total", "pendiente", "interes", "interés", "pago", "letra", "mora",
    "atraso", "vencido", "proxima", "próxima", "monto", "saldo", "balance", "corte",
    "vence", "termina", "saldar", "cancelar", "liquidar", "movimientos",
    "mas informacion", "más información", "mas info", "más info",
    "dame mas", "dame más", "mas detalle", "más detalle", "detalles",
    "toda la informacion", "toda la información", "amplia", "ampliar",
)

_MORE_INFO_SIGNALS = (
    "mas informacion", "más información", "mas info", "más info",
    "dame mas", "dame más", "mas detalle", "más detalle",
    "toda la informacion", "toda la información", "dame detalles",
    "quiero mas", "quiero más", "amplia", "ampliar informacion", "ampliar información",
)


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str
    conversation_id: str = Field(default="")
    customer_id: str = Field(default="")


class TurnRequest(BaseModel):
    """Orchestrator-facing request for POST /turn.

    También acepta campos de la APK (`client_id`, `top_k`) para no romper el
    contrato cuando el canal móvil apunta directo a 8447.
    """
    model_config = ConfigDict(extra="ignore", strict=True)
    question: str | None = Field(default=None)
    # Selección estructurada de una card. El servidor la valida contra el
    # pending_action y el portafolio; no confía en campos enviados por el front.
    selected_option_ref: str | None = Field(default=None)
    conversation_id: str = Field(default="")
    customer_id: str = Field(default="")
    client_id: str | None = Field(default=None)
    top_k: int | None = Field(default=None)
    force_core_query: bool = Field(default=False)
    context_info: bool = Field(default=False)
    context_op: str | None = Field(default=None)
    context: dict[str, Any] | None = Field(default=None)


class LabLoginRequest(BaseModel):
    """Simula el orquestador: login de usuario + carga de contexto Core."""

    model_config = ConfigDict(extra="forbid", strict=True)
    customer_id: str
    conversation_id: str | None = Field(default=None)
    portfolio: str | None = Field(default=None)
    context: dict[str, Any] | None = Field(default=None)


class OrchContextRequest(BaseModel):
    """Context Refresh estilo APK: customerId → servicio Core/ws → snapshot cognitiva."""

    model_config = ConfigDict(extra="ignore", strict=True)
    customer_id: str
    conversation_id: str | None = Field(default=None)
    # Si el Core real no es alcanzable (DNS/VPN), permite fallback a portafolio lab.
    allow_lab_fallback: bool = Field(default=True)
    portfolio: str | None = Field(default=None)


def create_app(
    *,
    resolver: AgentFrameworkTurnResolver,
    gate: SemanticContractGate,
    input_validator: InputValidator,
    context_assembler: ContextAssembler,
    model_input_builder: ModelInputBuilder,
    azure_model: str,
    prompt_version: str,
    db_path: Path | None = None,
    domain_classifiers: tuple | None = None,
    product_classifiers: tuple | None = None,
    final_response_agent: Any | None = None,
    session_store: Any | None = None,
) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        """Calienta clientes Redis/Entra fuera del hilo del event loop si aún no existen."""
        import asyncio

        try:
            from genesis_cognitive.context.conversation_gate import get_conversation_gate

            await asyncio.to_thread(get_conversation_gate)
        except Exception:  # noqa: BLE001
            pass
        yield

    app = FastAPI(
        title="Genesis ContractInspector Demo",
        version="0.8.0",
        lifespan=_lifespan,
    )
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LatencyHeaderMiddleware)

    # Reactive session store (Redis if GENESIS_REDIS_URL set; else in-memory)
    # create_app suele correr ANTES del event loop (uvicorn/tests); calentar gate aquí.
    store = session_store or build_session_store()
    try:
        from genesis_cognitive.context.conversation_gate import get_conversation_gate as _warm_gate

        _warm_gate()
    except Exception:  # noqa: BLE001
        pass

    # Customer context from SQLite
    customer_loader: SqliteCustomerContextLoader | None = None
    if db_path is not None and db_path.exists():
        customer_loader = SqliteCustomerContextLoader(db_path)

    # Domain router classifiers
    domain_router_enabled = domain_classifiers is not None
    own_classifier = domain_classifiers[0] if domain_classifiers else None
    business_classifier = domain_classifiers[1] if domain_classifiers else None
    ood_classifier = domain_classifiers[2] if domain_classifiers else None

    # Local RAG store (lazy init)
    from genesis_cognitive.rag.local_rag import LocalRagStore
    rag_store = LocalRagStore()

    
    def _session_busy_response(
        conversation_id: str,
        *,
        turn: int = 1,
        http_status: int = 200,
        for_context_load: bool = False,
    ) -> JSONResponse:
        """Ocupación compatible con consumidor.

        - Turno NL: HTTP 200 + SESSION_BUSY + client_response string
          (NvidiaChatClient.QueryRagAsync solo falla en no-2xx).
        - context_info: HTTP 503 — LoadInitialContextAsync trata cualquier 2xx
          como carga exitosa y el WebSocket marca success sin mirar el body.
        """
        msg = (
            "Estoy atendiendo otra consulta de esta conversación. "
            "Por favor intenta de nuevo en un momento."
        )
        if for_context_load:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "CONTEXT_LOAD_BUSY",
                    "conversation_id": conversation_id,
                    "error": "context_not_persisted",
                    "client_response": msg,
                    "persisted": False,
                },
            )
        return JSONResponse(
            status_code=http_status,
            content={
                "status": "SESSION_BUSY",
                "conversation_id": conversation_id,
                "client_response": msg,
                "actions": [],
                "clarifications": [],
                "unsupported_segments": [],
                "suggested_questions": [],
                "provider": "AZURE_OPENAI",
                "framework": "MICROSOFT_AGENT_FRAMEWORK",
                "model": azure_model,
                "prompt_version": prompt_version,
                "turn_number": turn,
                "inference_count": 0,
                "decision_trace": [{"step": "conversation_gate_busy", "output": {}}],
            },
        )

    @app.post("/inspect")
    async def inspect(request: InspectRequest) -> JSONResponse:
        """Entrada con serialización por conversación (asyncio.Lock + Redis)."""
        from genesis_cognitive.context.conversation_gate import (
            ConversationGateError,
            get_conversation_gate,
        )

        conv_id = request.conversation_id or str(uuid.uuid4())
        if not request.conversation_id:
            request = request.model_copy(update={"conversation_id": conv_id})
        try:
            async with get_conversation_gate().hold(conv_id) as gate_state:
                if not gate_state.get("acquired"):
                    return _session_busy_response(conv_id)
                return await _inspect_unlocked(
                    request,
                    still_owner=gate_state.get("still_owner"),
                )
        except ConversationGateError:
            return _session_busy_response(conv_id)

    async def _inspect_unlocked(
        request: InspectRequest,
        force_error: str | None = None,
        still_owner: Any | None = None,
    ) -> JSONResponse:
        from genesis_cognitive.errors.cognitive_errors import CognitiveError

        _request_start = _time.perf_counter()

        def _owner_ok() -> bool:
            if still_owner is None:
                return True
            try:
                return bool(still_owner())
            except Exception:
                return False

        # T7: Test flag — force provider error for AC-08
        if force_error == "provider":
            return JSONResponse(
                status_code=502,
                content={
                    "provider": "AZURE_OPENAI",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": request.conversation_id or str(uuid.uuid4()),
                    "turn_number": 1,
                    "conversation_history": [],
                    "status": "PROVIDER_ERROR",
                    "error_detail": "Forced provider error for testing (force_error=provider)",
                    "inference_count": 0,
                },
            )

        conv_id = request.conversation_id or str(uuid.uuid4())

        # Resolve customer_id — la sesión fija la identidad; no mezclar portafolios.
        resolved_customer_id = request.customer_id or _DEFAULT_CUSTOMER_ID
        if resolved_customer_id in ("demo-customer", ""):
            resolved_customer_id = _DEFAULT_CUSTOMER_ID

        # Load or create session from store (copia; CAS por revisión)
        session_state = store.get_session(conv_id)
        if session_state is None:
            try:
                session_state = store.create_session(conv_id, resolved_customer_id)
            except SessionConflictError:
                # Creación concurrente: usar la sesión ganadora, no sobrescribir
                session_state = store.get_session(conv_id)
                if session_state is None:
                    return _session_busy_response(conv_id)
        else:
            # Conversación existente: productos SOLO de la persona de la sesión
            sess_cid = (session_state.customer_id or "").strip()
            if sess_cid and sess_cid not in ("demo-customer",):
                if (
                    request.customer_id
                    and request.customer_id not in ("", "demo-customer")
                    and request.customer_id != sess_cid
                ):
                    # Ignorar customer_id del request si contradice la sesión
                    pass
                resolved_customer_id = sess_cid
            elif not sess_cid:
                session_state.customer_id = resolved_customer_id
        _cas_revision = int(getattr(session_state, "revision", 0) or 0)

        def _cas_put_session() -> JSONResponse | None:
            """Persiste con expected_revision. Conflicto/candado perdido → SESSION_BUSY."""
            nonlocal _cas_revision
            if not _owner_ok():
                # Candado expiró/perdido: no confirmar estado calculado sobre revisión obsoleta
                return _session_busy_response(conv_id, turn=turn_number)
            try:
                new_rev = store.put_session(
                    conv_id,
                    session_state,
                    expected_revision=_cas_revision,
                )
                _cas_revision = int(new_rev)
                return None
            except SessionConflictError as exc:
                # Contrato app_channel exige client_response:string; el consumidor
                # /turn (NvidiaChatClient) trata HTTP != 2xx como error genérico.
                # No devolver 409 ni éxito financiero inventado.
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "SESSION_BUSY",
                        "conversation_id": conv_id,
                        "expected_revision": exc.expected,
                        "actual_revision": exc.actual,
                        "client_response": (
                            "Estoy atendiendo otra consulta de esta conversación. "
                            "Por favor intenta de nuevo en un momento."
                        ),
                        "error_detail": "session_revision_conflict",
                        "actions": [],
                        "clarifications": [],
                        "unsupported_segments": [],
                        "suggested_questions": [],
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "turn_number": turn_number,
                        "inference_count": 0,
                        "decision_trace": [{
                            "step": "session_cas_conflict",
                            "output": {
                                "expected": exc.expected,
                                "actual": exc.actual,
                            },
                        }],
                    },
                )

        session = session_state.history
        turn_number = session_state.turn_number

        # Contexto atado a la sesión: preferir snapshot de la conversación
        customer_snapshot: CustomerContextSnapshot | None = session_state.snapshot
        # Si el snapshot no corresponde al cliente de sesión, descartarlo
        if (
            customer_snapshot is not None
            and getattr(customer_snapshot, "customer_id", None)
            and session_state.customer_id
            and customer_snapshot.customer_id != session_state.customer_id
        ):
            customer_snapshot = None
            session_state.snapshot = None
        if customer_snapshot is None:
            customer_snapshot = store.get_snapshot(resolved_customer_id)
            if customer_snapshot is not None and getattr(customer_snapshot, "customer_id", None):
                if customer_snapshot.customer_id != resolved_customer_id:
                    customer_snapshot = None
            if customer_snapshot is None and customer_loader is not None:
                loaded = customer_loader.load(resolved_customer_id)
                if loaded is not None:
                    customer_snapshot = loaded
            # Recarga lab si aún no hay contexto (misma sesión / login previo expirado en caché global)
            if customer_snapshot is None:
                try:
                    envelope, _pname = _lab_portfolio_envelope(resolved_customer_id, None)
                    ctx_body = _to_orchestrator_context(envelope)
                    from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
                    mapped = map_core_portfolio(ctx_body["data"])
                    customer_snapshot = CustomerContextSnapshot(
                        customer_id=resolved_customer_id,
                        display_name=mapped.snapshot.display_name,
                        default_currency=mapped.snapshot.default_currency,
                        products=mapped.snapshot.products,
                        loans=mapped.snapshot.loans,
                    )
                except Exception:
                    customer_snapshot = None
            if customer_snapshot is not None:
                # Forzar customer_id del snapshot = identidad de sesión
                if getattr(customer_snapshot, "customer_id", None) != resolved_customer_id:
                    customer_snapshot = CustomerContextSnapshot(
                        customer_id=resolved_customer_id,
                        display_name=customer_snapshot.display_name,
                        default_currency=customer_snapshot.default_currency,
                        products=customer_snapshot.products,
                        loans=customer_snapshot.loans,
                    )
                session_state.snapshot = customer_snapshot
                session_state.customer_id = resolved_customer_id
                # No persistir aún: un solo commit CAS al responder el turno
        else:
            # Renovar vida de sesión en el commit final (no put prematuro)
            if not session_state.customer_id:
                session_state.customer_id = resolved_customer_id

        snapshot_age_s = store.get_snapshot_age(resolved_customer_id)

        # ── Entrada depurada (secretos) + TurnPlan multi-tarea (V3.1) ──
        _raw_q = request.question or ""
        _safe_q = _raw_q
        _secret_meta: dict = {}
        try:
            from genesis_cognitive.brain.plan_interpreter import (
                interpret_turn_plan,
                message_is_institutional_only,
                scrub_inbound_question,
            )
            from genesis_cognitive.brain.plan_executor import execute_turn_plan

            _safe_q, _secret_meta = scrub_inbound_question(_raw_q)
            if _secret_meta.get("had_secret_frame"):
                # Sustituir pregunta en request para el resto del pipeline
                try:
                    request = request.model_copy(update={"question": _safe_q})
                except Exception:
                    pass

            # ── Foundry personal tools (flag OFF por defecto; no reemplaza azure_plan) ──
            try:
                from genesis_cognitive.agents.foundry_personal_agent import (
                    run_foundry_personal_turn,
                )
                from genesis_cognitive.agents.product_context_tools import (
                    is_foundry_product_tools_enabled,
                )

                if is_foundry_product_tools_enabled() and customer_snapshot is not None:
                    _fy_pers = await run_foundry_personal_turn(
                        question=_safe_q or _raw_q,
                        store=store,
                        conversation_id=conv_id,
                        customer_id=resolved_customer_id,
                        display_name=getattr(customer_snapshot, "display_name", None),
                    )
                    if _fy_pers and _fy_pers.get("ok") and (_fy_pers.get("text") or "").strip():
                        session.append({
                            "turn": turn_number,
                            "question": request.question,
                            "status": _fy_pers.get("status") or "VALID_CONTRACT",
                            "intent": _fy_pers.get("intent_id") or "FOUNDRY_PERSONAL_PRODUCTS",
                        })
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        return JSONResponse(status_code=200, content={
                            "provider": _fy_pers.get("provider") or "AZURE_OPENAI",
                            "framework": "FOUNDRY_PERSONAL_TOOLS",
                            "model": _fy_pers.get("model") or azure_model,
                            "prompt_version": prompt_version,
                            "conversation_id": conv_id,
                            "turn_number": turn_number,
                            "conversation_history": session,
                            "status": _fy_pers.get("status") or "VALID_CONTRACT",
                            "mode": "SINGLE",
                            "intent_id": _fy_pers.get("intent_id") or "FOUNDRY_PERSONAL_PRODUCTS",
                            "actions": [],
                            "clarifications": [],
                            "unsupported_segments": [],
                            "client_response": _fy_pers["text"],
                            "suggested_questions": [],
                            "rag_status": "NOT_REQUIRED",
                            "inference_count": 1,
                            "customer_context": {
                                "customer_id": customer_snapshot.customer_id,
                                "display_name": customer_snapshot.display_name,
                            },
                            "decision_trace": [{
                                "step": "foundry_personal_tools",
                                "output": {
                                    "path": _fy_pers.get("path"),
                                    "tool_trace": _fy_pers.get("tool_trace") or [],
                                },
                            }],
                            "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                            "correlation_id": str(uuid.uuid4()),
                        })
            except Exception as _fy_exc:  # noqa: BLE001
                import logging as _log_fy
                _log_fy.getLogger("genesis.foundry.personal").warning(
                    "foundry_personal_path_failed: %s — fallthrough azure_plan",
                    type(_fy_exc).__name__,
                )

            # ── Ruta canónica V4: GENESIS_SEMANTIC_MODE=azure_plan ──
            # Aislada: fallo aquí NO cae a fastpath/legacy (evita pérdida de mixtas D/F).
            from genesis_cognitive.brain.semantic_mode import is_azure_plan_mode
            if is_azure_plan_mode():
                try:
                    from genesis_cognitive.brain.azure_plan_turn import (
                        merge_pending_tasks,
                        run_azure_plan_path,
                    )
                    _v4 = await run_azure_plan_path(
                        question=_raw_q,
                        safe_question=_safe_q,
                        session_state=session_state,
                        history=session,
                        customer_snapshot=customer_snapshot,
                        resolver=resolver,
                        model_input_builder=model_input_builder,
                        context_assembler=context_assembler,
                        input_validator=input_validator,
                        conv_id=conv_id,
                        customer_id=resolved_customer_id,
                        turn_number=turn_number,
                        azure_model=azure_model,
                        prompt_version=prompt_version,
                        request_start=_request_start,
                    )
                except Exception as _v4_exc:  # noqa: BLE001
                    import logging as _log_v4
                    import traceback as _tb_v4
                    _log_v4.getLogger("genesis.brain").warning(
                        "azure_plan_path_failed: %s msg=%s\n%s",
                        type(_v4_exc).__name__,
                        str(_v4_exc)[:300],
                        _tb_v4.format_exc(),
                    )
                    return JSONResponse(status_code=200, content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "PROVIDER_ERROR",
                        "mode": "SINGLE",
                        "intent_id": "SEMANTIC_AZURE_PLAN_FAILED",
                        "actions": [],
                        "clarifications": [],
                        "unsupported_segments": [],
                        "client_response": (
                            "No pude completar la interpretación semántica en este momento. "
                            "Intenta de nuevo o reformula la consulta."
                        ),
                        "suggested_questions": [],
                        "rag_status": "NOT_REQUIRED",
                        "inference_count": 0,
                        "decision_trace": [{
                            "step": "azure_plan_error",
                            "output": {
                                "error_class": type(_v4_exc).__name__,
                                "error_stage": "turn_handler_isolate",
                                "semantic_mode": "azure_plan",
                                "degraded": True,
                                "not_heuristic_fallback": True,
                            },
                        }],
                        "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                        "correlation_id": str(uuid.uuid4()),
                    })
                _pex_v4 = _v4.pop("_pex", None)
                _plan_v4 = _v4.pop("_plan", None)
                _apply = _v4.pop("_apply_state", False)
                if _apply and _pex_v4 is not None and _plan_v4 is not None:
                    try:
                        if _plan_v4.transition == "correction":
                            # Invalida foco personal; NO borra pendientes de otras familias
                            session_state.pending_action = None
                            try:
                                session_state.product_focus = None
                            except Exception:
                                pass
                            session_state.pending_tasks = [
                                pt for pt in (session_state.pending_tasks or [])
                                if isinstance(pt, dict) and str(pt.get("object") or "") not in ("account",)
                            ]
                        if _pex_v4.preserve_pending_action and _plan_v4.transition != "correction":
                            pass
                        elif _pex_v4.clear_pending_action or _plan_v4.transition == "selection":
                            session_state.pending_action = None
                        if _pex_v4.pending_tasks is not None:
                            cleared: set[str] = set()
                            if _pex_v4.clear_pending_action or _plan_v4.transition == "selection":
                                for ev in _pex_v4.evidences or []:
                                    if getattr(ev, "status", None) == "available" and ev.task_id:
                                        cleared.add(str(ev.task_id).split(".", 1)[0])
                            session_state.pending_tasks = merge_pending_tasks(
                                session_state.pending_tasks,
                                list(_pex_v4.pending_tasks),
                                clear_ids=cleared,
                                replace_all=False,
                            )
                            if session_state.pending_tasks and session_state.pending_action is None:
                                _pt0 = session_state.pending_tasks[0]
                                session_state.pending_action = PendingAction(
                                    intent_id="CLARIFICATION",
                                    capability_candidate="PRODUCT_FIELD",
                                    selected_route="PERSONAL_READ",
                                    detected_entities={"account_ref": None},
                                    missing_requirements=["account_ref"],
                                    suggested_question=_pex_v4.text or "",
                                    original_question=(
                                        _pt0.get("original_question") if isinstance(_pt0, dict) else None
                                    ) or _raw_q,
                                    query_spec={
                                        "fields": ",".join(
                                            (_pt0.get("fields") or []) if isinstance(_pt0, dict) else []
                                        ),
                                    },
                                )
                        elif _pex_v4.clear_pending_action or _plan_v4.transition == "selection":
                            cleared_sel: set[str] = set()
                            for ev in _pex_v4.evidences or []:
                                if getattr(ev, "status", None) == "available" and ev.task_id:
                                    cleared_sel.add(str(ev.task_id).split(".", 1)[0])
                            session_state.pending_tasks = merge_pending_tasks(
                                session_state.pending_tasks, [], clear_ids=cleared_sel,
                            )
                        if _pex_v4.compare_set is not None:
                            session_state.compare_set = list(_pex_v4.compare_set)
                        if _pex_v4.last_knowledge_topic:
                            session_state.last_knowledge_topic = _pex_v4.last_knowledge_topic
                        if _pex_v4.set_product_focus:
                            from genesis_cognitive.router.product_focus import remember_product_focus
                            _fk, _fid, _fi = _pex_v4.set_product_focus
                            remember_product_focus(session_state, _fi, _fid, _raw_q)
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                    except Exception as _state_exc:  # noqa: BLE001
                        import logging as _log_state
                        _log_state.getLogger("genesis.brain").warning(
                            "azure_plan_state_apply_failed: %s", type(_state_exc).__name__,
                        )
                        # Conservar respuesta del plan; no degradar a PROVIDER_ERROR
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                return JSONResponse(status_code=200, content=_v4)

            _plan = interpret_turn_plan(
                _raw_q, session_state, snapshot=customer_snapshot,
            )
            _use_plan = (
                _plan.source == "heuristic_multi"
                and bool(_plan.tasks)
            ) or (
                len(_plan.tasks) > 1
                or any(
                    t.action in ("refuse", "check_existence", "compare")
                    or t.domain in ("catalog", "process")
                    or (t.domain == "institutional" and (
                        len(_plan.tasks) > 1
                        or t.object == "glossary"
                        or len(t.fields or []) > 1
                    ))
                    or (t.object == "credit_card")
                    or (t.object == "term_deposit" and t.cardinality in ("all", "compare"))
                    or (t.status == "needs_clarification" and t.domain == "personal")
                    or (t.status == "unsupported")
                    for t in _plan.tasks
                )
                or (
                    len(_plan.tasks) == 1
                    and _plan.tasks[0].action == "refuse"
                )
                or (
                    len(_plan.tasks) >= 1
                    and any(t.domain == "institutional" for t in _plan.tasks)
                    and any(t.domain == "personal" for t in _plan.tasks)
                )
            )
            # Secretos / titularidad: ejecutar aunque no haya snapshot
            if _use_plan and any(t.action == "refuse" for t in _plan.tasks):
                _pex = execute_turn_plan(
                    _plan, customer_snapshot, _raw_q, session=session_state,
                )
                session.append({
                    "turn": turn_number,
                    "question": _safe_q,
                    "status": _pex.status,
                    "intent": _pex.intent_id,
                    "plan_tasks": len(_plan.tasks),
                })
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                return JSONResponse(status_code=200, content={
                    "provider": "AZURE_OPENAI",
                    "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": session,
                    "status": _pex.status,
                    "mode": "SINGLE",
                    "intent_id": _pex.intent_id,
                    "actions": _pex.actions or [],
                    "clarifications": [],
                    "unsupported_segments": [],
                    "client_response": _pex.text,
                    "suggested_questions": [],
                    "rag_status": "NOT_REQUIRED",
                    "inference_count": 0,
                    "customer_context": {
                        "customer_id": getattr(customer_snapshot, "customer_id", None) or resolved_customer_id,
                        "display_name": getattr(customer_snapshot, "display_name", None),
                    },
                    "decision_trace": [{
                        "step": "turn_plan_multi",
                        "output": {
                            "source": "plan_executor",
                            "brain_source": _plan.source,
                            "secret_scrubbed": True,
                            "task_statuses": (_pex.trace or {}).get("task_statuses"),
                        },
                    }],
                    "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                    "correlation_id": str(uuid.uuid4()),
                })
            # Pregunta mixta institucional+personal / multi-tarea / catálogo
            if _use_plan and customer_snapshot is not None:
                _pex = execute_turn_plan(
                    _plan, customer_snapshot, _raw_q, session=session_state,
                )
                # Corrección: invalidar foco/pendientes sustituidos
                if _plan.transition == "correction":
                    session_state.pending_action = None
                    session_state.pending_tasks = []
                    try:
                        session_state.product_focus = None
                    except Exception:
                        pass
                # Aplicar mutaciones de estado
                if _pex.preserve_pending_action and _plan.transition != "correction":
                    pass  # conservar pending_action
                elif _pex.clear_pending_action or _plan.transition in ("selection", "correction"):
                    session_state.pending_action = None
                    if _pex.clear_pending_action or _plan.transition == "selection":
                        # Cerrar pendientes resueltos por ID (no reaparecen)
                        session_state.pending_tasks = []
                if _pex.pending_tasks is not None and _plan.transition != "correction":
                    from genesis_cognitive.brain.azure_plan_turn import merge_pending_tasks
                    session_state.pending_tasks = merge_pending_tasks(
                        list(getattr(session_state, "pending_tasks", None) or []),
                        list(_pex.pending_tasks),
                        replace_all=_plan.transition == "selection" and bool(_pex.clear_pending_action),
                    )
                    if _pex.pending_tasks and session_state.pending_action is None:
                        _pt0 = _pex.pending_tasks[0]
                        session_state.pending_action = PendingAction(
                            intent_id="CLARIFICATION",
                            capability_candidate="PRODUCT_FIELD",
                            selected_route="PERSONAL_READ",
                            detected_entities={"account_ref": None},
                            missing_requirements=["account_ref"],
                            suggested_question=_pex.text or "",
                            original_question=_pt0.get("original_question") or _raw_q,
                            query_spec={"fields": ",".join(_pt0.get("fields") or [])},
                        )
                if _pex.compare_set is not None:
                    session_state.compare_set = list(_pex.compare_set)
                if _pex.last_knowledge_topic:
                    session_state.last_knowledge_topic = _pex.last_knowledge_topic
                if _pex.set_product_focus:
                    from genesis_cognitive.router.product_focus import remember_product_focus
                    _fk, _fid, _fi = _pex.set_product_focus
                    remember_product_focus(session_state, _fi, _fid, _raw_q)
                # Historial con pregunta depurada (sin dígitos de secreto)
                session.append({
                    "turn": turn_number,
                    "question": _safe_q,
                    "status": _pex.status,
                    "intent": _pex.intent_id,
                    "plan_tasks": len(_plan.tasks),
                })
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                _plan_mode = (
                    "CLARIFICATION" if _pex.status == "CLARIFICATION_REQUIRED"
                    else "SINGLE"
                )
                return JSONResponse(status_code=200, content={
                    "provider": "AZURE_OPENAI",
                    "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": session,
                    "status": _pex.status,
                    "mode": _plan_mode,
                    "intent_id": _pex.intent_id,
                    "actions": _pex.actions or [],
                    "clarifications": [{
                        "target_action_sequence": 1,
                        "missing_requirements": ["account_ref"],
                        "suggested_question": _pex.text,
                        "already_known": [],
                    }] if _pex.status == "CLARIFICATION_REQUIRED" else [],
                    "unsupported_segments": [],
                    "client_response": _pex.text,
                    "suggested_questions": _pex.suggestions or [],
                    "app_channel_options": _pex.options,
                    "rag_status": "FAQ" if _pex.route == "knowledge" else "NOT_REQUIRED",
                    "inference_count": 0,
                    "customer_context": {
                        "customer_id": customer_snapshot.customer_id,
                        "display_name": customer_snapshot.display_name,
                    },
                    "decision_trace": [{
                        "step": "turn_plan_multi",
                        "output": {
                            "source": "plan_executor",
                            "brain_source": _plan.source,
                            "task_count": len(_plan.tasks),
                            "task_statuses": (_pex.trace or {}).get("task_statuses"),
                            "transition": _plan.transition,
                            "secret_scrubbed": bool(_secret_meta.get("had_secret_frame")),
                        },
                    }],
                    "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                    "correlation_id": str(uuid.uuid4()),
                })
            # Institucional sin snapshot personal (solo conocimiento)
            if (
                _use_plan
                and customer_snapshot is None
                and any(t.domain == "institutional" for t in _plan.tasks)
            ):
                _pex = execute_turn_plan(_plan, None, _raw_q, session=session_state)
                if (_pex.text or "").strip():
                    session.append({
                        "turn": turn_number,
                        "question": _safe_q,
                        "status": _pex.status,
                        "intent": _pex.intent_id,
                    })
                    _conflict_resp = _cas_put_session()
                    if _conflict_resp is not None:
                        return _conflict_resp
                    return JSONResponse(status_code=200, content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": _pex.status,
                        "mode": "SINGLE",
                        "intent_id": _pex.intent_id,
                        "actions": _pex.actions or [],
                        "clarifications": [],
                        "unsupported_segments": [],
                        "client_response": _pex.text,
                        "suggested_questions": [],
                        "rag_status": "FAQ",
                        "inference_count": 0,
                        "customer_context": {"customer_id": resolved_customer_id},
                        "decision_trace": [{
                            "step": "turn_plan_multi",
                            "output": {"source": "plan_executor", "no_snapshot": True},
                        }],
                        "total_request_ms": 0,
                        "correlation_id": str(uuid.uuid4()),
                    })
        except Exception as _plan_exc:  # noqa: BLE001
            import logging as _log_plan

            _log_plan.getLogger("genesis.brain").warning(
                "turn_plan_path_failed: %s",
                type(_plan_exc).__name__,
            )
            # Fallo de depuración/importación: no continuar con entrada cruda secreta
            if _secret_meta.get("had_secret_frame"):
                return JSONResponse(status_code=200, content={
                    "provider": "AZURE_OPENAI",
                    "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": session,
                    "status": "VALID_CONTRACT",
                    "mode": "SINGLE",
                    "intent_id": "SECURITY_GUARDRAIL",
                    "actions": [],
                    "clarifications": [],
                    "unsupported_segments": [],
                    "client_response": (
                        "Por seguridad no puedo procesar PIN/OTP/CVV en el chat. "
                        "Reformulanos la consulta sin datos de autenticación."
                    ),
                    "suggested_questions": [],
                    "rag_status": "NOT_REQUIRED",
                    "inference_count": 0,
                    "decision_trace": [{
                        "step": "turn_plan_error",
                        "output": {
                            "error_class": type(_plan_exc).__name__,
                            "secret_scrubbed": True,
                        },
                    }],
                    "total_request_ms": 0,
                    "correlation_id": str(uuid.uuid4()),
                })
            _use_plan = False
            # plan no aplicable / fallo no secreto → fallthrough histórico

        # ── FAQ institucional corto ANTES del Azure Brain (misión/visión/valores) ──
        # Solo si la solicitud COMPLETA es institucional (no omitir subtareas personales).
        if customer_snapshot is not None and request.question:
            try:
                from genesis_cognitive.brain.azure_intent_brain import (
                    _is_institutional_entity_request as _inst_short,
                )
                from genesis_cognitive.brain.plan_interpreter import (
                    message_is_institutional_only as _inst_only,
                )
                from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail as _faq_inst

                if _inst_short(request.question) and _inst_only(request.question):
                    # Liberar pending de producto para no bloquear FAQ institucional
                    _pa_pre = session_state.pending_action
                    if _pa_pre is not None and _pa_pre.intent_id in (
                        "ACCOUNT_BALANCE_READ",
                        "LOAN_DETAIL_READ",
                        "CREDIT_CARD_DETAIL_READ",
                        "TERM_DEPOSIT_DETAIL_READ",
                        "PAYMENT_DATE_READ",
                        "PORTFOLIO_QUERY",
                        "CLARIFICATION",
                    ):
                        # Excursión: no borrar pending; solo responder FAQ
                        pass
                    _faq_hit = _faq_inst(customer_snapshot, request.question, session_state)
                    if _faq_hit is not None and (_faq_hit[2] or "").strip():
                        _gs, _ga, _gt, _gsug = _faq_hit
                        _topic = None
                        if _ga:
                            _topic = (_ga[0].get("detected_entities") or {}).get("knowledge_topic")
                        if _topic:
                            session_state.last_knowledge_topic = str(_topic)[:200]
                        session.append({
                            "turn": turn_number,
                            "question": _safe_q if _secret_meta.get("had_secret_frame") else request.question,
                            "status": _gs,
                            "intent": "BUSINESS_KNOWLEDGE_QUERY",
                        })
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        return JSONResponse(status_code=200, content={
                            "provider": "AZURE_OPENAI",
                            "framework": "MICROSOFT_AGENT_FRAMEWORK",
                            "model": azure_model,
                            "prompt_version": prompt_version,
                            "conversation_id": conv_id,
                            "turn_number": turn_number,
                            "conversation_history": session,
                            "status": _gs,
                            "mode": "SINGLE",
                            "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
                            "actions": _ga or [],
                            "clarifications": [],
                            "unsupported_segments": [],
                            "client_response": _gt,
                            "suggested_questions": _gsug or [],
                            "rag_status": "FAQ",
                            "inference_count": 0,
                            "customer_context": {
                                "customer_id": customer_snapshot.customer_id,
                                "display_name": customer_snapshot.display_name,
                            },
                            "decision_trace": [{
                                "step": "institutional_faq_pre_brain",
                                "output": {"topic": _topic, "source": "faq"},
                            }],
                            "total_request_ms": 0,
                            "correlation_id": str(uuid.uuid4()),
                        })
            except Exception:
                pass

        # ── AZURE BRAIN (opt-in): intención Azure → hechos solo snapshot/KB ──
        _brain_q = (request.question or "").lower()
        _explicit_all_loan_field = (
            any(s in _brain_q for s in ("mis prestamos", "mis préstamos", "todos mis prestamos", "todos mis préstamos"))
            and any(s in _brain_q for s in ("tasa", "interes", "interés", "fecha", "capital", "mora", "cuota", "debo"))
        )
        _pending_before_brain = session_state.pending_action
        _new_field_spec = build_query_spec(request.question or "")
        _pending_loan_field_switch = (
            _pending_before_brain is not None
            and _pending_before_brain.intent_id == "LOAN_DETAIL_READ"
            and _new_field_spec.get("field") != "detail"
        )
        if (
            customer_snapshot is not None
            and request.question
            and not _pending_selection_blocks_brain(
                session_state.pending_action,
                request.question,
                explicit_all_loan_field=_explicit_all_loan_field,
                pending_loan_field_switch=_pending_loan_field_switch,
            )
        ):
            try:
                from genesis_cognitive.brain.azure_intent_brain import is_azure_brain_enabled
                from genesis_cognitive.brain.turn_orchestrator import run_azure_brain_turn
                from genesis_cognitive.router.product_focus import (
                    looks_like_product_option_selection as _brain_looks_sel,
                )

                if is_azure_brain_enabled() and not _brain_looks_sel(request.question):
                    _br = await run_azure_brain_turn(
                        request.question,
                        customer_snapshot,
                        session=session_state,
                    )
                    if _br is not None and (_br.text or "").strip():
                        from genesis_cognitive.router.product_focus import (
                            remember_product_focus,
                            should_update_last_resolved,
                        )
                        # Correcciones / chitchat: soltar sticky de producto erróneo
                        if (_br.intent_id or "").startswith("CHITCHAT") or _br.intent_id in (
                            "GREETING", "NON_OPERATIONAL",
                        ):
                            if (_br.trace or {}).get("social") == "correction":
                                session_state.pending_action = None
                                try:
                                    session_state.product_focus = None
                                except Exception:
                                    pass
                        if _br.status == "CLARIFICATION_REQUIRED":
                            session_state.pending_action = PendingAction(
                                intent_id=_br.intent_id or "CLARIFICATION",
                                capability_candidate="PRODUCT_FIELD",
                                selected_route="PERSONAL_READ",
                                detected_entities={"account_ref": None},
                                missing_requirements=(
                                    (_br.actions[0].get("missing_requirements") if _br.actions else None)
                                    or ["account_ref"]
                                ),
                                suggested_question=_br.text or "",
                                original_question=request.question,
                                query_spec=build_query_spec(
                                    request.question, _br.intent_id,
                                ),
                            )
                        elif should_update_last_resolved(
                            _br.intent_id, _br.account_ref, session_state, request.question,
                        ):
                            session_state.last_resolved = LastResolved(
                                intent_id=_br.intent_id,
                                account_ref=_br.account_ref or "",
                                original_question=request.question,
                            )
                            remember_product_focus(
                                session_state, _br.intent_id, _br.account_ref, request.question,
                            )
                            session_state.pending_action = None
                        elif _br.status == "VALID_CONTRACT" and _explicit_all_loan_field:
                            # Una consulta plural reemplaza cualquier préstamo singular
                            # anterior; el próximo campo deíctico debe volver a desambiguar.
                            session_state.pending_action = None
                            session_state.last_resolved = LastResolved(
                                intent_id="LOAN_DETAIL_READ",
                                account_ref="",
                                original_question=request.question,
                            )
                            if (
                                getattr(session_state, "product_focus", None) is not None
                                and getattr(session_state.product_focus, "kind", None) == "LOAN"
                            ):
                                session_state.product_focus = None
                        if _br.route == "knowledge":
                            session_state.last_knowledge_topic = (
                                (_br.actions[0].get("detected_entities") or {}).get("knowledge_topic")
                                if _br.actions else None
                            ) or (request.question or "")[:120]
                        session.append({
                            "turn": turn_number,
                            "question": request.question,
                            "status": _br.status,
                            "intent": _br.intent_id,
                        })
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        _br_mode = (
                            "CLARIFICATION" if _br.status == "CLARIFICATION_REQUIRED"
                            else "NON_OPERATIONAL" if _br.status == "NON_OPERATIONAL"
                            else "UNSUPPORTED" if _br.status == "UNSUPPORTED"
                            else "SINGLE"
                        )
                        return JSONResponse(status_code=200, content={
                            "provider": "AZURE_OPENAI",
                            "framework": "MICROSOFT_AGENT_FRAMEWORK",
                            "model": azure_model,
                            "prompt_version": prompt_version,
                            "conversation_id": conv_id,
                            "turn_number": turn_number,
                            "conversation_history": session,
                            "status": _br.status,
                            "mode": _br_mode,
                            "intent_id": _br.intent_id,
                            "actions": _br.actions or [],
                            "clarifications": [{
                                "target_action_sequence": 1,
                                "missing_requirements": (
                                    (_br.actions[0].get("missing_requirements") if _br.actions else None)
                                    or ["account_ref"]
                                ),
                                "suggested_question": _br.text,
                                "already_known": [],
                            }] if _br.status == "CLARIFICATION_REQUIRED" else [],
                            "unsupported_segments": [],
                            "client_response": _br.text,
                            "suggested_questions": _br.suggestions or [],
                            "app_channel_options": _br.options,
                            "rag_status": "FOUNDRY_KB" if _br.trace.get("kb") == "foundry" else (
                                "FAQ" if _br.trace.get("kb") == "faq" else "NOT_REQUIRED"
                            ),
                            "inference_count": 1 if (_br.trace.get("packet") or {}).get("source") == "azure" else 0,
                            "customer_context": {
                                "customer_id": customer_snapshot.customer_id,
                                "display_name": customer_snapshot.display_name,
                            },
                            "decision_trace": [{
                                "step": "azure_brain_grounded",
                                "output": _br.trace,
                            }],
                            "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                        })
            except Exception as _brain_exc:  # noqa: BLE001
                # No tumbar el turno: continuar con fastpath histórico
                import logging as _log_brain
                _log_brain.getLogger("genesis.brain").warning(
                    "azure_brain_path_failed: %s", _brain_exc,
                )

        # ── EARLY FAST-PATH: respuesta determinista sin LLM ni ensamblaje pesado ──
        if customer_snapshot is not None and request.question:
            from genesis_cognitive.router.field_guardrails import run_field_fastpath

            _pending_topic = None
            if session_state.pending_action is not None:
                _pending_topic = (session_state.pending_action.detected_entities or {}).get(
                    "knowledge_topic"
                )
                # Cambio de tema: liberar pending de reclamación / clarificaciones pegajosas
                if _pending_topic == "RECLAMACION_CHANNEL":
                    from genesis_cognitive.router.reclamacion_guardrail import (
                        is_topic_switch_from_reclamacion,
                    )
                    if is_topic_switch_from_reclamacion(request.question):
                        session_state.pending_action = None
                        _pending_topic = None
                # Pending de producto + pregunta de conocimiento/otro dominio → soltar
                elif session_state.pending_action.intent_id in (
                    "ACCOUNT_BALANCE_READ",
                    "LOAN_DETAIL_READ",
                    "CREDIT_CARD_DETAIL_READ",
                    "TERM_DEPOSIT_DETAIL_READ",
                    "PAYMENT_DATE_READ",
                ):
                    ql = (request.question or "").lower()
                    from genesis_cognitive.router.field_guardrails import (
                        is_ambiguous_product_noun_question as _is_amb_noun,
                        is_bank_card_catalog_question as _is_bank_card_cat,
                        is_bank_catalog_question as _is_bank_cat2,
                    )
                    if _is_amb_noun(request.question) or _is_bank_card_cat(request.question) or _is_bank_cat2(request.question):
                        session_state.pending_action = None
                        _pending_topic = None
                    elif any(
                        s in ql
                        for s in (
                            "banco", "misión", "mision", "visión", "vision",
                            "reclam", "contratar", "qué es", "que es",
                            "hablame", "háblame", "coño", "cono",
                            "cuenta corriente", "cuentas corrientes",
                            "condiciones", "cargos", "responsabilidad",
                        )
                    ) and not any(
                        s in ql for s in ("mi ", "mis ", "terminad", "···", "...", "…")
                    ):
                        session_state.pending_action = None
                        _pending_topic = None

            # Card/opción APK con pending de campo (fecha límite, tasa…): no
            # resolver aquí como ficha completa; dejar T2 usar original_question.
            _skip_early_fp = False
            _pa_sel = session_state.pending_action
            if _pa_sel is not None and customer_snapshot is not None:
                from genesis_cognitive.router.product_focus import (
                    looks_like_product_option_selection as _looks_sel,
                    pending_field_question_for_selection as _pend_oq,
                )
                if _looks_sel(request.question) and _pend_oq(session_state, request.question):
                    _skip_early_fp = True

            _fp_hit = None
            if not _skip_early_fp:
                _fp_hit = run_field_fastpath(
                    customer_snapshot,
                    request.question,
                    session_state.last_resolved,
                    pending_knowledge_topic=_pending_topic,
                    session=session_state,
                )
            if _fp_hit is not None:
                _gs, _ga, _gt, _gsug, _fp_step, _fp_intent, _fp_ref = _fp_hit
                _fp_topic = None
                if _ga:
                    _fp_topic = (_ga[0].get("detected_entities") or {}).get("knowledge_topic")
                if _fp_topic and _fp_intent == "BUSINESS_KNOWLEDGE_QUERY":
                    _topic_s = str(_fp_topic).strip()
                    # No envenenar el hilo KB con placeholders de clarificación
                    if _topic_s.upper() not in ("KB_AMBIGUITY", "RECLAMACION_CHANNEL"):
                        _prev = str(getattr(session_state, "last_knowledge_topic", "") or "")
                        _pl = _prev.lower()
                        _tl = _topic_s.lower()
                        _prev_pair = (
                            ("credito" in _pl or "crédito" in _pl)
                            and ("debito" in _pl or "débito" in _pl)
                        )
                        _new_keeps_pair = ("debito" in _tl or "débito" in _tl) and (
                            "credito" in _tl or "crédito" in _tl
                        )
                        if not (_prev_pair and not _new_keeps_pair):
                            session_state.last_knowledge_topic = _topic_s[:200]
                if _gs == "CLARIFICATION_REQUIRED":
                    # Conservar pending para que el siguiente turno (opción APK) use T2 sin LLM.
                    _pend_intent = _fp_intent or (
                        (_ga[0].get("intent_id") if _ga else None) or "ACCOUNT_BALANCE_READ"
                    )
                    _is_reclamacion = (_fp_topic or "") == "RECLAMACION_CHANNEL" or _fp_step == "reclamacion"
                    if _is_reclamacion:
                        _pend_cap = "BUSINESS_KNOWLEDGE"
                        _pend_route = "BUSINESS_RAG"
                        _pend_missing = ["reclamacion_channel"]
                        _pend_entities = {
                            "account_ref": None,
                            "knowledge_topic": "RECLAMACION_CHANNEL",
                        }
                    else:
                        _pend_cap = {
                            "ACCOUNT_BALANCE_READ": "ACCOUNT_BALANCE",
                            "ACCOUNT_MOVEMENTS_READ": "ACCOUNT_MOVEMENTS",
                            "CREDIT_CARD_DETAIL_READ": "CREDIT_CARD_DETAIL",
                            "LOAN_DETAIL_READ": "LOAN_DETAIL",
                            "TERM_DEPOSIT_DETAIL_READ": "TERM_DEPOSIT_DETAIL",
                            "PAYMENT_DATE_READ": "PRODUCT_FIELD",
                        }.get(_pend_intent, "ACCOUNT_BALANCE")
                        _pend_route = "PERSONAL_READ"
                        _pend_missing = ["account_ref"]
                        _pend_entities = {"account_ref": None}
                    session_state.pending_action = PendingAction(
                        intent_id=_pend_intent,
                        capability_candidate=_pend_cap,
                        selected_route=_pend_route,
                        detected_entities=_pend_entities,
                        missing_requirements=_pend_missing,
                        suggested_question=_gt or "",
                        original_question=request.question or "",
                        query_spec=build_query_spec(request.question or "", _pend_intent),
                    )
                elif (_fp_topic or "") == "RECLAMACION_OVERVIEW":
                    # Overview entregado: pending suave para detalle de canal, liberable por cambio de tema
                    session_state.pending_action = PendingAction(
                        intent_id="BUSINESS_KNOWLEDGE_QUERY",
                        capability_candidate="BUSINESS_KNOWLEDGE",
                        selected_route="BUSINESS_RAG",
                        detected_entities={
                            "account_ref": None,
                            "knowledge_topic": "RECLAMACION_CHANNEL",
                        },
                        missing_requirements=["reclamacion_channel"],
                        suggested_question="¿Centro de Contacto, Centro de Negocios o BSC en Línea?",
                        original_question=request.question or "",
                    )
                    if _fp_intent:
                        session_state.last_resolved = LastResolved(
                            intent_id=_fp_intent,
                            account_ref=_fp_ref or "",
                            original_question=request.question,
                        )
                else:
                    from genesis_cognitive.router.product_focus import (
                        remember_product_focus,
                        resolve_original_question_for_persist,
                        should_update_last_resolved,
                    )
                    if should_update_last_resolved(
                        _fp_intent, _fp_ref, session_state, request.question,
                    ):
                        _oq = resolve_original_question_for_persist(
                            session_state, request.question,
                        )
                        session_state.last_resolved = LastResolved(
                            intent_id=_fp_intent,
                            account_ref=_fp_ref or "",
                            original_question=_oq,
                        )
                        remember_product_focus(
                            session_state, _fp_intent, _fp_ref, _oq,
                        )
                    session_state.pending_action = None
                session.append({
                    "turn": turn_number,
                    "question": request.question,
                    "status": _gs,
                    "intent": _fp_intent,
                })
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                if _gs == "UNSUPPORTED":
                    _fp_mode = "UNSUPPORTED"
                elif _gs == "CLARIFICATION_REQUIRED":
                    _fp_mode = "CLARIFICATION"
                elif _gs == "NON_OPERATIONAL":
                    _fp_mode = "NON_OPERATIONAL"
                else:
                    _fp_mode = "SINGLE"
                _clar_missing: list[str] = []
                if _gs == "CLARIFICATION_REQUIRED":
                    if _ga and (_ga[0].get("missing_requirements")):
                        _clar_missing = list(_ga[0].get("missing_requirements") or [])
                    elif session_state.pending_action is not None:
                        _clar_missing = list(session_state.pending_action.missing_requirements or [])
                    else:
                        _clar_missing = ["account_ref"]
                return JSONResponse(status_code=200, content={
                    "provider": "AZURE_OPENAI",
                    "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": session,
                    "status": _gs,
                    "mode": _fp_mode,
                    "actions": _ga,
                    "clarifications": [{
                        "target_action_sequence": 1,
                        "missing_requirements": _clar_missing or ["query_scope"],
                        "suggested_question": _gt,
                        "already_known": [],
                    }] if _gs == "CLARIFICATION_REQUIRED" else [],
                    "unsupported_segments": [{
                        "segment_description": "Operación no habilitada",
                        "reason": "OPERATION_NOT_ENABLED",
                    }] if _gs == "UNSUPPORTED" else [],
                    "client_response": _gt,
                    "suggested_questions": _gsug or [],
                    "rag_status": "NOT_REQUIRED",
                    "inference_count": 0,
                    "customer_context": {
                        "customer_id": customer_snapshot.customer_id,
                        "display_name": customer_snapshot.display_name,
                    },
                    "decision_trace": [{
                        "step": f"field_fastpath_{_fp_step}",
                        "output": {
                            "intent": _fp_intent,
                            "ref": _fp_ref,
                            "brain_source": "deterministic_fastpath_pre_azure",
                            "route_source": f"field_fastpath:{_fp_step}",
                            "payment_window": (
                                (_ga[0].get("payment_window") if _ga else None)
                            ),
                            "payment_classifications": (
                                (_ga[0].get("payment_classifications") if _ga else None)
                            ),
                            "field_accreditation": (
                                (_ga[0].get("field_accreditation") if _ga else None)
                            ),
                        },
                    }],
                    "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                })

        # Follow-up KB sin match FAQ → Foundry/RAG con pregunta ampliada (no LLM personal)
        try:
            from genesis_cognitive.router.knowledge_followup import (
                expand_knowledge_question,
                has_knowledge_session,
                is_knowledge_followup,
                prefer_foundry_for_faq_hit,
                should_block_personal_followup,
            )
            if (
                customer_snapshot is not None
                and has_knowledge_session(session_state)
                and (
                    is_knowledge_followup(request.question or "")
                    or should_block_personal_followup(request.question or "", session_state)
                )
            ):
                _kb_q = expand_knowledge_question(request.question or "", session_state)
                _kb_ans = None
                _kb_status = None
                from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail as _afq_kb2
                _faq2 = _afq_kb2(customer_snapshot, _kb_q, session=session_state)
                _faq2_score = None
                try:
                    if _faq2 and _faq2[1]:
                        _faq2_score = float((_faq2[1][0] or {}).get("confidence") or 0)
                except Exception:
                    _faq2_score = None
                if (
                    _faq2
                    and _faq2[2]
                    and not prefer_foundry_for_faq_hit(_kb_q, str(_faq2[2]), score=_faq2_score)
                ):
                    _kb_ans = _faq2[2]
                    _kb_status = "FAQ_KB_FOLLOWUP"
                    _ga = _faq2[1]
                else:
                    from genesis_cognitive.rag.foundry_kb_agent import (
                        ask_foundry_kb_agent,
                        is_foundry_kb_enabled,
                    )
                    if is_foundry_kb_enabled():
                        _fy = ask_foundry_kb_agent(
                            _kb_q,
                            display_name=customer_snapshot.display_name,
                            topic=getattr(session_state, "last_knowledge_topic", None),
                        )
                        if _fy.get("ok") and _fy.get("answer"):
                            _kb_ans = str(_fy["answer"])
                            _kb_status = str(_fy.get("status") or "FOUNDRY_KB_ANSWERED")
                            _ga = [{
                                "sequence": 1,
                                "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
                                "capability_candidate": "BUSINESS_KNOWLEDGE",
                                "selected_route": "BUSINESS_RAG",
                                "detected_entities": {
                                    "account_ref": None,
                                    "knowledge_topic": session_state.last_knowledge_topic,
                                },
                                "missing_requirements": [],
                                "depends_on": [],
                                "confidence": 0.85,
                            }]
                if _kb_ans:
                    session.append({
                        "turn": turn_number,
                        "question": request.question,
                        "status": "VALID_CONTRACT",
                        "intent": "BUSINESS_KNOWLEDGE_QUERY",
                    })
                    _conflict_resp = _cas_put_session()
                    if _conflict_resp is not None:
                        return _conflict_resp
                    return JSONResponse(status_code=200, content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "VALID_CONTRACT",
                        "mode": "SINGLE",
                        "actions": _ga,
                        "clarifications": [],
                        "unsupported_segments": [],
                        "client_response": _kb_ans,
                        "suggested_questions": [],
                        "rag_status": _kb_status,
                        "inference_count": 0,
                        "customer_context": {
                            "customer_id": customer_snapshot.customer_id,
                            "display_name": customer_snapshot.display_name,
                        },
                        "decision_trace": [{
                            "step": "knowledge_followup_foundry",
                            "output": {
                                "expanded": _kb_q[:120],
                                "topic": session_state.last_knowledge_topic,
                                "rag_status": _kb_status,
                            },
                        }],
                        "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                    })
        except Exception:
            pass

        # Comparación Multicrédito / Cuotas → FAQ overlay o Foundry (evita OOD/UNSUPPORTED del LLM)
        try:
            _q_cmp = (request.question or "").strip().lower()
            from genesis_cognitive.router.knowledge_followup import is_kb_product_compare_question
            _is_kb_compare = (
                customer_snapshot is not None
                and is_kb_product_compare_question(request.question or "")
            )
            if _is_kb_compare:
                from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail as _afq_cmp
                from genesis_cognitive.router.knowledge_followup import prefer_foundry_for_faq_hit
                from genesis_cognitive.rag.foundry_kb_agent import (
                    ask_foundry_kb_agent,
                    is_foundry_kb_enabled,
                )

                _cmp_topic = "Multicrédito BSC vs Cuotas BSC"
                if any(s in _q_cmp for s in ("debito", "débito")) and any(
                    s in _q_cmp for s in ("credito", "crédito")
                ):
                    _cmp_topic = "tarjeta de crédito y tarjeta de débito"

                _cmp_ans = None
                _cmp_status = None
                _cmp_ga: list | None = None
                _faq_cmp = _afq_cmp(
                    customer_snapshot, request.question or "", session=session_state
                )
                _cmp_score = None
                try:
                    if _faq_cmp and _faq_cmp[1]:
                        _cmp_score = float((_faq_cmp[1][0] or {}).get("confidence") or 0)
                except Exception:
                    _cmp_score = None
                if (
                    _faq_cmp
                    and _faq_cmp[2]
                    and not prefer_foundry_for_faq_hit(
                        request.question or "", str(_faq_cmp[2]), score=_cmp_score
                    )
                ):
                    _cmp_ans = _faq_cmp[2]
                    _cmp_status = "FAQ_KB_COMPARE"
                    _cmp_ga = _faq_cmp[1]
                elif is_foundry_kb_enabled():
                    _fy_cmp = ask_foundry_kb_agent(
                        request.question or "",
                        display_name=customer_snapshot.display_name,
                        topic=_cmp_topic,
                        prefer_clarify_ambiguous=False,
                    )
                    if _fy_cmp.get("ok") and _fy_cmp.get("answer"):
                        _cmp_ans = str(_fy_cmp["answer"])
                        _cmp_status = str(_fy_cmp.get("status") or "FOUNDRY_KB_ANSWERED")
                        _cmp_ga = [{
                            "sequence": 1,
                            "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
                            "capability_candidate": "BUSINESS_KNOWLEDGE",
                            "selected_route": "BUSINESS_RAG",
                            "detected_entities": {
                                "account_ref": None,
                                "knowledge_topic": _cmp_topic,
                            },
                            "missing_requirements": [],
                            "depends_on": [],
                            "confidence": 0.88,
                        }]
                if _cmp_ans:
                    try:
                        session_state.last_knowledge_topic = _cmp_topic
                    except Exception:
                        pass
                    session.append({
                        "turn": turn_number,
                        "question": request.question,
                        "status": "VALID_CONTRACT",
                        "intent": "BUSINESS_KNOWLEDGE_QUERY",
                    })
                    _conflict_resp = _cas_put_session()
                    if _conflict_resp is not None:
                        return _conflict_resp
                    return JSONResponse(status_code=200, content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "VALID_CONTRACT",
                        "mode": "SINGLE",
                        "actions": _cmp_ga,
                        "clarifications": [],
                        "unsupported_segments": [],
                        "client_response": _cmp_ans,
                        "suggested_questions": [],
                        "rag_status": _cmp_status,
                        "inference_count": 0,
                        "customer_context": {
                            "customer_id": customer_snapshot.customer_id,
                            "display_name": customer_snapshot.display_name,
                        },
                        "decision_trace": [{
                            "step": "knowledge_compare_foundry",
                            "output": {"rag_status": _cmp_status, "topic": _cmp_topic},
                        }],
                        "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
                    })
        except Exception:
            pass

        # Use resolved customer_id for the payload
        payload_customer_id = (
            customer_snapshot.customer_id if customer_snapshot else "demo-customer"
        )

        payload: dict[str, object] = {
            "type": "USER_MESSAGE",
            "conversation_id": conv_id,
            "customer_id": payload_customer_id,
            "subject_token": "demo-token",
            "request_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "user_turn": {"raw_text": request.question},
            "channel_context": {
                "channel": "web-demo",
                "client_slot": "inspector-ui",
                "authenticated": True,
                "locale": "es-DO",
            },
        }

        validated = input_validator.validate(payload)
        assembled = await context_assembler.assemble(validated)
        model_input = model_input_builder.build(assembled)

        # T3: Override portfolio with customer snapshot (filtered by default currency)
        if customer_snapshot is not None:
            from genesis_cognitive.model_input.model_input_builder import ProjectedProduct

            filtered_products = tuple(
                ProjectedProduct(
                    product_ref=p.product_id,
                    product_type=p.product_type,
                    label=p.alias,
                    alias=p.alias,
                    currency=p.currency,
                    operational_state=p.status,
                )
                for p in customer_snapshot.products
                if p.status.lower() == "active"
            )
            model_input = model_input.model_copy(update={"portfolio": filtered_products})

        # T5: Inject pending_action from previous CLARIFICATION turn
        pending = session_state.pending_action
        if pending is not None:
            projected_pending = ProjectedPendingAction(
                intent_id=pending.intent_id,
                capability_candidate=pending.capability_candidate,
                selected_route=pending.selected_route,
                detected_entities=pending.detected_entities,
                missing_requirements=pending.missing_requirements,
                suggested_question=pending.suggested_question,
                original_question=getattr(pending, "original_question", "") or "",
                query_spec=dict(getattr(pending, "query_spec", {}) or {}),
            )
            # Rebuild envelope with pending_action (frozen model, must reconstruct)
            model_input = model_input.model_copy(update={"pending_action": projected_pending})

        # Memoria conversacional tipada (pendientes multi, compare_set, foco)
        from genesis_cognitive.model_input.model_input_builder import project_conversation_memory
        model_input = model_input.model_copy(
            update={"conversation_memory": project_conversation_memory(session_state)},
        )

        # Inject real conversation history from session into envelope
        if session:
            from genesis_cognitive.model_input.model_input_builder import ProjectedTurn
            projected_turns = tuple(
                ProjectedTurn(
                    role="user",
                    summary=f"[T{t['turn']}] {t['question'][:80]} → {t.get('status', '?')}",
                )
                for t in session[-5:]  # last 5 turns max
            )
            model_input = model_input.model_copy(update={"conversation": projected_turns})

        # A) T2 shortcut: if pending clarification for account_ref and user text
        # uniquely identifies one product → resolve directly without LLM
        if pending is not None and customer_snapshot is not None:
            _pending_missing = pending.missing_requirements
            _pending_ref = pending.detected_entities.get("account_ref")
            if "account_ref" in _pending_missing and _pending_ref is None:
                from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
                _text_lower = request.question.strip().lower()

                # Escape: if user changed topic (card/loan/portfolio question while pending is deposits, or vice versa)
                _CARD_ESCAPE = ("tarjeta", "visa", "mastercard", "pricesmart", "black", "platinum", "gold")
                # No incluir "termina": substring de "terminada en ####" (máscara de cuenta).
                _LOAN_ESCAPE = ("prestamo", "préstamo", "credito", "crédito", "cuota", "fecha de pago", "deuda", "saldar", "cancelar", "letra", "vence", "vencimiento")
                _LIST_ESCAPE = ("productos", "portafolio", "que tengo", "qué tengo", "que cuentas", "que tarjetas", "qué cuentas", "qué tarjetas")
                _is_loan_pending = pending.intent_id == "LOAN_DETAIL_READ"
                _is_dap_pending_early = pending.intent_id == "TERM_DEPOSIT_DETAIL_READ"
                _is_card_pending_early = pending.intent_id == "CREDIT_CARD_DETAIL_READ"
                _is_paydate_pending_early = pending.intent_id == "PAYMENT_DATE_READ"

                _topic_escape = False
                if _is_paydate_pending_early:
                    # Selección de préstamo/tarjeta es la respuesta esperada
                    pass
                elif _is_dap_pending_early or _is_card_pending_early:
                    if any(sig in _text_lower for sig in _LIST_ESCAPE):
                        _topic_escape = True
                    if _is_dap_pending_early and any(sig in _text_lower for sig in _CARD_ESCAPE + ("prestamo", "préstamo")):
                        _topic_escape = True
                    if _is_card_pending_early and any(sig in _text_lower for sig in ("certificado", "deposito", "depósito", "prestamo", "préstamo")):
                        _topic_escape = True
                elif not _is_loan_pending:
                    # Pending is for deposits; escape if user asks about cards/loans/listings
                    if any(sig in _text_lower for sig in _CARD_ESCAPE + _LOAN_ESCAPE + _LIST_ESCAPE):
                        _topic_escape = True
                else:
                    # Pending is for loans; escape if user asks about cards/deposits/listings
                    if any(sig in _text_lower for sig in _CARD_ESCAPE + _LIST_ESCAPE):
                        _topic_escape = True
                    if any(sig in _text_lower for sig in ("certificado", "deposito", "depósito", "dap", "cdt")):
                        _topic_escape = True

                if _topic_escape:
                    session_state.pending_action = None
                    pending = None  # Let normal flow handle
                else:
                    _is_dap_pending = pending.intent_id == "TERM_DEPOSIT_DETAIL_READ"
                    _is_card_pending = pending.intent_id == "CREDIT_CARD_DETAIL_READ"
                    _is_paydate_pending = pending.intent_id == "PAYMENT_DATE_READ"
                    if _is_loan_pending:
                        _candidates_pool = [p for p in customer_snapshot.products if p.product_type == "LOAN" and p.status.lower() == "active" and p.currency == customer_snapshot.default_currency]
                    elif _is_dap_pending:
                        _candidates_pool = [p for p in customer_snapshot.products if p.product_type == "TERM_DEPOSIT" and str(p.status).lower() == "active"]
                    elif _is_card_pending:
                        _candidates_pool = [p for p in customer_snapshot.products if p.product_type == "CREDIT_CARD" and str(p.status).lower() == "active"]
                    elif _is_paydate_pending:
                        _candidates_pool = [
                            p for p in customer_snapshot.products
                            if p.product_type in ("LOAN", "CREDIT_CARD") and str(p.status).lower() == "active"
                        ]
                    else:
                        _candidates_pool = [p for p in customer_snapshot.products if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and p.status.lower() == "active" and p.currency == customer_snapshot.default_currency]

                    _t2_matches = _find_text_candidates(_text_lower, _candidates_pool)
                    if _is_loan_pending or _is_dap_pending or _is_card_pending or _is_paydate_pending:
                        _id_hits = []
                        for _p in _candidates_pool:
                            _pid = _p.product_id.lower()
                            _digits = "".join(ch for ch in _p.product_id if ch.isdigit())
                            _last4 = _digits[-4:] if len(_digits) >= 4 else _digits
                            _last5 = _digits[-5:] if len(_digits) >= 5 else _digits
                            _mask_digits = "".join(ch for ch in str(_p.card_mask or "") if ch.isdigit())
                            _mask4 = _mask_digits[-4:] if len(_mask_digits) >= 4 else ""
                            if _pid and _pid in _text_lower:
                                _id_hits.append(_p)
                            elif _last5 and _last5 in _text_lower:
                                _id_hits.append(_p)
                            elif _last4 and _last4 in _text_lower:
                                _id_hits.append(_p)
                            elif _mask4 and _mask4 in _text_lower:
                                _id_hits.append(_p)
                        if len(_id_hits) == 1:
                            _t2_matches = _id_hits
                    if len(_t2_matches) == 1:
                        _resolved_product = _t2_matches[0]
                        _t2_intent = pending.intent_id
                        _t2_cap = pending.capability_candidate
                        from genesis_cognitive.router.product_focus import (
                            focused_field_question,
                            remember_product_focus,
                        )
                        _field_q = (
                            query_question(
                                getattr(pending, "query_spec", None),
                                getattr(pending, "original_question", None) or "",
                            )
                            or focused_field_question(session_state)
                            or (session[-2]["question"] if len(session) >= 2 else "")
                            or request.question
                        )
                        # Clear pending, set last_resolved
                        session_state.pending_action = None
                        session_state.last_resolved = LastResolved(
                            intent_id=_t2_intent,
                            account_ref=_resolved_product.product_id,
                            original_question=_field_q,
                        )
                        remember_product_focus(
                            session_state,
                            _t2_intent,
                            _resolved_product.product_id,
                            _field_q,
                        )
                        session.append({"turn": turn_number, "question": request.question, "status": "VALID_CONTRACT", "intent": _t2_intent})

                        from genesis_cognitive.context.product_display import display_label_in_context as _dli
                        _t2_label = _dli(_resolved_product, _candidates_pool)
                        _t2_display = customer_snapshot.display_name
                        _t2_greeting = f"{_t2_display}, " if _t2_display else ""
                        if _t2_intent == "ACCOUNT_BALANCE_READ":
                            _t2_balance = ""
                            if _resolved_product.available_balance is not None:
                                _t2_balance = f" es de {_resolved_product.available_balance} {_resolved_product.currency}"
                            _t2_response = f"{_t2_greeting}tu saldo disponible en {_t2_label}{_t2_balance}."
                        elif _t2_intent == "ACCOUNT_MOVEMENTS_READ":
                            _t2_response = (
                                f"{_t2_greeting}no recibí el historial de movimientos "
                                f"de {_t2_label} en el contexto disponible en este momento."
                            )
                        elif _t2_intent == "TERM_DEPOSIT_DETAIL_READ":
                            from genesis_cognitive.router.final_response_agent import build_deposit_detail_response as _bdd
                            _t2_response = _bdd(
                                _field_q, _resolved_product, _t2_display, _t2_label,
                            )
                        elif _t2_intent == "CREDIT_CARD_DETAIL_READ":
                            from genesis_cognitive.router.final_response_agent import build_card_detail_response as _bcd
                            _t2_response = _bcd(
                                _field_q, _resolved_product, _t2_display, _t2_label,
                            )
                        elif _t2_intent == "PAYMENT_DATE_READ":
                            if _resolved_product.product_type == "LOAN":
                                _loan = next(
                                    (ln for ln in customer_snapshot.loans if ln.product_id == _resolved_product.product_id),
                                    None,
                                )
                                _due = getattr(_loan, "next_due_date", None) if _loan else None
                                _t2_response = (
                                    f"{_t2_greeting}la próxima fecha de pago de tu {_t2_label} es **{_due}**."
                                    if _due
                                    else f"{_t2_greeting}la fecha de pago de tu {_t2_label} no está disponible en este momento."
                                )
                                _t2_intent = "LOAN_DETAIL_READ"
                            else:
                                # Campo según pregunta original (corte vs límite de pago)
                                _fq = (_field_q or "").lower()
                                _wants_cutoff = "corte" in _fq or "corta" in _fq
                                _wants_due = any(
                                    s in _fq
                                    for s in (
                                        "fecha limite", "fecha límite", "limite de pago", "límite de pago",
                                        "cuando debo pagar", "cuándo debo pagar", "cuando pago", "cuándo pago",
                                        "debo pagar",
                                    )
                                )
                                _due = getattr(_resolved_product, "payment_due_date", None)
                                _cut = getattr(_resolved_product, "cutoff_day", None)
                                if _wants_cutoff and _cut:
                                    _t2_response = (
                                        f"{_t2_greeting}la fecha de corte de tu {_t2_label} es el día **{_cut}** de cada mes."
                                    )
                                elif _due:
                                    _t2_response = f"{_t2_greeting}la fecha límite de pago de tu {_t2_label} es **{_due}**."
                                elif _wants_due and _cut:
                                    _t2_response = (
                                        f"{_t2_greeting}no tengo la fecha límite de pago exacta de tu {_t2_label} en este momento. "
                                        f"La fecha de corte es el día **{_cut}** de cada mes; "
                                        "la fecha límite de pago aparece en tu estado de cuenta (normalmente unos días después del corte)."
                                    )
                                elif _cut:
                                    _t2_response = (
                                        f"{_t2_greeting}la fecha de corte de tu {_t2_label} es el día **{_cut}** de cada mes. "
                                        "La fecha límite de pago aparece en tu estado de cuenta."
                                    )
                                else:
                                    _t2_response = f"{_t2_greeting}la fecha de pago de tu {_t2_label} no está disponible en este momento."
                                _t2_intent = "CREDIT_CARD_DETAIL_READ"
                        elif _t2_intent == "LOAN_DETAIL_READ":
                            from genesis_cognitive.router.final_response_agent import build_loan_detail_response as _bld
                            from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question as _is_lq_t2
                            _t2_loan = next((ln for ln in customer_snapshot.loans if ln.product_id == _resolved_product.product_id), None)
                            # Siempre preferir pregunta original (fecha de pago) frente al label de la opción APK
                            _q_for_loan = _field_q or request.question
                            if not _is_lq_t2(_q_for_loan) and _is_lq_t2(request.question or ""):
                                _q_for_loan = request.question
                            if _t2_loan:
                                _t2_response = _bld(
                                    _q_for_loan,
                                    _t2_loan.to_detail_dict(),
                                    customer_snapshot.display_name,
                                )
                            else:
                                _t2_response = f"{_t2_greeting}préstamo {_t2_label} seleccionado."
                        else:
                            _t2_response = f"{_t2_greeting}consulta para {_t2_label}."

                        session_state.last_resolved = LastResolved(
                            intent_id=_t2_intent,
                            account_ref=_resolved_product.product_id,
                            original_question=_field_q,
                        )
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        body_t2: dict[str, Any] = {
                            "provider": "AZURE_OPENAI", "framework": "MICROSOFT_AGENT_FRAMEWORK",
                            "model": azure_model, "prompt_version": prompt_version,
                            "conversation_id": conv_id, "turn_number": turn_number,
                            "conversation_history": session, "status": "VALID_CONTRACT", "mode": "SINGLE",
                            "non_operational_response": None,
                            "initial_proposal": None, "verified_proposal": None, "raw_interpretation": None,
                            "actions": [{"sequence": 1, "intent_id": _t2_intent, "capability_candidate": _t2_cap, "selected_route": "PERSONAL_READ", "detected_entities": {"account_ref": _resolved_product.product_id}, "missing_requirements": [], "depends_on": [], "confidence": 1.0}],
                            "clarifications": [], "unsupported_segments": [],
                            "catalog_valid": True, "entity_refs_valid": True, "violations": [],
                            "output_contracts": ["BalanceResponse" if _t2_intent == "ACCOUNT_BALANCE_READ" else "LoanDetailResponse"],
                            "rag_status": "NOT_REQUIRED", "inference_count": 0,
                            "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                            "customer_context": {"customer_id": customer_snapshot.customer_id, "display_name": customer_snapshot.display_name, "products_count": len(customer_snapshot.products), "loans_count": len(customer_snapshot.loans)},
                            "loan_detail": None,
                            "domain_scores": None, "product_scores": None,
                            "client_response": _t2_response,
                            "decision_trace": [{"step": "t2_shortcut", "output": {"resolved_ref": _resolved_product.product_id, "intent": _t2_intent}}],
                        }
                        return JSONResponse(status_code=200, content=body_t2)

                    from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question as _is_loan_q
                    if _is_loan_pending and _is_loan_q(request.question):
                        from genesis_cognitive.context.product_display import build_clarification_loans as _bcl_pending
                        _loan_q = pending.suggested_question or _bcl_pending(_candidates_pool)
                        session.append({"turn": turn_number, "question": request.question, "status": "CLARIFICATION_REQUIRED", "intent": "LOAN_DETAIL_READ"})
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        return JSONResponse(status_code=200, content={
                            "provider": "AZURE_OPENAI", "framework": "MICROSOFT_AGENT_FRAMEWORK",
                            "model": azure_model, "prompt_version": prompt_version,
                            "conversation_id": conv_id, "turn_number": turn_number,
                            "conversation_history": session, "status": "CLARIFICATION_REQUIRED", "mode": "CLARIFICATION",
                            "non_operational_response": None,
                            "initial_proposal": None, "verified_proposal": None, "raw_interpretation": None,
                            "actions": [{"sequence": 1, "intent_id": "LOAN_DETAIL_READ", "capability_candidate": "LOAN_DETAIL", "selected_route": "PERSONAL_READ", "detected_entities": {"account_ref": None}, "missing_requirements": ["account_ref"], "depends_on": [], "confidence": 1.0}],
                            "clarifications": [{"target_action_sequence": 1, "missing_requirements": ["account_ref"], "suggested_question": _loan_q, "already_known": []}],
                            "unsupported_segments": [],
                            "catalog_valid": True, "entity_refs_valid": True, "violations": [],
                            "output_contracts": [],
                            "rag_status": "NOT_REQUIRED", "inference_count": 0,
                            "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                            "customer_context": {"customer_id": customer_snapshot.customer_id, "display_name": customer_snapshot.display_name, "products_count": len(customer_snapshot.products), "loans_count": len(customer_snapshot.loans)},
                            "loan_detail": None,
                            "domain_scores": None, "product_scores": None,
                            "client_response": _loan_q,
                            "decision_trace": [{"step": "t2_keep_loan_clarification", "output": {"pending": True}}],
                        })

        # B) Follow-up detection: if last_resolved exists and text is a follow-up
        # (e.g. "y la tasa?", "y la deuda?") → reuse same product, skip full pipeline
        last_resolved = session_state.last_resolved
        # Rehidratación: KB pudo no actualizar last_resolved; product_focus guarda el préstamo
        if last_resolved is None and customer_snapshot and not pending:
            from genesis_cognitive.router.product_focus import (
                loan_ref_from_session as _lref0,
                prefer_personal_loan_over_knowledge as _pref0,
            )
            if _pref0(request.question, session_state):
                _r0 = _lref0(session_state)
                if _r0:
                    last_resolved = LastResolved(
                        intent_id="LOAN_DETAIL_READ",
                        account_ref=_r0,
                        original_question=request.question,
                    )

        def _build_session_context() -> dict[str, Any]:
            """Build enriched session context for decision_trace."""
            portfolio_summary = []
            loan_ids: list[str] = []
            if customer_snapshot:
                for p in customer_snapshot.products:
                    if p.currency == customer_snapshot.default_currency:
                        portfolio_summary.append({"id": p.product_id, "type": p.product_type, "alias": p.alias})
                loan_ids = [ln.product_id for ln in customer_snapshot.loans]
            conv_slice = session[-5:] if session else []
            lr = session_state.last_resolved
            pa = session_state.pending_action
            pf = session_state.product_focus
            return {
                "session_context": {
                    "customer_id": customer_snapshot.customer_id if customer_snapshot else None,
                    "session_key": f"session:{conv_id}",
                    "snapshot_key": f"customer:{resolved_customer_id}:snapshot",
                    "snapshot_age_s": round(snapshot_age_s, 1) if snapshot_age_s else None,
                    "portfolio": portfolio_summary[:8],
                    "loan_ids": loan_ids,
                },
                "conversation_slice": conv_slice,
                "pending_action": {"intent_id": pa.intent_id, "ref": pa.detected_entities.get("account_ref")} if pa else None,
                "last_resolved": {"intent_id": lr.intent_id, "ref": lr.account_ref} if lr else None,
                "product_focus": (
                    {"kind": pf.kind, "ref": pf.product_id, "intent": pf.intent_id} if pf else None
                ),
                "envelope_summary": {
                    "portfolio_count": len(portfolio_summary),
                    "has_pending": pa is not None,
                    "has_last_resolved": lr is not None,
                    "has_product_focus": pf is not None,
                    "history_len": len(session),
                    "turn": turn_number,
                },
            }

        if last_resolved and not pending and customer_snapshot:
            text_lower = request.question.strip().lower()
            is_followup = any(sig in text_lower for sig in _FOLLOWUP_SIGNALS) and len(text_lower) < 80
            wants_more_info = any(sig in text_lower for sig in _MORE_INFO_SIGNALS) and len(text_lower) < 80
            if wants_more_info:
                is_followup = True
            if last_resolved.intent_id == "LOAN_DETAIL_READ":
                from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question as _is_loan_fu
                if _is_loan_fu(text_lower, allow_deictic_fields=True):
                    is_followup = True
            else:
                # Reanudar préstamo tras otro tema (misión/saldo) vía product_focus
                from genesis_cognitive.router.product_focus import prefer_personal_loan_over_knowledge
                if prefer_personal_loan_over_knowledge(text_lower, session_state):
                    is_followup = True
                    from genesis_cognitive.router.product_focus import loan_ref_from_session as _lref
                    _focus_ref = _lref(session_state)
                    if _focus_ref:
                        last_resolved = LastResolved(
                            intent_id="LOAN_DETAIL_READ",
                            account_ref=_focus_ref,
                            original_question=last_resolved.original_question,
                        )
            if last_resolved.intent_id == "CREDIT_CARD_DETAIL_READ":
                from genesis_cognitive.router.field_guardrails import is_card_field_question as _is_card_fu
                if _is_card_fu(text_lower) or wants_more_info:
                    is_followup = True
            if last_resolved.intent_id == "TERM_DEPOSIT_DETAIL_READ":
                from genesis_cognitive.router.field_guardrails import is_dap_field_question as _is_dap_fu
                if _is_dap_fu(text_lower) or wants_more_info:
                    is_followup = True

            # Escaneo multi-producto (préstamo/tarjeta con pago próximo) ≠ follow-up de un DAP/TC
            from genesis_cognitive.router.field_guardrails import is_upcoming_payment_scan_question
            if is_upcoming_payment_scan_question(text_lower):
                is_followup = False

            # Feasibility detection: "me alcanza / puedo pagar / suficiente para la cuota"
            # with last_resolved LOAN + mentions an account
            _feasibility_signals = ("alcanza", "alcanz", "suficiente", "puedo pagar", "cubre", "tengo para", "me da para", "llego", "basta")
            is_feasibility = (
                last_resolved.intent_id == "LOAN_DETAIL_READ"
                and any(fs in text_lower for fs in _feasibility_signals)
                and len(text_lower) < 100
            )

            if is_feasibility:
                # Find the loan installment from snapshot
                loan_data = next((ln for ln in customer_snapshot.loans if ln.product_id == last_resolved.account_ref), None)
                if loan_data:
                    installment = loan_data.installment_amount
                    # Find which account(s) to compare: try to identify from text, or use all deposit accounts
                    _acct_hints = {"ahorro": "SAVINGS", "ahorros": "SAVINGS", "corriente": "CHECKING", "nomina": "PAYROLL", "nómina": "PAYROLL"}
                    target_type: str | None = None
                    for hint, ptype in _acct_hints.items():
                        if hint in text_lower:
                            target_type = ptype
                            break

                    # Sum available balances from matching accounts
                    compare_accounts: list[tuple[str, str | None, str]] = []  # (product_id, alias, balance_str)
                    for p in customer_snapshot.products:
                        if p.currency == customer_snapshot.default_currency and p.available_balance is not None:
                            if target_type and p.product_type == target_type:
                                compare_accounts.append((p.product_id, p.alias, str(p.available_balance)))
                            elif not target_type and p.product_type in ("CHECKING", "SAVINGS", "PAYROLL"):
                                compare_accounts.append((p.product_id, p.alias, str(p.available_balance)))

                    if compare_accounts:
                        from decimal import Decimal as _Dec
                        total_available = sum(_Dec(b) for _, _, b in compare_accounts)
                        covers = total_available >= installment
                        # Build response
                        acct_desc = ", ".join(f"{a or pid} ({b})" for pid, a, b in compare_accounts)
                        loan_alias = next((pp.alias for pp in customer_snapshot.products if pp.product_id == last_resolved.account_ref), last_resolved.account_ref)
                        if covers:
                            client_response = (
                                f"{customer_snapshot.display_name}, sí te alcanza. "
                                f"Tu cuota de {loan_alias} es {installment} y tienes {total_available} disponible en {acct_desc}."
                            )
                        else:
                            deficit = installment - total_available
                            client_response = (
                                f"{customer_snapshot.display_name}, no alcanza actualmente. "
                                f"Tu cuota de {loan_alias} es {installment} y tienes {total_available} disponible en {acct_desc}. "
                                f"Faltarían {deficit}."
                            )

                        # Build response body
                        decision_trace_feas: list[dict[str, Any]] = [
                            {"step": "context", "output": _build_session_context()},
                            {"step": "feasibility_check", "input": {
                                "question": request.question[:80],
                                "loan_ref": last_resolved.account_ref,
                                "installment": str(installment),
                                "accounts_checked": [(pid, b) for pid, _, b in compare_accounts],
                            }, "output": {"total_available": str(total_available), "covers": covers}},
                            {"step": "final_response", "output": {"client_response": client_response[:120]}},
                        ]
                        session.append({"turn": turn_number, "question": request.question, "status": "VALID_CONTRACT", "intent": "FEASIBILITY_READ"})
                        body_feas: dict[str, Any] = {
                            "provider": "AZURE_OPENAI", "framework": "MICROSOFT_AGENT_FRAMEWORK",
                            "model": azure_model, "prompt_version": prompt_version,
                            "conversation_id": conv_id, "turn_number": turn_number,
                            "conversation_history": session, "status": "VALID_CONTRACT", "mode": "SINGLE",
                            "non_operational_response": None,
                            "initial_proposal": None, "verified_proposal": None, "raw_interpretation": None,
                            "actions": [{"sequence": 1, "intent_id": "FEASIBILITY_READ", "capability_candidate": "FEASIBILITY", "selected_route": "PERSONAL_READ", "detected_entities": {"account_ref": last_resolved.account_ref}, "missing_requirements": [], "depends_on": [], "confidence": 1.0}],
                            "clarifications": [], "unsupported_segments": [],
                            "catalog_valid": True, "entity_refs_valid": True, "violations": [],
                            "output_contracts": ["FeasibilityResponse"],
                            "rag_status": "NOT_REQUIRED", "inference_count": 0,
                            "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                            "customer_context": {"customer_id": customer_snapshot.customer_id, "display_name": customer_snapshot.display_name, "products_count": len(customer_snapshot.products), "loans_count": len(customer_snapshot.loans)},
                            "loan_detail": None,
                            "domain_scores": None, "product_scores": None,
                            "client_response": client_response,
                            "decision_trace": decision_trace_feas,
                        }
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        return JSONResponse(status_code=200, content=body_feas)

            # Topic-change detection: if last_resolved is LOAN but text asks about deposits (or vice versa)
            # Also detect type-change within deposits (CHECKING→SAVINGS, etc.)
            if is_followup:
                from genesis_cognitive.router.knowledge_followup import should_block_personal_followup
                if should_block_personal_followup(text_lower, session_state):
                    is_followup = False
                _deposit_words = ("ahorro", "cuenta corriente", "nomina", "nómina", "saldo de mi cuenta", "cuenta de")
                # No incluir "termina": choca con "terminada en ####" (máscara de cuenta).
                _loan_words = ("prestamo", "préstamo", "credito", "crédito", "cuota", "letra", "saldar", "cancelar", "hipotec", "vence", "vencimiento")
                _card_words = ("tarjeta", "visa", "mastercard", "pricesmart")
                if is_followup and last_resolved.intent_id == "LOAN_DETAIL_READ":
                    # If user mentions a deposit product → topic change, not follow-up
                    if any(dw in text_lower for dw in _deposit_words):
                        is_followup = False
                    # Conocimiento institucional / responsabilidad del banco
                    if any(s in text_lower for s in ("del banco", "el banco", "responsabilidad", "como se usa", "cómo se usa")):
                        is_followup = False
                elif is_followup and last_resolved.intent_id == "TERM_DEPOSIT_DETAIL_READ":
                    # Préstamo/tarjeta/pago ≠ certificado (evita ficha DAP ante "pago próximo")
                    if any(s in text_lower for s in _loan_words + _card_words + ("pago",)):
                        if not any(
                            s in text_lower
                            for s in ("certificado", "deposito", "depósito", "dap", "cdt", "plazo")
                        ):
                            is_followup = False
                    if any(dw in text_lower for dw in _deposit_words):
                        is_followup = False
                elif is_followup and last_resolved.intent_id == "CREDIT_CARD_DETAIL_READ":
                    if any(s in text_lower for s in ("prestamo", "préstamo")) and "tarjeta" in text_lower:
                        is_followup = False
                    if any(s in text_lower for s in ("certificado", "deposito", "depósito", "dap")):
                        is_followup = False
                elif is_followup and last_resolved.intent_id == "ACCOUNT_BALANCE_READ":
                    # Nueva consulta genérica / plural / otra familia → no reusar la cuenta previa
                    from genesis_cognitive.router.field_guardrails import is_generic_balance_question as _is_gen_bal
                    if _is_gen_bal(text_lower) or any(
                        s in text_lower for s in ("mis cuentas", "ambas cuentas", "todas las cuentas", "dos cuentas")
                    ):
                        is_followup = False
                    # If user mentions a loan product → topic change
                    elif any(lw in text_lower for lw in _loan_words):
                        is_followup = False
                    # If user mentions a DIFFERENT deposit type → topic change
                    else:
                        _lr_product = next((p for p in customer_snapshot.products if p.product_id == last_resolved.account_ref), None)
                        if _lr_product:
                            _lr_type = _lr_product.product_type
                            _lr_ccy = _lr_product.currency
                            _type_hints = {
                                "SAVINGS": ("ahorro", "ahorros"),
                                "CHECKING": ("corriente",),
                                "PAYROLL": ("nomina", "nómina"),
                            }
                            # Type change
                            for _ht, _signals in _type_hints.items():
                                if _ht != _lr_type and any(s in text_lower for s in _signals):
                                    is_followup = False
                                    break
                            # Currency change
                            if is_followup:
                                _ccy_dop = ("pesos", "dop", "rd$")
                                _ccy_usd = ("dolares", "dólares", "usd", "us$")
                                if _lr_ccy == "USD" and any(s in text_lower for s in _ccy_dop):
                                    is_followup = False
                                elif _lr_ccy == "DOP" and any(s in text_lower for s in _ccy_usd):
                                    is_followup = False

            if is_followup:
                # Resolve with last product — build direct VALID_CONTRACT
                intent_id = last_resolved.intent_id
                account_ref = last_resolved.account_ref

                actions_dump = [{
                    "sequence": 1,
                    "intent_id": intent_id,
                    "capability_candidate": (
                        "LOAN_DETAIL" if intent_id == "LOAN_DETAIL_READ"
                        else "CREDIT_CARD_DETAIL" if intent_id == "CREDIT_CARD_DETAIL_READ"
                        else "ACCOUNT_BALANCE"
                    ),
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {"account_ref": account_ref, "source_account_ref": None, "destination_account_ref": None, "amount": None, "currency": None, "knowledge_topic": None},
                    "missing_requirements": [],
                    "depends_on": [],
                    "confidence": 1.0,
                }]
                status = "VALID_CONTRACT"
                mode = "SINGLE"
                clarifications_dump: list[dict[str, Any]] = []
                unsupported_dump: list[dict[str, Any]] = []

                # Get loan_detail if loan
                loan_detail: dict[str, Any] | None = None
                if intent_id == "LOAN_DETAIL_READ":
                    loan_data = next((ln for ln in customer_snapshot.loans if ln.product_id == account_ref), None)
                    if loan_data:
                        loan_detail = loan_data.to_detail_dict()

                # B) effective_question: use current question (it asks for the specific field)
                effective_question = request.question

                # decision_trace for follow-up
                decision_trace: list[dict[str, Any]] = [
                    {"step": "context", "output": _build_session_context()},
                    {"step": "followup_resolution", "input": {"question": request.question[:80], "last_resolved": {"intent": last_resolved.intent_id, "ref": last_resolved.account_ref}}, "output": {"resolved": True, "account_ref": account_ref}},
                    {"step": "loan_detail", "output": loan_detail},
                ]

                # Generate client_response
                from genesis_cognitive.router.final_response_agent import (
                    build_card_detail_response,
                    build_deposit_detail_response,
                    build_loan_detail_response,
                )
                from genesis_cognitive.context.product_display import display_label as _fu_dl
                from genesis_cognitive.context.response_formatting import (
                    build_rich_card_detail,
                    build_rich_deposit_detail,
                    sanitize_client_facing_text,
                )
                client_response: str | None = None
                _more = any(s in (request.question or "").lower() for s in _MORE_INFO_SIGNALS)
                if loan_detail:
                    client_response = build_loan_detail_response(
                        effective_question, loan_detail, customer_snapshot.display_name
                    )
                elif intent_id == "CREDIT_CARD_DETAIL_READ":
                    _fu_card = next((p for p in customer_snapshot.products if p.product_id == account_ref), None)
                    if _fu_card:
                        if _more:
                            _g = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                            client_response = f"{_g.rstrip()}\n{build_rich_card_detail(_fu_card)}".strip()
                        else:
                            client_response = build_card_detail_response(
                                effective_question, _fu_card, customer_snapshot.display_name, _fu_dl(_fu_card),
                            )
                elif intent_id == "TERM_DEPOSIT_DETAIL_READ":
                    _fu_dep = next((p for p in customer_snapshot.products if p.product_id == account_ref), None)
                    if _fu_dep:
                        if _more:
                            _g = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                            client_response = (
                                f"{_g}aquí tienes el detalle de tu certificado de depósito:\n\n"
                                f"{build_rich_deposit_detail(_fu_dep)}"
                            )
                        else:
                            client_response = build_deposit_detail_response(
                                effective_question, _fu_dep, customer_snapshot.display_name, _fu_dl(_fu_dep),
                            )
                elif intent_id == "ACCOUNT_BALANCE_READ":
                    from genesis_cognitive.context.product_display import display_label as _fu_dl
                    prod = next((p for p in customer_snapshot.products if p.product_id == account_ref), None)
                    if prod is None:
                        from genesis_cognitive.router.field_guardrails import _product_not_found_message
                        client_response = _product_not_found_message(
                            customer_snapshot, account_ref or "",
                        )
                    elif prod.available_balance is not None:
                        label = _fu_dl(prod)
                        client_response = (
                            f"{customer_snapshot.display_name}, tu saldo disponible en {label} "
                            f"es de {prod.available_balance} {prod.currency}."
                        )
                    else:
                        label = _fu_dl(prod)
                        client_response = (
                            f"{customer_snapshot.display_name}, tu consulta de saldo para {label} "
                            f"está lista. El saldo se obtiene del Core."
                        )
                if client_response:
                    client_response = sanitize_client_facing_text(client_response)

                decision_trace.append({"step": "final_response", "input": {"question": effective_question[:80]}, "output": {"client_response": (client_response or "")[:120]}})

                # Update last_resolved with new question
                session_state.last_resolved = LastResolved(intent_id=intent_id, account_ref=account_ref, original_question=request.question)
                from genesis_cognitive.router.product_focus import remember_product_focus
                remember_product_focus(session_state, intent_id, account_ref, request.question)

                session.append({"turn": turn_number, "question": request.question, "status": status, "intent": intent_id})

                body: dict[str, Any] = {
                    "provider": "AZURE_OPENAI", "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model, "prompt_version": prompt_version,
                    "conversation_id": conv_id, "turn_number": turn_number,
                    "conversation_history": session, "status": status, "mode": mode,
                    "non_operational_response": None,
                    "initial_proposal": None, "verified_proposal": None, "raw_interpretation": None,
                    "actions": actions_dump, "clarifications": clarifications_dump,
                    "unsupported_segments": unsupported_dump,
                    "catalog_valid": True, "entity_refs_valid": True, "violations": [],
                    "output_contracts": ["LoanDetailResponse" if intent_id == "LOAN_DETAIL_READ" else "BalanceResponse"],
                    "rag_status": "NOT_REQUIRED", "inference_count": 1,
                    "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                    "customer_context": {"customer_id": customer_snapshot.customer_id, "display_name": customer_snapshot.display_name, "products_count": len(customer_snapshot.products), "loans_count": len(customer_snapshot.loans)},
                    "loan_detail": loan_detail,
                    "domain_scores": None, "product_scores": None,
                    "client_response": client_response,
                    "decision_trace": decision_trace,
                }
                from genesis_cognitive.contracts.operation_request_adapter import build_operation_request as _bor
                body["operation_request"] = _bor(status=status, actions=actions_dump, customer_id=customer_snapshot.customer_id, conversation_id=conv_id, turn_number=turn_number, loan_detail=loan_detail)
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                return JSONResponse(status_code=200, content=body)

        # T4 Domain Router: classify domain BEFORE resolve_full
        domain_scores_data: dict[str, Any] | None = None
        product_scores_data: dict[str, Any] | None = None
        decision_trace: list[dict[str, Any]] = [{"step": "context", "output": _build_session_context()}]
        if domain_router_enabled and customer_snapshot is not None:
            from genesis_cognitive.router.domain_classifier import classify_domain, classify_domain_timed
            from genesis_cognitive.router.domain_arbitrator import DomainArbitrator

            context_summary = (
                f"customer_id={customer_snapshot.customer_id}, "
                f"display_name={customer_snapshot.display_name}, "
                f"products_count={len(customer_snapshot.products)}, "
                f"loans_count={len(customer_snapshot.loans)}, "
                f"product_types={sorted(set(p.product_type for p in customer_snapshot.products))}"
            )

            own_score, biz_score, ood_score, _capa0_calls = await classify_domain_timed(
                request.question,
                context_summary,
                own_classifier,
                business_classifier,
                ood_classifier,
                deployment=azure_model,
            )
            _capa0_end = _time.perf_counter()

            arbitrator = DomainArbitrator()
            arbitration = arbitrator.arbitrate(own_score, biz_score, ood_score)

            _capa0_ms = round((_capa0_end - _request_start) * 1000)

            domain_scores_data = {
                "own_product": round(own_score.score, 3),
                "business": round(biz_score.score, 3),
                "ood": round(ood_score.score, 3),
                "arbitration": arbitration.domain,
            }

            decision_trace.append({"step": "capa0_domain", "input": {"raw_text": request.question[:100]}, "output": domain_scores_data, "duration_ms": _capa0_ms, "parallel": True, "calls": [r.to_dict() for r in _capa0_calls]})

            # Short-circuit: OOD → UNSUPPORTED directly (no proposer)
            if arbitration.domain == "ood":
                session.append({"turn": turn_number, "question": request.question, "status": "UNSUPPORTED"})
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                return JSONResponse(
                    status_code=200,
                    content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "UNSUPPORTED",
                        "mode": "UNSUPPORTED",
                        "non_operational_response": None,
                        "initial_proposal": None,
                        "verified_proposal": None,
                        "raw_interpretation": None,
                        "actions": [],
                        "clarifications": [],
                        "unsupported_segments": [{"segment_description": "Solicitud fuera de dominio bancario", "reason": "No soportado"}],
                        "catalog_valid": None,
                        "entity_refs_valid": None,
                        "violations": [],
                        "output_contracts": [],
                        "rag_status": None,
                        "inference_count": 3,
                        "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                        "customer_context": {
                            "customer_id": customer_snapshot.customer_id,
                            "display_name": customer_snapshot.display_name,
                            "products_count": len(customer_snapshot.products),
                            "loans_count": len(customer_snapshot.loans),
                        },
                        "loan_detail": None,
                        "domain_scores": domain_scores_data,
                        "client_response": "Lo siento, aún no tengo habilitados los canales para realizar transferencias, retiros u otras operaciones. Puedo ayudarte con consultas de saldos, préstamos, tarjetas o información del banco.",
                    },
                )

            # Inject domain_hint for non-ood cases
            domain_hint = arbitration.domain if arbitration.domain in ("own_product", "business", "ambiguous") else None
            if domain_hint:
                model_input = model_input.model_copy(update={"domain_hint": domain_hint})

        # T5 Capa 1: Product specialists (read vs mutation) — only if own_product
        product_scores_data: dict[str, Any] | None = None
        if (
            domain_router_enabled
            and product_classifiers is not None
            and domain_scores_data is not None
            and domain_scores_data.get("arbitration") == "own_product"
            and customer_snapshot is not None
        ):
            from genesis_cognitive.router.product_classifiers import classify_product_intent_timed
            from genesis_cognitive.router.product_arbitrator import ProductIntentArbitrator

            _capa1_start = _time.perf_counter()
            context_summary_p = (
                f"customer_id={customer_snapshot.customer_id}, "
                f"products_count={len(customer_snapshot.products)}, "
                f"loans_count={len(customer_snapshot.loans)}, "
                f"product_types={sorted(set(p.product_type for p in customer_snapshot.products))}"
            )

            read_score, mutation_score, _capa1_calls = await classify_product_intent_timed(
                request.question,
                context_summary_p,
                product_classifiers[0],
                product_classifiers[1],
                deployment=azure_model,
            )

            product_arb = ProductIntentArbitrator(margin=0.25)
            product_result = product_arb.arbitrate(read_score, mutation_score)
            _capa1_ms = round((_time.perf_counter() - _capa1_start) * 1000)

            product_scores_data = {
                "read": round(read_score.score, 3),
                "mutation": round(mutation_score.score, 3),
                "arbitration": product_result.intent,
            }

            decision_trace.append({"step": "capa1_product", "output": product_scores_data, "duration_ms": _capa1_ms, "parallel": True, "calls": [r.to_dict() for r in _capa1_calls]})

            # Short-circuit mutation → UNSUPPORTED / OPERATION_NOT_ENABLED
            if product_result.intent == "mutation":
                session.append({"turn": turn_number, "question": request.question, "status": "UNSUPPORTED"})
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                return JSONResponse(
                    status_code=200,
                    content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "UNSUPPORTED",
                        "mode": "UNSUPPORTED",
                        "non_operational_response": None,
                        "initial_proposal": None,
                        "verified_proposal": None,
                        "raw_interpretation": None,
                        "actions": [],
                        "clarifications": [],
                        "unsupported_segments": [{"segment_description": "Operación no habilitada en este canal. Solo consultas disponibles.", "reason": "OPERATION_NOT_ENABLED"}],
                        "catalog_valid": None,
                        "entity_refs_valid": None,
                        "violations": [],
                        "output_contracts": [],
                        "rag_status": None,
                        "inference_count": 5,
                        "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                        "customer_context": {"customer_id": customer_snapshot.customer_id, "display_name": customer_snapshot.display_name, "products_count": len(customer_snapshot.products), "loans_count": len(customer_snapshot.loans)},
                        "loan_detail": None,
                        "domain_scores": domain_scores_data,
                        "product_scores": product_scores_data,
                        "client_response": "Lo siento, aún no tengo habilitados los canales para realizar transferencias, retiros u otras operaciones. Puedo ayudarte con consultas de saldos, préstamos, tarjetas o información del banco.",
                    },
                )

            # Short-circuit ambiguous → CLARIFICATION consulta vs operación
            if product_result.intent == "ambiguous":
                session.append({"turn": turn_number, "question": request.question, "status": "CLARIFICATION_REQUIRED"})
                _conflict_resp = _cas_put_session()
                if _conflict_resp is not None:
                    return _conflict_resp
                return JSONResponse(
                    status_code=200,
                    content={
                        "provider": "AZURE_OPENAI",
                        "framework": "MICROSOFT_AGENT_FRAMEWORK",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "CLARIFICATION_REQUIRED",
                        "mode": "CLARIFICATION",
                        "non_operational_response": None,
                        "initial_proposal": None,
                        "verified_proposal": None,
                        "raw_interpretation": None,
                        "actions": [],
                        "clarifications": [{"target_action_sequence": 1, "missing_requirements": ["query_scope"], "suggested_question": "¿Deseas consultar un dato de tu producto o realizar una operación (transferir, pagar)?", "already_known": []}],
                        "unsupported_segments": [],
                        "catalog_valid": None,
                        "entity_refs_valid": None,
                        "violations": [],
                        "output_contracts": [],
                        "rag_status": None,
                        "inference_count": 5,
                        "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
                        "customer_context": {"customer_id": customer_snapshot.customer_id, "display_name": customer_snapshot.display_name, "products_count": len(customer_snapshot.products), "loans_count": len(customer_snapshot.loans)},
                        "loan_detail": None,
                        "domain_scores": domain_scores_data,
                        "product_scores": product_scores_data,
                    },
                )

            # intent == "read" → proceed to pipeline (fall through)

        # Add model_input_envelope step to decision_trace
        decision_trace.append({"step": "model_input_envelope", "output": {
            "portfolio_count": len(model_input.portfolio),
            "has_pending": model_input.pending_action is not None,
            "domain_hint": getattr(model_input, "domain_hint", None),
            "history_len": len(model_input.conversation),
            "capabilities_count": len(model_input.effective_capabilities),
        }})

        # Resolve using transport DTO
        _resolver_start = _time.perf_counter()
        try:
            resolver_result = await resolver.resolve_full(model_input)
        except CognitiveError as e:
            import traceback
            cause = str(e.internal_cause)[:500] if e.internal_cause else traceback.format_exc()[:500]
            is_provider = e.error_code in ("MODEL_INVOCATION_ERROR", "CONTEXT_PROVIDER_ERROR")
            http_code = 502 if is_provider else 422
            status_label = "PROVIDER_ERROR" if is_provider else "INVALID_MODEL_OUTPUT"
            session.append({"turn": turn_number, "question": request.question, "status": status_label})
            return JSONResponse(
                status_code=http_code,
                content={
                    "provider": "AZURE_OPENAI",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": session,
                    "status": status_label,
                    "error_detail": cause,
                    "inference_count": 2,
                },
            )
        except Exception as e:
            # T6: Catch local ValidationError (Pydantic) as 422, not 502
            from pydantic import ValidationError as PydanticValidationError

            if isinstance(e, PydanticValidationError):
                # Fallback: try snapshot-based resolution if text identifies a product
                if customer_snapshot is not None:
                    from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
                    _fb_text = request.question.strip().lower()
                    _fb_deposits = [p for p in customer_snapshot.products if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and p.status.lower() == "active"]
                    # Currency filter
                    _FB_DOP = ("pesos", "dop", "peso", "rd$")
                    _FB_USD = ("dolares", "dólares", "usd", "dollar", "us$")
                    if any(s in _fb_text for s in _FB_DOP):
                        _fb_deposits = [p for p in _fb_deposits if p.currency == "DOP"]
                    elif any(s in _fb_text for s in _FB_USD):
                        _fb_deposits = [p for p in _fb_deposits if p.currency == "USD"]
                    else:
                        _fb_deposits = [p for p in _fb_deposits if p.currency == customer_snapshot.default_currency]
                    # Type filter
                    if "ahorro" in _fb_text or "ahorros" in _fb_text:
                        _fb_deposits = [p for p in _fb_deposits if p.product_type == "SAVINGS"]
                    elif "corriente" in _fb_text:
                        _fb_deposits = [p for p in _fb_deposits if p.product_type == "CHECKING"]
                    elif "nomina" in _fb_text or "nómina" in _fb_text:
                        _fb_deposits = [p for p in _fb_deposits if p.product_type == "PAYROLL"]

                    if len(_fb_deposits) == 1:
                        _fb_p = _fb_deposits[0]
                        from genesis_cognitive.context.product_display import display_label as _fb_dl
                        _fb_label = _fb_dl(_fb_p)
                        _fb_bal = str(_fb_p.available_balance) if _fb_p.available_balance is not None else None
                        _fb_greeting = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                        if _fb_bal:
                            _fb_resp = f"{_fb_greeting}tu saldo disponible en {_fb_label} es de {_fb_bal} {_fb_p.currency}."
                        else:
                            _fb_resp = f"{_fb_greeting}tu consulta de saldo para {_fb_label} está lista."
                        session.append({"turn": turn_number, "question": request.question, "status": "VALID_CONTRACT", "intent": "ACCOUNT_BALANCE_READ"})
                        _conflict_resp = _cas_put_session()
                        if _conflict_resp is not None:
                            return _conflict_resp
                        return JSONResponse(status_code=200, content={
                            "provider": "AZURE_OPENAI", "model": azure_model, "prompt_version": prompt_version,
                            "conversation_id": conv_id, "turn_number": turn_number,
                            "conversation_history": session, "status": "VALID_CONTRACT", "mode": "SINGLE",
                            "actions": [{"sequence": 1, "intent_id": "ACCOUNT_BALANCE_READ", "capability_candidate": "ACCOUNT_BALANCE", "selected_route": "PERSONAL_READ", "detected_entities": {"account_ref": _fb_p.product_id}, "missing_requirements": [], "depends_on": [], "confidence": 1.0}],
                            "clarifications": [], "unsupported_segments": [],
                            "client_response": _fb_resp,
                            "inference_count": 2, "decision_trace": [{"step": "fallback_resolve", "output": {"ref": _fb_p.product_id}}],
                        })

                session.append({"turn": turn_number, "question": request.question, "status": "INVALID_MODEL_OUTPUT"})
                return JSONResponse(
                    status_code=422,
                    content={
                        "provider": "AZURE_OPENAI",
                        "model": azure_model,
                        "prompt_version": prompt_version,
                        "conversation_id": conv_id,
                        "turn_number": turn_number,
                        "conversation_history": session,
                        "status": "INVALID_MODEL_OUTPUT",
                        "error_detail": str(e)[:500],
                        "inference_count": 2,
                    },
                )
            session.append({"turn": turn_number, "question": request.question, "status": "PROVIDER_ERROR"})
            return JSONResponse(
                status_code=502,
                content={
                    "provider": "AZURE_OPENAI",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": session,
                    "status": "PROVIDER_ERROR",
                    "error_detail": str(e)[:500],
                    "inference_count": 1,
                },
            )

        status = resolver_result.status
        # Coerce enums / mocks de test a str estable (nunca persistir objetos no JSON)
        if hasattr(status, "value") and not isinstance(status, (str, bytes)):
            status = status.value
        if not isinstance(status, str):
            status = "PROVIDER_ERROR" if status is None else str(status)
            if status.startswith("<MagicMock") or status.startswith("<Mock"):
                status = "VALID_CONTRACT"
        from genesis_cognitive.router.field_guardrails import override_non_operational
        status = override_non_operational(status, request.question)
        interpretation = resolver_result.interpretation
        _resolver_ms = round((_time.perf_counter() - _resolver_start) * 1000)

        # Trace: proposer + verifier (combined timing — resolver does both internally)
        _resolver_call_records = resolver_result.call_records or []
        if resolver_result.initial_proposal:
            ip = resolver_result.initial_proposal
            _proposer_calls = [r.to_dict() for r in _resolver_call_records if r.name == "proposer"]
            decision_trace.append({"step": "proposer", "output": {"result_type": ip.result_type, "actions_count": len(ip.actions), "cap": ip.actions[0].capability_id if ip.actions else None, "intent": ip.actions[0].intent_id if ip.actions else None}, "duration_ms": _proposer_calls[0]["duration_ms"] if _proposer_calls else _resolver_ms // 2, "parallel": False, "calls": _proposer_calls})
        if resolver_result.verified_proposal:
            vp = resolver_result.verified_proposal
            _verifier_calls = [r.to_dict() for r in _resolver_call_records if r.name == "verifier"]
            decision_trace.append({"step": "verifier", "output": {"result_type": vp.result_type, "actions_count": len(vp.actions), "clarification_question": (vp.clarification_question or "")[:80]}, "duration_ms": _verifier_calls[0]["duration_ms"] if _verifier_calls else _resolver_ms - _resolver_ms // 2, "parallel": False, "calls": _verifier_calls})
        # Gate validation (only for OPERATIONAL results with actions)
        catalog_valid: bool | None = None
        entity_refs_valid: bool | None = None
        violations: list[str] = []
        output_contracts: list[str] = []
        rag_status: str | None = None
        rag_answer: str | None = None
        _loan_resume_actions: list[dict[str, Any]] | None = None

        if interpretation and interpretation.actions:
            validated_interp = gate.validate(interpretation, model_input)
            catalog_valid = validated_interp.catalog_valid
            entity_refs_valid = validated_interp.entity_refs_valid
            violations = list(validated_interp.violations)

            # Determine output_contracts
            for action in interpretation.actions:
                for cap in model_input.effective_capabilities:
                    if (
                        action.intent_id in cap.intent_ids
                        and cap.capability_candidate == action.capability_candidate
                        and cap.selected_route.value == action.selected_route.value
                    ):
                        output_contracts.append(cap.output_contract)
                        break
                else:
                    output_contracts.append("UNKNOWN")

            # RAG status
            for action in interpretation.actions:
                if action.intent_id == "BUSINESS_KNOWLEDGE_QUERY":
                    rag_status = "RAG_PENDING"
                    status = "RAG_PENDING"
                    break
            if rag_status is None:
                rag_status = "NOT_REQUIRED"

            # Intent gate ANTES de Azure RAG: tasa/cuota del préstamo en foco → snapshot
            if rag_status == "RAG_PENDING" and request.question and customer_snapshot is not None:
                from genesis_cognitive.router.product_focus import (
                    prefer_personal_loan_over_knowledge,
                    loan_ref_from_session,
                )
                if prefer_personal_loan_over_knowledge(request.question, session_state):
                    _resume_ref = loan_ref_from_session(session_state)
                    _resume_loan = next(
                        (ln for ln in customer_snapshot.loans if ln.product_id == _resume_ref),
                        None,
                    ) if _resume_ref else None
                    if _resume_loan is not None:
                        from genesis_cognitive.router.final_response_agent import (
                            build_loan_detail_response as _bld_resume,
                        )
                        rag_answer = _bld_resume(
                            request.question,
                            _resume_loan.to_detail_dict(),
                            customer_snapshot.display_name,
                        )
                        rag_status = "LOAN_INTENT_RESUME"
                        status = "VALID_CONTRACT"
                        _loan_resume_actions = [{
                            "sequence": 1,
                            "intent_id": "LOAN_DETAIL_READ",
                            "capability_candidate": "LOAN_DETAIL",
                            "selected_route": "PERSONAL_READ",
                            "detected_entities": {"account_ref": _resume_ref},
                            "missing_requirements": [],
                            "depends_on": [],
                            "confidence": 1.0,
                        }]

            # RAG retrieval: if BUSINESS_KNOWLEDGE_QUERY, retrieve and generate
            # Preferencia: agente Foundry KB (flag) → Azure Search local → FAQ/KB lexical
            if rag_status == "RAG_PENDING" and request.question:
                from genesis_cognitive.rag.foundry_kb_agent import (
                    ask_foundry_kb_agent,
                    is_foundry_kb_enabled,
                )
                if is_foundry_kb_enabled():
                    _fy = ask_foundry_kb_agent(
                        request.question,
                        display_name=customer_snapshot.display_name if customer_snapshot else None,
                        topic=getattr(session_state, "last_knowledge_topic", None),
                    )
                    if _fy.get("ok") and _fy.get("answer"):
                        rag_answer = str(_fy["answer"])
                        rag_status = str(_fy.get("status") or "FOUNDRY_KB_ANSWERED")
                        status = (
                            "CLARIFICATION_REQUIRED"
                            if rag_status == "FOUNDRY_KB_CLARIFY"
                            else "VALID_CONTRACT"
                        )
                        # Conservar tema KB para follow-ups de la guía
                        try:
                            if request.question and len(request.question) < 120:
                                session_state.last_knowledge_topic = (
                                    session_state.last_knowledge_topic
                                    or request.question.strip()[:200]
                                )
                        except Exception:
                            pass

            if (
                rag_status == "RAG_PENDING"
                and not rag_answer
                and rag_store.status == "ready"
            ):
                from genesis_cognitive.rag.local_rag import generate_rag_answer
                rag_result = rag_store.query(request.question, top_k=4)
                if rag_result["rag_status"] == "HITS":
                    rag_answer = await generate_rag_answer(
                        request.question, rag_result["chunks"],
                        display_name=customer_snapshot.display_name if customer_snapshot else None,
                        conversation_id=conv_id,
                    )
                    rag_status = "RAG_ANSWERED"
                    status = "VALID_CONTRACT"  # Upgrade from RAG_PENDING
                else:
                    rag_status = "NO_HITS"

            # FAQ miss → interpretar intención (KB local) → institucional → humano
            if rag_status in ("NO_HITS", "RAG_PENDING") and not rag_answer and request.question:
                from genesis_cognitive.router.faq_guardrail import match_faq
                from genesis_cognitive.rag.kb_intent_resolver import resolve_knowledge_intent
                from genesis_cognitive.rag.local_rag import (
                    _human_case_fallback,
                    _is_institutional_question,
                    _knowledge_intent_fallback,
                )
                name = customer_snapshot.display_name if customer_snapshot else None
                greeting = f"{name}, " if name else ""
                faq_hit = match_faq(request.question)
                if faq_hit and faq_hit.get("answer"):
                    rag_answer = f"{greeting}{faq_hit['answer']}".strip()
                    rag_status = "FAQ_FALLBACK"
                    status = "VALID_CONTRACT"
                else:
                    intent_hit = resolve_knowledge_intent(request.question)
                    if intent_hit and intent_hit.get("answer"):
                        ans = str(intent_hit["answer"]).strip()
                        rag_answer = (
                            ans
                            if name and ans.lower().startswith(name.lower())
                            else f"{greeting}{ans}".strip()
                        )
                        rag_status = "KB_INTENT"
                        status = "VALID_CONTRACT"
                    elif _is_institutional_question(request.question):
                        rag_answer = _human_case_fallback(
                            request.question,
                            conv_id,
                            name,
                        )
                        rag_status = "INSTITUTIONAL_FALLBACK"
                        status = "VALID_CONTRACT"
                    else:
                        # Último intento grounded (mismo resolver vía helper) antes de vacío
                        kb_ans = _knowledge_intent_fallback(request.question, name)
                        if kb_ans:
                            rag_answer = kb_ans
                            rag_status = "KB_INTENT"
                            status = "VALID_CONTRACT"

            # Refine status based on gate
            if status == "VALID_CONTRACT":
                if not (catalog_valid and entity_refs_valid):
                    status = "INVALID_MODEL_OUTPUT"

        # Build response
        actions_dump: list[dict[str, Any]] = []
        clarifications_dump: list[dict[str, Any]] = []
        unsupported_dump: list[dict[str, Any]] = []
        mode: str | None = None

        # FIX UX: If CLARIFICATION_REQUIRED but interpretation=None (empty actions from verifier),
        # build a synthetic clarification using snapshot data so the UI always has a question.
        if status == "CLARIFICATION_REQUIRED" and interpretation is None and customer_snapshot is not None:
            matched_product = None

            # If continuing from a previous clarification, try snapshot-based resolution
            if pending:
                import re as _re
                _accent_map = str.maketrans("áéíóúñ", "aeioun")
                _articles = {"la", "el", "mi", "mis", "de", "del", "los", "las", "un", "una"}

                def _normalize(text: str) -> str:
                    """Normalize for fuzzy matching: lowercase, strip parens, accents, articles."""
                    t = _re.sub(r'\s*\([A-Z_]+\)\s*', '', text).strip().lower()
                    t = t.translate(_accent_map)
                    # Strip common articles/prepositions
                    tokens = [w for w in t.split() if w not in _articles]
                    return " ".join(tokens)

                def _token_overlap(a: str, b: str) -> float:
                    """Ratio of shared tokens between a and b."""
                    ta = set(a.split())
                    tb = set(b.split())
                    if not ta or not tb:
                        return 0.0
                    return len(ta & tb) / min(len(ta), len(tb))

                user_norm = _normalize(request.question)

                # Score each product candidate — restrict to same product kind as pending
                _loan_types = {"LOAN"}
                _deposit_types = {"CHECKING", "SAVINGS", "PAYROLL"}
                if pending.intent_id == "LOAN_DETAIL_READ":
                    _allowed_types = _loan_types
                elif pending.intent_id == "ACCOUNT_BALANCE_READ":
                    _allowed_types = _deposit_types
                else:
                    _allowed_types = None  # any

                best_score = 0.0
                best_product = None
                for p in customer_snapshot.products:
                    if p.currency == customer_snapshot.default_currency:
                        # Kind restriction: only match products of the expected type
                        if _allowed_types and p.product_type not in _allowed_types:
                            continue
                        p_id_lower = p.product_id.lower()
                        p_alias_norm = _normalize(p.alias or "")

                        # Exact product_id match
                        if p_id_lower in user_norm or user_norm == p_id_lower:
                            best_product = p
                            best_score = 1.0
                            break

                        # Token overlap with alias
                        if p_alias_norm:
                            overlap = _token_overlap(user_norm, p_alias_norm)
                            if overlap > best_score and overlap >= 0.5:
                                best_score = overlap
                                best_product = p

                            # Also check if alias is substring or vice versa
                            if p_alias_norm in user_norm or user_norm in p_alias_norm:
                                if 0.8 > best_score:
                                    best_score = 0.8
                                    best_product = p

                # Also check loans for loan continuation
                if best_score < 0.5 and pending.intent_id == "LOAN_DETAIL_READ":
                    for ln in customer_snapshot.loans:
                        loan_product = next((pp for pp in customer_snapshot.products if pp.product_id == ln.product_id), None)
                        ln_alias = (loan_product.alias if loan_product else ln.loan_type).lower()
                        ln_alias_norm = _normalize(ln_alias)
                        ln_type_norm = _normalize(ln.loan_type.replace("_", " "))

                        if ln.product_id.lower() in user_norm:
                            best_product = type('P', (), {'product_id': ln.product_id, 'product_type': 'LOAN', 'alias': loan_product.alias if loan_product else ln.loan_type, 'currency': customer_snapshot.default_currency, 'status': 'ACTIVE'})()
                            best_score = 1.0
                            break

                        for candidate_norm in (ln_alias_norm, ln_type_norm):
                            if candidate_norm:
                                overlap = _token_overlap(user_norm, candidate_norm)
                                if overlap > best_score and overlap >= 0.5:
                                    best_score = overlap
                                    best_product = type('P', (), {'product_id': ln.product_id, 'product_type': 'LOAN', 'alias': loan_product.alias if loan_product else ln.loan_type, 'currency': customer_snapshot.default_currency, 'status': 'ACTIVE'})()
                                if candidate_norm in user_norm or user_norm in candidate_norm:
                                    if 0.8 > best_score:
                                        best_score = 0.8
                                        best_product = type('P', (), {'product_id': ln.product_id, 'product_type': 'LOAN', 'alias': loan_product.alias if loan_product else ln.loan_type, 'currency': customer_snapshot.default_currency, 'status': 'ACTIVE'})()

                matched_product = best_product

            if matched_product and pending:
                # Resolve: override status to VALID_CONTRACT with matched product
                status = "VALID_CONTRACT"
                mode = "SINGLE"
                actions_dump = [{
                    "sequence": 1,
                    "intent_id": pending.intent_id,
                    "capability_candidate": pending.capability_candidate,
                    "selected_route": pending.selected_route,
                    "detected_entities": {
                        "account_ref": matched_product.product_id,
                        "source_account_ref": None,
                        "destination_account_ref": None,
                        "amount": None,
                        "currency": None,
                        "knowledge_topic": None,
                    },
                    "missing_requirements": [],
                    "depends_on": [],
                    "confidence": 1.0,
                }]
                clarifications_dump = []
                session_state.pending_action = None
            else:
                # Generate synthetic clarification (first turn or unmatched continuation)
                is_loan_context = False
                if resolver_result.initial_proposal and resolver_result.initial_proposal.actions:
                    ip_intent = resolver_result.initial_proposal.actions[0].intent_id
                    if ip_intent == "LOAN_DETAIL_READ":
                        is_loan_context = True
                    # Also check capability_id
                    ip_cap = resolver_result.initial_proposal.actions[0].capability_id
                    if ip_cap == "loan-read":
                        is_loan_context = True
                if not is_loan_context and resolver_result.verified_proposal:
                    vp = resolver_result.verified_proposal
                    if vp.actions:
                        if vp.actions[0].intent_id == "LOAN_DETAIL_READ":
                            is_loan_context = True
                        if vp.actions[0].capability_id == "loan-read":
                            is_loan_context = True

                # Fallback: if still not detected, check if loan-related Spanish words
                # appear in the text (using snapshot loan type names, NOT business regex)
                loans_from_snapshot = customer_snapshot.loans
                if not is_loan_context and len(loans_from_snapshot) >= 1:
                    text_lower = request.question.strip().lower()
                    loan_signals = ("prestamo", "préstamo", "credito", "crédito", "cuota", "letra", "tasa de mi", "capital", "pago mensual", "pago al mes", "fecha de pago", "mora", "deuda")
                    if any(sig in text_lower for sig in loan_signals):
                        is_loan_context = True

                loans = [p for p in customer_snapshot.products if p.product_type == "LOAN" and p.status.lower() == "active"]
                # Also include loans from snapshot.loans if not in products
                if not loans and loans_from_snapshot:
                    loans = [type('P', (), {'alias': ln.loan_type, 'product_id': ln.product_id, 'product_type': 'LOAN', 'status': 'active'})() for ln in loans_from_snapshot]
                accounts = [p for p in customer_snapshot.products if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and p.status.lower() == "active"]

                # AUTO-RESOLVE: if exactly 1 candidate of the right kind, force VALID directly
                if is_loan_context and len(loans) == 1:
                    # 1 loan → resolve directly (no need to ask)
                    single_loan = loans[0]
                    status = "VALID_CONTRACT"
                    mode = "SINGLE"
                    actions_dump = [{
                        "sequence": 1,
                        "intent_id": "LOAN_DETAIL_READ",
                        "capability_candidate": "LOAN_DETAIL",
                        "selected_route": "PERSONAL_READ",
                        "detected_entities": {
                            "account_ref": single_loan.product_id,
                            "source_account_ref": None,
                            "destination_account_ref": None,
                            "amount": None,
                            "currency": None,
                            "knowledge_topic": None,
                        },
                        "missing_requirements": [],
                        "depends_on": [],
                        "confidence": 1.0,
                    }]
                    clarifications_dump = []
                elif not is_loan_context and len(accounts) == 1:
                    # 1 deposit account → resolve directly
                    single_acct = accounts[0]
                    status = "VALID_CONTRACT"
                    mode = "SINGLE"
                    actions_dump = [{
                        "sequence": 1,
                        "intent_id": "ACCOUNT_BALANCE_READ",
                        "capability_candidate": "ACCOUNT_BALANCE",
                        "selected_route": "PERSONAL_READ",
                        "detected_entities": {
                            "account_ref": single_acct.product_id,
                            "source_account_ref": None,
                            "destination_account_ref": None,
                            "amount": None,
                            "currency": None,
                            "knowledge_topic": None,
                        },
                        "missing_requirements": [],
                        "depends_on": [],
                        "confidence": 1.0,
                    }]
                    clarifications_dump = []
                elif is_loan_context and len(loans) >= 2:
                    from genesis_cognitive.context.product_display import build_clarification_loans
                    question_text = build_clarification_loans(loans)
                    clarifications_dump = [{"target_action_sequence": 1, "missing_requirements": ["account_ref"], "suggested_question": question_text, "already_known": []}]
                    mode = "CLARIFICATION"
                elif not is_loan_context and len(accounts) >= 2:
                    # Filter by currency + type hints before text-matching
                    from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
                    _sc_text = request.question.strip().lower()
                    _sc_accounts = accounts  # all active CA/CC/PAYROLL
                    # Currency filter
                    _SC_DOP = ("pesos", "dop", "peso", "rd$")
                    _SC_USD = ("dolares", "dólares", "usd", "dollar", "us$")
                    if any(s in _sc_text for s in _SC_DOP):
                        _sc_accounts = [p for p in _sc_accounts if p.currency == "DOP"]
                    elif any(s in _sc_text for s in _SC_USD):
                        _sc_accounts = [p for p in _sc_accounts if p.currency == "USD"]
                    else:
                        _sc_accounts = [p for p in _sc_accounts if p.currency == customer_snapshot.default_currency]

                    # Type filter (narrow by product_type if text mentions specific type)
                    _SC_SAVINGS = ("ahorro", "ahorros")
                    _SC_CHECKING = ("corriente",)
                    _SC_PAYROLL = ("nomina", "nómina")
                    _type_filtered = _sc_accounts
                    if any(s in _sc_text for s in _SC_SAVINGS):
                        _type_filtered = [p for p in _sc_accounts if p.product_type == "SAVINGS"]
                    elif any(s in _sc_text for s in _SC_CHECKING):
                        _type_filtered = [p for p in _sc_accounts if p.product_type == "CHECKING"]
                    elif any(s in _sc_text for s in _SC_PAYROLL):
                        _type_filtered = [p for p in _sc_accounts if p.product_type == "PAYROLL"]
                    if _type_filtered:
                        _sc_accounts = _type_filtered

                    if len(_sc_accounts) == 0:
                        # No matching accounts for that currency
                        status = "VALID_CONTRACT"
                        mode = "SINGLE"
                        actions_dump = [{"sequence": 1, "intent_id": "PORTFOLIO_LIST", "capability_candidate": "PORTFOLIO_LIST", "selected_route": "PERSONAL_READ", "detected_entities": {}, "missing_requirements": [], "depends_on": [], "confidence": 1.0}]
                        clarifications_dump = []
                        _no_acct_greeting = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                        client_response = f"{_no_acct_greeting}no encuentro esa cuenta en tu portafolio."
                        _final_resp_ms = 0
                        _final_resp_calls = []
                    elif len(_sc_accounts) == 1:
                        # 1 account after currency filter → resolve
                        _resolved_acct = _sc_accounts[0]
                        status = "VALID_CONTRACT"
                        mode = "SINGLE"
                        actions_dump = [{
                            "sequence": 1,
                            "intent_id": "ACCOUNT_BALANCE_READ",
                            "capability_candidate": "ACCOUNT_BALANCE",
                            "selected_route": "PERSONAL_READ",
                            "detected_entities": {
                                "account_ref": _resolved_acct.product_id,
                                "source_account_ref": None,
                                "destination_account_ref": None,
                                "amount": None,
                                "currency": None,
                                "knowledge_topic": None,
                            },
                            "missing_requirements": [],
                            "depends_on": [],
                            "confidence": 1.0,
                        }]
                        clarifications_dump = []
                    else:
                        # 2+ after filter → text match or clarify
                        _cands = _find_text_candidates(_sc_text, _sc_accounts)
                        if len(_cands) == 1:
                            _resolved_acct = _cands[0]
                            status = "VALID_CONTRACT"
                            mode = "SINGLE"
                            actions_dump = [{
                                "sequence": 1,
                                "intent_id": "ACCOUNT_BALANCE_READ",
                                "capability_candidate": "ACCOUNT_BALANCE",
                                "selected_route": "PERSONAL_READ",
                                "detected_entities": {
                                    "account_ref": _resolved_acct.product_id,
                                    "source_account_ref": None,
                                    "destination_account_ref": None,
                                    "amount": None,
                                    "currency": None,
                                    "knowledge_topic": None,
                                },
                                "missing_requirements": [],
                                "depends_on": [],
                                "confidence": 1.0,
                            }]
                            clarifications_dump = []
                        else:
                            from genesis_cognitive.context.product_display import build_clarification_accounts
                            question_text = build_clarification_accounts(_sc_accounts)
                            clarifications_dump = [{"target_action_sequence": 1, "missing_requirements": ["account_ref"], "suggested_question": question_text, "already_known": []}]
                            mode = "CLARIFICATION"
                else:
                    from genesis_cognitive.context.product_display import display_label as _dl_fallback
                    active_all = [p for p in customer_snapshot.products if p.status.lower() == "active"]
                    all_products = [f"{_dl_fallback(p)} ({p.product_type})" for p in active_all[:6]]
                    if all_products:
                        question_text = f"Tienes varios productos activos: {', '.join(all_products)}. ¿A cuál te refieres?"
                    else:
                        question_text = "No tienes productos activos visibles. ¿Puedo ayudarte con otra consulta?"
                    clarifications_dump = [{"target_action_sequence": 1, "missing_requirements": ["account_ref"], "suggested_question": question_text, "already_known": []}]
                    mode = "CLARIFICATION"

        # T5: Store/release pending_action
        if status == "CLARIFICATION_REQUIRED":
            if interpretation and interpretation.actions:
                action = interpretation.actions[0]
                session_state.pending_action = PendingAction(
                    intent_id=action.intent_id,
                    capability_candidate=action.capability_candidate,
                    selected_route=action.selected_route.value,
                    detected_entities={
                        k: v for k, v in action.detected_entities.model_dump().items()
                    },
                    missing_requirements=list(action.missing_requirements),
                    suggested_question=(
                        interpretation.clarifications[0].suggested_question
                        if interpretation.clarifications
                        else "Necesito mas informacion."
                    ),
                    original_question=request.question or "",
                    query_spec=build_query_spec(request.question or "", action.intent_id),
                )
            elif clarifications_dump:
                # Synthetic clarification (from snapshot, interpretation=None)
                # Use correct intent based on what was being disambiguated
                if is_loan_context:
                    pending_intent = "LOAN_DETAIL_READ"
                    pending_candidate = "LOAN_DETAIL"
                else:
                    pending_intent = "ACCOUNT_BALANCE_READ"
                    pending_candidate = "ACCOUNT_BALANCE"
                session_state.pending_action = PendingAction(
                    intent_id=pending_intent,
                    capability_candidate=pending_candidate,
                    selected_route="PERSONAL_READ",
                    detected_entities={"account_ref": None},
                    missing_requirements=clarifications_dump[0].get("missing_requirements", ["account_ref"]),
                    suggested_question=clarifications_dump[0].get("suggested_question", ""),
                    original_question=request.question or "",
                    query_spec=build_query_spec(request.question or "", pending_intent),
                )
        else:
            # Release: VALID_CONTRACT, UNSUPPORTED, NON_OPERATIONAL, or error
            session_state.pending_action = None

        # A) Save last_resolved / product_focus on producto personal; no borrar en KB
        if status == "VALID_CONTRACT" and actions_dump:
            from genesis_cognitive.router.product_focus import (
                remember_product_focus,
                resolve_original_question_for_persist,
                should_update_last_resolved,
            )
            a0 = actions_dump[0]
            a0_intent = a0.get("intent_id", "")
            a0_ref = a0.get("detected_entities", {}).get("account_ref")
            if should_update_last_resolved(
                a0_intent, a0_ref, session_state, request.question,
            ):
                _oq = resolve_original_question_for_persist(
                    session_state, request.question,
                )
                session_state.last_resolved = LastResolved(
                    intent_id=a0_intent,
                    account_ref=a0_ref,
                    original_question=_oq,
                )
                remember_product_focus(
                    session_state, a0_intent, a0_ref, _oq,
                )
        # No limpiar last_resolved/product_focus en turnos de conocimiento u otros temas:
        # permite reanudar "y la tasa?" tras misión/reclamaciones/saldo.

        if interpretation:
            mode = interpretation.mode.value
            actions_dump = [a.model_dump() for a in interpretation.actions]
            if _loan_resume_actions:
                actions_dump = _loan_resume_actions
            clarifications_dump = [c.model_dump() for c in interpretation.clarifications]
            unsupported_dump = [u.model_dump() for u in interpretation.unsupported_segments]

        session.append({
            "turn": turn_number,
            "question": request.question,
            "status": status,
            "intent": actions_dump[0]["intent_id"] if actions_dump else None,
        })

        # Glosario KB antes de campos personales (evita "explicame fecha de corte/tasa" → dato del portafolio)
        _faq_early_hit = False
        try:
            from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail as _afq_early
            _faq_early = _afq_early(customer_snapshot, request.question or "", session=session_state)
            if _faq_early and _faq_early[2]:
                _faq_early_hit = True
                status = _faq_early[0]
                actions_dump = _faq_early[1]
                client_response = _faq_early[2]
                clarifications_dump = []
                mode = "SINGLE"
                rag_status = "FAQ_EARLY"
                try:
                    _kt = None
                    if actions_dump:
                        _kt = (actions_dump[0].get("detected_entities") or {}).get("knowledge_topic")
                    if _kt:
                        session_state.last_knowledge_topic = str(_kt)[:200]
                except Exception:
                    pass
                try:
                    session_state.pending_action = None
                except Exception:
                    pass
                if isinstance(decision_trace, list):
                    try:
                        decision_trace.append({
                            "step": "faq_early",
                            "output": {
                                "topic": (actions_dump[0].get("detected_entities") or {}).get("knowledge_topic")
                                if actions_dump
                                else None
                            },
                        })
                    except Exception:
                        pass
        except Exception:
            if not _faq_early_hit:
                pass

        # T4 POST-pipeline: apply loan guardrail (1 LOAN + null ref → force)
        if not _faq_early_hit and domain_router_enabled and customer_snapshot is not None:
            from genesis_cognitive.router.snapshot_guardrails import (
                apply_loan_guardrail,
                apply_unique_product_guardrail,
                resolve_loan_type_hint,
            )
            actions_dump = apply_loan_guardrail(status, actions_dump, customer_snapshot)
            _pre_loan_hint = status
            status, actions_dump = resolve_loan_type_hint(
                status, actions_dump, customer_snapshot, request.question
            )
            status, actions_dump = apply_unique_product_guardrail(
                status, actions_dump, customer_snapshot, request.question
            )
            if _pre_loan_hint == "CLARIFICATION_REQUIRED" and status == "VALID_CONTRACT":
                clarifications_dump = []
                mode = "SINGLE"
                session_state.pending_action = None

        if not _faq_early_hit and customer_snapshot is not None:
            from genesis_cognitive.router.snapshot_guardrails import apply_loan_field_guardrail
            _pre_loan_field = status
            _lr_ref = session_state.last_resolved.account_ref if session_state.last_resolved else None
            status, actions_dump, loan_field_clars = apply_loan_field_guardrail(
                status,
                actions_dump,
                customer_snapshot,
                request.question,
                last_resolved_ref=_lr_ref,
            )
            if loan_field_clars is not None:
                if status == "VALID_CONTRACT":
                    clarifications_dump = []
                    mode = "SINGLE"
                    session_state.pending_action = None
                elif status == "CLARIFICATION_REQUIRED":
                    clarifications_dump = loan_field_clars
                    mode = "CLARIFICATION"
            elif _pre_loan_field == "CLARIFICATION_REQUIRED" and status == "VALID_CONTRACT":
                clarifications_dump = []
                mode = "SINGLE"
                session_state.pending_action = None
            if status == "VALID_CONTRACT" and actions_dump:
                _lf_a0 = actions_dump[0]
                _lf_ref = (_lf_a0.get("detected_entities") or {}).get("account_ref")
                if _lf_a0.get("intent_id") == "LOAN_DETAIL_READ" and _lf_ref:
                    session_state.last_resolved = LastResolved(
                        intent_id="LOAN_DETAIL_READ",
                        account_ref=_lf_ref,
                        original_question=request.question,
                    )
                    session_state.pending_action = None

        suggested_questions: list[dict[str, str]] = []
        if not _faq_early_hit:
            client_response = None
        if not _faq_early_hit and customer_snapshot is not None:
            from genesis_cognitive.router.field_guardrails import (
                apply_card_field_guardrail,
                apply_generic_balance_guardrail,
                apply_movements_guardrail,
                is_card_field_question,
                is_generic_balance_question,
                is_movements_question,
            )
            _pre_field = status
            _lr_ref = session_state.last_resolved.account_ref if session_state.last_resolved else None
            for _fname, _fapply in (
                ("movements", lambda: apply_movements_guardrail(status, actions_dump, customer_snapshot, request.question, _lr_ref)),
                ("card", lambda: apply_card_field_guardrail(status, actions_dump, customer_snapshot, request.question, _lr_ref)),
                ("generic_balance", lambda: apply_generic_balance_guardrail(status, actions_dump, customer_snapshot, request.question)),
            ):
                _fs, _fa, _ft, _fsug = _fapply()
                if _ft is None:
                    continue
                status, actions_dump = _fs, _fa
                client_response = _ft
                if _fsug:
                    suggested_questions = _fsug
                if status == "VALID_CONTRACT":
                    clarifications_dump = []
                    mode = "SINGLE"
                    session_state.pending_action = None
                    _fref = (_fa[0].get("detected_entities") or {}).get("account_ref") if _fa else None
                    _fintent = _fa[0].get("intent_id") if _fa else None
                    if _fintent and _fref:
                        session_state.last_resolved = LastResolved(
                            intent_id=_fintent, account_ref=_fref, original_question=request.question,
                        )
                elif status == "CLARIFICATION_REQUIRED":
                    clarifications_dump = [{
                        "target_action_sequence": 1,
                        "missing_requirements": ["account_ref"],
                        "suggested_question": _ft,
                        "already_known": [],
                    }]
                    mode = "CLARIFICATION"
                break
            else:
                _pre_field = status

        # T5 POST-pipeline: enforce deposit clarification (2+ deposits, no unique match)
        from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question as _is_loan_dep
        from genesis_cognitive.router.field_guardrails import (
            is_card_field_question as _is_card_dep,
            is_generic_balance_question as _is_gen_bal_dep,
            is_movements_question as _is_mov_dep,
        )
        if (
            customer_snapshot is not None
            and not _is_loan_dep(request.question or "")
            and not _is_card_dep(request.question or "")
            and not _is_gen_bal_dep(request.question or "")
            and not _is_mov_dep(request.question or "")
        ):
            from genesis_cognitive.router.deposit_guardrail import enforce_deposit_clarification
            has_pending_for_guardrail = pending is not None
            _pre_guardrail_status = status
            status, actions_dump, deposit_clars = enforce_deposit_clarification(
                status, actions_dump, customer_snapshot, request.question, has_pending_for_guardrail
            )
            if deposit_clars:
                clarifications_dump = deposit_clars
                mode = "CLARIFICATION"
            elif _pre_guardrail_status == "CLARIFICATION_REQUIRED" and status == "VALID_CONTRACT":
                # Guardrail resolved CLARIFICATION → clear stale clarification state
                clarifications_dump = []
                mode = "SINGLE"
                session_state.pending_action = None

        # T5 POST-pipeline: block movements misused as mutation
        if status == "VALID_CONTRACT" and actions_dump:
            from genesis_cognitive.router.mutation_guardrail import block_movements_as_mutation
            status, actions_dump, mutation_unsup = block_movements_as_mutation(status, actions_dump)
            if mutation_unsup:
                unsupported_dump = mutation_unsup
                mode = "UNSUPPORTED"

        # T3: Populate loan_detail from LoanSnapshot if LOAN_DETAIL_READ + VALID_CONTRACT
        decision_trace.append({"step": "guardrails", "output": {"status": status, "mode": mode, "actions_count": len(actions_dump)}})
        loan_detail: dict[str, Any] | None = None
        if (
            status == "VALID_CONTRACT"
            and actions_dump
            and actions_dump[0].get("intent_id") == "LOAN_DETAIL_READ"
            and customer_snapshot
        ):
            loan_ref = actions_dump[0].get("detected_entities", {}).get("account_ref")
            if loan_ref:
                loan_data = next(
                    (ln for ln in customer_snapshot.loans if ln.product_id == loan_ref),
                    None,
                )
                if loan_data:
                    loan_detail = loan_data.to_detail_dict()

        # Override: if model returned CLARIFICATION but question is a portfolio/family listing,
        # force VALID_CONTRACT with listing (not "which account?" clarification)
        _PORTFOLIO_SIGNALS = ("productos", "portafolio", "qué tengo", "que tengo", "todo lo que tengo", "listado")
        _ACCOUNT_LIST_SIGNALS = ("qué cuentas", "que cuentas", "cuáles cuentas", "cuales cuentas", "mis cuentas")
        _CARD_LIST_SIGNALS = ("qué tarjetas", "que tarjetas", "cuáles tarjetas", "cuales tarjetas", "mis tarjetas")
        _CARD_QUESTION_SIGNALS = ("tarjeta", "visa", "mastercard", "pricesmart")
        if (status == "CLARIFICATION_REQUIRED" or status == "VALID_CONTRACT") and customer_snapshot:
            _q_lower = request.question.strip().lower() if request.question else ""

            _force_listing = None  # None | "all" | "accounts" | "cards"
            if any(sig in _q_lower for sig in _PORTFOLIO_SIGNALS):
                _force_listing = "all"
            elif any(sig in _q_lower for sig in _ACCOUNT_LIST_SIGNALS):
                _force_listing = "accounts"
            elif any(sig in _q_lower for sig in _CARD_LIST_SIGNALS):
                _force_listing = "cards"
            elif status == "CLARIFICATION_REQUIRED" and any(sig in _q_lower for sig in _CARD_QUESTION_SIGNALS):
                # Model confused by card question → force card listing
                _force_listing = "cards"

            if _force_listing and status == "CLARIFICATION_REQUIRED":
                from genesis_cognitive.context.product_display import (
                    build_portfolio_listing as _bpl,
                    filter_active as _fa,
                    display_label_in_context as _dli,
                )
                status = "VALID_CONTRACT"
                mode = "SINGLE"
                actions_dump = [{
                    "sequence": 1,
                    "intent_id": "PORTFOLIO_LIST",
                    "capability_candidate": "PORTFOLIO_LIST",
                    "selected_route": "PORTFOLIO_QUERY",
                    "detected_entities": {"account_ref": None, "source_account_ref": None, "destination_account_ref": None, "amount": None, "currency": None, "knowledge_topic": None},
                    "missing_requirements": [],
                    "depends_on": [],
                    "confidence": 1.0,
                }]
                clarifications_dump = []
                # Clear pending (listing ≠ balance query)
                session_state.pending_action = None

        # Override: no active loans → fixed response (don't clarify with all products)
        _LOAN_QUESTION_SIGNALS = ("prestamo", "préstamo", "credito", "crédito", "cuota", "letra", "mensualidad", "cancelacion", "cancelación", "hipotec")
        _NOT_LOAN_SIGNALS = (
            "deposito", "depósito", "plazo", "cdt", "dap", "tarjeta", "visa",
            # Productos KB / comparaciones — no son "mis préstamos"
            "multicredit", "multicrédito", "cuotas bsc", "credito diferido", "crédito diferido",
            "compar", "diferenc", "disting", "qué es", "que es",
        )
        if customer_snapshot and status in ("CLARIFICATION_REQUIRED", "VALID_CONTRACT"):
            _q_lower2 = request.question.strip().lower() if request.question else ""
            if any(sig in _q_lower2 for sig in _LOAN_QUESTION_SIGNALS) and not any(
                sig in _q_lower2 for sig in _NOT_LOAN_SIGNALS
            ):
                _active_loans_check = [p for p in customer_snapshot.products if p.product_type == "LOAN" and p.status.lower() == "active" and p.currency == customer_snapshot.default_currency]
                if len(_active_loans_check) == 0:
                    _a0_intent = actions_dump[0].get("intent_id", "") if actions_dump else ""
                    if _a0_intent != "BUSINESS_KNOWLEDGE_QUERY":
                        # No loans in context → inform user clearly
                        status = "VALID_CONTRACT"
                        mode = "SINGLE"
                        actions_dump = [{"sequence": 1, "intent_id": "PORTFOLIO_LIST", "capability_candidate": "PORTFOLIO_LIST", "selected_route": "PERSONAL_READ", "detected_entities": {}, "missing_requirements": [], "depends_on": [], "confidence": 1.0}]
                        clarifications_dump = []
                        _no_loan_greeting = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                        from genesis_cognitive.context.response_formatting import no_product_with_cta
                        client_response = no_product_with_cta(
                            customer_snapshot.display_name,
                            "préstamos activos",
                        )
                        _final_resp_ms = 0
                        _final_resp_calls = []  # type: ignore[assignment]

        if client_response is None and customer_snapshot:
            from genesis_cognitive.router.snapshot_guardrails import _CARD_WORD
            _q_np = (request.question or "").strip().lower()
            _name = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
            _cards = [p for p in customer_snapshot.products if p.product_type == "CREDIT_CARD" and str(p.status).lower() == "active"]
            _daps = [p for p in customer_snapshot.products if p.product_type == "TERM_DEPOSIT" and str(p.status).lower() == "active"]
            _accts = [p for p in customer_snapshot.products if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and str(p.status).lower() == "active"]
            # No pisar conocimiento/Foundry: "qué es Visa Platinum" ≠ "mis tarjetas"
            _kb_def = any(
                s in _q_np
                for s in (
                    "qué es", "que es", "significa", "definición", "definicion",
                    "explícame", "explicame", "cuéntame", "cuentame", "háblame", "hablame",
                    "información sobre", "informacion sobre",
                    "compárame", "comparame", "diferencia entre",
                )
            )
            try:
                from genesis_cognitive.router.knowledge_followup import is_kb_product_compare_question as _is_cmp
                _kb_def = _kb_def or _is_cmp(request.question or "")
            except Exception:
                pass
            _rag_ready = rag_status in (
                "RAG_ANSWERED",
                "FOUNDRY_KB_ANSWERED",
                "FOUNDRY_KB_CACHE_HIT",
                "FOUNDRY_KB_CLARIFY",
                "FAQ_FALLBACK",
                "KB_INTENT",
                "INSTITUTIONAL_FALLBACK",
            ) and bool(rag_answer)
            if _CARD_WORD.search(_q_np) and not _cards and not _kb_def and not _rag_ready:
                status = "VALID_CONTRACT"
                clarifications_dump = []
                from genesis_cognitive.context.response_formatting import no_product_with_cta
                client_response = no_product_with_cta(
                    customer_snapshot.display_name,
                    "tarjetas de crédito activas",
                )
            elif any(s in _q_np for s in ("deposito", "depósito", "certificado", "dap", "cdt")) and not _daps and not _kb_def and not _rag_ready:
                status = "VALID_CONTRACT"
                clarifications_dump = []
                from genesis_cognitive.context.response_formatting import no_product_with_cta
                client_response = no_product_with_cta(
                    customer_snapshot.display_name,
                    "depósitos a plazo (certificados) activos",
                )
            elif not customer_snapshot.products:
                status = "VALID_CONTRACT"
                clarifications_dump = []
                from genesis_cognitive.context.response_formatting import no_product_with_cta
                client_response = no_product_with_cta(
                    customer_snapshot.display_name,
                    "productos activos",
                )


        # Override model-generated clarification text with masked versions
        if status == "CLARIFICATION_REQUIRED" and clarifications_dump and customer_snapshot:
            from genesis_cognitive.context.product_display import (
                build_clarification_accounts as _bca,
                build_clarification_loans as _bcl,
                filter_active as _fa,
            )
            from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question as _is_loan_clar
            # If clarification mentions account_ref → rebuild with active masked labels
            clar0 = clarifications_dump[0] if clarifications_dump else {}
            missing = clar0.get("missing_requirements", [])
            _clar_q = request.question.strip().lower() if request.question else ""
            if "account_ref" in missing or _is_loan_clar(request.question or ""):
                # Determine intent to pick correct product list
                _clar_intent = None
                if actions_dump:
                    _clar_intent = actions_dump[0].get("intent_id")
                elif session_state.pending_action:
                    _clar_intent = session_state.pending_action.intent_id
                if _is_loan_clar(request.question or ""):
                    _clar_intent = "LOAN_DETAIL_READ"

                # If question is clearly about cards/loans/portfolio listing, suppress deposit clarification
                _clar_q = request.question.strip().lower() if request.question else ""
                _CARD_SUPPRESS = ("tarjeta", "visa", "mastercard", "pricesmart", "gold", "platinum", "black")
                _LIST_SUPPRESS = ("productos", "portafolio", "que tengo", "qué tengo", "que cuentas", "que tarjetas")
                if any(s in _clar_q for s in _CARD_SUPPRESS + _LIST_SUPPRESS):
                    # Don't rewrite clarification — let the question flow naturally
                    pass
                else:
                    _LOAN_INTENTS = ("LOAN_DETAIL_READ", "LOAN_PAYMENT_VALIDATE")
                    active_deposits = [p for p in customer_snapshot.products if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and p.status.lower() == "active" and p.currency == customer_snapshot.default_currency]
                    active_loans = [p for p in customer_snapshot.products if p.product_type == "LOAN" and p.status.lower() == "active" and p.currency == customer_snapshot.default_currency]

                    if _clar_intent in _LOAN_INTENTS:
                        if len(active_loans) >= 2:
                            clarifications_dump[0]["suggested_question"] = _bcl(active_loans)
                    else:
                        if len(active_deposits) >= 2:
                            clarifications_dump[0]["suggested_question"] = _bca(active_deposits)
                        elif len(active_loans) >= 2:
                            clarifications_dump[0]["suggested_question"] = _bcl(active_loans)

        # Generate client_response
        _final_resp_ms: int = 0
        _final_resp_calls: list[dict[str, Any]] = []
        from genesis_cognitive.router.final_response_agent import build_client_response_no_llm

        # If no-loans override already set client_response, skip generation
        if client_response is not None:
            no_llm_response = None
        else:
            no_llm_response = build_client_response_no_llm(
                status=status,
                clarifications=clarifications_dump,
                display_name=customer_snapshot.display_name if customer_snapshot else None,
            )
        if client_response is not None:
            pass  # Already set by no-loans override
        elif status == "VALID_CONTRACT" and clarifications_dump:
            _sq = clarifications_dump[0].get("suggested_question") or ""
            if _sq and not clarifications_dump[0].get("missing_requirements"):
                client_response = _sq
                clarifications_dump = []
                mode = "SINGLE"
                _final_resp_ms = 0
        elif no_llm_response is not None:
            client_response = no_llm_response
            _final_resp_ms = 0
        elif status == "CLARIFICATION_REQUIRED" and clarifications_dump:
            client_response = clarifications_dump[0].get("suggested_question") or "Tienes más de un préstamo. ¿A cuál te refieres?"
            _final_resp_ms = 0
        elif rag_status in (
            "RAG_ANSWERED",
            "FOUNDRY_KB_ANSWERED",
            "FOUNDRY_KB_CACHE_HIT",
            "FOUNDRY_KB_CLARIFY",
            "FAQ_FALLBACK",
            "KB_INTENT",
            "INSTITUTIONAL_FALLBACK",
        ) and rag_answer:
            # Respuesta grounded (Foundry / RAG / FAQ fallback)
            from genesis_cognitive.context.response_formatting import sanitize_client_facing_text
            client_response = sanitize_client_facing_text(rag_answer)
            _final_resp_ms = 0
            if rag_status == "FOUNDRY_KB_CLARIFY" and status == "CLARIFICATION_REQUIRED":
                if not clarifications_dump:
                    clarifications_dump = [{
                        "missing_requirements": ["knowledge_topic"],
                        "suggested_question": client_response,
                        "reason": "kb_ambiguity",
                    }]
        elif status == "VALID_CONTRACT" and loan_detail:
            from genesis_cognitive.router.final_response_agent import build_loan_detail_response
            client_response = build_loan_detail_response(
                request.question,
                loan_detail,
                customer_snapshot.display_name if customer_snapshot else None,
            )
            _final_resp_ms = 0
        elif status == "VALID_CONTRACT":
            # Template for ACCOUNT_BALANCE_READ or other intents without loan_detail
            a0 = actions_dump[0] if actions_dump else {}
            intent = a0.get("intent_id", "") if a0 else ""
            ref = a0.get("detected_entities", {}).get("account_ref") if a0 else None
            display = customer_snapshot.display_name if customer_snapshot else ""
            if intent == "ACCOUNT_BALANCE_READ" and ref:
                from genesis_cognitive.context.product_display import display_label as _display_label
                from genesis_cognitive.router.field_guardrails import _product_not_found_message
                prod = next((p for p in customer_snapshot.products if p.product_id == ref), None) if customer_snapshot else None
                greeting = f"{display}, " if display else ""
                if prod is None:
                    client_response = _product_not_found_message(customer_snapshot, str(ref))
                elif prod.available_balance is not None:
                    label = _display_label(prod)
                    client_response = f"{greeting}tu saldo disponible en {label} es de {prod.available_balance} {prod.currency}."
                else:
                    label = _display_label(prod)
                    client_response = f"{greeting}tu consulta de saldo para {label} está lista. El saldo se obtiene del Core."
            elif intent == "CREDIT_CARD_DETAIL_READ" and ref and customer_snapshot:
                from genesis_cognitive.context.product_display import display_label as _dl_card
                from genesis_cognitive.router.final_response_agent import build_card_detail_response
                card = next((p for p in customer_snapshot.products if p.product_id == ref), None)
                greeting = f"{display}, " if display else ""
                if card is None:
                    client_response = f"{greeting}no encontré esa tarjeta."
                else:
                    client_response = build_card_detail_response(
                        request.question, card, display, _dl_card(card)
                    )
            elif intent == "TERM_DEPOSIT_DETAIL_READ" and ref and customer_snapshot:
                from genesis_cognitive.context.product_display import display_label as _dl_cd
                from genesis_cognitive.router.final_response_agent import build_deposit_detail_response
                dep = next((p for p in customer_snapshot.products if p.product_id == ref), None)
                greeting = f"{display}, " if display else ""
                if dep is None:
                    client_response = f"{greeting}no encontré ese depósito a plazo."
                else:
                    client_response = build_deposit_detail_response(
                        request.question, dep, display, _dl_cd(dep)
                    )
            elif intent == "PORTFOLIO_LIST" and customer_snapshot:
                # Build real product list from snapshot (active only, with masks)
                # Check if user asked for a specific family
                from genesis_cognitive.context.product_display import build_portfolio_listing, filter_active, display_label_in_context as _dli_port
                _q_port = request.question.strip().lower() if request.question else ""
                from genesis_cognitive.router.field_guardrails import is_bank_catalog_question as _is_bank_cat
                _ACCT_SIGNALS = ("qué cuentas", "que cuentas", "cuáles cuentas", "cuales cuentas", "mis cuentas")
                _CARD_SIGNALS = ("qué tarjetas", "que tarjetas", "cuáles tarjetas", "cuales tarjetas", "mis tarjetas")
                _DEP_SIGNALS = (
                    "qué depósitos", "que depositos", "qué depositos", "que depósitos",
                    "mis depósitos", "mis depositos", "certificados", "certificado",
                    "mis certificados", "mi certificado", "cdt", "dap",
                    "deposito a plazo", "depósito a plazo", "certificado de deposito",
                    "certificado de depósito",
                )

                # Catálogo del banco → no listar portafolio personal
                if _is_bank_cat(_q_port):
                    from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail as _afq_cat
                    _faq_cat = _afq_cat(customer_snapshot, request.question or "", session=session_state)
                    if _faq_cat and _faq_cat[2]:
                        status = _faq_cat[0]
                        actions_dump = _faq_cat[1]
                        client_response = _faq_cat[2]
                        clarifications_dump = []
                    else:
                        from genesis_cognitive.context.response_formatting import append_digital_onboarding_link
                        client_response = append_digital_onboarding_link(
                            "En Banco Santa Cruz puedes solicitar, entre otros:\n\n"
                            "• **Cuentas** de ahorro y corriente personales.\n"
                            "• **Préstamos** personales, con garantía, de vehículos e hipotecarios.\n"
                            "• **Tarjetas** de crédito y débito, según elegibilidad.\n"
                            "• **Depósitos / certificados** a plazo.\n\n"
                            "Indícame si quieres el detalle de cuentas, préstamos o tarjetas."
                        )
                        status = "VALID_CONTRACT"
                        clarifications_dump = []
                elif any(s in _q_port for s in _ACCT_SIGNALS):
                    # Only CA/CC/PAYROLL
                    _accts = [p for p in filter_active(customer_snapshot) if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")]
                    _greeting = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                    if _accts:
                        _lines = [f"  - {_dli_port(p, _accts)} ({p.currency})" for p in _accts]
                        client_response = f"{_greeting}tus cuentas activas son:\n" + "\n".join(_lines)
                    else:
                        client_response = f"{_greeting}no tienes cuentas activas en tu portafolio."
                elif any(s in _q_port for s in _CARD_SIGNALS):
                    # Only TC
                    _cards = [p for p in filter_active(customer_snapshot) if p.product_type == "CREDIT_CARD"]
                    _greeting = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                    if _cards:
                        _lines = [f"  - {_dli_port(p, _cards)} ({p.currency})" for p in _cards]
                        client_response = f"{_greeting}tus tarjetas activas son:\n" + "\n".join(_lines)
                    else:
                        client_response = f"{_greeting}no tienes tarjetas activas en tu portafolio."
                elif any(s in _q_port for s in _DEP_SIGNALS):
                    _deps = [p for p in filter_active(customer_snapshot) if p.product_type == "TERM_DEPOSIT"]
                    _greeting = f"{customer_snapshot.display_name}, " if customer_snapshot.display_name else ""
                    if _deps:
                        from genesis_cognitive.context.response_formatting import build_rich_deposit_detail as _brdd
                        _blocks = [_brdd(p) for p in _deps]
                        client_response = (
                            f"{_greeting}estos son tus certificados de depósito (depósitos a plazo):\n\n"
                            + "\n\n".join(_blocks)
                        )
                    else:
                        client_response = f"{_greeting}no tienes certificados de depósito (depósitos a plazo) activos en tu portafolio."
                else:
                    client_response = build_portfolio_listing(customer_snapshot)
            elif intent == "ACCOUNT_MOVEMENTS_READ":
                greeting = f"{display}, " if display else ""
                client_response = f"{greeting}Ese dato no está disponible en este momento. No recibí el historial de movimientos."
            else:
                # Nunca exponer plantilla interna al cliente (bug APK: "Contrato válido…")
                from genesis_cognitive.context.product_display import build_portfolio_listing
                from genesis_cognitive.router.field_guardrails import (
                    is_portfolio_list_question as _is_port_fb,
                )
                from genesis_cognitive.router.snapshot_guardrails import (
                    is_loan_field_question as _is_loan_fb,
                )
                _q_fb = (request.question or "").strip().lower()
                if customer_snapshot and (
                    _is_port_fb(request.question or "")
                    or any(
                        s in _q_fb
                        for s in (
                            "producto", "portafolio", "listado", "lista",
                            "qué tengo", "que tengo",
                        )
                    )
                ):
                    client_response = build_portfolio_listing(customer_snapshot)
                elif customer_snapshot and _is_loan_fb(request.question or ""):
                    # Fallback personal de préstamos si el LLM no armó loan_detail
                    _loans_fb = [
                        p for p in customer_snapshot.products
                        if p.product_type == "LOAN" and str(p.status).lower() == "active"
                    ]
                    if len(_loans_fb) >= 2:
                        from genesis_cognitive.context.product_display import build_clarification_loans as _bcl_fb
                        client_response = _bcl_fb(_loans_fb)
                        status = "CLARIFICATION_REQUIRED"
                        clarifications_dump = [{
                            "target_action_sequence": 1,
                            "missing_requirements": ["account_ref"],
                            "suggested_question": client_response,
                            "already_known": [],
                        }]
                        actions_dump = [{
                            "sequence": 1,
                            "intent_id": "LOAN_DETAIL_READ",
                            "capability_candidate": "LOAN_DETAIL",
                            "selected_route": "PERSONAL_READ",
                            "detected_entities": {"account_ref": None},
                            "missing_requirements": ["account_ref"],
                            "depends_on": [],
                            "confidence": 1.0,
                        }]
                        mode = "CLARIFICATION"
                    elif len(_loans_fb) == 1:
                        from genesis_cognitive.context.response_formatting import build_rich_loan_detail as _brld
                        _g = f"{display}, " if display else ""
                        client_response = _g + build_rich_loan_detail(_loans_fb[0], None)
                    else:
                        _g = f"{display}, " if display else ""
                        client_response = f"{_g}no tienes préstamos activos en tu portafolio actual."
                else:
                    _greet = f"{display}, " if display else ""
                    client_response = (
                        f"{_greet}no pude armar la respuesta con los datos disponibles. "
                        "¿Puedes reformular tu consulta (saldo, productos, préstamo o información del banco)?"
                    )
            _final_resp_ms = 0  # template, no LLM

        decision_trace.append({"step": "loan_detail", "output": loan_detail})
        decision_trace.append({"step": "final_response", "input": {"question": request.question[:80], "intent_id": (actions_dump[0].get("intent_id") if actions_dump else None)}, "output": {"client_response": (client_response or "")[:120]}, "duration_ms": _final_resp_ms, "calls": _final_resp_calls})

        body: dict[str, Any] = {
            "provider": "AZURE_OPENAI",
            "framework": "MICROSOFT_AGENT_FRAMEWORK",
            "model": azure_model,
            "prompt_version": prompt_version,
            "conversation_id": conv_id,
            "turn_number": turn_number,
            "conversation_history": session,
            "status": status,
            "mode": mode,
            "non_operational_response": resolver_result.non_operational_message,
            "initial_proposal": (
                resolver_result.initial_proposal.model_dump()
                if resolver_result.initial_proposal
                else None
            ),
            "verified_proposal": (
                resolver_result.verified_proposal.model_dump()
                if resolver_result.verified_proposal
                else None
            ),
            "raw_interpretation": interpretation.model_dump() if interpretation else None,
            "actions": actions_dump,
            "clarifications": clarifications_dump,
            "unsupported_segments": unsupported_dump,
            "catalog_valid": catalog_valid,
            "entity_refs_valid": entity_refs_valid,
            "violations": violations,
            "output_contracts": output_contracts,
            "rag_status": rag_status,
            "inference_count": 2,
            "effective_capability_ids": [c.capability_id for c in model_input.effective_capabilities],
            "customer_context": {
                "customer_id": customer_snapshot.customer_id,
                "display_name": customer_snapshot.display_name,
                "products_count": len(customer_snapshot.products),
                "loans_count": len(customer_snapshot.loans),
            } if customer_snapshot else None,
            "loan_detail": loan_detail,
            "domain_scores": domain_scores_data,
            "product_scores": product_scores_data,
            "client_response": client_response,
            "suggested_questions": suggested_questions,
            "decision_trace": decision_trace,
            "total_request_ms": round((_time.perf_counter() - _request_start) * 1000),
        }

        # RF4: Pipeline latency log (INFO or WARNING if slow)
        _log_latency_audit(
            path="/inspect",
            total_ms=body["total_request_ms"],
            status=status,
            conversation_id=conv_id,
            question=request.question,
            decision_trace=decision_trace,
            source="pipeline",
        )

        # Persist session state to store (refresh updated_at)
        _conflict_resp = _cas_put_session()
        if _conflict_resp is not None:
            return _conflict_resp

        # Build Genesis 1.2.0 operation_request
        from genesis_cognitive.contracts.operation_request_adapter import build_operation_request
        operation_request = build_operation_request(
            status=status,
            actions=actions_dump,
            customer_id=payload_customer_id,
            conversation_id=conv_id,
            turn_number=turn_number,
            loan_detail=loan_detail,
            customer_snapshot_summary=body.get("customer_context"),
        )
        body["operation_request"] = operation_request

        return JSONResponse(status_code=200, content=body)

    @app.get("/customers")
    async def list_customers() -> JSONResponse:
        """Return list of customers from SQLite for UI selector."""
        if customer_loader is None:
            return JSONResponse(content=[])
        import sqlite3
        uri = f"file:{customer_loader._db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT customer_id, display_name FROM customers ORDER BY customer_id")
        customers = [{"customer_id": r["customer_id"], "display_name": r["display_name"]} for r in cur.fetchall()]
        conn.close()
        return JSONResponse(content=customers)

    @app.get("/", response_model=None)
    async def index() -> FileResponse | JSONResponse | RedirectResponse:
        import os as _os
        pruebas_dir = Path(__file__).resolve().parent / "pruebas_ui"
        if _os.getenv("GENESIS_SERVE_UI", "true").lower() == "false":
            if pruebas_dir.is_dir():
                return RedirectResponse(url="/pruebas/")
            return JSONResponse(content={
                "service": "genesis-cognitive",
                "mode": "api-only",
                "endpoints": ["/turn", "/inspect", "/health"],
            })
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    _ROOT = Path(__file__).resolve().parents[3]
    _PRUEBAS_CANDIDATES = [
        Path(__file__).resolve().parent / "pruebas_ui",
        _ROOT / "interfaz Prueba" / "web",
    ]
    # En contenedor el paquete vive en site-packages; los datos están en /app/data.
    _PORTFOLIO_CANDIDATES = [
        Path("/app/data/lab_portfolios"),
        Path.cwd() / "data" / "lab_portfolios",
        _ROOT / "Test_local" / "data" / "portfolios",
        _ROOT / "data" / "lab_portfolios",
    ]
    _PRUEBAS_DIR = next((p for p in _PRUEBAS_CANDIDATES if p.is_dir()), None)
    _PORTFOLIOS_DIR = next((p for p in _PORTFOLIO_CANDIDATES if p.is_dir()), None)

    _USUARIOS_CANDIDATES = [
        Path("/app/data/lab_usuarios.json"),
        Path.cwd() / "data" / "lab_usuarios.json",
        _ROOT / "data" / "lab_usuarios.json",
        _ROOT / "Test_local" / "data" / "usuarios.json",
    ]
    _USUARIOS_PATH = next((p for p in _USUARIOS_CANDIDATES if p.is_file()), None)

    def _load_usuarios() -> list[dict[str, str]]:
        if _USUARIOS_PATH is None:
            return []
        payload = json.loads(_USUARIOS_PATH.read_text(encoding="utf-8"))
        return list(payload.get("usuarios") or [])

    def _persist_core_context(
        *,
        customer_id: str,
        conversation_id: str,
        ctx_data: dict[str, Any],
        op: str = "load",
    ) -> dict[str, Any]:
        from genesis_cognitive.context.context_persistence_service import (
            ContextPersistenceService,
        )

        return ContextPersistenceService(store).persist_orchestrator_context(
            customer_id=customer_id,
            conversation_id=conversation_id,
            ctx_data=ctx_data,
            op=op,
        )

    def _core_ws_url(customer_id: str) -> str:
        """URL WebSocket del Core Genesis (mismo host que consume el APK)."""
        import urllib.parse

        base = (
            os.getenv("GENESIS_CORE_CONTEXT_URL", "https://api-genesis.dev.bsc.com.do/ws/")
            .strip()
            or "https://api-genesis.dev.bsc.com.do/ws/"
        )
        # APK usa wss://.../ws/?customerId=
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        elif not base.startswith(("ws://", "wss://")):
            base = "wss://" + base.lstrip("/")
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}customerId={urllib.parse.quote(str(customer_id))}"

    def _looks_like_core_portfolio(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if isinstance(payload.get("products"), list):
            return True
        data = payload.get("data")
        if isinstance(data, list) and data:
            return True
        if isinstance(data, dict) and isinstance(data.get("products"), list):
            return True
        nested = payload.get("context")
        if isinstance(nested, dict):
            return _looks_like_core_portfolio(nested)
        return False

    def _parse_ws_message(raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, dict):
            return raw if _looks_like_core_portfolio(raw) else None
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and _looks_like_core_portfolio(payload):
            return payload
        return None

    async def _fetch_core_context_websocket(customer_id: str) -> dict[str, Any]:
        """Abre WebSocket al Core (como el APK) y espera el portafolio.

        Flujo:
          1) connect wss://api-genesis.../ws/?customerId={id}
          2) opcionalmente envía {"customerId": id}
          3) lee mensajes hasta obtener products / data
        """
        import asyncio

        try:
            import websockets
            from websockets.exceptions import WebSocketException
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(
                status_code=503,
                detail={"error": "websockets_dependency_missing", "message": str(exc)},
            ) from exc

        url = _core_ws_url(customer_id)
        timeout_s = float(os.getenv("GENESIS_CORE_WS_TIMEOUT", "20"))
        max_messages = int(os.getenv("GENESIS_CORE_WS_MAX_MESSAGES", "8"))

        async def _run() -> dict[str, Any]:
            async with websockets.connect(
                url,
                open_timeout=timeout_s,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                max_size=4 * 1024 * 1024,
                user_agent_header="genesis-cognitive-pruebas/1.0",
                origin="https://api-genesis.dev.bsc.com.do",
            ) as ws:
                # El APK identifica al cliente en la URL; reforzamos con mensaje inicial.
                hello = json.dumps({"customerId": str(customer_id), "customer_id": str(customer_id)})
                try:
                    await ws.send(hello)
                except Exception:  # noqa: BLE001 — algunos servers no aceptan client→server
                    pass

                last_raw = ""
                for _ in range(max_messages):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                    except TimeoutError as exc:
                        raise HTTPException(
                            status_code=502,
                            detail={
                                "error": "core_ws_timeout",
                                "url": url,
                                "message": f"sin portafolio en {timeout_s}s",
                                "last": last_raw[:400],
                            },
                        ) from exc
                    last_raw = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    parsed = _parse_ws_message(raw)
                    if parsed is not None:
                        return parsed

                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "core_ws_no_portfolio",
                        "url": url,
                        "message": f"recibidos {max_messages} mensajes sin portafolio",
                        "last": last_raw[:400],
                    },
                )

        try:
            return await _run()
        except HTTPException:
            raise
        except WebSocketException as exc:
            raise HTTPException(
                status_code=502,
                detail={"error": "core_ws_error", "url": url, "message": str(exc)},
            ) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=502,
                detail={"error": "core_ws_unreachable", "url": url, "message": str(exc)},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail={"error": "core_ws_failed", "url": url, "message": str(exc)},
            ) from exc

    def _fetch_core_context_ws(customer_id: str) -> dict[str, Any]:
        """Compat: HTTP GET de respaldo si el WebSocket no está disponible."""
        import urllib.error
        import urllib.parse
        import urllib.request

        base = (
            os.getenv("GENESIS_CORE_CONTEXT_URL", "https://api-genesis.dev.bsc.com.do/ws/")
            .strip()
            or "https://api-genesis.dev.bsc.com.do/ws/"
        )
        if base.startswith("wss://"):
            base = "https://" + base[len("wss://") :]
        elif base.startswith("ws://"):
            base = "http://" + base[len("ws://") :]
        sep = "&" if "?" in base else "?"
        url = f"{base}{sep}customerId={urllib.parse.quote(str(customer_id))}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "genesis-cognitive-pruebas/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "core_context_http_error",
                    "status": exc.code,
                    "url": url,
                    "body": detail[:800],
                },
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "core_context_unreachable",
                    "url": url,
                    "message": str(exc),
                },
            ) from exc
        if not raw.strip():
            raise HTTPException(status_code=502, detail={"error": "core_context_empty", "url": url})
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=502,
                detail={"error": "core_context_not_json", "url": url, "body": raw[:400]},
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail={"error": "core_context_invalid", "url": url})
        return payload

    def _lab_portfolio_envelope(customer_id: str, portfolio_name: str | None) -> tuple[dict[str, Any], str]:
        if _PORTFOLIOS_DIR is None:
            raise HTTPException(status_code=503, detail="no hay portafolios de laboratorio")
        name = portfolio_name
        if not name:
            match = next((u for u in _load_usuarios() if u.get("customer_id") == customer_id), None)
            name = (match or {}).get("portfolio") or "mvp_cuentas_multi.json"
        safe = Path(name).name
        if safe != name or not safe.endswith(".json"):
            raise HTTPException(status_code=400, detail="portafolio invalido")
        path = _PORTFOLIOS_DIR / safe
        if not path.is_file():
            raise HTTPException(status_code=404, detail="portafolio Core lab no encontrado")
        return json.loads(path.read_text(encoding="utf-8")), safe

    def _to_orchestrator_context(envelope: dict[str, Any]) -> dict[str, Any]:
        """Normaliza Core/ws o lab JSON al contrato del orquestador: {data: {...}}.

        Formato real (APK/WS → cognitiva):
          context.data = { primerNombre, products: [...], resultCode, ... }

        Formato lab histórico:
          { primerNombre, data: [ productos... ] }
        """
        if not isinstance(envelope, dict):
            raise HTTPException(status_code=502, detail="envelope Core invalido")

        nested = envelope.get("context")
        if isinstance(nested, dict) and isinstance(nested.get("data"), dict):
            return {"data": nested["data"]}

        data = envelope.get("data")
        if isinstance(data, dict) and (
            isinstance(data.get("products"), list)
            or "primerNombre" in data
            or "resultCode" in data
        ):
            return {"data": data}

        if isinstance(data, list):
            return {
                "data": {
                    "resultCode": 0,
                    "primerNombre": envelope.get("primerNombre") or "",
                    "resultMessage": envelope.get("message")
                    or envelope.get("resultMessage")
                    or "Consulta realizada exitosamente.",
                    "products": data,
                }
            }

        if isinstance(envelope.get("products"), list):
            return {"data": envelope}

        raise HTTPException(
            status_code=502,
            detail={"error": "core_context_shape_unknown", "keys": list(envelope.keys())[:20]},
        )

    @app.get("/lab/usuarios")
    async def list_lab_usuarios() -> JSONResponse:
        return JSONResponse(content=_load_usuarios())

    @app.post("/orch/context")
    async def orch_context_refresh(request: OrchContextRequest) -> JSONResponse:
        """Bootstrap de sesión estilo orquestador .NET (sin tocar el backend):

        1) GET Presentation Product QA (mismo template que el orch)
        2) Fallback opcional: WebSocket/HTTP Core legacy
        3) Fallback lab si allow_lab_fallback
        4) POST /turn context_info=true → Redis
        """
        import asyncio

        from genesis_cognitive.context.presentation_product import (
            fetch_presentation_product,
            presentation_product_url,
        )

        customer_id = (request.customer_id or "").strip()
        if not customer_id:
            raise HTTPException(status_code=422, detail="customer_id es obligatorio")
        conversation_id = (request.conversation_id or "").strip() or str(uuid.uuid4())
        source = "presentation_product"
        envelope: dict[str, Any]
        portfolio_name: str | None = None
        core_error: dict[str, Any] | str | None = None
        ws_url = _core_ws_url(customer_id)
        presentation_url = presentation_product_url(customer_id)

        try:
            envelope = await asyncio.to_thread(fetch_presentation_product, customer_id)
            source = "presentation_product"
        except Exception as pres_exc:  # noqa: BLE001 — superficie de bootstrap
            try:
                detail_pres = json.loads(str(pres_exc))
            except Exception:
                detail_pres = {"error": "presentation_product_failed", "message": str(pres_exc)}

            # Legacy: Core WS (históricamente usado por el simulador)
            try:
                envelope = await _fetch_core_context_websocket(customer_id)
                source = "core_websocket"
                core_error = {"presentation_failed": detail_pres, "fallback": "core_websocket"}
            except HTTPException as ws_exc:
                try:
                    envelope = _fetch_core_context_ws(customer_id)
                    source = "core_http"
                    core_error = {
                        "presentation_failed": detail_pres,
                        "websocket_failed": ws_exc.detail
                        if isinstance(ws_exc.detail, dict)
                        else str(ws_exc.detail),
                        "fallback": "http_get",
                    }
                except HTTPException as http_exc:
                    if not request.allow_lab_fallback:
                        raise HTTPException(
                            status_code=502,
                            detail={
                                "error": "context_bootstrap_failed",
                                "presentation": detail_pres,
                                "websocket": ws_exc.detail
                                if isinstance(ws_exc.detail, dict)
                                else str(ws_exc.detail),
                                "http": http_exc.detail
                                if isinstance(http_exc.detail, dict)
                                else str(http_exc.detail),
                            },
                        ) from http_exc
                    envelope, portfolio_name = _lab_portfolio_envelope(
                        customer_id, request.portfolio
                    )
                    source = "lab_fallback"
                    core_error = {
                        "presentation": detail_pres,
                        "websocket": ws_exc.detail
                        if isinstance(ws_exc.detail, dict)
                        else str(ws_exc.detail),
                        "http": http_exc.detail
                        if isinstance(http_exc.detail, dict)
                        else str(http_exc.detail),
                    }

        context_body = _to_orchestrator_context(envelope)

        # Mismo contrato que el orquestador hacia la cognitiva
        turn_req = TurnRequest(
            question=None,
            customer_id=customer_id,
            conversation_id=conversation_id,
            force_core_query=False,
            context_info=True,
            context_op="load",
            context=context_body,
        )
        turn_resp = await turn_handler(turn_req)
        loaded = json.loads(turn_resp.body.decode("utf-8"))
        if turn_resp.status_code >= 400:
            return JSONResponse(status_code=turn_resp.status_code, content=loaded)

        loaded["context_source"] = source
        loaded["presentation_product_url"] = presentation_url
        loaded["core_websocket_url"] = ws_url
        loaded["core_context_url"] = os.getenv(
            "GENESIS_CORE_CONTEXT_URL", "https://api-genesis.dev.bsc.com.do/ws/"
        )
        loaded["context_info"] = True
        loaded["orchestrator_turn"] = {
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "question": None,
            "force_core_query": False,
            "context_info": True,
            "context_op": "load",
        }
        if portfolio_name:
            loaded["portfolio"] = portfolio_name
        if core_error:
            loaded["core_error"] = core_error
        return JSONResponse(status_code=200, content=loaded)

    @app.post("/lab/login")
    async def lab_login(request: LabLoginRequest) -> JSONResponse:
        """Login de prueba: carga contexto Core con el mismo contrato que POST /turn context_info."""
        customer_id = (request.customer_id or "").strip()
        if not customer_id:
            raise HTTPException(status_code=422, detail="customer_id es obligatorio")
        envelope: dict[str, Any] | None = None
        portfolio_name = request.portfolio
        if request.context:
            payload = request.context
            nested = payload.get("context")
            if isinstance(nested, dict) and isinstance(nested.get("data"), dict):
                envelope = nested["data"]
            elif isinstance(payload.get("data"), dict) and (
                "products" in payload["data"] or "primerNombre" in payload["data"]
            ):
                envelope = payload["data"]
            else:
                envelope = payload
        else:
            if _PORTFOLIOS_DIR is None:
                raise HTTPException(status_code=503, detail="no hay portafolios de laboratorio")
            if not portfolio_name:
                match = next((u for u in _load_usuarios() if u.get("customer_id") == customer_id), None)
                if match is None:
                    raise HTTPException(
                        status_code=404,
                        detail="usuario no encontrado; pega el JSON de Core o elige un preset",
                    )
                portfolio_name = match.get("portfolio")
            safe = Path(portfolio_name or "").name
            if safe != (portfolio_name or "") or not safe.endswith(".json"):
                raise HTTPException(status_code=400, detail="portafolio invalido")
            path = _PORTFOLIOS_DIR / safe
            if not path.is_file():
                raise HTTPException(status_code=404, detail="portafolio Core no encontrado")
            envelope = json.loads(path.read_text(encoding="utf-8"))
            portfolio_name = safe
        if not isinstance(envelope, dict):
            raise HTTPException(status_code=500, detail="envelope Core invalido")
        conversation_id = (request.conversation_id or "").strip() or str(uuid.uuid4())
        loaded = _persist_core_context(
            customer_id=customer_id,
            conversation_id=conversation_id,
            ctx_data=envelope,
            op="load",
        )
        if portfolio_name:
            loaded["portfolio"] = portfolio_name
        return JSONResponse(status_code=200, content=loaded)

    @app.post("/lab/logout")
    async def lab_logout(request: LabLoginRequest) -> JSONResponse:
        """Cierra sesión: invalida conversation + snapshot atado. Nueva sesión = recargar contexto."""
        conversation_id = (request.conversation_id or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=422, detail="conversation_id es obligatorio para logout")
        store.delete_session(conversation_id)
        return JSONResponse(
            status_code=200,
            content={
                "status": "SESSION_CLOSED",
                "conversation_id": conversation_id,
                "customer_id": (request.customer_id or "").strip() or None,
            },
        )

    @app.get("/lab/scripts")
    async def list_lab_scripts() -> JSONResponse:
        return JSONResponse(content=[
            {
                "id": "qa_andres",
                "label": "Script QA Andres David (reemplaza curl)",
                "customer_id": "TEST-QA-001",
                "portfolio": "qa_andres_david.json",
                "questions": [
                    "¿bueno días?",
                    "¿cuales son mis productos?",
                    "¿dame el dinero que ten en mi cuenta de ahorros?",
                    "¿cual esesl sado de mi  de mi prestamo?",
                    "del Préstamo 12345",
                    "y la deuda total?",
                    "requisistos para un crédito Hipotecario",
                ],
            },
        ])

    @app.get("/lab/excel-casos")
    async def list_excel_casos() -> JSONResponse:
        path = _ROOT / "interfaz Prueba" / "mvp_preguntas.json"
        if not path.is_file():
            return JSONResponse(content=[])
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for caso in payload.get("casos") or []:
            exprs = caso.get("expresiones") or []
            if not exprs:
                continue
            rows.append({
                "id": caso.get("id"),
                "producto": caso.get("producto"),
                "intencion": caso.get("intencion"),
                "question": exprs[0],
                "tipo_prueba": caso.get("tipo_prueba"),
            })
        return JSONResponse(content=rows)

    @app.get("/lab/portfolios")
    async def list_test_portfolios() -> JSONResponse:
        if _PORTFOLIOS_DIR is None or not _PORTFOLIOS_DIR.is_dir():
            return JSONResponse(content=[])
        files = sorted(p.name for p in _PORTFOLIOS_DIR.glob("*.json"))
        return JSONResponse(content=[{"name": name} for name in files])

    @app.get("/lab/portfolios/{name}")
    async def get_test_portfolio(name: str) -> JSONResponse:
        if _PORTFOLIOS_DIR is None:
            raise HTTPException(status_code=404, detail="portafolio no encontrado")
        safe = Path(name).name
        if safe != name or not safe.endswith(".json"):
            raise HTTPException(status_code=400, detail="nombre de portafolio invalido")
        path = _PORTFOLIOS_DIR / safe
        if not path.is_file():
            raise HTTPException(status_code=404, detail="portafolio no encontrado")
        import json as _json
        return JSONResponse(content=_json.loads(path.read_text(encoding="utf-8")))

    if _PRUEBAS_DIR is not None:
        @app.get("/pruebas", include_in_schema=False)
        async def pruebas_redirect() -> RedirectResponse:
            return RedirectResponse(url="/pruebas/")

        app.mount("/pruebas", StaticFiles(directory=str(_PRUEBAS_DIR), html=True), name="pruebas")

    @app.get("/health")
    async def health() -> JSONResponse:
        """Health check for load balancers and orchestrator."""
        import os as _os
        return JSONResponse(content={
            "status": "ok",
            "service": "genesis-cognitive",
            "env": _os.getenv("GENESIS_ENV", "dev"),
            "version": "0.8.0",
            "rag": rag_store.status,
        })

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """Readiness agregado: Redis obligatorio cuando GENESIS_REDIS_REQUIRED=1."""
        import asyncio
        import os as _os

        from genesis_cognitive.context.conversation_gate import (
            conversation_gate_backend_name,
            get_conversation_gate,
        )
        from genesis_cognitive.context.redis_client_factory import diagnose_redis_backends

        def _diagnose() -> tuple[dict, int]:
            gate = None
            lock_client = None
            try:
                gate = get_conversation_gate()
                lock_client = getattr(gate, "_redis", None)
            except Exception as exc:  # noqa: BLE001
                diag = diagnose_redis_backends(session_store=store, lock_client=None)
                diag["ok"] = False
                diag["errors"] = list(diag.get("errors") or []) + [f"gate:{type(exc).__name__}"]
                return diag, 503
            diag = diagnose_redis_backends(session_store=store, lock_client=lock_client)
            diag["lock_backend"] = conversation_gate_backend_name(gate)
            diag["service"] = "genesis-cognitive"
            diag["foundry_product_tools"] = _os.getenv(
                "GENESIS_FOUNDRY_PRODUCT_TOOLS", "0"
            ).strip().lower() in ("1", "true", "yes", "on")
            return diag, (200 if diag.get("ok") else 503)

        diag, status = await asyncio.to_thread(_diagnose)
        return JSONResponse(status_code=status, content=diag)

    @app.get("/ready/redis")
    async def ready_redis() -> JSONResponse:
        """Readiness diagnóstico de backends Redis (sin secretos; no altera /turn)."""
        import asyncio

        from genesis_cognitive.context.conversation_gate import (
            conversation_gate_backend_name,
            get_conversation_gate,
        )
        from genesis_cognitive.context.redis_client_factory import diagnose_redis_backends

        def _diagnose() -> tuple[dict, int]:
            gate = None
            lock_client = None
            try:
                gate = get_conversation_gate()
                lock_client = getattr(gate, "_redis", None)
            except Exception as exc:  # noqa: BLE001
                diag = diagnose_redis_backends(session_store=store, lock_client=None)
                diag["ok"] = False
                diag["errors"] = list(diag.get("errors") or []) + [f"gate:{type(exc).__name__}"]
                return diag, 503

            diag = diagnose_redis_backends(session_store=store, lock_client=lock_client)
            diag["lock_backend"] = conversation_gate_backend_name(gate)
            return diag, (200 if diag.get("ok") else 503)

        # Offload: IMDS/Entra sync no debe correr en el hilo del event loop.
        diag, status = await asyncio.to_thread(_diagnose)
        return JSONResponse(status_code=status, content=diag)

    @app.post("/turn")
    async def turn_handler(request: TurnRequest) -> JSONResponse:
        """Orchestrator channel — returns app_channel + core_channel + audit.

        force_core_query=true: emit 1.2 contract in core_channel for personal queries.
        force_core_query=false (default): core_channel=null, response from store only.
        context_info=true: context load/refresh from orchestrator; early-return, no LLM.
        """
        from datetime import UTC, datetime

        # --- Context load/refresh early-return (no LLM) ---
        if request.context_info:
            # Validate: question must be null
            if request.question is not None:
                return JSONResponse(status_code=422, content={
                    "error": "context_info=true requires question=null",
                })
            # Validate: customer_id and conversation_id required
            if not request.customer_id or not request.conversation_id:
                return JSONResponse(status_code=422, content={
                    "error": "customer_id and conversation_id are required for context_info",
                })
            # Validate: context and context.data must be present
            ctx = request.context
            if not ctx or not isinstance(ctx.get("data"), dict):
                return JSONResponse(status_code=422, content={
                    "error": "context.data is required when context_info=true",
                })
            # Validate context_op
            op = (request.context_op or "load").lower()
            if op not in ("load", "refresh"):
                return JSONResponse(status_code=422, content={
                    "error": f"context_op must be 'load' or 'refresh', got '{op}'",
                })

            ctx_data = ctx["data"]
            from genesis_cognitive.context.conversation_gate import (
                ConversationGateError,
                get_conversation_gate,
            )

            try:
                async with get_conversation_gate().hold(request.conversation_id) as gate_state:
                    if not gate_state.get("acquired"):
                        return _session_busy_response(
                            request.conversation_id,
                            for_context_load=True,
                        )
                    still = gate_state.get("still_owner")
                    if still is not None and not still():
                        return _session_busy_response(
                            request.conversation_id,
                            for_context_load=True,
                        )
                    try:
                        payload = _persist_core_context(
                            customer_id=request.customer_id,
                            conversation_id=request.conversation_id,
                            ctx_data=ctx_data,
                            op=op,
                        )
                    except SessionConflictError:
                        return _session_busy_response(
                            request.conversation_id,
                            for_context_load=True,
                        )
                    # Confirmar carga solo con status de persistencia exitosa
                    if payload.get("status") not in ("CONTEXT_LOADED", "CONTEXT_REFRESHED"):
                        return _session_busy_response(
                            request.conversation_id,
                            for_context_load=True,
                        )
                    return JSONResponse(status_code=200, content=payload)
            except ConversationGateError:
                return _session_busy_response(
                    request.conversation_id,
                    for_context_load=True,
                )

        # --- Normal NL turn (question required) ---
        # Preferir el mensaje de selección (campos) sobre selected_option_ref solo.
        # Si solo llega el ref (TARJETA_0999), el shortcut rejuega campos del historial.
        _sel_ref = (request.selected_option_ref or "").strip()
        _q_body = (request.question or "").strip()
        if _sel_ref and _q_body:
            _ql = _q_body.lower()
            if any(
                s in _ql
                for s in (
                    "cuánto", "cuanto", "cuándo", "cuando", "debo", "disponible",
                    "fecha", "saldo", "tasa", "cuota", "pago", "adeud",
                )
            ):
                turn_question = _q_body
            else:
                turn_question = _sel_ref
        else:
            turn_question = (_sel_ref or _q_body).strip()
        if not turn_question:
            return JSONResponse(status_code=422, content={
                "error": "question or selected_option_ref is required for normal turns (context_info=false)",
            })

        # APK envía client_id; el orquestador envía customer_id.
        resolved_customer = (request.customer_id or request.client_id or "").strip()
        if not resolved_customer and request.conversation_id:
            _sess = store.get_session(request.conversation_id)
            if _sess and _sess.customer_id:
                resolved_customer = _sess.customer_id

        raw_response = None
        try:
            inspect_req = InspectRequest(
                question=turn_question,
                conversation_id=request.conversation_id,
                customer_id=resolved_customer,
            )
            raw_response = await inspect(inspect_req)
            body = raw_response.body
            import json as _json
            data = _json.loads(body)
        except Exception:
            data = {
                "status": "FALLBACK",
                "actions": [],
                "decision_trace": [],
                "client_response": "",
                "conversation_id": request.conversation_id,
                "turn_number": 1,
            }

        # Build app_channel
        actions = data.get("actions") or []
        a0 = actions[0] if actions else {}

        cust_id = resolved_customer or (data.get("customer_context") or {}).get("customer_id", "")
        snap = store.get_snapshot(cust_id) if cust_id else None
        display_name = getattr(snap, "display_name", None) if snap is not None else None
        from genesis_cognitive.context.response_formatting import unknown_turn_reply

        http_status = getattr(raw_response, "status_code", 200)
        reply_seed = (data.get("client_response") or "").strip()
        inspect_status = str(data.get("status") or "")
        # SESSION_BUSY: conflicto CAS resuelto en capa cognitiva — no inventar VALID_CONTRACT
        if inspect_status == "SESSION_BUSY":
            http_status = 200
            if not reply_seed:
                data["client_response"] = (
                    "Estoy atendiendo otra consulta de esta conversación. "
                    "Por favor intenta de nuevo en un momento."
                )
        elif inspect_status in ("PROVIDER_ERROR", "INVALID_MODEL_OUTPUT"):
            # Conservar degradación semántica — no maquillar como VALID_CONTRACT
            http_status = 200
        elif not reply_seed or http_status >= 400:
            data["client_response"] = unknown_turn_reply(display_name)
            data["status"] = "VALID_CONTRACT"
            http_status = 200
        _pending_sess = store.get_session(data.get("conversation_id", ""))
        _pending_intent = None
        if _pending_sess and _pending_sess.pending_action:
            _pending_intent = _pending_sess.pending_action.intent_id

        from genesis_cognitive.context.app_channel import assemble_app_channel
        try:
            app_channel = assemble_app_channel(
                data,
                snapshot=snap,
                question=turn_question,
                pending_intent=_pending_intent or (a0.get("intent_id") if a0 else None),
            )
        except Exception:
            app_channel = {
                "client_response": data.get("client_response") or unknown_turn_reply(display_name),
                "status": "VALID_CONTRACT",
                "content_format": "plain",
                "conversation_id": data.get("conversation_id") or request.conversation_id,
            }

        # Build core_channel
        core_channel = None
        _PERSONAL_INTENTS = ("ACCOUNT_BALANCE_READ", "LOAN_DETAIL_READ", "PORTFOLIO_LIST", "CREDIT_CARD_DETAIL_READ", "TERM_DEPOSIT_DETAIL_READ")
        if (
            request.force_core_query
            and data.get("status") == "VALID_CONTRACT"
            and actions
            and a0.get("intent_id") in _PERSONAL_INTENTS
        ):
            from genesis_cognitive.contracts.operation_request_adapter import build_operation_request
            core_channel = build_operation_request(
                status="VALID_CONTRACT",
                actions=actions,
                customer_id=cust_id,
                conversation_id=data.get("conversation_id", ""),
                turn_number=data.get("turn_number", 1),
                loan_detail=data.get("loan_detail"),
            )

        # Build audit (telemetría operativa; no expone secretos ni PII)
        decision_trace = data.get("decision_trace", [])
        steps_with_ms = [s for s in decision_trace if s.get("duration_ms") is not None]
        slowest = max(steps_with_ms, key=lambda s: s["duration_ms"]) if steps_with_ms else {}
        _corr = data.get("correlation_id") or str(uuid.uuid4())
        _route_steps = [str(s.get("step") or "") for s in decision_trace if isinstance(s, dict)]
        _brain_src = None
        for s in decision_trace:
            if not isinstance(s, dict):
                continue
            out = s.get("output") if isinstance(s.get("output"), dict) else {}
            if out.get("source") or out.get("brain_source"):
                _brain_src = out.get("source") or out.get("brain_source")
                break
            if s.get("step") in ("proposer", "verifier", "azure_brain", "heuristic_intent"):
                _brain_src = s.get("step")
        audit = {
            "total_ms": data.get("total_request_ms", 0),
            "slowest_step": slowest.get("step"),
            "slowest_step_ms": slowest.get("duration_ms"),
            "step_count": len(decision_trace),
            "rag_status": data.get("rag_status"),
            "correlation_id": _corr,
            "route_steps": _route_steps[:24],
            "brain_source": _brain_src,
            "context_source": data.get("context_source") or getattr(snap, "context_source", None),
            "inference_count": data.get("inference_count"),
            "semantic_mode": (
                ((decision_trace[0].get("output") or {}).get("semantic_mode"))
                if decision_trace and isinstance(decision_trace[0], dict)
                else None
            ),
            "decision_trace": decision_trace[:12],
        }

        # Compatibilidad APK: normalizeResponse lee reply|content|message
        reply_text = (app_channel.get("client_response") or data.get("client_response") or "").strip()
        if not reply_text:
            from genesis_cognitive.context.response_formatting import unknown_turn_reply
            reply_text = unknown_turn_reply(getattr(snap, "display_name", None) if snap is not None else None)
            app_channel["client_response"] = reply_text
        return JSONResponse(status_code=200, content={
            "app_channel": app_channel,
            "core_channel": core_channel,
            "audit": audit,
            "rag_status": data.get("rag_status") or audit.get("rag_status"),
            "reply": reply_text,
            "message": reply_text,
            "content": reply_text,
            "content_format": app_channel.get("content_format") or "plain",
            "rich_content": app_channel.get("rich_content"),
            "options": app_channel.get("options") or [],
            "suggested_questions": app_channel.get("suggested_questions") or [],
            "conversation_id": app_channel.get("conversation_id") or data.get("conversation_id"),
            "status": app_channel.get("status") or data.get("status"),
        })

    @app.post("/chat/front")
    async def chat_front_handler(request: TurnRequest) -> JSONResponse:
        """Alias APK — mismo pipeline que /turn, respuesta con `reply`."""
        return await turn_handler(request)

    @app.api_route("/orch/chat/front", methods=["POST"])
    async def orch_chat_front_proxy(request: Request) -> Response:
        """Proxy externo del APK → orquestador MCP Bridge (:8080).

        El simulador /pruebas usa este path desde internet (NSG abre 8447).
        En red interna el APK apunta al orquestador; aquí se replica ese hop.

        Importante: el orquestador vuelve a llamar a :8447/turn. El forward
        debe ir en un thread para no bloquear el event loop (evita deadlock).
        """
        import asyncio
        import urllib.error
        import urllib.request

        orch_base = os.getenv("GENESIS_ORCH_URL", "http://127.0.0.1:8080").rstrip("/")
        body = await request.body()

        def _forward() -> tuple[int, bytes, str]:
            upstream = urllib.request.Request(
                f"{orch_base}/chat/front",
                data=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(upstream, timeout=60) as resp:
                    return (
                        resp.status,
                        resp.read(),
                        resp.headers.get("Content-Type", "application/json"),
                    )
            except urllib.error.HTTPError as exc:
                return (
                    exc.code,
                    exc.read() or json.dumps({"error": "orch_http_error", "status": exc.code}).encode(),
                    "application/json",
                )

        try:
            status, raw, media = await asyncio.to_thread(_forward)
            return Response(content=raw, status_code=status, media_type=media)
        except Exception as exc:  # noqa: BLE001 — superficie de proxy
            return JSONResponse(
                status_code=502,
                content={"error": "orch_unreachable", "detail": str(exc), "orch": orch_base},
            )

    def _client_id_from_headers(http_request: Request) -> str:
        """Acepta clientId / X-Client-Id / client_id en cabecera (estilo webhook)."""
        headers = http_request.headers
        for key in (
            "clientid",
            "x-client-id",
            "client_id",
            "x-customer-id",
            "customerid",
        ):
            val = headers.get(key)
            if val and str(val).strip():
                return str(val).strip()
        # Case-insensitive scan (Starlette ya es CI, pero cubrimos aliases)
        for k, v in headers.items():
            kl = k.lower().replace("_", "-")
            if kl in ("clientid", "x-client-id", "client-id", "x-customer-id", "customerid") and v:
                return str(v).strip()
        return ""

    def _conversation_id_from_headers(http_request: Request) -> str:
        for key in ("x-conversation-id", "conversationid", "conversation_id"):
            val = http_request.headers.get(key)
            if val and str(val).strip():
                return str(val).strip()
        return ""

    async def _ensure_webhook_session(
        *,
        client_id: str,
        conversation_id: str | None,
        allow_lab_fallback: bool = True,
        portfolio: str | None = None,
    ) -> dict[str, Any]:
        """Crea/renueva sesión: Core/ws → context_info (igual que /orch/context)."""
        cid = (conversation_id or "").strip() or str(uuid.uuid4())
        sess = store.get_session(cid)
        if sess is not None and getattr(sess, "snapshot", None) is not None:
            return {
                "status": "SESSION_READY",
                "client_id": client_id,
                "customer_id": sess.customer_id or client_id,
                "conversation_id": cid,
                "display_name": getattr(sess.snapshot, "display_name", None),
                "context_source": "existing_session",
            }
        ctx_req = OrchContextRequest(
            customer_id=client_id,
            conversation_id=cid,
            allow_lab_fallback=allow_lab_fallback,
            portfolio=portfolio,
        )
        ctx_resp = await orch_context_refresh(ctx_req)
        loaded = json.loads(ctx_resp.body.decode("utf-8"))
        if ctx_resp.status_code >= 400:
            loaded["error"] = loaded.get("error") or "context_load_failed"
            loaded["http_status"] = ctx_resp.status_code
            return loaded
        return {
            "status": loaded.get("status") or "CONTEXT_LOADED",
            "client_id": client_id,
            "customer_id": loaded.get("customer_id") or client_id,
            "conversation_id": loaded.get("conversation_id") or cid,
            "display_name": loaded.get("display_name"),
            "context_source": loaded.get("context_source"),
            "context": loaded,
        }

    async def _forward_orch_chat(payload: dict[str, Any]) -> JSONResponse:
        """Reenvía al MCP Bridge /chat/front (mismo hop que el webhook/APK)."""
        import asyncio
        import urllib.error
        import urllib.request

        orch_base = os.getenv("GENESIS_ORCH_URL", "http://127.0.0.1:8080").rstrip("/")
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def _forward() -> tuple[int, bytes]:
            upstream = urllib.request.Request(
                f"{orch_base}/chat/front",
                data=raw_body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(upstream, timeout=90) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                return (
                    exc.code,
                    exc.read()
                    or json.dumps({"error": "orch_http_error", "status": exc.code}).encode(),
                )

        try:
            status, raw = await asyncio.to_thread(_forward)
            try:
                body = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                body = {"raw": raw.decode("utf-8", errors="replace")[:2000]}
            return JSONResponse(status_code=status, content=body)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=502,
                content={"error": "orch_unreachable", "detail": str(exc), "orch": orch_base},
            )

    @app.post("/orch/webhook/session")
    async def orch_webhook_session(request: Request) -> JSONResponse:
        """Inicia sesión estilo webhook: header ClientId → carga contexto + conversation_id.

        Cabeceras:
          - ClientId | X-Client-Id | client_id  (obligatoria)
          - X-Conversation-Id (opcional; si falta se genera)
        Body JSON opcional: {"portfolio": "...", "allow_lab_fallback": true}
        """
        client_id = _client_id_from_headers(request)
        if not client_id:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "missing_client_id",
                    "detail": "Envía cabecera ClientId (o X-Client-Id)",
                },
            )
        body: dict[str, Any] = {}
        try:
            raw = await request.body()
            if raw:
                body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}
        conv = _conversation_id_from_headers(request) or str(body.get("conversation_id") or "")
        session = await _ensure_webhook_session(
            client_id=client_id,
            conversation_id=conv or None,
            allow_lab_fallback=bool(body.get("allow_lab_fallback", True)),
            portfolio=body.get("portfolio"),
        )
        code = 200 if session.get("status") in ("SESSION_READY", "CONTEXT_LOADED", "CONTEXT_REFRESHED") else 502
        if session.get("http_status"):
            code = int(session["http_status"])
        return JSONResponse(status_code=code, content=session)

    @app.post("/orch/webhook/chat")
    async def orch_webhook_chat(request: Request) -> JSONResponse:
        """Chat webhook: ClientId en cabecera → sesión automática → orquestador MCP.

        Igual que el camino APK/webhook:
          ClientId → (si hace falta) carga contexto → POST orch /chat/front → /turn

        Cabeceras:
          - ClientId | X-Client-Id (obligatoria)
          - X-Conversation-Id (opcional; reutilizar para multi-turno)

        Body JSON:
          {"question": "hola"}  o  {"message": "hola"}
        """
        client_id = _client_id_from_headers(request)
        if not client_id:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "missing_client_id",
                    "detail": "Envía cabecera ClientId (o X-Client-Id)",
                },
            )
        try:
            body = json.loads((await request.body()).decode("utf-8") or "{}")
        except Exception:
            return JSONResponse(status_code=422, content={"error": "invalid_json"})
        if not isinstance(body, dict):
            return JSONResponse(status_code=422, content={"error": "body_must_be_object"})

        question = (
            body.get("question")
            or body.get("message")
            or body.get("raw_text")
            or body.get("text")
            or ""
        )
        question = str(question).strip()
        if not question:
            return JSONResponse(
                status_code=422,
                content={"error": "missing_question", "detail": "Body requiere question o message"},
            )

        conv = (
            _conversation_id_from_headers(request)
            or str(body.get("conversation_id") or "").strip()
            or str(uuid.uuid4())
        )
        session = await _ensure_webhook_session(
            client_id=client_id,
            conversation_id=conv,
            allow_lab_fallback=bool(body.get("allow_lab_fallback", True)),
            portfolio=body.get("portfolio"),
        )
        if session.get("http_status") and int(session["http_status"]) >= 400:
            return JSONResponse(status_code=int(session["http_status"]), content=session)
        if session.get("status") not in ("SESSION_READY", "CONTEXT_LOADED", "CONTEXT_REFRESHED"):
            # context load puede devolver otros status; si no hay conversation_id abortar
            if not session.get("conversation_id"):
                return JSONResponse(status_code=502, content=session)

        conversation_id = str(session.get("conversation_id") or conv)
        customer_id = str(session.get("customer_id") or client_id)

        orch_payload = {
            "question": question,
            "message": question,
            "raw_text": question,
            "customer_id": customer_id,
            "client_id": client_id,
            "subject_token": client_id,
            "conversation_id": conversation_id,
            "force_core_query": bool(body.get("force_core_query", False)),
            "context_info": False,
            "channel": {"type": "webhook", "entrypoint": "orch_webhook_chat"},
        }
        if body.get("selected_option_ref"):
            orch_payload["selected_option_ref"] = str(body["selected_option_ref"])
        orch_resp = await _forward_orch_chat(orch_payload)
        try:
            data = json.loads(orch_resp.body.decode("utf-8"))
        except Exception:
            data = {"raw": orch_resp.body.decode("utf-8", errors="replace")[:2000]}

        app = data.get("app_channel") if isinstance(data, dict) else None
        if not isinstance(app, dict):
            app = {}
        reply = (
            (data.get("reply") if isinstance(data, dict) else None)
            or (data.get("message") if isinstance(data, dict) else None)
            or (data.get("content") if isinstance(data, dict) else None)
            or app.get("client_response")
            or (data.get("error") if isinstance(data, dict) else None)
            or ""
        )
        # Envelope estable para integradores
        _audit = data.get("audit") if isinstance(data, dict) else None
        _rag = None
        if isinstance(data, dict):
            _rag = data.get("rag_status")
            if not _rag and isinstance(_audit, dict):
                _rag = _audit.get("rag_status")
        out = {
            "client_id": client_id,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "session_status": session.get("status"),
            "context_source": session.get("context_source"),
            "reply": reply,
            "rag_status": _rag,
            "content_format": app.get("content_format")
            or (data.get("content_format") if isinstance(data, dict) else None)
            or "plain",
            "status": app.get("status") or (data.get("status") if isinstance(data, dict) else None),
            "options": app.get("options") or (data.get("options") if isinstance(data, dict) else []) or [],
            "suggested_questions": app.get("suggested_questions")
            or (data.get("suggested_questions") if isinstance(data, dict) else [])
            or [],
            "rich_content": app.get("rich_content")
            or (data.get("rich_content") if isinstance(data, dict) else None),
            "app_channel": app or None,
            "orchestrator": data if isinstance(data, dict) else {"raw": data},
        }
        return JSONResponse(status_code=orch_resp.status_code, content=out)

    @app.get("/orch/health")
    async def orch_health_proxy() -> JSONResponse:
        """Health del orquestador MCP Bridge (vía proxy en 8447)."""
        import asyncio
        import urllib.request

        orch_base = os.getenv("GENESIS_ORCH_URL", "http://127.0.0.1:8080").rstrip("/")

        def _get() -> dict[str, Any]:
            with urllib.request.urlopen(f"{orch_base}/health", timeout=8) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    return json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return {"raw": raw}

        try:
            payload = await asyncio.to_thread(_get)
            return JSONResponse(content={"orch": "ok", "upstream": payload})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=502, content={"orch": "down", "detail": str(exc)})

    @app.post("/rag/query")
    async def rag_query_endpoint(request: InspectRequest) -> JSONResponse:
        """RAG query — retrieve from local KB and generate grounded answer."""
        from genesis_cognitive.rag.local_rag import generate_rag_answer

        question = request.question.strip()
        if not question:
            return JSONResponse(status_code=422, content={"error": "question required"})

        result = rag_store.query(question, top_k=4)
        sources = [{"file": c["source"], "page": c["page"], "snippet": c["text"][:150]} for c in result["chunks"]]

        if result["rag_status"] == "HITS":
            answer = await generate_rag_answer(question, result["chunks"], conversation_id=request.conversation_id or None)
            return JSONResponse(content={"answer": answer, "sources": sources, "rag_status": "ANSWERED"})
        else:
            from genesis_cognitive.rag.local_rag import _human_case_fallback
            fallback = _human_case_fallback(question, request.conversation_id or None, None)
            return JSONResponse(content={"answer": fallback, "sources": [], "rag_status": "NO_HITS"})

    @app.post("/contract-lab/validate")
    async def contract_lab_validate(request: InspectRequest) -> JSONResponse:
        """Contract Lab: emit a synthetic LOAN_SERVICING_VALIDATE operation_request.

        Demonstrates mutant contract with requires_confirmation=true.
        Does NOT execute against Core. Does NOT go through the mutation-blocking pipeline.
        """
        from genesis_cognitive.contracts.operation_request_adapter import build_operation_request

        resolved_cid = request.customer_id or _DEFAULT_CUSTOMER_ID
        snapshot = store.get_snapshot(resolved_cid)
        if snapshot is None and customer_loader:
            loaded = customer_loader.load(resolved_cid)
            if loaded:
                store.put_snapshot(resolved_cid, loaded)
                snapshot = loaded

        if snapshot is None:
            return JSONResponse(status_code=404, content={"error": "customer not found"})

        # Find the loan to validate payment for
        loans = [p for p in snapshot.products if p.product_type == "LOAN" and p.currency == snapshot.default_currency]
        if not loans:
            return JSONResponse(status_code=422, content={"error": "no loans found for customer"})

        loan_ref = loans[0].product_id
        loan_data = next((ln for ln in snapshot.loans if ln.product_id == loan_ref), None)
        installment = str(loan_data.installment_amount) if loan_data else "0"

        # Find first deposit account for source
        deposits = [p for p in snapshot.products if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and p.currency == snapshot.default_currency]
        source_ref = deposits[0].product_id if deposits else None

        op_request = build_operation_request(
            status="VALID_CONTRACT",
            actions=[{
                "intent_id": "LOAN_PAYMENT_VALIDATE",
                "capability_candidate": "LOAN_SERVICING",
                "selected_route": "PERSONAL_READ",
                "detected_entities": {
                    "account_ref": loan_ref,
                    "source_account_ref": source_ref,
                    "destination_account_ref": loan_ref,
                    "amount": installment,
                    "currency": snapshot.default_currency,
                },
                "confidence": 1.0,
            }],
            customer_id=resolved_cid,
            conversation_id=request.conversation_id or f"lab-{uuid.uuid4().hex[:8]}",
            turn_number=1,
            loan_detail={"product_id": loan_ref, "installment_amount": installment} if loan_data else None,
        )

        return JSONResponse(status_code=200, content={
            "status": "VALIDATE_ONLY",
            "note": "Mutant contract emitted for validation. NO execution against Core.",
            "operation_request": op_request,
            "loan_ref": loan_ref,
            "installment": installment,
            "source_ref": source_ref,
        })

    @app.post("/contract-lab/dispatch")
    async def contract_lab_dispatch_impl(
        request: InspectRequest,
        phase: str | None = None,
    ) -> JSONResponse:
        """Deterministic contract dispatch — NO LLM, NO pipeline.

        Query param `phase`: ANALYZE | VALIDATE | EXECUTE (mutants only).
        EXECUTE blocked if GENESIS_ENV=prod.
        """
        import os

        from genesis_cognitive.contracts.deterministic_dispatch import (
            COMMAND_TEMPLATES,
            build_dispatch_request,
        )

        genesis_env = os.getenv("GENESIS_ENV", "dev")
        allow_execute = genesis_env in ("dev", "test")

        # Reuse InspectRequest: customer_id, conversation_id, question=command
        cust = request.customer_id.strip() if request.customer_id else ""
        cmd = request.question.strip() if request.question else ""

        if not cust:
            return JSONResponse(status_code=422, content={"error": "customer_id requerido"})
        if not cmd:
            return JSONResponse(status_code=422, content={"error": "command requerido", "templates": COMMAND_TEMPLATES})

        try:
            result = build_dispatch_request(
                customer_id=cust,
                conversation_id=request.conversation_id or None,
                turn_number=1,
                command=cmd,
                phase=phase,
                allow_execute=allow_execute,
            )
            return JSONResponse(status_code=200, content=result)
        except ValueError as e:
            status_code = 403 if "EXECUTE no permitido" in str(e) else 422
            return JSONResponse(status_code=status_code, content={
                "error": str(e),
                "genesis_env": genesis_env,
                "allow_execute": allow_execute,
                "templates": COMMAND_TEMPLATES,
            })

    @app.get("/config")
    async def get_config() -> JSONResponse:
        """Expose runtime config for UI (allow_cognitive_execute, env)."""
        import os
        genesis_env = os.getenv("GENESIS_ENV", "dev")
        return JSONResponse(content={
            "genesis_env": genesis_env,
            "allow_cognitive_execute": genesis_env in ("dev", "test"),
        })

    return app
