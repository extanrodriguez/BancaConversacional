"""App channel helpers — options, disambiguation copy, status mapping for /turn."""

from __future__ import annotations

import re
from typing import Any

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot, ProductSnapshot
from genesis_cognitive.context.product_display import display_label_in_context

PRODUCT_TYPE_API: dict[str, str] = {
    "SAVINGS": "savings_account",
    "CHECKING": "checking_account",
    "PAYROLL": "payroll_account",
    "CREDIT_CARD": "credit_card",
    "LOAN": "loan",
    "TERM_DEPOSIT": "term_deposit",
}

REF_PREFIX: dict[str, str] = {
    "SAVINGS": "CUENTA_AHORRO",
    "CHECKING": "CUENTA_CORRIENTE",
    "PAYROLL": "CUENTA_NOMINA",
    "CREDIT_CARD": "TARJETA",
    "LOAN": "PRESTAMO",
    "TERM_DEPOSIT": "DEPOSITO_PLAZO",
}

OPTION_LABEL: dict[str, str] = {
    "SAVINGS": "Cuenta de ahorro",
    "CHECKING": "Cuenta corriente",
    "PAYROLL": "Cuenta nómina",
    "CREDIT_CARD": "Tarjeta de crédito",
    "LOAN": "Préstamo",
    "TERM_DEPOSIT": "Depósito a plazo",
}


def api_product_type(internal_type: str) -> str:
    return PRODUCT_TYPE_API.get(internal_type, internal_type.lower())


def build_option_ref(product: ProductSnapshot) -> str:
    prefix = REF_PREFIX.get(product.product_type, "PRODUCTO")
    digits = "".join(ch for ch in product.product_id if ch.isdigit())
    # Préstamos: 5 dígitos (alineado con display_label); resto 4
    n = 5 if product.product_type == "LOAN" and len(digits) >= 5 else 4
    suffix = digits[-n:] if digits else (
        product.product_id[-4:] if len(product.product_id) >= 4 else product.product_id
    )
    return f"{prefix}_{suffix}"


def _safe_visible_label(label: str) -> str:
    """Evita que máscaras con asteriscos rompan el Markdown del canal."""
    return re.sub(r"\*{2,}(?=\d{3,})", "••••", label or "")


def _display_date(value: str | None) -> str | None:
    if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        year, month, day = value.split("-")
        return f"{day}/{month}/{year}"
    return value


def _money_bit(value: Any, currency: str) -> str:
    from genesis_cognitive.context.response_formatting import format_money

    return format_money(value, currency) or "No disponible"


def _field_snippet(
    product: ProductSnapshot,
    field: str,
    snapshot: CustomerContextSnapshot | None,
) -> str | None:
    """Una línea corta del campo pedido, para la card de selección."""
    loan = None
    if snapshot is not None and product.product_type == "LOAN":
        loan = next(
            (item for item in snapshot.loans if item.product_id == product.product_id),
            None,
        )
    ccy = product.currency or "DOP"
    key = {
        "payment_due_date": "due_date",
        "interest_rate": "rate",
        "available_balance": "available",
        "maturity_date": "maturity",
        "card_expiry": "expiry",
    }.get(field, field)
    if key in ("balance",) and product.product_type == "CREDIT_CARD":
        return f"Saldo adeudado: {_money_bit(product.ledger_balance, ccy)}"
    if key == "available":
        raw = (
            product.available_purchases_domestic
            if product.available_purchases_domestic is not None
            else product.available_balance
        )
        return f"Disponible: {_money_bit(raw, ccy)}"
    if key == "due_date":
        value = getattr(product, "payment_due_date", None) or getattr(loan, "next_due_date", None)
        return f"Fecha límite: {_display_date(value) or 'No disponible'}"
    if key == "min_payment":
        return f"Pago mínimo: {_money_bit(product.min_payment_rd, ccy)}"
    if key == "rate":
        value = product.interest_rate or getattr(loan, "annual_interest_rate", None)
        return f"Tasa: {value}%" if value is not None else "Tasa: No disponible"
    if key == "principal":
        if product.product_type == "TERM_DEPOSIT":
            return f"Invertido: {_money_bit(product.ledger_balance, ccy)}"
        return f"Capital: {_money_bit(getattr(loan, 'outstanding_principal', None), ccy)}"
    if key == "interest_amount":
        return f"Generado: {_money_bit(getattr(product, 'interest_amount', None), ccy)}"
    if key == "payoff":
        return f"Para cancelar: {_money_bit(getattr(loan, 'payoff_amount', None), ccy)}"
    if key == "installment_amount":
        return f"Cuota: {_money_bit(getattr(loan, 'installment_amount', None), ccy)}"
    if key == "cutoff":
        day = product.cutoff_day
        return f"Corte: día {day}" if day is not None else "Corte: No disponible"
    if key in ("maturity", "expiry", "card_expiry"):
        if product.product_type == "CREDIT_CARD":
            value = getattr(product, "card_expiry", None)
            return f"Vence: {value or 'No disponible'}"
        value = product.maturity_date or getattr(loan, "maturity_date", None)
        return f"Vence: {_display_date(value) or 'No disponible'}"
    if key == "balance":
        raw = product.ledger_balance if product.ledger_balance is not None else product.available_balance
        if product.product_type == "TERM_DEPOSIT":
            return f"Invertido: {_money_bit(raw, ccy)}"
        return f"Saldo: {_money_bit(raw, ccy)}"
    return None


