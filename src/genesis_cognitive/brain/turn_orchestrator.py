"""Orquestación del path Azure-brain → grounded facts / KB."""

from __future__ import annotations

from typing import Any

from genesis_cognitive.brain.azure_intent_brain import (
    classify_intent_async,
    heuristic_intent,
    is_azure_brain_enabled,
)
from genesis_cognitive.brain.continuity import (
    apply_continuity_to_packet,
    pending_is_product_selection,
    resolve_product_reference,
)
from genesis_cognitive.brain.grounded_executor import execute_grounded
from genesis_cognitive.brain.intent_types import GroundedResult, IntentPacket
from genesis_cognitive.brain.natural_draft import draft_natural_async
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


def _packet_from_continuity(
    question: str,
    snapshot: CustomerContextSnapshot,
    session: Any | None,
) -> IntentPacket | None:
    """Resuelve selección pendiente / deíxis sin depender del modelo."""
    resolution = resolve_product_reference(question, snapshot, session)
    if resolution is None:
        return None

    if not pending_is_product_selection(session):
        if resolution.reason not in (
            "deictic_focus",
            "currency_unique",
            "ordinal",
            "other_unique",
        ):
            return None
        if not resolution.product_id:
            return None
    else:
        if resolution.missing:
            return IntentPacket(
                "personal",
                "account",
                resolution.field,
                confidence=0.95,
                needs_clarification=False,
                source="heuristic",
                rationale=f"continuity:{resolution.reason}",
            )
        if resolution.ambiguous or not resolution.product_id:
            return IntentPacket(
                "personal",
                "account",
                resolution.field,
                confidence=0.9,
                needs_clarification=True,
                clarification_question="¿A cuál producto te refieres?",
                source="heuristic",
                rationale=f"continuity:{resolution.reason}",
            )

    return IntentPacket(
        "personal",
        resolution.product_kind,
        resolution.field,
        confidence=0.96,
        product_hint_digits=resolution.product_id,
        rewritten_question=resolution.original_question or question,
        source="heuristic",
        rationale=f"continuity:{resolution.reason}",
    )


async def _maybe_draft(
    question: str,
    snapshot: CustomerContextSnapshot,
    result: GroundedResult,
) -> GroundedResult:
    if result.status == "VALID_CONTRACT" and (result.text or "").strip():
        drafted = await draft_natural_async(
            question, result.text, display_name=snapshot.display_name,
        )
        if drafted and drafted != result.text:
            result.trace["draft"] = "azure"
            result.trace["facts_text"] = result.text[:500]
            result.text = drafted
        else:
            result.trace["draft"] = "passthrough"
    return result


