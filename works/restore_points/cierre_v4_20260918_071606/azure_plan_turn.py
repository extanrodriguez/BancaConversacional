"""Ejecución de un turno en modo GENESIS_SEMANTIC_MODE=azure_plan."""

from __future__ import annotations

import time
import uuid
from typing import Any

from genesis_cognitive.brain.azure_plan_adapter import (
    interpretation_to_turn_plan,
    is_unequivocal_structured_shortcut,
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
        filtered = tuple(
            ProjectedProduct(
                product_ref=p.product_id,
                product_type=p.product_type,
                label=p.alias,
                alias=p.alias,
                currency=p.currency,
                operational_state=p.status,
            )
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

    mem = project_conversation_memory(session_state)
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
        tid = str(pt.get("task_id") or pt.get("id") or "")
        if tid:
            by_id[tid] = dict(pt)
    for tid in clear_ids or set():
        by_id.pop(tid, None)
    for pt in incoming or []:
        tid = str(pt.get("task_id") or pt.get("id") or "")
        if tid:
            by_id[tid] = dict(pt)
    return list(by_id.values())


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
    """
    shortcut, shortcut_reason = is_unequivocal_structured_shortcut(question, session_state)
    inference_count = 0
    call_meta: list[dict] = []
    deployment = azure_deployment_name(default=azure_model)

    if shortcut:
        plan = interpret_turn_plan(question, session_state, snapshot=customer_snapshot)
        plan.source = f"shortcut:{shortcut_reason}"
        pex = execute_turn_plan(plan, customer_snapshot, question, session=session_state)
        route_source = plan.source
        brain_source = "structured_shortcut"
    else:
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
        try:
            result = await resolver.resolve_full(envelope)
        except Exception as exc:  # noqa: BLE001
            # Degradación explícita — no sustituir por heurística etiquetada azure
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
                "inference_count": 0,
                "decision_trace": [{
                    "step": "azure_plan_error",
                    "output": {
                        "error_class": type(exc).__name__,
                        "semantic_mode": "azure_plan",
                        "degraded": True,
                        "not_heuristic_fallback": True,
                    },
                }],
                "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                "correlation_id": str(uuid.uuid4()),
                "_pex": None,
                "_plan": None,
                "_apply_state": False,
            }

        inference_count = len(getattr(result, "call_records", None) or [])
        for rec in getattr(result, "call_records", None) or []:
            call_meta.append({
                "name": getattr(rec, "name", None),
                "duration_ms": getattr(rec, "duration_ms", None),
                "deployment": getattr(rec, "deployment", deployment),
            })

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
                    },
                }],
                "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                "correlation_id": str(uuid.uuid4()),
                "_pex": None,
                "_plan": None,
                "_apply_state": False,
            }

        try:
            plan = interpretation_to_turn_plan(
                result.interpretation, question, session=session_state, source="azure_plan",
            )
        except InvalidTurnPlanError as exc:
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
                    "output": {"errors": list(exc.errors), "calls": call_meta},
                }],
                "total_request_ms": round((time.perf_counter() - request_start) * 1000),
                "correlation_id": str(uuid.uuid4()),
                "_pex": None,
                "_plan": None,
                "_apply_state": False,
            }

        pex = execute_turn_plan(plan, customer_snapshot, question, session=session_state)
        route_source = "azure_plan"
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
    return {
        "provider": "AZURE_OPENAI",
        "framework": "MICROSOFT_AGENT_FRAMEWORK",
        "model": azure_model,
        "prompt_version": prompt_version,
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
        "suggested_questions": pex.suggestions or [],
        "app_channel_options": pex.options,
        "rag_status": "FAQ" if pex.route == "knowledge" else "NOT_REQUIRED",
        "inference_count": inference_count,
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
                "transition": plan.transition,
                "calls": call_meta,
                "inference_count": inference_count,
            },
        }],
        "total_request_ms": round((time.perf_counter() - request_start) * 1000),
        "correlation_id": str(uuid.uuid4()),
        "_pex": pex,
        "_plan": plan,
        "_apply_state": True,
    }