def _multi_field_message(label: str, fields: list[str]) -> str:
    """La burbuja de selección repite lo pedido, no un solo campo."""
    names = {
        "balance": "cuánto debo",
        "available": "cuánto tengo disponible",
        "due_date": "cuándo es la fecha límite de pago",
        "min_payment": "cuál es el pago mínimo",
        "rate": "cuál es la tasa",
        "principal": "cuánto invertí",
        "interest_amount": "cuánto ha generado",
        "payoff": "cuánto necesito para cancelarlo",
        "installment_amount": "cuánto es la cuota",
        "cutoff": "cuál es la fecha de corte",
        "maturity": "cuándo vence",
        "expiry": "cuándo expira la tarjeta",
        "detail": "el detalle",
    }
    bits = [names[f] for f in fields if f in names]
    product = (label or "producto").strip()
    if not bits:
        return f"¿Detalle de mi {product}?" if fields == ["detail"] or "detail" in (fields or []) else product
    if len(bits) == 1:
        return f"¿{bits[0][0].upper()}{bits[0][1:]} de mi {product}?"
    head = ", ".join(bits[:-1])
    return f"¿{head[0].upper()}{head[1:]} y {bits[-1]} de mi {product}?"


def _selection_from_original_question(question: str, label: str) -> str | None:
    """Reescribe la pregunta original anclada al producto seleccionado."""
    raw = (question or "").strip()
    if not raw or len(raw) < 12:
        return None
    qlow = raw.lower()
    # Preferir pregunta original reescrita por producto
    # (p. ej. «cuánto debo de mi tarjeta (••••2240)?»)
    signals = sum(
        1
        for s in (
            "inverti", "invertí", "tasa", "generad", "vence", "vencimiento",
            "debo", "disponible", "fecha", "capital", "cuanto", "cuánto",
            "saldo", "cuota", "compar", "pagar", "consulta", "revisa",
        )
        if s in qlow
    )
    if signals < 1:
        return None
    if signals < 2 and not any(s in qlow for s in ("debo", "cuanto", "cuánto", "saldo", "disponible")):
        if not any(s in qlow for s in ("tarjeta", "cuenta", "prestamo", "préstamo", "certificado")):
            return None
    base = raw.rstrip(" ?.!")
    product = (label or "producto").strip()
    # Extraer máscara (...05511) o dígitos del label
    import re as _re
    mask = None
    m = _re.search(r"(\(\s*[.•*…•]*\s*\d{3,}\s*\))", product)
    if m:
        mask = m.group(1).replace(" ", "")
    else:
        digits = _re.findall(r"\d{3,}", product)
        if digits:
            mask = f"(...{digits[-1][-5:]})" if len(digits[-1]) >= 5 else f"(...{digits[-1]})"
    if mask and mask not in base:
        return f"{base} {mask}?"
    if product and product.lower() not in base.lower():
        return f"{base} de mi {product}?"
    return f"{base}?"


