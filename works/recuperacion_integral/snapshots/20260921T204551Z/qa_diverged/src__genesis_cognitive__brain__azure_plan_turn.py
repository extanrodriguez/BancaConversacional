"""Ejecución de un turno en modo GENESIS_SEMANTIC_MODE=azure_plan."""

from __future__ import annotations

import time
import uuid
from typing import Any

from genesis_cognitive.brain.azure_plan_adapter import (
    interpretation_to_turn_plan,
    is_unequivocal_structured_shortcut,
    plan_from_pending_selection,
)
from genesis_cognitive.brain.plan_executor import execute_turn_plan
from genesis_cognitive.brain.plan_interpreter import interpret_turn_plan
from genesis_cognitive.brain.semantic_mode import azure_deployment_name
from genesis_cognitive.brain.turn_plan import InvalidTurnPlanError
from genesis_cognitive.model_input.model_input_builder import (
    ProjectedPendingAction,
    ProjectedProduct,
    ProjectedTurn,
    project_conversation_memory,
)

# Versión cognitiva desplegada (trazabilidad /turn; no altera contrato externo)
COGNITIVE_CODE_VERSION = "potenciacion-strict-v2.2"
KNOWLEDGE_VERSION = "bsc-kb-2026-09-19-candidate-1"


def _version_fields() -> dict[str, str]:
    return {
        "cognitive_code_version": COGNITIVE_CODE_VERSION,
        "knowledge_version": KNOWLEDGE_VERSION,
    }


def _provider_for_brain(brain_source: str, *, inference_count: int = 0) -> str:
    """Etiqueta honesta: no reportar AZURE_OPENAI si el modelo no se invocó."""
    if brain_source == "structured_shortcut":
        return "STRUCTURED_SHORTCUT"
    if brain_source == "deterministic_fastpath_pre_azure":
        return "DETERMINISTIC_FASTPATH"
    if brain_source in ("structural_repair",) and inference_count <= 0:
        return "LOCAL_TURN_PLAN"
    if inference_count > 0:
        return "AZURE_OPENAI"
    if brain_source in ("resolve_full", "azure_plan"):
        return "AZURE_OPENAI"
    return "LOCAL_TURN_PLAN"


def _norm_q(text: str) -> str:
    return (text or "").strip().lower()


def _eligible_for_deterministic_fastpath(question: str) -> bool:
    """Casos que el fastpath ya resolvía bien antes de azure_plan (regresiones UX).

    No consume consultas multi-intención (P01 y similares): el intérprete/plan
    debe conservar todos los campos.
    """
    from genesis_cognitive.router.field_guardrails import (
        is_compound_personal_query,
        is_personal_payment_date_question,
    )
    from genesis_cognitive.router.reclamacion_guardrail import is_reclamacion_question

    q = _norm_q(question)
    if is_compound_personal_query(question):
        return False
    if is_personal_payment_date_question(question):
        return True
    if is_reclamacion_question(question):
        return True
    if any(s in q for s in ("fallecido", "fallecimiento", "de cujus")):
        return True
    # Procesos KB explícitos (no personales)
    if "proceso" in q and any(
        s in q for s in ("reclam", "fallecid", "cancel", "retiro de fondo")
    ):
        return True
    return False


