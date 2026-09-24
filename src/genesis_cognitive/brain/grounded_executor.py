"""Ejecutor grounded: responde hechos SOLO desde snapshot/KB route.

Azure clasifica; este módulo es la boca de hechos personales.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from genesis_cognitive.brain.core_facts_catalog import fact_by_id
from genesis_cognitive.brain.intent_types import GroundedResult, IntentPacket
from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
from genesis_cognitive.context.product_display import (
    display_label_in_context,
    filter_active_by_type,
)
from genesis_cognitive.context.response_formatting import format_money


_MSG_NO_INSTALLMENT = (
    "no tengo el monto de la cuota contractual de tu préstamo{mask} "
    "en el contexto disponible en este momento.{offer} "
    "También puedes consultarlo en BSC en Línea o en el Centro de Contacto (809.726.1000)."
)

_MSG_DEBIT = (
    "en tu portafolio no figuran **tarjetas de débito** como producto consultable "
    "(suelen estar ligadas a tus cuentas). "
    "Puedo darte el saldo de tus cuentas o, si te referías a **tarjetas de crédito**, dímelo."
)


def _greeting(snapshot: CustomerContextSnapshot) -> str:
    return f"{snapshot.display_name}, " if snapshot.display_name else ""


def _action(intent_id: str, ref: str | None = None, missing: list[str] | None = None) -> dict:
    return {
        "sequence": 1,
        "intent_id": intent_id,
        "capability_candidate": "PRODUCT_FIELD",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {"account_ref": ref},
        "missing_requirements": missing or [],
        "depends_on": [],
        "confidence": 1.0,
    }


def _pick_products(
    snapshot: CustomerContextSnapshot,
    packet: IntentPacket,
    types: tuple[str, ...],
) -> list[Any]:
    pool = filter_active_by_type(snapshot, types)
    if packet.product_hint_digits:
        d = str(packet.product_hint_digits)
        # Match exacto por product_id (continuidad) además de dígitos/máscara
        exact = [p for p in pool if p.product_id == d]
        if exact:
            return exact
        hits = []
        for p in pool:
            pid = "".join(ch for ch in p.product_id if ch.isdigit())
            mask = "".join(ch for ch in str(p.card_mask or "") if ch.isdigit())
            lf = str(p.last_four or "")
            digits_hint = "".join(ch for ch in d if ch.isdigit()) or d
            if (
                pid.endswith(digits_hint)
                or digits_hint in pid[-6:]
                or mask.endswith(digits_hint[-4:])
                or lf == digits_hint[-4:]
            ):
                hits.append(p)
        if hits:
            return hits
    return list(pool)


def _loan_for(snapshot: CustomerContextSnapshot, product_id: str) -> Any | None:
    return next((ln for ln in snapshot.loans if ln.product_id == product_id), None)


def execute_grounded(
    packet: IntentPacket,
    snapshot: CustomerContextSnapshot,
    question: str,
    session: Any | None = None,
) -> GroundedResult:
    """Ejecuta la intención contra hechos del snapshot (o enruta a KB)."""
    # Continuidad: moneda/deíxis/pending sobre el packet antes de ejecutar
    if session is not None and packet.family in ("personal", "clarify"):
        from genesis_cognitive.brain.continuity import apply_continuity_to_packet

        packet = apply_continuity_to_packet(question, snapshot, session, packet)

    g = _greeting(snapshot)
    trace = {
        "packet": packet.to_dict(),
        "brain": "grounded_executor",
        "question": question,
        "session": session,
    }

    if packet.family == "greeting":
        name = snapshot.display_name or "Cliente"
        return GroundedResult(
            "NON_OPERATIONAL",
            f"¡Hola, {name}! Aquí estoy. ¿En qué puedo ayudarte?",
            "GREETING",
            route="none",
            trace=trace,
        )

    if packet.field == "security":
        return GroundedResult(
            "UNSUPPORTED",
            f"{g}por seguridad, no compartas PIN, contraseña, CVV ni códigos de "
            "verificación. Tampoco puedo omitir controles ni mostrar información "
            "de productos sin autorización. Puedo ayudarte con una consulta permitida.",
            "SECURITY_GUARDRAIL",
            route="none",
            trace=trace,
        )

    if packet.field == "human_help":
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}claro. Puedes recibir asistencia de una persona por estos canales:\n\n"
            "• Centro de Contacto: [809.726.1000](tel:+18097261000)\n"
            "• Correo: [serviciobancanet@bsc.com.do]"
            "(mailto:serviciobancanet@bsc.com.do)\n"
            "• Web: [bsc.com.do](https://bsc.com.do/)\n"
            "• Centro de Negocios o BSC en Línea",
            "HUMAN_ASSISTANCE",
            route="none",
            trace=trace,
        )

    if packet.field == "frustration":
        asks_claim = "reclam" in question.lower()
        text = (
            f"{g}entiendo tu frustración. Voy a ayudarte con tu reclamación. "
            "¿Tienes el número del caso?"
            if asks_claim
            else f"{g}entiendo que esto ha sido frustrante. Estoy aquí para ayudarte. "
            "Cuéntame qué operación o producto presentó el problema."
        )
        return GroundedResult(
            "CLARIFICATION_REQUIRED",
            text,
            "CUSTOMER_FRUSTRATION",
            actions=[_action("CUSTOMER_FRUSTRATION", missing=["query_scope"])],
            route="none",
            trace=trace,
        )

    if packet.field == "unsupported_calculation":
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no puedo calcular ni estimar ese monto con precisión. El valor exacto "
            "debe obtenerse de los sistemas del Banco. Sí puedo mostrarte los datos "
            "contractuales disponibles de tus productos.",
            "UNSUPPORTED_CALCULATION",
            route="none",
            trace=trace,
        )

    if packet.family == "chitchat":
        return _chitchat(snapshot, packet, g, trace)

    if packet.family in ("knowledge", "process"):
        q = packet.rewritten_question or question
        return GroundedResult(
            "VALID_CONTRACT",
            "",
            "BUSINESS_KNOWLEDGE_QUERY",
            route="knowledge",
            knowledge_question=q,
            actions=[_action("BUSINESS_KNOWLEDGE_QUERY")],
            trace=trace,
        )

    if packet.family == "ood":
        return GroundedResult(
            "UNSUPPORTED",
            f"{g}esa consulta está fuera del alcance de la banca conversacional. "
            "Puedo ayudarte con saldos, préstamos, tarjetas o información del banco.",
            "UNSUPPORTED",
            route="none",
            trace=trace,
        )

    if packet.product == "debit_card":
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}{_MSG_DEBIT}",
            "CREDIT_CARD_DETAIL_READ",
            actions=[_action("CREDIT_CARD_DETAIL_READ")],
            route="personal",
            trace=trace,
        )

    if packet.product == "mixed" and packet.field == "payoff":
        return _generic_debt(snapshot, g, trace, packet)

    if packet.product == "mixed" and packet.field in ("rate", "maturity"):
        return _generic_product_field(snapshot, g, trace, packet)

    if packet.product == "mixed" and packet.field in ("balance", "available"):
        return _generic_balance(snapshot, g, trace, packet)

    if packet.field == "upcoming_payments" or (
        packet.product == "mixed" and packet.field in ("due_date", "upcoming_payments", "other")
    ):
        return _upcoming(snapshot, g, trace)

    if packet.product == "credit_card" and (
        packet.field == "multi_summary" or packet.scope == "all"
    ):
        return _card_multi(snapshot, g, trace, packet)

    if packet.product == "loan":
        return _loan_field(snapshot, g, trace, packet)

    if packet.product == "credit_card":
        return _card_field(snapshot, g, trace, packet)

    if packet.product == "account":
        return _account_field(snapshot, g, trace, packet, question=question)

    if packet.product == "term_deposit":
        return _dap_field(snapshot, g, trace, packet)

    if packet.needs_clarification or packet.family == "clarify":
        q = packet.clarification_question or (
            f"{g}¿Quieres consultar un dato de tus productos o información general del banco?"
        )
        return GroundedResult(
            "CLARIFICATION_REQUIRED",
            q if q.startswith(g) or not g else f"{g}{q}",
            "CLARIFICATION",
            actions=[_action("CLARIFICATION", missing=["query_scope"])],
            route="none",
            trace=trace,
        )

    # Dejar que el fastpath histórico intente
    return GroundedResult(
        "VALID_CONTRACT",
        "",
        "FALLTHROUGH",
        route="none",
        trace={**trace, "fallthrough": True},
    )


def _generic_balance(
    snapshot: CustomerContextSnapshot,
    g: str,
    trace: dict,
    packet: IntentPacket,
) -> GroundedResult:
    """Resuelve frases como “cuánto tengo” usando los tipos realmente elegibles."""
    accounts = filter_active_by_type(snapshot, ("SAVINGS", "CHECKING", "PAYROLL"))
    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    loans = filter_active_by_type(snapshot, ("LOAN",))
    deposits = filter_active_by_type(snapshot, ("TERM_DEPOSIT",))
    q = str(trace.get("question") or "").lower()
    wants_available = packet.field == "available" or (
        "disponible" in q and "saldo actual" not in q
    )
    wants_current = packet.field == "balance" or any(
        s in q for s in ("saldo actual", "balance actual", "saldo contable")
    )
    # Liquidez / saldo de cuenta: no mezclar con préstamos
    if wants_available or wants_current or packet.product == "account":
        groups = [("account", accounts)]
        if wants_available and cards:
            groups.append(("credit_card", cards))
    else:
        groups = [
            ("account", accounts),
            ("credit_card", cards),
            ("loan", loans),
            ("term_deposit", deposits),
        ]
    available = [(kind, products) for kind, products in groups if products]
    if len(available) == 1:
        kind, _ = available[0]
        packet.product = kind
        if kind == "loan":
            packet.field = "principal"
        elif kind == "credit_card":
            packet.field = "available" if wants_available else "balance"
        elif kind == "account":
            packet.field = "balance" if wants_current else "available"
        elif kind == "term_deposit":
            packet.field = "capital"
        if kind == "account":
            return _account_field(
                snapshot,
                g,
                trace,
                packet,
                question=str(trace.get("question") or ""),
            )
        if kind == "credit_card":
            return _card_field(snapshot, g, trace, packet)
        if kind == "loan":
            return _loan_field(snapshot, g, trace, packet)
        return _dap_field(snapshot, g, trace, packet)

    if not available:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no encontré cuentas activas para consultar saldo o disponible.",
            "PORTFOLIO_QUERY",
            actions=[_action("PORTFOLIO_QUERY")],
            route="personal",
            trace=trace,
        )

    from genesis_cognitive.context.app_channel import build_product_options

    pool = [product for _, products in available for product in products]
    label = "el saldo actual" if wants_current else "el disponible"
    return GroundedResult(
        "CLARIFICATION_REQUIRED",
        f"{g}¿De cuál cuenta deseas consultar {label}?",
        "ACCOUNT_BALANCE_READ",
        actions=[_action("ACCOUNT_BALANCE_READ", missing=["account_ref"])],
        options=build_product_options(
            pool, field=packet.field, snapshot=snapshot,
        ) or None,
        route="personal",
        trace={**trace, "generic_balance": True, "liquidity_only": True},
    )


def _generic_product_field(
    snapshot: CustomerContextSnapshot,
    g: str,
    trace: dict,
    packet: IntentPacket,
) -> GroundedResult:
    loans = filter_active_by_type(snapshot, ("LOAN",))
    deposits = filter_active_by_type(snapshot, ("TERM_DEPOSIT",))
    available = [
        (kind, products)
        for kind, products in (("loan", loans), ("term_deposit", deposits))
        if products
    ]
    if len(available) == 1:
        kind, _ = available[0]
        packet.product = kind
        return (
            _loan_field(snapshot, g, trace, packet)
            if kind == "loan"
            else _dap_field(snapshot, g, trace, packet)
        )
    if not available:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no encontré préstamos ni depósitos a plazo activos.",
            "PORTFOLIO_QUERY",
            actions=[_action("PORTFOLIO_QUERY")],
            route="personal",
            trace=trace,
        )

    from genesis_cognitive.context.app_channel import build_product_options

    pool = [product for _, products in available for product in products]
    field_label = "la tasa" if packet.field == "rate" else "el vencimiento"
    return GroundedResult(
        "CLARIFICATION_REQUIRED",
        f"{g}¿De cuál préstamo o depósito deseas consultar {field_label}?",
        "PORTFOLIO_QUERY",
        actions=[_action("PORTFOLIO_QUERY", missing=["account_ref"])],
        options=build_product_options(
            pool, field=packet.field, snapshot=snapshot,
        ) or None,
        route="personal",
        trace={**trace, "generic_product_field": packet.field},
    )


def _generic_debt(
    snapshot: CustomerContextSnapshot,
    g: str,
    trace: dict,
    packet: IntentPacket,
) -> GroundedResult:
    """Resuelve “cuánto debo” entre tarjetas y préstamos sin asumir."""
    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    loans = filter_active_by_type(snapshot, ("LOAN",))
    available = [
        (kind, products)
        for kind, products in (("credit_card", cards), ("loan", loans))
        if products
    ]
    if len(available) == 1:
        kind, _ = available[0]
        packet.product = kind
        packet.field = "balance" if kind == "credit_card" else "payoff"
        return (
            _card_field(snapshot, g, trace, packet)
            if kind == "credit_card"
            else _loan_field(snapshot, g, trace, packet)
        )
    if not available:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no encontré tarjetas de crédito ni préstamos activos.",
            "PORTFOLIO_QUERY",
            actions=[_action("PORTFOLIO_QUERY")],
            route="personal",
            trace=trace,
        )

    from genesis_cognitive.context.app_channel import build_product_options

    pool = [product for _, products in available for product in products]
    return GroundedResult(
        "CLARIFICATION_REQUIRED",
        f"{g}¿De cuál tarjeta o préstamo deseas consultar lo adeudado?",
        "PORTFOLIO_QUERY",
        actions=[_action("PORTFOLIO_QUERY", missing=["account_ref"])],
        options=build_product_options(
            pool, field="payoff", snapshot=snapshot,
        ) or None,
        route="personal",
        trace={**trace, "generic_debt": True},
    )


def _chitchat(
    snapshot: CustomerContextSnapshot,
    packet: IntentPacket,
    g: str,
    trace: dict,
) -> GroundedResult:
    """Respuestas de IA bancaria para presencia, correcciones y cortesía."""
    name = snapshot.display_name or "Cliente"
    first = (name.split() or ["Cliente"])[0]
    field = (packet.field or "smalltalk").lower()

    if field == "presence":
        text = (
            f"Sí, {first}, aquí estoy. ¿En qué te puedo ayudar? "
            "Puedo consultar tus productos o responderte sobre el banco."
        )
        intent = "CHITCHAT_PRESENCE"
    elif field == "correction":
        text = (
            f"Tienes razón, {first}: me desvié del tema. "
            "Dime qué necesitas y lo vemos — saldo, préstamo, tarjeta o info del banco."
        )
        intent = "CHITCHAT_CORRECTION"
    elif field == "thanks":
        text = f"Con gusto, {first}. Si necesitas algo más de tus productos o del banco, aquí estoy."
        intent = "CHITCHAT_THANKS"
    elif field == "ack":
        text = f"Perfecto, {first}. Cuando quieras, dime en qué te ayudo."
        intent = "CHITCHAT_ACK"
    else:
        text = (
            f"Claro, {first}. Estoy aquí para ayudarte con tu banca: "
            "cuentas, tarjetas, préstamos o información del banco. ¿Qué necesitas?"
        )
        intent = "CHITCHAT"

    return GroundedResult(
        "NON_OPERATIONAL",
        text,
        intent,
        route="none",
        trace={**trace, "social": field},
    )


def _upcoming(snapshot: CustomerContextSnapshot, g: str, trace: dict) -> GroundedResult:
    from genesis_cognitive.context.upcoming_payment_window import (
        card_due_from_cutoff,
        classify_due_date,
        parse_payment_date,
        resolve_payment_window,
        window_audit_dict,
    )

    loans = filter_active_by_type(snapshot, ("LOAN",))
    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    window = resolve_payment_window()
    upcoming_lines: list[str] = []
    other_dated: list[str] = []
    classifications: list[dict] = []

    for lp in loans:
        loan = _loan_for(snapshot, lp.product_id)
        due = parse_payment_date(getattr(loan, "next_due_date", None) if loan else None)
        label = display_label_in_context(lp, list(loans) + list(cards))
        bucket = classify_due_date(due, window)
        classifications.append({
            "product_id": lp.product_id, "kind": "loan",
            "due_date": due.isoformat() if due else None, "class": bucket,
        })
        if bucket == "upcoming":
            upcoming_lines.append(f"• **{label}**: pago próximo el **{due.isoformat()}**")
        elif due is not None:
            other_dated.append(
                f"• **{label}**: tiene fecha de pago **{due.isoformat()}** "
                f"(no es pago próximo en esta ventana)"
            )

    for card in cards:
        label = display_label_in_context(card, list(loans) + list(cards))
        due = parse_payment_date(getattr(card, "payment_due_date", None))
        cutoff = getattr(card, "cutoff_day", None)
        if due is None and cutoff is not None:
            due = card_due_from_cutoff(cutoff, window)
        bucket = classify_due_date(due, window)
        classifications.append({
            "product_id": getattr(card, "product_id", None), "kind": "card",
            "due_date": due.isoformat() if due else None, "class": bucket,
        })
        if bucket == "upcoming":
            upcoming_lines.append(
                f"• **{label}**: pago próximo / fecha límite **{due.isoformat()}**"
            )
        elif due is not None:
            other_dated.append(
                f"• **{label}**: tiene fecha de pago **{due.isoformat()}** "
                f"(no es pago próximo en esta ventana)"
            )

    parts = [f"{g}{window.describe_es()}."]
    if upcoming_lines:
        parts.append("Sí: productos con **pago próximo** dentro de la ventana:")
        parts.extend(upcoming_lines)
    else:
        parts.append(
            "No tienes productos con **pago próximo** dentro de esa ventana "
            "(tener fecha de pago no equivale a pago próximo)."
        )
    if other_dated:
        parts.append("Fechas registradas fuera de la ventana:")
        parts.extend(other_dated)
    if not upcoming_lines and not other_dated:
        parts.append("No hallé fechas de pago usables en préstamos/tarjetas activos.")

    return GroundedResult(
        "VALID_CONTRACT",
        "\n".join(parts),
        "PAYMENT_DATE_READ",
        actions=[_action("PAYMENT_DATE_READ")],
        route="personal",
        trace={
            **trace,
            **window_audit_dict(window),
            "payment_classifications": classifications,
        },
    )


def _card_multi(
    snapshot: CustomerContextSnapshot, g: str, trace: dict, packet: IntentPacket,
) -> GroundedResult:
    cards = _pick_products(snapshot, packet, ("CREDIT_CARD",))
    if not cards:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no tienes tarjetas de crédito activas en tu portafolio.",
            "CREDIT_CARD_DETAIL_READ",
            actions=[_action("CREDIT_CARD_DETAIL_READ")],
            route="personal",
            trace=trace,
        )
    q = str(packet.rewritten_question or trace.get("question") or "").lower()
    # Inferir qué campos mostrar según el paquete / pregunta
    if packet.field == "balance":
        wants_debt, wants_avail = True, False
    elif packet.field == "available":
        wants_debt, wants_avail = False, True
    else:
        wants_debt = any(
            s in q for s in ("debo", "adeud", "saldo adeud", "cuanto debo", "cuánto debo")
        ) or packet.field in ("balance", "multi_summary", None, "")
        wants_avail = any(
            s in q for s in ("disponible", "cupo", "credito disponible", "crédito disponible", "más crédito", "mas credito")
        ) or packet.field in ("available", "multi_summary")
        if not wants_debt and not wants_avail:
            wants_debt = True
            wants_avail = "disponible" in q or "crédito" in q or "credito" in q
    lines: list[str] = []
    best_label = None
    best_val: Decimal | None = None
    best_fmt = None
    for card in cards:
        label = display_label_in_context(card, cards)
        bits: list[str] = []
        if wants_debt:
            owed = format_money(card.ledger_balance, card.currency or "DOP")
            bits.append(f"adeudas **{owed or 'N/D'}**")
        raw_av = card.available_purchases_domestic or card.available_balance
        if wants_avail:
            avail = format_money(raw_av, "DOP")
            bits.append(f"disponible **{avail or 'N/D'}**")
        lines.append(f"• **{label}**: " + "; ".join(bits) if bits else f"• **{label}**")
        if wants_avail and raw_av is not None:
            try:
                val = Decimal(str(raw_av))
            except Exception:
                continue
            if best_val is None or val > best_val:
                best_val = val
                best_label = label
                best_fmt = format_money(raw_av, "DOP")
    extra = ""
    if best_label and best_fmt and any(s in q for s in ("más", "mas", "cual de", "cuál de", "mayor")):
        extra = f"\nLa que tiene más crédito disponible es **{best_label}** ({best_fmt})."
    intro = "aquí tienes el resumen de tus tarjetas de crédito"
    if wants_debt and not wants_avail:
        intro = "aquí tienes el saldo adeudado de tus tarjetas de crédito"
    elif wants_avail and not wants_debt:
        intro = "aquí tienes el disponible de tus tarjetas de crédito"
    text = f"{g}{intro}:\n" + "\n".join(lines) + extra
    return GroundedResult(
        "VALID_CONTRACT",
        text,
        "CREDIT_CARD_DETAIL_READ",
        actions=[_action("CREDIT_CARD_DETAIL_READ")],
        route="personal",
        trace=trace,
    )


def _loan_all_field(
    snapshot: CustomerContextSnapshot,
    loans_p: list[Any],
    g: str,
    trace: dict,
    packet: IntentPacket,
) -> GroundedResult:
    """Lista el mismo campo para todos los préstamos, sin elegir uno arbitrario."""
    lines: list[str] = []
    for product in loans_p:
        loan = _loan_for(snapshot, product.product_id)
        label = display_label_in_context(product, loans_p)
        if not loan:
            value = "dato no disponible"
        elif packet.field == "rate":
            value = (
                f"tasa **{loan.annual_interest_rate}%** anual"
                if loan.annual_interest_rate and loan.annual_interest_rate > 0
                else "tasa no disponible"
            )
        elif packet.field == "due_date":
            value = (
                f"próxima fecha de pago **{loan.next_due_date}**"
                if loan.next_due_date
                else "fecha de pago no disponible"
            )
        elif packet.field == "principal":
            amount = format_money(loan.outstanding_principal, "DOP")
            value = f"capital pendiente **{amount}**" if amount else "capital no disponible"
        elif packet.field == "payoff":
            amount = format_money(
                loan.payoff_amount if loan.payoff_amount is not None else None, "DOP",
            )
            if amount:
                value = f"monto para cancelar **{amount}** (`payoff_amount`)"
            elif loan.outstanding_principal is not None:
                amount = format_money(loan.outstanding_principal, "DOP")
                value = (
                    f"capital pendiente **{amount}** (`outstanding_principal`; "
                    "no es monto oficial de cancelación — falta `payoff_amount`)"
                )
            else:
                value = "total no disponible"
        elif packet.field == "overdue":
            amount = format_money(loan.overdue_amount, "DOP")
            value = f"mora **{amount}**" if amount else "sin mora reportada"
        elif packet.field == "maturity":
            value = (
                f"vencimiento **{loan.maturity_date}**"
                if loan.maturity_date
                else "vencimiento no disponible"
            )
        elif packet.field == "installment_amount":
            if loan and loan.installment_amount and loan.installment_amount > 0:
                amount = format_money(loan.installment_amount, "DOP")
                value = f"cuota **{amount}**" if amount else "cuota no disponible"
            else:
                value = "monto de cuota contractual no disponible en el portafolio"
        else:
            value = "detalle disponible al seleccionar este préstamo"
        lines.append(f"• **{label}**: {value}")

    field_name = {
        "rate": "las tasas",
        "due_date": "las fechas de pago",
        "principal": "el capital pendiente",
        "payoff": "los totales adeudados",
        "overdue": "la mora",
        "maturity": "los vencimientos",
        "installment_amount": "las cuotas",
    }.get(packet.field, "el detalle")
    return GroundedResult(
        "VALID_CONTRACT",
        f"{g}aquí tienes {field_name} de tus préstamos:\n" + "\n".join(lines),
        "LOAN_DETAIL_READ",
        actions=[_action("LOAN_DETAIL_READ")],
        route="personal",
        trace={**trace, "scope": "all", "field": packet.field},
    )


def _loan_field(
    snapshot: CustomerContextSnapshot, g: str, trace: dict, packet: IntentPacket,
) -> GroundedResult:
    loans_p = _pick_products(snapshot, packet, ("LOAN",))
    if not loans_p:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no tienes préstamos activos en tu portafolio.",
            "LOAN_DETAIL_READ",
            actions=[_action("LOAN_DETAIL_READ")],
            route="personal",
            trace=trace,
        )
    if len(loans_p) > 1 and packet.scope in ("all", "compare") and not packet.product_hint_digits:
        return _loan_all_field(snapshot, loans_p, g, trace, packet)
    if len(loans_p) > 1 and not packet.product_hint_digits:
        from genesis_cognitive.context.app_channel import (
            build_loan_disambiguation_question,
            build_product_options,
        )
        q = f"{g}" + build_loan_disambiguation_question(loans_p)
        return GroundedResult(
            "CLARIFICATION_REQUIRED",
            q,
            "LOAN_DETAIL_READ",
            actions=[_action("LOAN_DETAIL_READ", missing=["account_ref"])],
            options=build_product_options(
                loans_p, field=packet.field, snapshot=snapshot,
            ) or None,
            route="personal",
            trace=trace,
        )
    lp = loans_p[0]
    loan = _loan_for(snapshot, lp.product_id)
    label = display_label_in_context(lp, loans_p)
    mask = f" terminado en {lp.last_four}" if lp.last_four else ""
    field = packet.field

    if field == "installment_amount":
        spec = fact_by_id("loan_installment_amount")
        # Lab / fuentes enriquecidas pueden traer cuota; Core a menudo no.
        if loan and loan.installment_amount and loan.installment_amount > 0:
            text = (
                f"{g}la próxima cuota de tu {label} es "
                f"**{format_money(loan.installment_amount, 'DOP')}**."
            )
            return GroundedResult(
                "VALID_CONTRACT",
                text,
                "LOAN_DETAIL_READ",
                account_ref=lp.product_id,
                actions=[_action("LOAN_DETAIL_READ", lp.product_id)],
                route="personal",
                trace={**trace, "fact": spec.fact_id if spec else None, "core_available": True},
            )
        # Sin cuota contractual: no inventar ni usar mora como proxy
        bits = []
        if loan and loan.next_due_date:
            bits.append(f"próxima fecha de pago **{loan.next_due_date}**")
        if loan and loan.outstanding_principal is not None:
            bits.append(
                f"capital pendiente **{format_money(loan.outstanding_principal, 'DOP')}**"
            )
        if loan and loan.annual_interest_rate and loan.annual_interest_rate > 0:
            bits.append(f"tasa **{loan.annual_interest_rate}%** anual")
        offer = (" Sí puedo indicarte: " + "; ".join(bits) + ".") if bits else ""
        text = f"{g}" + _MSG_NO_INSTALLMENT.format(mask=mask, offer=offer)
        return GroundedResult(
            "VALID_CONTRACT",
            text,
            "LOAN_DETAIL_READ",
            account_ref=lp.product_id,
            actions=[_action("LOAN_DETAIL_READ", lp.product_id)],
            route="personal",
            trace={**trace, "fact": spec.fact_id if spec else None, "core_available": False},
        )

    if not loan:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}el detalle de tu {label} no está disponible en este momento.",
            "LOAN_DETAIL_READ",
            account_ref=lp.product_id,
            actions=[_action("LOAN_DETAIL_READ", lp.product_id)],
            route="personal",
            trace=trace,
        )

    if field == "due_date":
        if loan.next_due_date:
            text = f"{g}la próxima fecha de pago de tu {label} es **{loan.next_due_date}**."
        else:
            text = f"{g}la fecha de pago de tu {label} no está disponible en este momento."
    elif field == "principal":
        val = format_money(loan.outstanding_principal, "DOP")
        text = f"{g}el capital pendiente de tu {label} es **{val}**."
    elif field == "payoff":
        from genesis_cognitive.context.response_formatting import format_money as _fm
        payoff_raw = loan.payoff_amount
        principal_raw = loan.outstanding_principal
        origin = (
            getattr(snapshot, "context_source", None)
            or (trace or {}).get("context_source")
            or "lab_or_snapshot"
        )
        fetched = (
            getattr(snapshot, "source_fetched_at", None)
            or (trace or {}).get("source_fetched_at")
        )
        # Auditoría solo en telemetría (no en texto al cliente)
        audit = {
            "field_path": None,
            "field_meaning": None,
            "field_origin": origin,
            "source_fetched_at": fetched,
            "payoff_accredited": False,
        }
        if payoff_raw is not None:
            val = _fm(payoff_raw, "DOP")
            qn = str(trace.get("question") or packet.rewritten_question or "").lower()
            if any(s in qn for s in ("debo", "adeud", "total adeud")) and not any(
                s in qn for s in ("cancel", "saldar", "liquidar")
            ):
                text = f"{g}el total adeudado de tu {label} es **{val}**."
            else:
                text = (
                    f"{g}el monto para cancelar tu {label} es **{val}**. "
                    "Corresponde al saldo de cancelación según el contrato cargado "
                    "en tu contexto autorizado."
                )
            audit.update({
                "field_path": "LoanSnapshot.payoff_amount",
                "field_meaning": "payoff/cancellation balance",
                "payoff_accredited": True,
            })
            trace = {**trace, **audit}
        elif principal_raw is not None:
            val = _fm(principal_raw, "DOP")
            text = (
                f"{g}aún no tengo el monto oficial de cancelación de tu {label} "
                f"en el contexto cargado. El capital pendiente es **{val}**, "
                "pero eso no equivale al monto de cancelación."
            )
            audit.update({
                "field_path": "LoanSnapshot.outstanding_principal",
                "field_meaning": "principal only; not official payoff",
                "payoff_limitation": "missing_payoff_amount",
            })
            trace = {**trace, **audit}
        else:
            text = (
                f"{g}el monto para cancelar tu {label} no está disponible "
                "en el contexto autorizado de esta sesión."
            )
            audit["payoff_limitation"] = "missing_both"
            trace = {**trace, **audit}
    elif field == "rate":
        text = (
            f"{g}la tasa de tu {label} es **{loan.annual_interest_rate}%** anual."
            if loan.annual_interest_rate and loan.annual_interest_rate > 0
            else f"{g}la tasa de tu {label} no está disponible."
        )
    elif field == "overdue":
        if loan.overdue_amount:
            text = f"{g}tienes **{format_money(loan.overdue_amount, 'DOP')}** en mora en tu {label}."
        else:
            text = f"{g}no registras mora en tu {label} en este momento."
    elif field == "maturity":
        text = (
            f"{g}tu {label} vence el **{loan.maturity_date}**."
            if loan.maturity_date
            else f"{g}la fecha de vencimiento de tu {label} no está disponible."
        )
    elif field == "transactions":
        text = (
            f"{g}los últimos pagos de tu {label} no están disponibles "
            "en el contexto actual. Para consultarlos contacte las líneas de atención:\n\n"
            "• Centro de Contacto: [809.726.1000](tel:+18097261000)\n"
            "• Centro de Negocios o BSC en Línea"
        )
    elif field == "detail":
        from genesis_cognitive.context.response_formatting import build_rich_loan_detail
        rich = build_rich_loan_detail(lp, loan)
        text = f"{g.rstrip()}\n{rich}".strip() if g else rich
    else:
        # ficha corta segura
        bits = []
        if loan.outstanding_principal is not None:
            bits.append(f"capital **{format_money(loan.outstanding_principal, 'DOP')}**")
        if loan.next_due_date:
            bits.append(f"próximo pago **{loan.next_due_date}**")
        text = f"{g}de tu {label}: " + "; ".join(bits) + "." if bits else f"{g}consulta de {label} lista."

    return GroundedResult(
        "VALID_CONTRACT",
        text,
        "LOAN_DETAIL_READ",
        account_ref=lp.product_id,
        actions=[_action("LOAN_DETAIL_READ", lp.product_id)],
        route="personal",
        trace=trace,
    )


def _card_field(
    snapshot: CustomerContextSnapshot, g: str, trace: dict, packet: IntentPacket,
) -> GroundedResult:
    cards = _pick_products(snapshot, packet, ("CREDIT_CARD",))
    if not cards:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no tienes tarjetas de crédito activas.",
            "CREDIT_CARD_DETAIL_READ",
            actions=[_action("CREDIT_CARD_DETAIL_READ")],
            route="personal",
            trace=trace,
        )
    if len(cards) > 1 and packet.scope != "all" and not packet.product_hint_digits:
        from genesis_cognitive.context.app_channel import (
            build_card_disambiguation_question,
            build_product_options,
        )
        return GroundedResult(
            "CLARIFICATION_REQUIRED",
            f"{g}" + build_card_disambiguation_question(cards),
            "CREDIT_CARD_DETAIL_READ",
            actions=[_action("CREDIT_CARD_DETAIL_READ", missing=["account_ref"])],
            options=build_product_options(
                cards, field=packet.field, snapshot=snapshot,
            ) or None,
            route="personal",
            trace=trace,
        )
    card = cards[0]
    label = display_label_in_context(card, cards)
    field = packet.field
    ccy = card.currency or snapshot.default_currency or "DOP"
    # Tabla de campos soportados para CREDIT_CARD — due_date no cae a balance
    if field == "available":
        raw = (
            card.available_purchases_domestic
            if card.available_purchases_domestic is not None
            else card.available_balance
        )
        if raw is None:
            text = f"{g}el disponible de tu {label} no está reportado (dato ausente)."
        else:
            val = format_money(raw, ccy)
            text = f"{g}tienes **{val}** disponibles en tu {label}."
    elif field == "limit":
        if card.credit_limit is None:
            text = f"{g}el límite de tu {label} no está disponible."
        else:
            text = f"{g}el límite de crédito de tu {label} es **{format_money(card.credit_limit, ccy)}**."
    elif field == "min_payment":
        if card.min_payment_rd is None:
            text = f"{g}el pago mínimo de tu {label} no está disponible."
        else:
            text = f"{g}el pago mínimo de tu {label} es **{format_money(card.min_payment_rd, ccy)}**."
    elif field == "cutoff":
        text = (
            f"{g}la fecha de corte de tu {label} es el día **{card.cutoff_day}** de cada mes."
            if card.cutoff_day is not None
            else f"{g}la fecha de corte de tu {label} no está disponible."
        )
    elif field == "due_date":
        due = getattr(card, "payment_due_date", None)
        if due:
            text = f"{g}la fecha límite de pago de tu {label} es **{due}**."
        else:
            cutoff = getattr(card, "cutoff_day", None)
            if cutoff is not None:
                text = (
                    f"{g}no tengo la fecha límite de pago exacta de tu {label} "
                    f"(corte día **{cutoff}**; la límite aparece en el estado de cuenta)."
                )
            else:
                text = (
                    f"{g}la fecha de pago de tu {label} no está disponible en el contexto actual "
                    "(no se deriva del día de corte ni se inventa)."
                )
    elif field in ("expiry", "maturity", "card_expiry"):
        expiry = getattr(card, "card_expiry", None)
        text = (
            f"{g}tu {label} vence en **{expiry}**."
            if expiry
            else f"{g}la fecha de vencimiento de tu {label} no está disponible."
        )
    elif field == "points":
        points = getattr(card, "loyalty_points", None)
        text = (
            f"{g}tienes **{points} puntos** en tu {label}."
            if points is not None
            else f"{g}los puntos de tu {label} no están disponibles."
        )
    elif field == "transactions":
        text = (
            f"{g}los últimos movimientos de tu {label} no están disponibles "
            "en este momento. Para consultarlos contacte las líneas de atención:\n\n"
            "• Centro de Contacto: [809.726.1000](tel:+18097261000)\n"
            "• Correo: [serviciobancanet@bsc.com.do](mailto:serviciobancanet@bsc.com.do)\n"
            "• Web: [bsc.com.do](https://bsc.com.do/)\n"
            "• Centro de Negocios o BSC en Línea"
        )
    elif field == "balance":
        if card.ledger_balance is None:
            text = f"{g}el saldo adeudado de tu {label} no está disponible (dato ausente)."
        else:
            text = (
                f"{g}el saldo adeudado de tu {label} es "
                f"**{format_money(card.ledger_balance, ccy)}**."
            )
    elif field == "detail":
        from genesis_cognitive.context.response_formatting import build_rich_card_detail
        rich = build_rich_card_detail(card)
        text = f"{g.rstrip()}\n{rich}".strip() if g else rich
    else:
        text = (
            f"{g}el campo «{field}» no está soportado para tarjetas en este contexto."
        )
    return GroundedResult(
        "VALID_CONTRACT",
        text,
        "CREDIT_CARD_DETAIL_READ",
        account_ref=card.product_id,
        actions=[_action("CREDIT_CARD_DETAIL_READ", card.product_id)],
        route="personal",
        trace={**trace, "card_field": field, "currency": ccy, "entity_id": card.product_id},
    )


def _account_field(
    snapshot: CustomerContextSnapshot,
    g: str,
    trace: dict,
    packet: IntentPacket,
    *,
    question: str = "",
) -> GroundedResult:
    accts = _pick_products(snapshot, packet, ("SAVINGS", "CHECKING", "PAYROLL"))
    if len(accts) > 1 and not packet.product_hint_digits:
        from genesis_cognitive.brain.continuity import _currency_from_text

        ccy = _currency_from_text(question or str(trace.get("question") or ""))
        if ccy:
            filtered = [p for p in accts if str(p.currency).upper() == ccy]
            if filtered:
                accts = filtered
    if not accts:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no tienes cuentas activas en el portafolio.",
            "ACCOUNT_BALANCE_READ",
            actions=[_action("ACCOUNT_BALANCE_READ")],
            route="personal",
            trace=trace,
        )
    if len(accts) > 1 and not packet.product_hint_digits and packet.scope != "all":
        from genesis_cognitive.context.app_channel import (
            build_account_disambiguation_question,
            build_product_options,
        )
        return GroundedResult(
            "CLARIFICATION_REQUIRED",
            f"{g}" + build_account_disambiguation_question(accts),
            "ACCOUNT_BALANCE_READ",
            actions=[_action("ACCOUNT_BALANCE_READ", missing=["account_ref"])],
            options=build_product_options(
                accts, field=packet.field, snapshot=snapshot,
            ) or None,
            route="personal",
            trace=trace,
        )
    if packet.scope == "all" or (len(accts) > 1 and packet.scope == "all"):
        from genesis_cognitive.context.product_display import build_multi_account_balance_response
        text = build_multi_account_balance_response(snapshot, accts)
        return GroundedResult(
            "VALID_CONTRACT", text, "ACCOUNT_BALANCE_READ",
            actions=[_action("ACCOUNT_BALANCE_READ")], route="personal", trace=trace,
        )
    acct = accts[0]
    label = display_label_in_context(acct, accts)
    if packet.field == "transactions":
        text = (
            f"{g}los últimos movimientos de {label} no están disponibles "
            "en este momento. Para consultarlos contacte las líneas de atención:\n\n"
            "• Centro de Contacto: [809.726.1000](tel:+18097261000)\n"
            "• Correo: [serviciobancanet@bsc.com.do](mailto:serviciobancanet@bsc.com.do)\n"
            "• Web: [bsc.com.do](https://bsc.com.do/)\n"
            "• Centro de Negocios o BSC en Línea"
        )
        return GroundedResult(
            "VALID_CONTRACT",
            text,
            "ACCOUNT_MOVEMENTS_READ",
            account_ref=acct.product_id,
            actions=[_action("ACCOUNT_MOVEMENTS_READ", acct.product_id)],
            route="personal",
            trace=trace,
        )

    # Distinguir disponible vs saldo actual/contable; None ≠ cero; NUNCA sustituir ledger por available
    ccy = acct.currency or snapshot.default_currency or "DOP"
    if packet.field == "available":
        amount = acct.available_balance
        label_field = "saldo disponible"
    elif packet.field == "balance":
        amount = acct.ledger_balance  # ausente si None; no usar available como sustituto
        # Etiqueta según pregunta cuando el ejecutor la propaga en trace
        qn = str(question or packet.rewritten_question or trace.get("question") or "").lower()
        if "contable" in qn:
            label_field = "saldo contable"
        else:
            label_field = "saldo actual"
    else:
        amount = acct.ledger_balance
        label_field = "saldo"

    if amount is None:
        text = (
            f"{g}el {label_field} de {label} no está disponible en el contexto actual. "
            "Para más información contacte las líneas de atención del banco:\n\n"
            "• Centro de Contacto: [809.726.1000](tel:+18097261000)\n"
            "• Correo: [serviciobancanet@bsc.com.do](mailto:serviciobancanet@bsc.com.do)\n"
            "• Web: [bsc.com.do](https://bsc.com.do/)\n"
            "• Centro de Negocios o BSC en Línea"
        )
    else:
        val = format_money(amount, ccy)
        text = f"{g}tu {label_field} en {label} es de **{val}**."
        from genesis_cognitive.context.snapshot_freshness import annotate_portfolio_amount_text

        text = annotate_portfolio_amount_text(text, session=trace.get("session"))
    return GroundedResult(
        "VALID_CONTRACT",
        text,
        "ACCOUNT_BALANCE_READ",
        account_ref=acct.product_id,
        actions=[_action("ACCOUNT_BALANCE_READ", acct.product_id)],
        route="personal",
        trace={
            **trace,
            "account_field": packet.field,
            "amount_present": amount is not None,
            "amount_source": (
                "available_balance" if packet.field == "available"
                else "ledger_balance" if packet.field == "balance"
                else "ledger_balance"
            ),
            "currency": ccy,
            "entity_id": acct.product_id,
        },
    )


def _dap_field(
    snapshot: CustomerContextSnapshot, g: str, trace: dict, packet: IntentPacket,
) -> GroundedResult:
    daps = _pick_products(snapshot, packet, ("TERM_DEPOSIT",))
    if not daps:
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}no tienes certificados de depósito activos.",
            "TERM_DEPOSIT_DETAIL_READ",
            actions=[_action("TERM_DEPOSIT_DETAIL_READ")],
            route="personal",
            trace=trace,
        )
    if len(daps) > 1 and packet.scope in ("all", "compare") and not packet.product_hint_digits:
        lines = []
        for dep in daps:
            label = display_label_in_context(dep, daps)
            capital = format_money(
                dep.ledger_balance if dep.ledger_balance is not None else None,
                dep.currency,
            ) if dep.ledger_balance is not None else None
            # No usar available como capital silencioso
            if capital is None and dep.available_balance is not None:
                capital = None  # capital ausente; no sustituir
            rate = f"{dep.interest_rate}%" if dep.interest_rate is not None else None
            maturity = dep.maturity_date or None
            bits = []
            if capital is not None:
                bits.append(f"capital **{capital}**")
            elif packet.field in ("capital", "balance", "detail") or packet.scope == "all":
                bits.append("capital no disponible")
            if rate is not None:
                bits.append(f"tasa **{rate}**")
            if maturity is not None:
                bits.append(f"vencimiento **{maturity}**")
            lines.append(f"• **{label}**: " + "; ".join(bits) if bits else f"• **{label}**")
        intro = "comparación" if packet.scope == "compare" else "resumen"
        return GroundedResult(
            "VALID_CONTRACT",
            f"{g}aquí tienes el {intro} de tus depósitos a plazo:\n" + "\n".join(lines),
            "TERM_DEPOSIT_DETAIL_READ",
            actions=[_action("TERM_DEPOSIT_DETAIL_READ")],
            route="personal",
            trace={**trace, "scope": packet.scope},
        )
    if len(daps) > 1 and not packet.product_hint_digits:
        from genesis_cognitive.context.app_channel import (
            build_dap_disambiguation_question,
            build_product_options,
        )
        return GroundedResult(
            "CLARIFICATION_REQUIRED",
            f"{g}" + build_dap_disambiguation_question(daps),
            "TERM_DEPOSIT_DETAIL_READ",
            actions=[_action("TERM_DEPOSIT_DETAIL_READ", missing=["account_ref"])],
            options=build_product_options(
                daps, field=packet.field, snapshot=snapshot,
            ) or None,
            route="personal",
            trace=trace,
        )
    dep = daps[0]
    label = display_label_in_context(dep, daps)
    field = packet.field
    if field == "rate":
        text = (
            f"{g}la tasa de tu {label} es **{dep.interest_rate}%** anual."
            if dep.interest_rate is not None
            else f"{g}la tasa de tu {label} no está disponible."
        )
    elif field == "interest_amount":
        val = format_money(dep.interest_amount, dep.currency)
        text = (
            f"{g}los intereses generados de tu {label} son **{val}**."
            if val
            else f"{g}los intereses generados de tu {label} no están disponibles."
        )
    elif field == "maturity":
        text = (
            f"{g}tu {label} vence el **{dep.maturity_date}**."
            if dep.maturity_date
            else f"{g}el vencimiento de tu {label} no está disponible."
        )
    elif field in ("principal", "capital", "balance"):
        if dep.ledger_balance is None:
            text = f"{g}el monto invertido de tu {label} no está disponible."
        else:
            val = format_money(dep.ledger_balance, dep.currency)
            text = f"{g}el monto invertido de tu {label} es **{val}**."
    elif field == "opening_date":
        text = f"{g}la fecha de apertura de tu {label} no está disponible en el contexto actual."
    elif field == "term_days":
        text = f"{g}el plazo contratado en días de tu {label} no está disponible en el contexto actual."
    elif field == "capitalization":
        text = f"{g}la modalidad de capitalización de intereses de tu {label} no está disponible en el contexto actual."
    elif field == "detail":
        if dep.ledger_balance is None:
            capital_txt = "no disponible"
        else:
            capital_txt = format_money(dep.ledger_balance, dep.currency) or "no disponible"
        rate = f"{dep.interest_rate}% anual" if dep.interest_rate is not None else "no disponible"
        maturity = dep.maturity_date if dep.maturity_date else "no disponible"
        generated = format_money(dep.interest_amount, dep.currency) if dep.interest_amount is not None else None
        bits = [
            f"capital **{capital_txt}**",
            f"tasa **{rate}**",
            f"vencimiento **{maturity}**",
        ]
        if generated:
            bits.insert(2, f"generado **{generated}**")
        text = f"{g}de tu {label}: " + "; ".join(bits) + "."
    else:
        # Capital: solo ledger; no sustituir por available
        if dep.ledger_balance is None:
            text = f"{g}el capital de tu {label} no está disponible."
        else:
            val = format_money(dep.ledger_balance, dep.currency)
            text = f"{g}el capital de tu {label} es **{val}**."
    return GroundedResult(
        "VALID_CONTRACT",
        text,
        "TERM_DEPOSIT_DETAIL_READ",
        account_ref=dep.product_id,
        actions=[_action("TERM_DEPOSIT_DETAIL_READ", dep.product_id)],
        route="personal",
        trace=trace,
    )