def _option_context(
    product: ProductSnapshot,
    field: str | None,
    snapshot: CustomerContextSnapshot | None,
) -> dict[str, Any] | None:
    canonical = {
        "maturity_date": "maturity",
        "card_expiry": "expiry",
        "interest_rate": "rate",
        "balance": "available_balance",
        "payment_due_date": "due_date",
        "cutoff_date": "cutoff",
        "payoff_amount": "payoff",
    }.get(field or "", field or "")
    loan = None
    if snapshot is not None and product.product_type == "LOAN":
        loan = next(
            (item for item in snapshot.loans if item.product_id == product.product_id),
            None,
        )

    label = ""
    formatted = ""
    if canonical == "rate":
        value = product.interest_rate or getattr(loan, "annual_interest_rate", None)
        label = "Tasa de interés"
        formatted = f"{value}%" if value is not None else "No disponible"
    elif canonical in ("maturity", "expiry", "card_expiry"):
        if product.product_type == "CREDIT_CARD":
            value = getattr(product, "card_expiry", None)
            label = "Vencimiento de la tarjeta"
            formatted = value or "No disponible"
        else:
            value = product.maturity_date or getattr(loan, "maturity_date", None)
            label = "Vence"
            formatted = _display_date(value) or "No disponible"
    elif canonical == "due_date":
        value = getattr(product, "payment_due_date", None) or getattr(loan, "next_due_date", None)
        label = "Próximo pago"
        formatted = _display_date(value) or "No disponible"
    elif canonical == "cutoff":
        value = product.cutoff_day
        label = "Fecha de corte"
        formatted = f"Día {value}" if value is not None else "No disponible"
    elif canonical in ("available_balance", "principal", "payoff"):
        if canonical == "principal":
            value = getattr(loan, "outstanding_principal", None)
            label = "Capital pendiente"
        elif canonical == "payoff":
            value = getattr(loan, "payoff_amount", None)
            label = "Total adeudado"
        else:
            value = product.available_balance or product.ledger_balance
            label = "Saldo disponible"
        formatted = (
            f"{product.currency} {value:,.2f}" if value is not None else "No disponible"
        )
    else:
        return None

    return {
        "field": canonical,
        "label": label,
        "formatted_value": formatted,
        "currency": product.currency,
    }


def _selection_message(label: str, field: str | None) -> str:
    product = (label or "producto").strip()
    if product:
        product = product[0].lower() + product[1:]
    return {
        "rate": f"¿Cuál es la tasa de interés de mi {product}?",
        "maturity": f"¿Cuándo vence mi {product}?",
        "due_date": f"¿Cuándo debo pagar mi {product}?",
        "cutoff": f"¿Cuál es la fecha de corte de mi {product}?",
        "available_balance": f"¿Cuál es el saldo disponible de mi {product}?",
        "principal": f"¿Cuál es el capital pendiente de mi {product}?",
        "payoff": f"¿Cuánto debo para saldar mi {product}?",
        "overdue": f"¿Tengo mora en mi {product}?",
    }.get(field or "", f"Dame información de mi {product}")


def build_product_option(
    product: ProductSnapshot,
    pool: list[ProductSnapshot] | None = None,
    *,
    field: str | None = None,
    fields: list[str] | None = None,
    snapshot: CustomerContextSnapshot | None = None,
    original_question: str | None = None,
) -> dict[str, Any]:
    """Single option entry for app_channel.options (orchestrator / APK contract)."""
    pool = pool or [product]
    # TC / préstamos / DAP: nombre comercial del Core (productDescription → alias)
    if product.product_type in ("LOAN", "CREDIT_CARD", "TERM_DEPOSIT"):
        label = _safe_visible_label(display_label_in_context(product, pool))
    else:
        base = OPTION_LABEL.get(product.product_type, display_label_in_context(product, pool))
        last4 = _last4(product)
        label = f"{base} ···{last4}" if last4 else base
    ref = build_option_ref(product)
    asked = [f for f in (fields or ([field] if field else [])) if f]
    snippets = [s for f in asked if (s := _field_snippet(product, f, snapshot))]
    context = _option_context(product, asked[0] if len(asked) == 1 else None, snapshot)
    result = {
        "ref": ref,
        "label": label,
        "product_type": api_product_type(product.product_type),
        "currency": product.currency,
        "selection": {
            "type": "product",
            "selected_option_ref": ref,
        },
    }
    sel_from_orig = _selection_from_original_question(original_question or "", label)
    if len(snippets) >= 2:
        result["subtitle"] = " · ".join(snippets)
        result["context"] = {
            "field": "+".join(asked),
            "label": "Consulta",
            "formatted_value": result["subtitle"],
            "currency": product.currency,
        }
        result["selection"]["message"] = (
            sel_from_orig or _multi_field_message(label, asked)
        )
    elif context:
        result["context"] = context
        result["subtitle"] = (
            f"{context['label']}: {context['formatted_value']}"
            f" · Moneda: {context['currency']}"
        )
        result["selection"]["message"] = (
            sel_from_orig
            or _selection_message(label, str(context.get("field") or ""))
        )
    elif snippets:
        result["subtitle"] = snippets[0]
        result["selection"]["message"] = (
            sel_from_orig
            or (_multi_field_message(label, asked) if asked else label)
        )
    elif sel_from_orig:
        result["selection"]["message"] = sel_from_orig
    return result