async def run_azure_brain_turn(
    question: str,
    snapshot: CustomerContextSnapshot,
    session: Any | None = None,
) -> GroundedResult | None:
    """Si GENESIS_AZURE_BRAIN está ON, clasifica y ejecuta. None = no aplica / fallthrough."""
    if not is_azure_brain_enabled() or not (question or "").strip():
        return None

    # El fastpath tiene la desambiguación multi-producto exacta para fechas
    # (préstamo vs tarjetas) y conserva el campo tras seleccionar una card.
    from genesis_cognitive.router.field_guardrails import (
        is_bank_catalog_question,
        is_card_field_question,
        is_portfolio_list_question,
        is_personal_payment_date_question,
    )
    from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question
    from genesis_cognitive.router.reclamacion_guardrail import is_reclamacion_question

    q_lower = question.lower()
    asks_all_loans = any(
        phrase in q_lower
        for phrase in (
            "mis prestamos",
            "mis préstamos",
            "todos mis prestamos",
            "todos mis préstamos",
        )
    )
    preclassified = heuristic_intent(question, session)
    force_brain = preclassified.rationale in {
        "critical:security",
        "critical:human_help",
        "critical:frustration",
        "critical:unsupported_calculation",
        "critical:generic_debt",
        "critical:term_deposit_field",
        "critical:generic_product_field",
    }

    # Continuidad pendiente / deíxis: priorizar sobre bypass de catálogo
    continuity_packet = _packet_from_continuity(question, snapshot, session)
    if continuity_packet is not None:
        if continuity_packet.rationale in {
            "continuity:currency_missing",
            "continuity:deictic_not_owned",
            "continuity:deictic_currency_conflict",
            "continuity:ordinal_out_of_range",
        }:
            g = f"{snapshot.display_name}, " if snapshot.display_name else ""
            return GroundedResult(
                "VALID_CONTRACT",
                f"{g}no encuentro un producto activo con esa referencia en tu portafolio.",
                "ACCOUNT_BALANCE_READ",
                route="personal",
                trace={"continuity": continuity_packet.rationale},
            )
        if continuity_packet.needs_clarification:
            return GroundedResult(
                "CLARIFICATION_REQUIRED",
                continuity_packet.clarification_question
                or "¿A cuál producto te refieres?",
                "ACCOUNT_BALANCE_READ",
                actions=[{
                    "sequence": 1,
                    "intent_id": "ACCOUNT_BALANCE_READ",
                    "capability_candidate": "PRODUCT_FIELD",
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {"account_ref": None},
                    "missing_requirements": ["account_ref"],
                    "depends_on": [],
                    "confidence": 1.0,
                }],
                route="personal",
                trace={"continuity": continuity_packet.rationale},
            )
        result = execute_grounded(
            continuity_packet, snapshot, question, session=session,
        )
        if result.intent_id != "FALLTHROUGH" and not result.trace.get("fallthrough"):
            if result.route != "knowledge":
                return await _maybe_draft(question, snapshot, result)

    if (
        not force_brain
        and continuity_packet is None
        and (
            is_personal_payment_date_question(question)
            or is_bank_catalog_question(question)
            or is_portfolio_list_question(question)
            or is_card_field_question(question)
            or is_reclamacion_question(question)
            or (is_loan_field_question(question) and not asks_all_loans)
        )
    ):
        return None

    packet = (
        preclassified
        if force_brain
        else await classify_intent_async(question, snapshot=snapshot, session=session)
    )
    packet = apply_continuity_to_packet(question, snapshot, session, packet)
    if (
        packet.family == "personal"
        and packet.product == "loan"
        and packet.scope != "all"
        and not packet.product_hint_digits
    ):
        from genesis_cognitive.router.product_focus import loan_ref_from_session

        focused_loan_ref = loan_ref_from_session(session)
        if focused_loan_ref:
            packet.product_hint_digits = focused_loan_ref
            packet.rationale = (
                f"{packet.rationale or packet.source}:focused_loan"
            )
    if (
        packet.family == "personal"
        and packet.product == "account"
        and packet.scope != "all"
        and not packet.product_hint_digits
    ):
        from genesis_cognitive.router.product_focus import account_ref_from_session
        from genesis_cognitive.brain.continuity import _currency_from_text

        focused_account = account_ref_from_session(session)
        if focused_account:
            ccy = _currency_from_text(question)
            prod = next(
                (p for p in snapshot.products if p.product_id == focused_account),
                None,
            )
            if prod is not None and (
                ccy is None or str(prod.currency).upper() == ccy
            ):
                packet.product_hint_digits = focused_account
                packet.rationale = (
                    f"{packet.rationale or packet.source}:focused_account"
                )
    result = execute_grounded(packet, snapshot, question, session=session)

    # Fallthrough → dejar pipeline histórico
    if result.intent_id == "FALLTHROUGH" or result.trace.get("fallthrough"):
        return None

    # Knowledge: resolver FAQ/Foundry aquí
    if result.route == "knowledge":
        kb_q = result.knowledge_question or question
        text = None
        from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail

        faq = apply_faq_guardrail(snapshot, kb_q, session=session)
        faq_score = None
        try:
            if faq and faq[1]:
                faq_score = float((faq[1][0] or {}).get("confidence") or 0)
        except Exception:
            faq_score = None
        prefer_foundry = False
        try:
            from genesis_cognitive.router.knowledge_followup import prefer_foundry_for_faq_hit

            prefer_foundry = prefer_foundry_for_faq_hit(
                kb_q, str((faq[2] if faq else "") or ""), score=faq_score,
            )
        except Exception:
            prefer_foundry = False

        if faq and faq[2] and not prefer_foundry:
            text = faq[2]
            result.actions = faq[1] or result.actions
            result.trace["kb"] = "faq"
        else:
            from genesis_cognitive.rag.foundry_kb_agent import (
                ask_foundry_kb_agent,
                is_foundry_kb_enabled,
            )
            if is_foundry_kb_enabled():
                fy = ask_foundry_kb_agent(kb_q, display_name=snapshot.display_name)
                if fy and fy.get("answer"):
                    text = fy["answer"]
                    result.trace["kb"] = "foundry"
            if not text:
                text = (
                    f"{snapshot.display_name}, " if snapshot.display_name else ""
                ) + "no encontré información suficiente en la base de conocimiento. ¿Puedes reformular?"
                result.trace["kb"] = "miss"
        result.text = text
        result.status = "VALID_CONTRACT"

    if not (result.text or "").strip() and result.status == "VALID_CONTRACT":
        return None

    return await _maybe_draft(question, snapshot, result)