def _apply_fastpath_pending(
    session_state: Any,
    *,
    question: str,
    status: str,
    step: str,
    intent: str | None,
    acts: list,
) -> None:
    """Replica el pending de clarificación del fastpath legacy (canal / producto)."""
    if session_state is None or status != "CLARIFICATION_REQUIRED":
        return
    from genesis_cognitive.context.query_spec import build_query_spec
    from genesis_cognitive.context.reactive_store import PendingAction

    topic = None
    if acts:
        topic = (acts[0].get("detected_entities") or {}).get("knowledge_topic")
    is_reclamacion = (topic or "") == "RECLAMACION_CHANNEL" or step == "reclamacion"
    if is_reclamacion:
        session_state.pending_action = PendingAction(
            intent_id=intent or "BUSINESS_KNOWLEDGE_QUERY",
            capability_candidate="BUSINESS_KNOWLEDGE",
            selected_route="BUSINESS_RAG",
            detected_entities={
                "account_ref": None,
                "knowledge_topic": "RECLAMACION_CHANNEL",
            },
            missing_requirements=["reclamacion_channel"],
            suggested_question="",
            original_question=question or "",
            query_spec=build_query_spec(question or "", intent),
        )
        return
    pend_intent = intent or "PAYMENT_DATE_READ"
    session_state.pending_action = PendingAction(
        intent_id=pend_intent,
        capability_candidate={
            "PAYMENT_DATE_READ": "PRODUCT_FIELD",
            "LOAN_DETAIL_READ": "LOAN_DETAIL",
            "CREDIT_CARD_DETAIL_READ": "CREDIT_CARD_DETAIL",
        }.get(pend_intent, "PRODUCT_FIELD"),
        selected_route="PERSONAL_READ",
        detected_entities={"account_ref": None},
        missing_requirements=["account_ref"],
        suggested_question="",
        original_question=question or "",
        query_spec=build_query_spec(question or "", pend_intent),
    )
    spec = getattr(session_state.pending_action, "query_spec", None) or {}
    field = {
        "payment_due_date": "due_date",
        "cutoff_date": "cutoff",
        "available_balance": "available",
        "minimum_payment": "min_payment",
        "payoff_amount": "payoff",
        "maturity_date": "maturity",
        "rate": "rate",
        "balance": "balance",
        "installment_amount": "installment_amount",
        "principal": "principal",
        "overdue": "overdue",
        "credit_limit": "limit",
        "movements": "movements",
    }.get(str(spec.get("field") or ""), "due_date" if pend_intent == "PAYMENT_DATE_READ" else "balance")
    obj = {
        "PAYMENT_DATE_READ": "product",
        "LOAN_DETAIL_READ": "loan",
        "CREDIT_CARD_DETAIL_READ": "credit_card",
        "ACCOUNT_BALANCE_READ": "account",
        "TERM_DEPOSIT_DETAIL_READ": "term_deposit",
    }.get(pend_intent, "product")
    session_state.pending_tasks = [{
        "task_id": "t1",
        "object": obj,
        "fields": [field],
        "original_question": question or "",
        "display_order": [],
    }]


def _fastpath_bridge_payload(
    *,
    hit: tuple,
    question: str,
    session_state: Any,
    azure_model: str,
    prompt_version: str,
    conv_id: str,
    turn_number: int,
    history: list[dict],
    customer_snapshot: Any,
    customer_id: str,
    request_start: float,
    request_id: str,
    timings: dict[str, float],
) -> dict[str, Any]:
    st, acts, txt, sug, step, intent, ref = hit
    _apply_fastpath_pending(
        session_state,
        question=question,
        status=st,
        step=step or "",
        intent=intent,
        acts=acts or [],
    )
    # Conservar topic KB cuando el FAQ entregó overview
    if acts and intent == "BUSINESS_KNOWLEDGE_QUERY":
        topic = (acts[0].get("detected_entities") or {}).get("knowledge_topic")
        if topic and str(topic).upper() not in ("KB_AMBIGUITY", "RECLAMACION_CHANNEL"):
            try:
                session_state.last_knowledge_topic = str(topic)[:200]
            except Exception:
                pass
    mode = "CLARIFICATION" if st == "CLARIFICATION_REQUIRED" else "SINGLE"
    history.append({
        "turn": turn_number,
        "question": question,
        "status": st,
        "intent": intent,
        "semantic_mode": "azure_plan",
        "fastpath_step": step,
    })
    return {
        "provider": _provider_for_brain("deterministic_fastpath_pre_azure"),
        "framework": "MICROSOFT_AGENT_FRAMEWORK",
        "model": azure_model,
        "prompt_version": prompt_version,
        **_version_fields(),
        "conversation_id": conv_id,
        "turn_number": turn_number,
        "conversation_history": history,
        "status": st,
        "mode": mode,
        "intent_id": intent or "TURN_PLAN_MULTI",
        "actions": acts or [],
        "clarifications": [],
        "unsupported_segments": [],
        "client_response": txt or "",
        "suggested_questions": sug or [],
        "rag_status": "FAQ" if step in ("faq", "reclamacion") else "NOT_REQUIRED",
        "inference_count": 0,
        "customer_context": {
            "customer_id": getattr(customer_snapshot, "customer_id", None) or customer_id,
            "display_name": getattr(customer_snapshot, "display_name", None),
        },
        "decision_trace": [{
            "step": "azure_plan",
            "output": {
                "semantic_mode": "azure_plan",
                "route_source": f"field_fastpath:{step}",
                "brain_source": "deterministic_fastpath_pre_azure",
                "fastpath_step": step,
                "account_ref": ref,
                "stage_timings_ms": timings,
                "not_heuristic_fallback": False,
                "deterministic_bridge": True,
                "inference_count": 0,
                **_version_fields(),
            },
            "duration_ms": round((time.perf_counter() - request_start) * 1000),
        }],
        "total_request_ms": round((time.perf_counter() - request_start) * 1000),
        "stage_timings_ms": timings,
        "correlation_id": request_id,
        "_pex": None,
        "_plan": None,
        "_apply_state": False,
    }