def build_product_options(
    products: list[ProductSnapshot],
    *,
    field: str | None = None,
    fields: list[str] | None = None,
    question: str | None = None,
    snapshot: CustomerContextSnapshot | None = None,
    allow_single: bool = False,
) -> list[dict[str, Any]]:
    if len(products) < 1:
        return []
    if len(products) < 2 and not allow_single:
        return []
    asked = list(fields or [])
    if not asked and not field and question:
        from genesis_cognitive.context.query_spec import build_query_spec

        derived = build_query_spec(question)
        field = derived.get("field")
    if not asked and field:
        asked = [field]
    return [
        build_product_option(
            p,
            products,
            field=field,
            fields=asked,
            snapshot=snapshot,
            original_question=question,
        )
        for p in products
    ]


def _last4(product: ProductSnapshot) -> str:
    if product.card_mask and len(product.card_mask) >= 4:
        digits = "".join(ch for ch in product.card_mask if ch.isdigit())
        if len(digits) >= 4:
            return digits[-4:]
    pid = product.product_id
    return pid[-4:] if len(pid) >= 4 else pid


def _join_options(parts: list[str], *, prefix: str = "¿Cuál deseas consultar") -> str:
    if len(parts) < 2:
        return "Selecciona el producto que deseas consultar."
    title = prefix.rstrip(" ?:") + ":"
    items = "\n".join(f"• **{_safe_visible_label(part)}**" for part in parts)
    return f"{title}\n\n{items}"


def build_account_disambiguation_question(accounts: list[ProductSnapshot]) -> str:
    """Matriz_Cuentas — pregunta con terminación en últimos 4 dígitos."""
    parts: list[str] = []
    only_savings = all(p.product_type == "SAVINGS" for p in accounts)
    for p in accounts:
        last4 = _last4(p)
        if p.product_type == "SAVINGS":
            if only_savings and len({a.currency for a in accounts}) > 1:
                ccy = "pesos" if p.currency == "DOP" else "dólares"
                parts.append(f"la cuenta de ahorros en {ccy} terminada en {last4}")
            elif only_savings:
                parts.append(f"la terminada en {last4}")
            else:
                parts.append(f"la cuenta de ahorros terminada en {last4}")
        elif p.product_type == "CHECKING":
            parts.append(f"la corriente terminada en {last4}")
        elif p.product_type == "PAYROLL":
            parts.append(f"la cuenta nómina terminada en {last4}")
        else:
            parts.append(display_label_in_context(p, accounts).lower())

    if only_savings and len(parts) == 2 and len({a.currency for a in accounts}) == 1:
        return _join_options(parts, prefix="Tienes dos cuentas de ahorros. ¿Quieres consultar")
    return _join_options(parts)


def build_card_disambiguation_question(cards: list[ProductSnapshot]) -> str:
    parts = [display_label_in_context(p, cards) for p in cards]
    return _join_options(parts, prefix="¿Cuál tarjeta deseas consultar")


def build_loan_disambiguation_question(loans: list[ProductSnapshot]) -> str:
    parts = [display_label_in_context(p, loans) for p in loans]
    return _join_options(parts, prefix="¿Sobre cuál préstamo deseas consultar")


def build_dap_disambiguation_question(deposits: list[ProductSnapshot]) -> str:
    parts = [display_label_in_context(p, deposits) for p in deposits]
    return _join_options(parts, prefix="¿Cuál certificado deseas consultar")


def build_product_disambiguation_question(
    products: list[ProductSnapshot],
    *,
    field: str | None = None,
) -> str:
    if not products:
        return "Selecciona el producto que deseas consultar."
    types = {p.product_type for p in products}
    labels = [display_label_in_context(p, products) for p in products]
    if len(types) > 1:
        if field in ("rate", "interest_rate", "tasa"):
            return _join_options(
                labels,
                prefix="Tienes varios productos con tasa de interés. ¿Cuál quieres consultar",
            )
        if field in ("maturity", "maturity_date", "vencimiento"):
            return _join_options(
                labels,
                prefix="Tienes varios productos con fecha de vencimiento. ¿Cuál quieres consultar",
            )
        return _join_options(labels, prefix="¿Cuál de estos productos deseas consultar")
    kind = products[0].product_type
    if kind in ("CHECKING", "SAVINGS", "PAYROLL"):
        return build_account_disambiguation_question(products)
    if kind == "CREDIT_CARD":
        return build_card_disambiguation_question(products)
    if kind == "LOAN":
        return build_loan_disambiguation_question(products)
    if kind == "TERM_DEPOSIT":
        return build_dap_disambiguation_question(products)
    return _join_options([lb.lower() for lb in labels])


def map_app_status(internal_status: str, *, has_options: bool) -> str:
    if internal_status == "CLARIFICATION_REQUIRED" and has_options:
        return "requires_selection"
    return internal_status


def map_app_intent(
    internal_intent: str | None,
    *,
    pool: list[ProductSnapshot],
) -> str | None:
    if len(pool) >= 2:
        types = {p.product_type for p in pool}
        if types <= {"CHECKING", "SAVINGS", "PAYROLL"}:
            return "ACCOUNTS"
        if types == {"CREDIT_CARD"}:
            return "CREDIT_CARDS"
        if types == {"LOAN"}:
            return "LOANS"
        if types == {"TERM_DEPOSIT"}:
            return "TERM_DEPOSITS"
    return internal_intent


def _missing_requirement_for_pool(pool: list[ProductSnapshot]) -> str | None:
    if not pool:
        return None
    kind = pool[0].product_type
    if kind in ("CHECKING", "SAVINGS", "PAYROLL"):
        return "tipo_de_cuenta"
    if kind == "CREDIT_CARD":
        return "tipo_de_tarjeta"
    if kind == "LOAN":
        return "tipo_de_prestamo"
    if kind == "TERM_DEPOSIT":
        return "deposito_plazo"
    return None