async def build_turn_envelope(
    *,
    question: str,
    session_state: Any,
    history: list[dict],
    customer_snapshot: Any,
    model_input_builder: Any,
    context_assembler: Any,
    input_validator: Any,
    conv_id: str,
    customer_id: str,
) -> Any:
    """Construye ModelInputEnvelope con memoria y portafolio del mismo snapshot."""
    payload: dict[str, object] = {
        "type": "USER_MESSAGE",
        "conversation_id": conv_id,
        "customer_id": customer_id,
        "subject_token": "demo-token",
        "request_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "user_turn": {"raw_text": question},
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

    if customer_snapshot is not None:
        from genesis_cognitive.model_input.model_input_builder import _project_one_product

        filtered = tuple(
            _project_one_product(p)
            for p in customer_snapshot.products
            if str(p.status).lower() == "active"
        )
        model_input = model_input.model_copy(update={"portfolio": filtered})

    pending = getattr(session_state, "pending_action", None)
    if pending is not None:
        model_input = model_input.model_copy(update={
            "pending_action": ProjectedPendingAction(
                intent_id=pending.intent_id,
                capability_candidate=pending.capability_candidate,
                selected_route=pending.selected_route,
                detected_entities=pending.detected_entities,
                missing_requirements=pending.missing_requirements,
                suggested_question=pending.suggested_question,
                original_question=getattr(pending, "original_question", "") or "",
                query_spec=dict(getattr(pending, "query_spec", {}) or {}),
            ),
        })

    if history:
        turns = tuple(
            ProjectedTurn(
                role="user",
                summary=f"[T{t.get('turn')}] {str(t.get('question') or '')[:80]} → {t.get('status', '?')}",
            )
            for t in history[-5:]
        )
        model_input = model_input.model_copy(update={"conversation": turns})

    # Completitud: lab vs core desconocido (no afirmar inventario completo)
    completeness = "unknown"
    src = getattr(session_state, "snapshot_source", None) or getattr(
        session_state, "context_source", None,
    )
    if isinstance(src, str) and "lab" in src.lower():
        completeness = "lab_fallback"
    rev = None
    fetched = getattr(session_state, "snapshot_source_fetched_at", None)
    if fetched is not None:
        rev = str(int(fetched)) if isinstance(fetched, (int, float)) else str(fetched)
    mem = project_conversation_memory(
        session_state,
        context_source=str(src) if src else None,
        snapshot_revision=rev,
        portfolio_completeness=completeness,
    )
    model_input = model_input.model_copy(update={"conversation_memory": mem})
    return model_input


def merge_pending_tasks(
    existing: list[dict] | None,
    incoming: list[dict] | None,
    *,
    clear_ids: set[str] | None = None,
    replace_all: bool = False,
) -> list[dict]:
    """Fusiona pendientes por task_id; no borra familias no resueltas."""
    if replace_all:
        return list(incoming or [])
    by_id: dict[str, dict] = {}
    for pt in existing or []:
        if not isinstance(pt, dict):
            continue
        tid = str(pt.get("task_id") or pt.get("id") or "")
        if tid:
            by_id[tid] = dict(pt)
    for tid in clear_ids or set():
        by_id.pop(tid, None)
    for pt in incoming or []:
        if not isinstance(pt, dict):
            continue
        tid = str(pt.get("task_id") or pt.get("id") or "")
        if tid:
            by_id[tid] = dict(pt)
    return list(by_id.values())


def _error_payload(
    *,
    exc: BaseException,
    stage: str,
    azure_model: str,
    prompt_version: str,
    conv_id: str,
    turn_number: int,
    history: list,
    request_start: float,
    inference_count: int = 0,
    call_meta: list | None = None,
    tasks_before: int | None = None,
    tasks_after: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    cause = getattr(exc, "internal_cause", None)
    return {
        "provider": "AZURE_OPENAI",
        "framework": "MICROSOFT_AGENT_FRAMEWORK",
        "model": azure_model,
        "prompt_version": prompt_version,
        "conversation_id": conv_id,
        "turn_number": turn_number,
        "conversation_history": history,
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
        "inference_count": inference_count,
        "decision_trace": [{
            "step": "azure_plan_error",
            "output": {
                "error_class": type(exc).__name__,
                "error_stage": stage,
                "cause_class": type(cause).__name__ if cause else None,
                "semantic_mode": "azure_plan",
                "degraded": True,
                "not_heuristic_fallback": True,
                "deployment": azure_deployment_name(default=azure_model),
                "prompt_version": prompt_version,
                "schema": "ModelSemanticProposal/VerifiedSemanticProposal",
                "request_id": request_id,
                "tasks_before": tasks_before,
                "tasks_after": tasks_after,
                "calls": call_meta or [],
                "failed_model_attempts": max(1, inference_count) if stage.startswith("model") else inference_count,
            },
        }],
        "total_request_ms": round((time.perf_counter() - request_start) * 1000),
        "correlation_id": str(uuid.uuid4()),
        "stage_timings_ms": {},
        "_pex": None,
        "_plan": None,
        "_apply_state": False,
    }


async def run_azure_plan_path(
    *,
    question: str,
    safe_question: str,
    session_state: Any,
    history: list[dict],
    customer_snapshot: Any,
    resolver: Any,
    model_input_builder: Any,
    context_assembler: Any,
    input_validator: Any,
    conv_id: str,
    customer_id: str,
    turn_number: int,
    azure_model: str,
    prompt_version: str,
    request_start: float,
) -> dict[str, Any]:
    """Ejecuta ruta canónica azure_plan. Devuelve cuerpo JSON de /turn.

    Nunca etiqueta source=azure si el modelo no fue invocado.
    Nunca degrada en silencio a heurística legacy.
    """
    timings: dict[str, float] = {}
    shortcut, shortcut_reason = is_unequivocal_structured_shortcut(
        question, session_state, snapshot=customer_snapshot,
    )
    inference_count = 0
    call_meta: list[dict] = []
    deployment = azure_deployment_name(default=azure_model)
    request_id = str(uuid.uuid4())
    failed_attempts = 0
    brain_source = "resolve_full"
    route_source = "azure_plan"

    # Puente determinista: fecha de pago / reclamación / procesos FAQ que el
    # fastpath ya resolvía y que azure_plan estaba rompiendo (PROVIDER_ERROR /
    # «definición» / «Seleccionaste None»).
    if customer_snapshot is not None and _eligible_for_deterministic_fastpath(question):
        t_fp = time.perf_counter()
        try:
            from genesis_cognitive.router.field_guardrails import run_field_fastpath

            pending_topic = None
            pa = getattr(session_state, "pending_action", None)
            if pa is not None:
                pending_topic = (getattr(pa, "detected_entities", None) or {}).get(
                    "knowledge_topic"
                )
            fp_hit = run_field_fastpath(
                customer_snapshot,
                question,
                getattr(session_state, "last_resolved", None),
                pending_knowledge_topic=pending_topic,
                session=session_state,
            )
        except Exception:
            fp_hit = None
        timings["deterministic_fastpath_ms"] = round(
            (time.perf_counter() - t_fp) * 1000, 1,
        )
        if fp_hit is not None and (fp_hit[2] or "").strip():
            return _fastpath_bridge_payload(
                hit=fp_hit,
                question=safe_question or question,
                session_state=session_state,
                azure_model=azure_model,
                prompt_version=prompt_version,
                conv_id=conv_id,
                turn_number=turn_number,
                history=history,
                customer_snapshot=customer_snapshot,
                customer_id=customer_id,
                request_start=request_start,
                request_id=request_id,
                timings=timings,
            )

    if shortcut:
        t0 = time.perf_counter()
        plan = None
        # Definiciones/glosario no deben consumirse como selección de pending personal
        if shortcut_reason not in (
            "kb_glossary_available",
            "kb_joven",
            "kb_reclamacion",
            "kb_fallecidos",
            "kb_catalog_define",
            "kb_cancelacion",
        ):
            plan = plan_from_pending_selection(
                selected_ref=question,
                session=session_state,
                question=safe_question,
                snapshot=customer_snapshot,
            )
        if plan is None:
            plan = interpret_turn_plan(question, session_state, snapshot=customer_snapshot)
            plan.source = f"shortcut:{shortcut_reason}"
        pex = execute_turn_plan(plan, customer_snapshot, question, session=session_state)
        timings["shortcut_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        route_source = plan.source
        brain_source = "structured_shortcut"
    else:
        t_env = time.perf_counter()
        envelope = await build_turn_envelope(
            question=safe_question,
            session_state=session_state,
            history=history,
            customer_snapshot=customer_snapshot,
            model_input_builder=model_input_builder,
            context_assembler=context_assembler,
            input_validator=input_validator,
            conv_id=conv_id,
            customer_id=customer_id,
        )
        timings["envelope_ms"] = round((time.perf_counter() - t_env) * 1000, 1)

        result = None
        last_exc: BaseException | None = None
        for attempt in range(2):  # intento + 1 reparación limitada
            t_model = time.perf_counter()
            try:
                result = await resolver.resolve_full(envelope)
                timings[f"resolve_full_attempt{attempt+1}_ms"] = round(
                    (time.perf_counter() - t_model) * 1000, 1,
                )
                break
            except Exception as exc:  # noqa: BLE001
                failed_attempts += 1
                last_exc = exc
                timings[f"resolve_full_attempt{attempt+1}_ms"] = round(
                    (time.perf_counter() - t_model) * 1000, 1,
                )
                # Reintento único solo para InvalidModelOutput; luego cae a reparación
                if attempt == 0 and type(exc).__name__ == "InvalidModelOutputError":
                    continue
                break

        if result is None and last_exc is not None:
            # Reparación estructural acotada tras fallos de modelo (no inventa montos)
            from genesis_cognitive.brain.azure_plan_adapter import _institutional_fields_from_question
            qn = (safe_question or "").lower()
            # Reintento determinista (mismos casos del puente pre-Azure)
            if customer_snapshot is not None and _eligible_for_deterministic_fastpath(question):
                try:
                    from genesis_cognitive.router.field_guardrails import run_field_fastpath

                    fp_hit = run_field_fastpath(
                        customer_snapshot,
                        question,
                        getattr(session_state, "last_resolved", None),
                        session=session_state,
                    )
                    if fp_hit is not None and (fp_hit[2] or "").strip():
                        return _fastpath_bridge_payload(
                            hit=fp_hit,
                            question=safe_question or question,
                            session_state=session_state,
                            azure_model=azure_model,
                            prompt_version=prompt_version,
                            conv_id=conv_id,
                            turn_number=turn_number,
                            history=history,
                            customer_snapshot=customer_snapshot,
                            customer_id=customer_id,
                            request_start=request_start,
                            request_id=request_id,
                            timings=timings,
                        )
                except Exception:
                    pass
            if (
                _institutional_fields_from_question(safe_question)
                or ("tasa" in qn and any(s in qn for s in ("significa", "préstamo", "prestamo")))
                or ("cuenta" in qn and ("préstamo" in qn or "prestamo" in qn))
                or any(s in qn for s in (
                    "corriente", "misión", "mision", "además", "ademas",
                    "fecha", "pago", "reclam", "fallecid", "proceso",
                ))
            ):
                t_rep = time.perf_counter()
                plan = interpret_turn_plan(
                    question, session_state, snapshot=customer_snapshot,
                )
                plan.source = f"repair:after_{type(last_exc).__name__}"
                pex = execute_turn_plan(plan, customer_snapshot, question, session=session_state)
                timings["invalid_output_repair_ms"] = round(
                    (time.perf_counter() - t_rep) * 1000, 1,
                )
                history.append({
                    "turn": turn_number,
                    "question": safe_question,
                    "status": pex.status,
                    "intent": pex.intent_id,
                    "plan_tasks": len(plan.tasks),
                    "semantic_mode": "azure_plan",
                })
                return {
                    "provider": "AZURE_OPENAI",
                    "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": history,
                    "status": pex.status,
                    "mode": "CLARIFICATION" if pex.status == "CLARIFICATION_REQUIRED" else "SINGLE",
                    "intent_id": pex.intent_id,
                    "actions": pex.actions or [],
                    "clarifications": [],
                    "unsupported_segments": [],
                    "client_response": pex.text,
                    "suggested_questions": getattr(pex, "suggestions", None) or [],
                    "app_channel_options": getattr(pex, "options", None),
                    "rag_status": "FAQ" if pex.route == "knowledge" else "NOT_REQUIRED",
                    "inference_count": failed_attempts,
                    "customer_context": {
                        "customer_id": getattr(customer_snapshot, "customer_id", None) or customer_id,
                        "display_name": getattr(customer_snapshot, "display_name", None),
                    },
                    "decision_trace": [{
                        "step": "azure_plan",
                        "output": {
                            "semantic_mode": "azure_plan",
                            "route_source": plan.source,
                            "brain_source": "repair_after_model_error",
                            "deployment": deployment,
                            "task_count": len(plan.tasks),
                            "task_statuses": (pex.trace or {}).get("task_statuses"),
                            "transition": plan.transition,
                            "calls": call_meta,
                            "failed_model_attempts": failed_attempts,
                            "error_class": type(last_exc).__name__,
                            "stage_timings_ms": timings,
                        },
                        "duration_ms": round((time.perf_counter() - request_start) * 1000),
                    }],
                    "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                    "stage_timings_ms": timings,
                    "correlation_id": request_id,
                    "_pex": pex,
                    "_plan": plan,
                    "_apply_state": True,
                }
            return _error_payload(
                exc=last_exc,
                stage="model_resolve_full_exhausted",
                azure_model=azure_model,
                prompt_version=prompt_version,
                conv_id=conv_id,
                turn_number=turn_number,
                history=history,
                request_start=request_start,
                inference_count=failed_attempts,
                call_meta=call_meta,
                request_id=request_id,
            )

        assert result is not None
        inference_count = len(getattr(result, "call_records", None) or [])
        for rec in getattr(result, "call_records", None) or []:
            call_meta.append({
                "name": getattr(rec, "name", None),
                "duration_ms": getattr(rec, "duration_ms", None),
                "deployment": getattr(rec, "deployment", deployment),
            })

        def _eligible_for_structural_repair(q: str) -> bool:
            from genesis_cognitive.brain.azure_plan_adapter import _institutional_fields_from_question
            qn = (q or "").lower()
            return bool(
                _institutional_fields_from_question(q)
                or any(
                    s in qn
                    for s in (
                        "tasa", "préstamo", "prestamo", "saldo", "cuenta",
                        "disponible", "corriente", "misión", "mision",
                        "además", "ademas", "definición", "definicion",
                        "significa", "contable", "ahorros", "ahorro",
                        "vence", "vencimiento", "pronto", "tarjeta", "cuota",
                        "pagar",
                    )
                )
            )

        def _run_structural_repair(label: str) -> dict[str, Any]:
            t_rep = time.perf_counter()
            repair_plan = interpret_turn_plan(
                question, session_state, snapshot=customer_snapshot,
            )
            repair_plan.source = label
            repair_pex = execute_turn_plan(
                repair_plan, customer_snapshot, question, session=session_state,
            )
            timings["structural_repair_ms"] = round(
                (time.perf_counter() - t_rep) * 1000, 1,
            )
            history.append({
                "turn": turn_number,
                "question": safe_question,
                "status": repair_pex.status,
                "intent": repair_pex.intent_id,
                "plan_tasks": len(repair_plan.tasks),
                "semantic_mode": "azure_plan",
            })
            mode = (
                "CLARIFICATION"
                if repair_pex.status == "CLARIFICATION_REQUIRED"
                else "SINGLE"
            )
            return {
                "provider": "AZURE_OPENAI",
                "framework": "MICROSOFT_AGENT_FRAMEWORK",
                "model": azure_model,
                "prompt_version": prompt_version,
                "conversation_id": conv_id,
                "turn_number": turn_number,
                "conversation_history": history,
                "status": repair_pex.status,
                "mode": mode,
                "intent_id": repair_pex.intent_id,
                "actions": repair_pex.actions or [],
                "clarifications": [],
                "unsupported_segments": [],
                "client_response": repair_pex.text,
                "suggested_questions": getattr(repair_pex, "suggestions", None) or [],
                "app_channel_options": getattr(repair_pex, "options", None),
                "rag_status": "FAQ" if repair_pex.route == "knowledge" else "NOT_REQUIRED",
                "inference_count": inference_count or failed_attempts,
                "customer_context": {
                    "customer_id": getattr(customer_snapshot, "customer_id", None) or customer_id,
                    "display_name": getattr(customer_snapshot, "display_name", None),
                },
                "decision_trace": [{
                    "step": "azure_plan",
                    "output": {
                        "semantic_mode": "azure_plan",
                        "route_source": repair_plan.source,
                        "brain_source": "structural_repair",
                        "deployment": deployment,
                        "task_count": len(repair_plan.tasks),
                        "task_statuses": (repair_pex.trace or {}).get("task_statuses"),
                        "transition": repair_plan.transition,
                        "calls": call_meta,
                        "inference_count": inference_count,
                        "failed_model_attempts": failed_attempts,
                        "stage_timings_ms": timings,
                        "repaired_from": result.status,
                        "interpretation_present": result.interpretation is not None,
                    },
                    "duration_ms": round((time.perf_counter() - request_start) * 1000),
                }],
                "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                "stage_timings_ms": timings,
                "correlation_id": request_id,
                "_pex": repair_pex,
                "_plan": repair_plan,
                "_apply_state": True,
            }

        # Si verifier dejó interpretation=None (p. ej. CLARIFICATION vacía) pero el
        # proposer entregó ACTIONS, intentar ensamblar ese proposal. Si el plan
        # recuperado no cubre vencimientos/ventana cuando la pregunta lo pide,
        # descartar y caer a reparación estructural (no acreditar proposal erróneo).
        if result.interpretation is None:
            initial = getattr(result, "initial_proposal", None)
            if (
                initial is not None
                and getattr(initial, "result_type", None) == "ACTIONS"
                and getattr(initial, "actions", None)
            ):
                try:
                    from genesis_cognitive.agents.agent_framework_turn_resolver import (
                        assemble_canonical_interpretation,
                    )
                    from genesis_cognitive.brain.azure_plan_adapter import (
                        interpretation_to_turn_plan as _to_plan,
                    )

                    t_init = time.perf_counter()
                    recovered = assemble_canonical_interpretation(initial, envelope)
                    timings["initial_proposal_recovery_ms"] = round(
                        (time.perf_counter() - t_init) * 1000, 1,
                    )
                    qn_rec = (safe_question or question or "").lower()
                    wants_upcoming = any(
                        s in qn_rec
                        for s in (
                            "vence", "vencimiento", "pronto", "estos dias", "estos días",
                            "proxima cuota", "próxima cuota", "pago proximo", "pago próximo",
                        )
                    )
                    accept_recovery = recovered.interpretation is not None
                    if accept_recovery and wants_upcoming:
                        try:
                            trial = _to_plan(
                                recovered.interpretation,
                                question,
                                session=session_state,
                                snapshot=customer_snapshot,
                                source="azure_plan",
                            )
                            covers = any(
                                (t.filters or {}).get("upcoming_payments")
                                or "due_date" in (t.fields or [])
                                or "min_payment" in (t.fields or [])
                                for t in (trial.tasks or [])
                            )
                            if not covers:
                                accept_recovery = False
                                timings["initial_proposal_recovery_rejected"] = "no_upcoming_coverage"
                        except Exception:
                            accept_recovery = False
                    if accept_recovery:
                        result = recovered
                        brain_source = "initial_proposal_recovery"
                except Exception:
                    pass

        if result.interpretation is None:
            repair_out = _run_structural_repair(
                f"repair:after_{result.status}_no_interpretation",
            )
            repair_plan = repair_out.get("_plan")
            if repair_plan is not None and getattr(repair_plan, "tasks", None):
                # Evitar respuesta vacía genérica si el intérprete no entendió nada útil
                statuses = ((repair_out.get("decision_trace") or [{}])[0].get("output") or {}).get(
                    "task_statuses"
                ) or {}
                useful = any(
                    t.domain != "none"
                    and (
                        (statuses.get(t.id) or statuses.get(f"{t.id}.{'.'.join(t.fields or [])}") or t.status)
                        in ("available", "absent", "needs_clarification", "refused", "ready")
                    )
                    for t in (repair_plan.tasks or [])
                )
                if useful:
                    return repair_out
            if result.status == "NON_OPERATIONAL":
                text = result.non_operational_message or (
                    "Puedo ayudarte con consultas de lectura sobre tus productos "
                    "o información del banco."
                )
                return {
                    "provider": "AZURE_OPENAI",
                    "framework": "MICROSOFT_AGENT_FRAMEWORK",
                    "model": azure_model,
                    "prompt_version": prompt_version,
                    "conversation_id": conv_id,
                    "turn_number": turn_number,
                    "conversation_history": history,
                    "status": "NON_OPERATIONAL",
                    "mode": "SINGLE",
                    "intent_id": "NON_OPERATIONAL",
                    "actions": [],
                    "clarifications": [],
                    "unsupported_segments": [],
                    "client_response": text,
                    "suggested_questions": [],
                    "rag_status": "NOT_REQUIRED",
                    "inference_count": inference_count,
                    "decision_trace": [{
                        "step": "azure_plan",
                        "output": {
                            "semantic_mode": "azure_plan",
                            "result_status": "NON_OPERATIONAL",
                            "calls": call_meta,
                            "deployment": deployment,
                            "failed_model_attempts": failed_attempts,
                            "interpretation_present": False,
                        },
                    }],
                    "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                    "stage_timings_ms": timings,
                    "correlation_id": request_id,
                    "_pex": None,
                    "_plan": None,
                    "_apply_state": False,
                }
            return _error_payload(
                exc=AttributeError("interpretation_missing"),
                stage=f"adapter_no_interpretation_{result.status}",
                azure_model=azure_model,
                prompt_version=prompt_version,
                conv_id=conv_id,
                turn_number=turn_number,
                history=history,
                request_start=request_start,
                inference_count=inference_count,
                call_meta=call_meta,
                request_id=request_id,
            )

        tasks_before = len(getattr(result.interpretation, "actions", None) or [])
        t_adapt = time.perf_counter()
        try:
            plan = interpretation_to_turn_plan(
                result.interpretation,
                question,
                session=session_state,
                snapshot=customer_snapshot,
                source="azure_plan",
            )
        except InvalidTurnPlanError as exc:
            if _eligible_for_structural_repair(safe_question):
                return _run_structural_repair("repair:after_invalid_turn_plan")
            return {
                "provider": "AZURE_OPENAI",
                "framework": "MICROSOFT_AGENT_FRAMEWORK",
                "model": azure_model,
                "prompt_version": prompt_version,
                "conversation_id": conv_id,
                "turn_number": turn_number,
                "conversation_history": history,
                "status": "INVALID_MODEL_OUTPUT",
                "mode": "SINGLE",
                "intent_id": "INVALID_TURN_PLAN",
                "actions": [],
                "clarifications": [],
                "unsupported_segments": list(exc.errors),
                "client_response": (
                    "La interpretación no produjo un plan ejecutable válido. "
                    "Reformula por favor."
                ),
                "suggested_questions": [],
                "rag_status": "NOT_REQUIRED",
                "inference_count": inference_count,
                "decision_trace": [{
                    "step": "azure_plan_invalid",
                    "output": {
                        "errors": list(exc.errors),
                        "calls": call_meta,
                        "tasks_before": tasks_before,
                        "error_stage": "adapter_validate",
                        "failed_model_attempts": failed_attempts,
                    },
                }],
                "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                "stage_timings_ms": timings,
                "correlation_id": request_id,
                "_pex": None,
                "_plan": None,
                "_apply_state": False,
            }
        timings["adapter_ms"] = round((time.perf_counter() - t_adapt) * 1000, 1)

        t_exec = time.perf_counter()
        pex = execute_turn_plan(plan, customer_snapshot, question, session=session_state)
        timings["execute_ms"] = round((time.perf_counter() - t_exec) * 1000, 1)
        route_source = "azure_plan"
        # Conservar etiqueta si recuperamos el proposal inicial tras verifier vacío
        if brain_source != "initial_proposal_recovery":
            brain_source = "resolve_full"

    history.append({
        "turn": turn_number,
        "question": safe_question,
        "status": pex.status,
        "intent": pex.intent_id,
        "plan_tasks": len(plan.tasks),
        "semantic_mode": "azure_plan",
    })

    mode = "CLARIFICATION" if pex.status == "CLARIFICATION_REQUIRED" else "SINGLE"
    evidence_sources = []
    for ev in getattr(pex, "evidences", None) or []:
        src = getattr(ev, "source", None)
        if src and src not in evidence_sources:
            evidence_sources.append(src)
    return {
        "provider": _provider_for_brain(brain_source, inference_count=inference_count),
        "framework": "MICROSOFT_AGENT_FRAMEWORK",
        "model": azure_model,
        "prompt_version": prompt_version,
        **_version_fields(),
        "conversation_id": conv_id,
        "turn_number": turn_number,
        "conversation_history": history,
        "status": pex.status,
        "mode": mode,
        "intent_id": pex.intent_id,
        "actions": pex.actions or [],
        "clarifications": [{
            "target_action_sequence": 1,
            "missing_requirements": ["account_ref"],
            "suggested_question": pex.text,
            "already_known": [],
        }] if pex.status == "CLARIFICATION_REQUIRED" else [],
        "unsupported_segments": [],
        "client_response": pex.text,
        "suggested_questions": getattr(pex, "suggestions", None) or [],
        "app_channel_options": getattr(pex, "options", None),
        "rag_status": "FAQ" if pex.route == "knowledge" else "NOT_REQUIRED",
        "inference_count": inference_count,
        "evidence_sources": evidence_sources,
        "customer_context": {
            "customer_id": getattr(customer_snapshot, "customer_id", None) or customer_id,
            "display_name": getattr(customer_snapshot, "display_name", None),
        },
        "decision_trace": [{
            "step": "azure_plan",
            "output": {
                "semantic_mode": "azure_plan",
                "route_source": route_source,
                "brain_source": brain_source,
                "deployment": deployment,
                "task_count": len(plan.tasks),
                "task_statuses": (pex.trace or {}).get("task_statuses"),
                "evidence_sources": evidence_sources,
                "field_accreditation": (pex.trace or {}).get("field_accreditation"),
                "payment_window": (pex.trace or {}).get("payment_window"),
                "transition": plan.transition,
                "calls": call_meta,
                "inference_count": inference_count,
                "failed_model_attempts": failed_attempts,
                "stage_timings_ms": timings,
                **_version_fields(),
            },
            "duration_ms": round((time.perf_counter() - request_start) * 1000),
        }],
        "total_request_ms": round((time.perf_counter() - request_start) * 1000),
        "stage_timings_ms": timings,
        "correlation_id": request_id,
        "_pex": pex,
        "_plan": plan,
        "_apply_state": True,
    }