def resolve_option_pool(
    snapshot: CustomerContextSnapshot,
    *,
    intent_id: str | None,
    question: str,
) -> list[ProductSnapshot]:
    """Pick eligible products for options list from intent + snapshot."""
    from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question as _is_loan_opt

    active_deposits = [
        p for p in snapshot.products
        if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL")
        and p.status.lower() == "active"
        and p.currency == snapshot.default_currency
    ]
    active_loans = [
        p for p in snapshot.products
        if p.product_type == "LOAN" and p.status.lower() == "active" and p.currency == snapshot.default_currency
    ]
    active_cards = [p for p in snapshot.products if p.product_type == "CREDIT_CARD" and p.status.lower() == "active"]
    active_daps = [p for p in snapshot.products if p.product_type == "TERM_DEPOSIT" and p.status.lower() == "active"]

    _LOAN_INTENTS = ("LOAN_DETAIL_READ", "LOAN_PAYMENT_VALIDATE")
    _CARD_INTENTS = ("CREDIT_CARD_DETAIL_READ",)
    _DAP_INTENTS = ("TERM_DEPOSIT_DETAIL_READ",)
    _NO_OPTIONS = (
        "AMBIGUOUS_PRODUCT_SCOPE",
        "BUSINESS_KNOWLEDGE_QUERY",
        "ASSISTANT_SCOPE",
        "NON_OPERATIONAL",
        "UNSUPPORTED",
        "SECURITY_GUARDRAIL",
    )

    if intent_id in _NO_OPTIONS:
        return []
    if intent_id in _LOAN_INTENTS or (intent_id is None and _is_loan_opt(question or "")):
        return active_loans
    if intent_id in _CARD_INTENTS:
        return active_cards
    if intent_id in _DAP_INTENTS:
        return active_daps
    if intent_id == "PAYMENT_DATE_READ":
        q = (question or "").lower()
        wants_loan = any(s in q for s in ("préstamo", "prestamo", "cuota"))
        wants_card = any(s in q for s in ("tarjeta", "visa", "mastercard"))
        if wants_loan and active_loans:
            return active_loans
        if wants_card and active_cards:
            return active_cards
        return [*active_loans, *active_cards]

    # Balance / movements — all active deposits (any currency) when clarifying account
    all_deposits = [
        p for p in snapshot.products
        if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL") and p.status.lower() == "active"
    ]
    qlow = (question or "").lower()
    liquidity_ask = any(
        s in qlow
        for s in (
            "disponible",
            "saldo actual",
            "cuanto tengo",
            "cuánto tengo",
            "mi saldo",
            "el saldo",
            "balance",
        )
    ) and not any(s in qlow for s in ("prestamo", "préstamo", "cuota", "debo", "deuda"))

    if intent_id in ("ACCOUNT_BALANCE_READ", "ACCOUNT_MOVEMENTS_READ"):
        if len(all_deposits) >= 2:
            return all_deposits
        if len(active_deposits) >= 2:
            return active_deposits
        # Una sola cuenta: no inventar pool de préstamos
        return all_deposits if all_deposits else []

    # PORTFOLIO_QUERY genérico de liquidez (QA A2): cuentas, nunca fallback a préstamos
    if intent_id == "PORTFOLIO_QUERY" and liquidity_ask:
        if len(all_deposits) >= 2:
            return all_deposits
        return all_deposits if all_deposits else []

    # Pregunta de tarjetas: no ofrecer cuentas ahorro/corriente por defecto
    if any(s in qlow for s in ("tarjeta", "visa", "mastercard", " tc", "tc ")) and len(active_cards) >= 2:
        return active_cards

    if len(all_deposits) >= 2:
        return all_deposits
    if len(active_deposits) >= 2:
        return active_deposits
    # Solo caer a préstamos si la pregunta es claramente de préstamo/deuda
    if len(active_loans) >= 2 and (
        intent_id in _LOAN_INTENTS
        or any(s in qlow for s in ("prestamo", "préstamo", "cuota", "debo", "deuda", "tasa"))
    ):
        return active_loans
    if len(active_cards) >= 2:
        return active_cards
    if len(active_daps) >= 2:
        return active_daps
    return []


def build_clarifications_for_app(
    clarifications: list[dict[str, Any]],
    *,
    pool: list[ProductSnapshot],
) -> list[dict[str, Any]]:
    missing_key = _missing_requirement_for_pool(pool)
    if not clarifications:
        if missing_key:
            return [{
                "target_action_sequence": 1,
                "missing_requirements": [missing_key],
                "suggested_question": build_product_disambiguation_question(pool),
                "already_known": [],
            }]
        return []
    out: list[dict[str, Any]] = []
    for c in clarifications:
        missing = list(c.get("missing_requirements") or [])
        if missing_key and "account_ref" in missing:
            missing = [missing_key if m == "account_ref" else m for m in missing]
            if missing_key not in missing:
                missing = [missing_key, *missing]
        out.append({**c, "missing_requirements": missing})
    return out


def assemble_app_channel(
    data: dict[str, Any],
    *,
    snapshot: CustomerContextSnapshot | None,
    question: str,
    pending_intent: str | None = None,
) -> dict[str, Any]:
    """Build app_channel dict from inspect pipeline body.

    Importante (orquestador BSC):
    - ``intent_id`` debe ser el intent operativo (ACCOUNT_BALANCE_READ, …).
      Dominios tipo ACCOUNTS/LOANS hacen que el orquestador derive a Banking API
      y descarte options/client_response de la cognitiva.
    - ``options`` se reenvía al APK solo cuando el orquestador clasifica como Normal.
    """
    import os

    actions = data.get("actions") or []
    a0 = actions[0] if actions else {}
    internal_status = data.get("status") or "ERROR"
    clarifications = data.get("clarifications") or []

    # La intención del turno actual prevalece sobre una selección pendiente.
    # Esto evita reportar TERM_DEPOSIT_DETAIL_READ para respuestas sociales.
    intent_id = (
        (a0.get("intent_id") if a0 else None)
        or data.get("intent_id")
        or (pending_intent if internal_status == "CLARIFICATION_REQUIRED" else None)
    )
    options: list[dict[str, Any]] = []
    pool: list[ProductSnapshot] = []

    # Preferir opciones ya construidas por el plan cognitivo (D/F parciales /
    # restantes tras responder una card). Aceptar 1+ (última card disponible).
    prebuilt = data.get("app_channel_options")
    if not isinstance(prebuilt, list) or not prebuilt:
        prebuilt = data.get("options") if isinstance(data.get("options"), list) else []
    if isinstance(prebuilt, list) and len(prebuilt) >= 1:
        options = list(prebuilt)

    # GENESIS_DISABLE_OPTIONS=1 solo para pruebas A/B; por defecto options activos.
    disable_options = os.getenv("GENESIS_DISABLE_OPTIONS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if disable_options:
        options = []

    needs_product_selection = (
        not options
        and internal_status == "CLARIFICATION_REQUIRED"
        and (
            (clarifications and "account_ref" in (clarifications[0].get("missing_requirements") or []))
            or intent_id in (
                "ACCOUNT_BALANCE_READ",
                "ACCOUNT_MOVEMENTS_READ",
                "CREDIT_CARD_DETAIL_READ",
                "LOAN_DETAIL_READ",
                "TERM_DEPOSIT_DETAIL_READ",
            )
        )
    )

    # Clarificaciones de conocimiento/proceso (ej. canal de reclamación) NO son
    # desambiguación de producto — no reescribir el mensaje con cuentas.
    if clarifications:
        _miss = clarifications[0].get("missing_requirements") or []
        if any(
            m in _miss
            for m in ("reclamacion_channel", "query_scope", "knowledge_topic", "channel")
        ):
            needs_product_selection = False
        topic = (a0.get("detected_entities") or {}).get("knowledge_topic") if a0 else None
        if topic == "RECLAMACION_CHANNEL" or (intent_id == "BUSINESS_KNOWLEDGE_QUERY" and "account_ref" not in _miss):
            needs_product_selection = False

    if needs_product_selection and snapshot is not None:
        pool = resolve_option_pool(snapshot, intent_id=intent_id, question=question)
        if len(pool) >= 2:
            if not disable_options:
                options = build_product_options(
                    pool, question=question, snapshot=snapshot,
                )
        else:
            needs_product_selection = False
            pool = []
    elif internal_status == "CLARIFICATION_REQUIRED":
        pool = []

    has_options = len(options) >= 2
    app_status = map_app_status(internal_status, has_options=has_options)
    # Siempre intent operativo hacia el orquestador (nunca ACCOUNTS/LOANS).
    app_intent = intent_id

    client_response = data.get("client_response")
    if needs_product_selection and pool and len(pool) >= 2:
        disamb = build_product_disambiguation_question(pool)
        # Conservar aviso de seguridad (PIN/OTP) si venía en la respuesta cognitiva
        prev = (client_response or "").strip()
        if prev and any(
            s in prev.lower()
            for s in ("pin", "otp", "cvv", "contraseña", "contrasena", "por seguridad")
        ):
            # Tomar solo el bloque de seguridad (primera parte antes de datos/aclaración)
            security_bits = []
            for para in prev.split("\n\n"):
                pl = para.lower()
                if any(s in pl for s in ("pin", "otp", "cvv", "contraseña", "contrasena", "por seguridad", "no debo recibir")):
                    security_bits.append(para.strip())
            if security_bits:
                client_response = "\n\n".join(security_bits + [disamb])
            else:
                client_response = disamb
        else:
            client_response = disamb

    from genesis_cognitive.context.response_formatting import looks_like_markdown_product
    from genesis_cognitive.context.rich_content import (
        build_rich_content,
        normalize_client_markdown,
    )

    client_response = normalize_client_markdown(client_response)
    content_format = (
        "markdown"
        if looks_like_markdown_product(client_response) or "](" in client_response
        else "plain"
    )
    suggestions = data.get("suggested_questions") or []
    rich_content = build_rich_content(
        client_response,
        options=options,
        suggestions=suggestions,
        normalized=True,
    )

    return {
        "status": app_status,
        "client_response": client_response,
        "content_format": content_format,
        "clarifications": build_clarifications_for_app(clarifications, pool=pool),
        "options": options,
        "suggested_questions": suggestions,
        "rich_content": rich_content,
        "conversation_id": data.get("conversation_id"),
        "turn_number": data.get("turn_number"),
        "intent_id": app_intent,
        "account_ref": a0.get("detected_entities", {}).get("account_ref") if a0 else None,
    }
