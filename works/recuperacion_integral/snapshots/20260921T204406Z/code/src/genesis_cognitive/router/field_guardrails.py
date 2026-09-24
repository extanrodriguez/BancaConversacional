"""Deterministic field guardrails — tarjetas, saldos genéricos, movimientos, transferencias."""

from __future__ import annotations

import re
from typing import Any

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot
from genesis_cognitive.context.app_channel import (
    build_account_disambiguation_question,
    build_card_disambiguation_question,
    build_dap_disambiguation_question,
    build_loan_disambiguation_question,
)
from genesis_cognitive.context.product_display import (
    build_clarification_cards,
    build_clarification_loans,
    build_product_suggestions,
    display_label_in_context,
    filter_active_by_type,
)
from genesis_cognitive.router.final_response_agent import (
    build_card_detail_response,
    build_loan_detail_response,
    build_multi_card_aggregate_response,
)

_DEPOSIT_TYPES = ("CHECKING", "SAVINGS", "PAYROLL")

_GENERIC_BALANCE_SIGNALS = (
    "dime mi saldo",
    "dame mi saldo",
    "dame el saldo",
    "dame el balance",
    "dame mi balance",
    "cual es mi saldo",
    "cuál es mi saldo",
    "cual es el saldo",
    "cuál es el saldo",
    "cual es el balance",
    "cuál es el balance",
    "cual es el saldo actual",
    "cuál es el saldo actual",
    "saldo actual",
    "cuanto tengo",
    "cuánto tengo",
    "cuanto me queda",
    "cuánto me queda",
    "cuanto tengo disponible",
    "cuánto tengo disponible",
    "que tengo disponible",
    "qué tengo disponible",
    "tengo disponible",
    "balance de mi cuenta",
    "balance de la cuenta",
    "balance de mis cuentas",
    "saldo de mi cuenta",
    "saldo de la cuenta",
    "saldo de mis cuentas",
    "mis cuentas",
    "mi saldo",
    "mi balance",
    "el balance",
    "el saldo",
)

_BALANCE_SPECIFIC_HINTS = (
    "tarjeta",
    "visa",
    "mastercard",
    "prestamo",
    "préstamo",
    "credito",
    "crédito",
    "hipotec",
    "deposito",
    "depósito",
    "certificado",
    "corriente",
    "ahorro",
    "ahorros",
    "nomina",
    "nómina",
    "dolares",
    "dólares",
    "usd",
    "pesos",
    "dop",
    "rd$",
    "peso dominicano",
    "limite",
    "límite",
    "corte",
    "corta",
    "movimiento",
    "transfer",
)

_CARD_FIELD_SIGNALS = (
    "limite",
    "límite",
    "corte",
    "corta",
    "pago minimo",
    "pago mínimo",
    "minimo",
    "mínimo",
    "disponible en mi tarjeta",
    "disponible de mi tarjeta",
    "puntos santa cruz",
    "balance al corte",
    "ultimo corte",
    "último corte",
    "monto a pagar",
)

_CARD_BALANCE_SIGNALS = (
    "debo",
    "saldo",
    "cuanto debo",
    "cuánto debo",
    "cual es mi saldo",
    "cuál es mi saldo",
    "cuanto tengo",
    "cuánto tengo",
)

_DAP_FIELD_SIGNALS = (
    "deposito",
    "depósito",
    "certificado",
    "dap",
    "cdt",
    "plazo",
    "metido",
    "metida",
    "ahi",
    "ahí",
    "inversion",
    "inversión",
    "capitaliz",
    "modalidad",
    "vence",
    "tasa",
    "interes",
    "interés",
)

_CARD_WORDS = ("tarjeta", "visa", "mastercard", "pricesmart")

_MOVEMENTS_SIGNALS = (
    "movimiento",
    "transaccion",
    "transacción",
    "historial",
    "ultimos pagos",
    "últimos pagos",
    "ultimas transacciones",
    "últimas transacciones",
)

_TRANSFER_SIGNALS = (
    "transfer",
    "transferir",
    "enviar dinero",
    "mandar dinero",
    "mover dinero",
    "pasar dinero",
    "retiro",
    "retirar",
    "pago a tercero",
    "pagar a",
)

_MUTATION_UNSUPPORTED_MSG = (
    "Lo siento, aún no tengo habilitados los canales para realizar transferencias, "
    "retiros u otras operaciones sobre tus productos. Puedo ayudarte con consultas de "
    "saldos, préstamos, tarjetas o información del banco."
)


def _contains_token(text: str, token: str) -> bool:
    """Match whole tokens — evita falsos positivos como 'visa' dentro de 'revisa'."""
    return bool(re.search(rf"(?<![a-záéíóúñ]){re.escape(token)}(?![a-záéíóúñ])", text))


def is_transfer_question(text: str) -> bool:
    t = (text or "").lower()
    # Procesos KB (retiro por fallecimiento) ≠ operación de retiro del canal
    if any(
        s in t
        for s in (
            "fallecid",
            "fallecimiento",
            "sucesor",
            "de cujus",
            "defuncion",
            "defunción",
        )
    ):
        return False
    return any(s in t for s in _TRANSFER_SIGNALS)


def is_generic_balance_question(text: str) -> bool:
    t = (text or "").lower()
    if any(s in t for s in _BALANCE_SPECIFIC_HINTS):
        return False
    # Moneda explícita → saldo específico (1 cuenta DOP/USD), no desambiguar genérico.
    if _currency_filter(t):
        return False
    # Con dígitos de producto no es genérico (p. ej. "saldo de la cuenta 1234").
    if re.search(r"\d{4,}", t):
        return False
    return any(s in t for s in _GENERIC_BALANCE_SIGNALS)


def asks_personal_debit_cards(text: str) -> bool:
    """True si el usuario pide sus tarjetas de débito (no catálogo del banco ni TC)."""
    t = (text or "").lower()
    if not any(s in t for s in ("tarjeta", "tarjetas")):
        return False
    # Producto crédito nombrado explícitamente → no es solo débito
    if any(
        s in t
        for s in (
            "tarjeta de credito",
            "tarjeta de crédito",
            "tarjetas de credito",
            "tarjetas de crédito",
        )
    ):
        return False
    return any(
        s in t
        for s in (
            "tarjeta de debito",
            "tarjeta de débito",
            "tarjetas de debito",
            "tarjetas de débito",
            "debito",
            "débito",
        )
    )


def is_multi_card_aggregate_question(text: str) -> bool:
    """Consulta que pide datos de varias tarjetas o compararlas (sin elegir una)."""
    t = (text or "").lower()
    if not any(s in t for s in ("tarjeta", "tarjetas", "visa", "mastercard")):
        return False
    return any(
        s in t
        for s in (
            "mis tarjetas",
            "todas mis",
            "todas las tarjetas",
            "en mis tarjetas",
            "de mis tarjetas",
            "cual de ellas",
            "cuál de ellas",
            "cuales de ellas",
            "cuáles de ellas",
            "cual tiene mas",
            "cuál tiene más",
            "cual tiene más",
            "cuál tiene mas",
            "cual tiene mayor",
            "cuál tiene mayor",
            "la que tiene mas",
            "la que tiene más",
            "que tarjeta tiene mas",
            "qué tarjeta tiene más",
            "entre mis tarjetas",
            "cuanto debo en mis",
            "cuánto debo en mis",
        )
    )


def _debit_cards_unavailable_message(display_name: str | None) -> str:
    greeting = f"{display_name}, " if display_name else ""
    return (
        f"{greeting}en tu portafolio no figuran **tarjetas de débito** como producto consultable "
        "(suelen estar ligadas a tus cuentas). "
        "Puedo darte el saldo de tus cuentas o, si te referías a **tarjetas de crédito**, "
        "pídemelo y te muestro el resumen de todas sin que tengas que elegir una."
    )


def is_card_field_question(text: str) -> bool:
    t = (text or "").lower()
    if any(s in t for s in ("prestamo", "préstamo", "deposito", "depósito", "certificado")):
        return False
    # Definiciones / catálogo de producto → FAQ/KB, no detalle de TC del cliente
    if any(
        s in t
        for s in (
            "qué es",
            "que es",
            "qué son",
            "que son",
            "significa",
            "definición",
            "definicion",
            "explícame",
            "explicame",
            "cuéntame",
            "cuentame",
            "háblame",
            "hablame",
            "información sobre",
            "informacion sobre",
            "explícame qué",
            "explicame que",
            "cuéntame sobre",
            "cuentame sobre",
            "háblame sobre",
            "hablame sobre",
            "explícame todo",
            "explicame todo",
            "cómo funciona",
            "como funciona",
            "requisito",
            "beneficios",
            "características",
            "caracteristicas",
            "dirigida",
            "diferencia",
            "conversión",
            "conversion",
            "internacional",
            "fuera del país",
            "fuera del pais",
        )
    ):
        return False
    # "tarjeta de débito/crédito X" como producto informativo (sin mi/saldo/disponible)
    # Excepción: nombre comercial específico (Visa Joven, Multicrédito…) → portafolio
    _named_card = any(
        s in t
        for s in (
            "joven",
            "multicredit",
            "multicrédito",
            "bravo",
            "clasica",
            "clásica",
            "pricesmart",
            "flotilla",
            "empleado",
        )
    )
    if any(s in t for s in ("mi tarjeta", "mis tarjetas")):
        return True
    if any(s in t for s in ("saldo", "disponible", "limite", "límite", "corte", "pago minimo", "pago mínimo")):
        pass  # sigue siendo field question si hay señal de campo
    elif (
        any(s in t for s in ("tarjeta de débito", "tarjeta de debito", "tarjeta de crédito", "tarjeta de credito"))
        and any(s in t for s in ("cuéntame", "cuentame", "qué", "que ", "sobre", "explícame", "explicame", "información", "informacion", "info "))
        and not _named_card
    ):
        return False
    if any(_contains_token(t, w) for w in _CARD_WORDS):
        return True
    return any(s in t for s in _CARD_FIELD_SIGNALS)


def is_dap_field_question(text: str) -> bool:
    t = (text or "").lower()
    if any(s in t for s in ("tarjeta", "visa", "prestamo", "préstamo", "cuota", "hipotec")):
        return False
    # Listado de portafolio ("dame mis certificados") ≠ campo de un DAP
    if any(
        s in t
        for s in (
            "dame mis",
            "dime mis",
            "mis certificados",
            "cuales son mis",
            "cuáles son mis",
            "qué certificados",
            "que certificados",
            "listado de mis",
        )
    ):
        return False
    # Glosario / definición → FAQ (no tasa del certificado personal)
    if any(
        s in t
        for s in (
            "qué es", "que es", "qué significa", "que significa",
            "definición", "definicion", "explícame", "explicame",
            "cuéntame", "cuentame", "háblame", "hablame",
            "información sobre", "informacion sobre",
        )
    ):
        return False
    # Corrección de contexto: "del deposito a plazo fue que te pregunte"
    if any(s in t for s in ("deposito", "depósito", "certificado", "dap", "cdt", "plazo")) and any(
        s in t
        for s in (
            "fue que te pregunt",
            "te pregunte",
            "te pregunté",
            "me referia",
            "me refería",
            "era del",
            "no la cuenta",
            "no el saldo",
            "no de la cuenta",
        )
    ):
        return True
    # Selección APK / card: DEPOSITO_PLAZO_5511 o "Depósito a plazo ···5511"
    if "deposito_plazo" in t or "depósito_plazo" in t:
        return True
    if re.search(r"(···|\.{2,}|…|••••|\*{4}|terminad)\s*\d{3,}", t) and any(
        s in t for s in ("deposito", "depósito", "certificado", "plazo", "dap", "cdt")
    ):
        return True
    # Dígitos + señal DAP (selección de un ítem del listado)
    if re.search(r"\d{3,}", t) and any(
        s in t for s in ("deposito", "depósito", "certificado", "dap", "cdt", "plazo")
    ):
        return True
    if not any(s in t for s in _DAP_FIELD_SIGNALS):
        return False
    # "cuál es mi tasa?" sin ancla de certificado/depósito → no monopolizar (préstamo/FAQ)
    if any(s in t for s in ("tasa", "interes", "interés")) and not any(
        s in t
        for s in (
            "deposito",
            "depósito",
            "certificado",
            "dap",
            "cdt",
            "plazo",
            "inversion",
            "inversión",
            "capitaliz",
            "modalidad",
            "metido",
            "metida",
        )
    ):
        other_dap = any(
            s in t for s in _DAP_FIELD_SIGNALS if s not in ("tasa", "interes", "interés")
        )
        if not other_dap:
            return False
    return True


_DIGIT_FOLLOWUP_RE = re.compile(
    r"(?is)^\s*(?:y\s+)?(?:del?|el|la|de\s+la|de\s+el|del\s+n[uú]mero)?\s*[#.]?\s*(\d{3,8})\s*\??\s*$"
)


def is_digit_followup_question(text: str) -> bool:
    """Follow-up corto tipo 'Y del 05809?' / 'del 5511'."""
    return bool(_DIGIT_FOLLOWUP_RE.match((text or "").strip()))


def apply_digit_followup_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved: Any | None = None,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Resuelve 'Y del 05809?' al producto correcto (prioriza DAP/préstamo/TC en foco)."""
    from genesis_cognitive.brain.security_secrets import scan_auth_secrets

    if snapshot is None or not is_digit_followup_question(raw_text):
        return None
    if scan_auth_secrets(raw_text).should_block_product_digit_match:
        return None

    m = _DIGIT_FOLLOWUP_RE.match((raw_text or "").strip())
    if not m:
        return None
    digits = m.group(1)

    from genesis_cognitive.context.product_display import display_label_in_context, filter_active
    from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
    from genesis_cognitive.router.final_response_agent import (
        build_card_detail_response,
        build_deposit_detail_response,
        build_loan_detail_response,
    )
    from genesis_cognitive.router.product_focus import dap_ref_from_session, focused_field_question

    active = filter_active(snapshot)
    hits = _find_text_candidates(digits, active)
    if not hits:
        # Match por sufijo en product_id / card_mask
        hits = []
        for p in active:
            pid = "".join(ch for ch in p.product_id if ch.isdigit())
            mask = "".join(ch for ch in str(p.card_mask or "") if ch.isdigit())
            if pid.endswith(digits) or digits in pid[-6:] or (mask and mask.endswith(digits[-4:])):
                hits.append(p)

    if not hits:
        return None

    # Preferir mismo tipo que el foco / last_resolved
    preferred_type = None
    lr_intent = getattr(last_resolved, "intent_id", None) if last_resolved else None
    if lr_intent == "TERM_DEPOSIT_DETAIL_READ" or dap_ref_from_session(session):
        preferred_type = "TERM_DEPOSIT"
    elif lr_intent == "LOAN_DETAIL_READ":
        preferred_type = "LOAN"
    elif lr_intent == "CREDIT_CARD_DETAIL_READ":
        preferred_type = "CREDIT_CARD"
    focus = getattr(session, "product_focus", None) if session is not None else None
    if focus is not None:
        kind = getattr(focus, "kind", None)
        if kind == "TERM_DEPOSIT":
            preferred_type = "TERM_DEPOSIT"
        elif kind == "LOAN":
            preferred_type = "LOAN"
        elif kind == "CARD":
            preferred_type = "CREDIT_CARD"

    if preferred_type:
        typed = [p for p in hits if p.product_type == preferred_type]
        if typed:
            hits = typed

    if len(hits) != 1:
        # Varios del mismo tipo → clarificar ese tipo
        if preferred_type == "TERM_DEPOSIT" and len(hits) >= 2:
            from genesis_cognitive.context.app_channel import (
                build_dap_disambiguation_question,
                build_product_options,
            )

            q = build_dap_disambiguation_question(hits)
            return (
                "CLARIFICATION_REQUIRED",
                [_dap_detail_action(None)],
                q,
                build_product_options(
                    hits,
                    question=focused_field_question(session) or raw_text,
                    snapshot=snapshot,
                ),
            )
        return None

    product = hits[0]
    field_q = focused_field_question(session) or (
        getattr(last_resolved, "original_question", None) if last_resolved else None
    ) or raw_text
    # Si la pregunta previa no es de campo útil, usar detalle completo
    field_l = (field_q or "").lower()
    if not any(
        s in field_l
        for s in (
            "tasa", "vence", "vencimiento", "interes", "interés", "saldo", "capital",
            "fecha", "monto", "disponible", "limite", "límite", "corte", "cuota",
        )
    ):
        field_q = "dame mas informacion"

    label = display_label_in_context(product, [p for p in active if p.product_type == product.product_type] or [product])
    if product.product_type == "TERM_DEPOSIT":
        text = build_deposit_detail_response(field_q, product, snapshot.display_name, label)
        return (
            "VALID_CONTRACT",
            [_dap_detail_action(product.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=product.product_id),
        )
    if product.product_type == "CREDIT_CARD":
        text = build_card_detail_response(field_q, product, snapshot.display_name, label)
        return (
            "VALID_CONTRACT",
            [_card_detail_action(product.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=product.product_id),
        )
    if product.product_type == "LOAN":
        loan = next((ln for ln in snapshot.loans if ln.product_id == product.product_id), None)
        if loan:
            text = build_loan_detail_response(field_q, loan.to_detail_dict(), snapshot.display_name)
            return (
                "VALID_CONTRACT",
                [{
                    "sequence": 1,
                    "intent_id": "LOAN_DETAIL_READ",
                    "capability_candidate": "LOAN_DETAIL",
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {"account_ref": product.product_id},
                    "missing_requirements": [],
                    "depends_on": [],
                    "confidence": 1.0,
                }],
                text,
                build_product_suggestions(snapshot, focus_product_id=product.product_id),
            )
    # Cuentas CA
    from genesis_cognitive.router.final_response_agent import _greeting

    bal = product.available_balance
    hello = _greeting(snapshot.display_name)
    text = (
        f"{hello}tu saldo disponible en {label} es de {bal} {product.currency}."
        if bal is not None
        else f"{hello}no tengo el saldo de {label} en este momento."
    )
    return "VALID_CONTRACT", [_balance_action(product.product_id)], text, None


def apply_dap_correction_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved: Any | None = None,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """'Del deposito a plazo fue que te pregunte' → reanudar DAP en foco con campo previo."""
    if snapshot is None:
        return None
    t = (raw_text or "").lower()
    if not any(s in t for s in ("deposito", "depósito", "certificado", "dap", "plazo")):
        return None
    if not any(
        s in t
        for s in (
            "fue que te pregunt",
            "te pregunte",
            "te pregunté",
            "me referia",
            "me refería",
            "era del deposito",
            "era del depósito",
            "no la cuenta",
            "no el saldo",
            "no de la cuenta",
        )
    ):
        return None

    from genesis_cognitive.context.product_display import display_label_in_context, filter_active_by_type
    from genesis_cognitive.router.final_response_agent import build_deposit_detail_response
    from genesis_cognitive.router.product_focus import dap_ref_from_session, focused_field_question

    daps = filter_active_by_type(snapshot, ("TERM_DEPOSIT",))
    if not daps:
        greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
        return "VALID_CONTRACT", [], f"{greeting}no tienes certificados de depósito activos.", None

    ref = dap_ref_from_session(session)
    if not ref and last_resolved and getattr(last_resolved, "intent_id", None) == "TERM_DEPOSIT_DETAIL_READ":
        ref = getattr(last_resolved, "account_ref", None)
    # Si last_resolved fue pisado por saldo, igual hay product_focus DAP
    dep = next((d for d in daps if d.product_id == ref), None) if ref else None
    if dep is None and len(daps) == 1:
        dep = daps[0]
    if dep is None:
        # Sin foco único → clarificar (no inventar)
        from genesis_cognitive.context.app_channel import (
            build_dap_disambiguation_question,
            build_product_options,
        )

        q = (
            f"{snapshot.display_name}, " if snapshot.display_name else ""
        ) + "entiendo, te refieres a un depósito a plazo. " + build_dap_disambiguation_question(daps)
        return (
            "CLARIFICATION_REQUIRED",
            [_dap_detail_action(None)],
            q,
            build_product_options(
                daps,
                question=focused_field_question(session) or raw_text,
                snapshot=snapshot,
            ),
        )

    field_q = focused_field_question(session) or "dame mas informacion"
    label = display_label_in_context(dep, daps)
    text = build_deposit_detail_response(field_q, dep, snapshot.display_name, label)
    return (
        "VALID_CONTRACT",
        [_dap_detail_action(dep.product_id)],
        text,
        build_product_suggestions(snapshot, focus_product_id=dep.product_id),
    )


def _is_card_only_balance_question(text: str, snapshot: CustomerContextSnapshot) -> bool:
    if filter_active_by_type(snapshot, _DEPOSIT_TYPES):
        return False
    if not filter_active_by_type(snapshot, ("CREDIT_CARD",)):
        return False
    t = (text or "").lower()
    return is_generic_balance_question(text) or any(s in t for s in _CARD_BALANCE_SIGNALS)


def is_movements_question(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in _MOVEMENTS_SIGNALS)


def is_currency_switch_question(text: str) -> bool:
    t = (text or "").lower()
    if any(s in t for s in ("revisa", "revisar", "mira", "mirar", "ahora el", "ahora la")):
        if any(s in t for s in ("dolares", "dólares", "usd", "us$", "pesos", "dop", "rd$")):
            return True
    return any(s in t for s in ("dolares", "dólares", "usd", "us$", "pesos", "dop", "rd$"))


def _card_detail_action(account_ref: str | None) -> dict:
    return {
        "sequence": 1,
        "intent_id": "CREDIT_CARD_DETAIL_READ",
        "capability_candidate": "CREDIT_CARD_DETAIL",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {
            "account_ref": account_ref,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": None,
        },
        "missing_requirements": [] if account_ref else ["account_ref"],
        "depends_on": [],
        "confidence": 1.0,
    }


def _multi_balance_action() -> dict:
    return {
        "sequence": 1,
        "intent_id": "ACCOUNT_BALANCE_READ",
        "capability_candidate": "ACCOUNT_BALANCE",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {
            "account_ref": None,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": None,
        },
        "missing_requirements": [],
        "depends_on": [],
        "confidence": 1.0,
    }


def _movements_action(account_ref: str | None) -> dict:
    return {
        "sequence": 1,
        "intent_id": "ACCOUNT_MOVEMENTS_READ",
        "capability_candidate": "ACCOUNT_MOVEMENTS",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {
            "account_ref": account_ref,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": None,
        },
        "missing_requirements": [] if account_ref else ["account_ref"],
        "depends_on": [],
        "confidence": 1.0,
    }


def apply_transfer_guardrail(
    status: str,
    actions: list[dict],
    raw_text: str,
) -> tuple[str, list[dict], str | None]:
    """Early UNSUPPORTED for transfer/mutation NL without LLM."""
    if not is_transfer_question(raw_text):
        return status, actions, None
    return "UNSUPPORTED", [], _MUTATION_UNSUPPORTED_MSG


def _balance_action(account_ref: str | None) -> dict:
    action = _multi_balance_action()
    action["detected_entities"] = {**action["detected_entities"], "account_ref": account_ref}
    action["missing_requirements"] = [] if account_ref else ["account_ref"]
    return action


def _deposit_type_filter(text: str) -> str | None:
    t = (text or "").lower()
    if "corriente" in t:
        return "CHECKING"
    if "ahorro" in t or "ahorros" in t:
        return "SAVINGS"
    if "nomina" in t or "nómina" in t:
        return "PAYROLL"
    return None


_TYPE_LABEL_PLURAL = {
    "CHECKING": "corrientes",
    "SAVINGS": "de ahorros",
    "PAYROLL": "de nómina",
}

_CURRENCY_LABEL = {
    "USD": "dólares",
    "DOP": "pesos dominicanos",
}


def _currency_filter(text: str) -> str | None:
    t = (text or "").lower()
    if any(s in t for s in ("dolares", "dólares", "usd", "us$", "dollar")):
        return "USD"
    if any(s in t for s in ("pesos", "dop", "rd$", "peso dominicano")):
        return "DOP"
    return None


def is_specific_deposit_balance_question(text: str) -> bool:
    """Saldo con tipo, dígitos o moneda (no genérico tipo 'dame el balance de la cuenta')."""
    if is_generic_balance_question(text):
        return False
    t = (text or "").lower()
    # Selección de préstamo/tarjeta no es consulta de depósito
    if any(s in t for s in ("prestamo", "préstamo", "tarjeta", "visa", "mastercard")):
        return False
    # Selección de opción APK/UI: "Cuenta de ahorro ···3641" / "terminada en 3641" / ref CUENTA_AHORRO_3641
    if re.search(r"\d{4,}", t) and any(
        s in t
        for s in (
            "cuenta", "ahorro", "ahorros", "corriente", "nómina", "nomina",
            "terminad", "cuenta_ahorro", "cuenta_corriente", "cuenta_nomina",
        )
    ):
        return True
    # Ellipsis de máscara solo si parece cuenta (evitar "Préstamo ...7615")
    if re.search(r"(···|\.{2,})\s*\d{4,}", t) and any(
        s in t for s in ("cuenta", "ahorro", "ahorros", "corriente", "nómina", "nomina")
    ):
        return True
    if not any(s in t for s in ("saldo", "balance", "cuanto", "cuánto", "tengo", "dime", "consulta", "revisa", "ahora")):
        return False
    if _deposit_type_filter(t):
        return True
    if re.search(r"\d{4,}", t):
        return True
    if _currency_filter(t):
        return True
    return False


def _balance_text_for_product(
    snapshot: CustomerContextSnapshot,
    product: Any,
    pool: list,
    *,
    session: Any | None = None,
) -> str:
    from genesis_cognitive.context.snapshot_freshness import annotate_portfolio_amount_text

    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    label = display_label_in_context(product, pool)
    bal = product.available_balance
    if bal is not None:
        text = f"{greeting}tu saldo disponible en {label} es de {bal} {product.currency}."
        return annotate_portfolio_amount_text(text, session=session)
    return f"{greeting}tu consulta de saldo para {label} está lista. El saldo se obtiene del Core."


def _multi_deposit_balance_text(
    snapshot: CustomerContextSnapshot,
    accounts: list[Any],
) -> str:
    """Matriz fila 9 — varias cuentas identificadas en un solo turno."""
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    chunks: list[str] = []
    for p in accounts:
        last4 = p.product_id[-4:] if len(p.product_id) >= 4 else p.product_id
        if p.product_type == "SAVINGS":
            label = f"Ahorros ••••{last4}"
        elif p.product_type == "CHECKING":
            label = f"Corriente ••••{last4}"
        elif p.product_type == "PAYROLL":
            label = f"Nómina ••••{last4}"
        else:
            label = f"{display_label_in_context(p, accounts)} ••••{last4}"
        cur = p.ledger_balance if p.ledger_balance is not None else p.available_balance
        avail = p.available_balance
        chunks.append(f"{label}: balance actual {cur} {p.currency}; disponible {avail} {p.currency}")
    return f"{greeting}{'. '.join(chunks)}."


def _card_last4(card: Any) -> str:
    mask = str(getattr(card, "card_mask", None) or "")
    digits = "".join(ch for ch in mask if ch.isdigit())
    if len(digits) >= 4:
        return digits[-4:]
    pid = str(getattr(card, "product_id", "") or "")
    return pid[-4:] if len(pid) >= 4 else pid


def _card_matches_hint(card: Any, hint: str) -> bool:
    if hint in (card.card_mask or ""):
        return True
    last4 = _card_last4(card)
    return hint.endswith(last4) or last4 == hint[-4:] or hint in str(card.product_id)


def _cards_for_hints(cards: list[Any], hints: list[str]) -> list[Any]:
    matched: list[Any] = []
    for card in cards:
        if any(_card_matches_hint(card, h) for h in hints):
            matched.append(card)
    return list({c.product_id: c for c in matched}.values())


def _product_not_found_message(
    snapshot: CustomerContextSnapshot | None,
    hint: str,
    *,
    kind: str = "cuenta",
) -> str:
    greeting = ""
    if snapshot is not None and snapshot.display_name:
        greeting = f"{snapshot.display_name}, "
    digits = "".join(ch for ch in hint if ch.isdigit())
    label = "préstamo" if kind in ("loan", "préstamo", "prestamo") else "cuenta"
    if len(digits) >= 4:
        mask = f"...{digits[-4:]}"
        return f"{greeting}el {label} {mask} que quieres consultar no existe en tu portafolio activo." if label == "préstamo" else f"{greeting}la {label} {mask} que quieres consultar no existe en tu portafolio activo."
    if hint and hint.strip():
        return f"{greeting}el {label} {hint.strip()} que quieres consultar no existe en tu portafolio activo." if label == "préstamo" else f"{greeting}la {label} {hint.strip()} que quieres consultar no existe en tu portafolio activo."
    return f"{greeting}no encontré el {label} que quieres consultar en tu portafolio activo." if label == "préstamo" else f"{greeting}no encontré la cuenta que quieres consultar en tu portafolio activo."


def apply_card_digits_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Resuelve tarjetas por últimos dígitos (Matriz filas 22, 24, 34)."""
    from genesis_cognitive.brain.security_secrets import scan_auth_secrets

    if snapshot is None:
        return None
    if scan_auth_secrets(raw_text).should_block_product_digit_match:
        return None
    hints = re.findall(r"\d{4,}", raw_text or "")
    if not hints:
        return None
    t = (raw_text or "").lower()
    if any(s in t for s in ("cuenta", "corriente", "ahorro", "ahorros", "nómina", "nomina")) and "tarjeta" not in t:
        return None
    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    if not cards:
        return None
    hits = _cards_for_hints(cards, hints)
    if len(hits) >= 2 and len(hits) == len(hints):
        greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
        parts = []
        for card in hits:
            last4 = _card_last4(card)
            avail = card.available_balance
            parts.append(f"TC ••••{last4}: saldo disponible {avail} {card.currency}")
        text = f"{greeting}{'. '.join(parts)}."
        return "VALID_CONTRACT", [_card_detail_action(None)], text, None
    if len(hits) == 1:
        card = hits[0]
        text = build_card_detail_response(
            raw_text, card, snapshot.display_name, display_label_in_context(card, cards),
        )
        return "VALID_CONTRACT", [_card_detail_action(card.product_id)], text, build_product_suggestions(
            snapshot, focus_product_id=card.product_id,
        )
    if any(s in t for s in ("tarjeta", "revisa", "revisar", "cambia")):
        greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
        return "VALID_CONTRACT", [_card_detail_action(None)], f"{greeting}no encontré esa tarjeta en tu portafolio activo.", None
    return None


def apply_specific_deposit_balance_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Saldo por tipo (corriente/ahorros), por dígitos o cuenta inexistente."""
    if snapshot is None or not is_specific_deposit_balance_question(raw_text):
        return None

    from genesis_cognitive.router.deposit_guardrail import _find_text_candidates

    text_lower = (raw_text or "").strip().lower()
    if any(s in text_lower for s in ("tarjeta", "visa", "mastercard", "pricesmart")):
        return None

    accounts = filter_active_by_type(snapshot, _DEPOSIT_TYPES)

    digit_hints = re.findall(r"\d{4,}", raw_text or "")
    # Matriz fila 9: varios dígitos = varias cuentas; no acotar a un solo tipo/moneda.
    multi_digit = len(digit_hints) >= 2

    type_filter = _deposit_type_filter(raw_text)
    if type_filter and not multi_digit:
        typed = [p for p in accounts if p.product_type == type_filter]
        if not typed:
            greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
            plural = _TYPE_LABEL_PLURAL.get(type_filter, "de ese tipo")
            msg = f"{greeting}no tienes cuentas {plural} activas en tu portafolio."
            return "VALID_CONTRACT", [_balance_action(None)], msg, None
        accounts = typed

    currency_filter = _currency_filter(raw_text)
    if currency_filter and not multi_digit:
        in_ccy = [p for p in accounts if p.currency == currency_filter]
        if not in_ccy:
            greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
            ccy_label = _CURRENCY_LABEL.get(currency_filter, currency_filter)
            msg = f"{greeting}no tienes cuentas activas en {ccy_label} en tu portafolio."
            return "VALID_CONTRACT", [_balance_action(None)], msg, None
        accounts = in_ccy

    if digit_hints:
        matched: list[Any] = []
        unmatched: list[str] = []
        for hint in digit_hints:
            hits = [
                p for p in accounts
                if hint in p.product_id or p.product_id.endswith(hint)
            ]
            if hits:
                matched.extend(hits)
            else:
                unmatched.append(hint)
        if unmatched and not matched:
            cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
            card_hits = _cards_for_hints(cards, unmatched)
            if card_hits:
                return None
            return (
                "VALID_CONTRACT",
                [_balance_action(None)],
                _product_not_found_message(snapshot, unmatched[0]),
                None,
            )
        if matched:
            unique = list({p.product_id: p for p in matched}.values())
            if len(unique) >= 2 and not unmatched:
                text = _multi_deposit_balance_text(snapshot, unique)
                return (
                    "VALID_CONTRACT",
                    [_multi_balance_action()],
                    text,
                    build_product_suggestions(snapshot),
                )
            if len(unique) == 1:
                p = unique[0]
                return (
                    "VALID_CONTRACT",
                    [_balance_action(p.product_id)],
                    _balance_text_for_product(snapshot, p, accounts),
                    build_product_suggestions(snapshot, focus_product_id=p.product_id),
                )
            q = build_account_disambiguation_question(unique)
            return "CLARIFICATION_REQUIRED", [_balance_action(None)], q, None

    if not digit_hints and (type_filter or currency_filter):
        if len(accounts) >= 2:
            q = build_account_disambiguation_question(accounts)
            return "CLARIFICATION_REQUIRED", [_balance_action(None)], q, None
        if len(accounts) == 1:
            p = accounts[0]
            return (
                "VALID_CONTRACT",
                [_balance_action(p.product_id)],
                _balance_text_for_product(snapshot, p, accounts),
                build_product_suggestions(snapshot, focus_product_id=p.product_id),
            )

    candidates = _find_text_candidates(text_lower, accounts)
    if len(candidates) == 1:
        p = candidates[0]
        return (
            "VALID_CONTRACT",
            [_balance_action(p.product_id)],
            _balance_text_for_product(snapshot, p, accounts),
            build_product_suggestions(snapshot, focus_product_id=p.product_id),
        )

    return None


def apply_generic_balance_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None]:
    """List all deposit balances when the user asks generically."""
    if snapshot is None or not is_generic_balance_question(raw_text):
        return status, actions, None, None

    accounts = filter_active_by_type(snapshot, _DEPOSIT_TYPES)
    if not accounts:
        cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
        if len(cards) >= 2 and _is_card_only_balance_question(raw_text, snapshot):
            q = build_card_disambiguation_question(cards)
            return "CLARIFICATION_REQUIRED", [_card_detail_action(None)], q, None
        if len(cards) == 1 and _is_card_only_balance_question(raw_text, snapshot):
            card = cards[0]
            text = build_card_detail_response(
                raw_text, card, snapshot.display_name, display_label_in_context(card, cards),
            )
            return "VALID_CONTRACT", [_card_detail_action(card.product_id)], text, None
        return status, actions, None, None

    # Si el usuario ya dijo la moneda y hay exactamente una cuenta, responder saldo.
    currency_filter = _currency_filter(raw_text)
    if currency_filter:
        in_ccy = [p for p in accounts if p.currency == currency_filter]
        if len(in_ccy) == 1:
            acct = in_ccy[0]
            return (
                "VALID_CONTRACT",
                [_balance_action(acct.product_id)],
                _balance_text_for_product(snapshot, acct, accounts),
                build_product_suggestions(snapshot, focus_product_id=acct.product_id),
            )
        if len(in_ccy) >= 2:
            accounts = in_ccy
        elif not in_ccy:
            greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
            ccy_label = _CURRENCY_LABEL.get(currency_filter, currency_filter)
            msg = f"{greeting}no tienes cuentas activas en {ccy_label} en tu portafolio."
            return "VALID_CONTRACT", [_balance_action(None)], msg, None

    if len(accounts) == 1:
        acct = accounts[0]
        label = display_label_in_context(acct, accounts)
        t = (raw_text or "").lower()
        wants_current = any(
            s in t for s in ("saldo actual", "balance actual", "saldo contable", "ledger")
        )
        if wants_current:
            bal = acct.ledger_balance if acct.ledger_balance is not None else None
            label_field = "saldo actual"
        else:
            bal = acct.available_balance
            label_field = "saldo disponible"
        greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
        if bal is not None:
            text = f"{greeting}tu {label_field} en {label} es de {bal} {acct.currency}."
        else:
            text = (
                f"{greeting}el {label_field} de {label} no está disponible en el contexto "
                "actual (dato ausente, no cero)."
            )
        suggestions = build_product_suggestions(snapshot, focus_product_id=acct.product_id)
        return (
            "VALID_CONTRACT",
            [{
                **_multi_balance_action(),
                "detected_entities": {**_multi_balance_action()["detected_entities"], "account_ref": acct.product_id},
            }],
            text,
            suggestions,
        )

    q = build_account_disambiguation_question(accounts)
    return "CLARIFICATION_REQUIRED", [_balance_action(None)], q, None


def _dap_detail_action(account_ref: str | None) -> dict:
    return {
        "sequence": 1,
        "intent_id": "TERM_DEPOSIT_DETAIL_READ",
        "capability_candidate": "TERM_DEPOSIT_DETAIL",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {
            "account_ref": account_ref,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": None,
        },
        "missing_requirements": [] if account_ref else ["account_ref"],
        "depends_on": [],
        "confidence": 1.0,
    }


def apply_dap_field_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved_ref: str | None = None,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None]:
    if snapshot is None or not is_dap_field_question(raw_text):
        return status, actions, None, None

    daps = filter_active_by_type(snapshot, ("TERM_DEPOSIT",))
    if not daps:
        from genesis_cognitive.context.response_formatting import no_product_with_cta

        msg = no_product_with_cta(
            snapshot.display_name,
            "depósitos a plazo (certificados) activos",
        )
        return "VALID_CONTRACT", [], msg, None

    from genesis_cognitive.context.product_display import display_label_in_context
    from genesis_cognitive.router.deposit_guardrail import _find_text_candidates
    from genesis_cognitive.router.final_response_agent import build_deposit_detail_response
    from genesis_cognitive.router.product_focus import (
        dap_ref_from_session,
        focused_field_question,
        pending_field_question_for_selection,
    )

    # Corrección de contexto: responder con el campo previo del DAP en foco
    t_l = (raw_text or "").lower()
    is_correction = any(
        s in t_l
        for s in (
            "fue que te pregunt",
            "te pregunte",
            "te pregunté",
            "me referia",
            "me refería",
            "no la cuenta",
            "no el saldo",
            "no de la cuenta",
        )
    )
    field_q = raw_text
    # Card APK tras clarificación de tasa/vence → usar pregunta original
    pending_oq = pending_field_question_for_selection(session, raw_text)
    if pending_oq:
        field_q = pending_oq
    elif is_correction:
        field_q = focused_field_question(session) or "dame mas informacion"
    else:
        # "y mi depósito a plazo" tras un saldo → mismo campo, otro producto
        prev = (focused_field_question(session) or "").lower()
        mine = any(s in t_l for s in ("y mi ", "mi deposito", "mi depósito", "mis certificados", "mi certificado"))
        if mine and any(s in prev for s in ("saldo", "balance", "disponible")):
            if not any(s in t_l for s in ("tasa", "vence", "interes", "interés", "apertura")):
                field_q = f"saldo {raw_text}"


    # Selección por dígitos / card / ref (ej. "Certificado de Depósito - 5511")
    text_lower = (raw_text or "").strip().lower()
    hits = _find_text_candidates(text_lower, daps)
    if len(hits) == 1:
        dep = hits[0]
        text = build_deposit_detail_response(
            field_q, dep, snapshot.display_name, display_label_in_context(dep, daps),
        )
        return (
            "VALID_CONTRACT",
            [_dap_detail_action(dep.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=dep.product_id),
        )

    if len(daps) == 1:
        dep = daps[0]
        text = build_deposit_detail_response(
            field_q, dep, snapshot.display_name, display_label_in_context(dep, daps),
        )
        return (
            "VALID_CONTRACT",
            [_dap_detail_action(dep.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=dep.product_id),
        )

    resolved_ref = last_resolved_ref or dap_ref_from_session(session)
    if resolved_ref and any(d.product_id == resolved_ref for d in daps):
        dep = next(d for d in daps if d.product_id == resolved_ref)
        text = build_deposit_detail_response(
            field_q, dep, snapshot.display_name, display_label_in_context(dep, daps),
        )
        return (
            "VALID_CONTRACT",
            [_dap_detail_action(dep.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=dep.product_id),
        )

    q = build_dap_disambiguation_question(daps)
    from genesis_cognitive.context.app_channel import build_product_options

    opts = build_product_options(daps, question=field_q, snapshot=snapshot)
    return "CLARIFICATION_REQUIRED", [_dap_detail_action(None)], q, opts or build_product_suggestions(snapshot)


def apply_card_field_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved_ref: str | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None]:
    if snapshot is None:
        return status, actions, None, None
    if is_ambiguous_product_noun_question(raw_text):
        return status, actions, None, None
    if is_bank_card_catalog_question(raw_text) or is_bank_catalog_question(raw_text):
        return status, actions, None, None
    if not is_card_field_question(raw_text) and not _is_card_only_balance_question(raw_text, snapshot):
        return status, actions, None, None

    # Débito personal: Core solo expone TC; no ofrecer crédito ni forzar elección
    if asks_personal_debit_cards(raw_text):
        return (
            "VALID_CONTRACT",
            [],
            _debit_cards_unavailable_message(snapshot.display_name),
            None,
        )

    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    if not cards:
        greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
        if "limite" in raw_text.lower() or "límite" in raw_text.lower():
            msg = (
                f"{greeting}no tienes tarjetas activas. ¿Te refieres al límite de alguna cuenta "
                f"o a otra consulta?"
            )
        else:
            from genesis_cognitive.context.response_formatting import no_product_with_cta

            msg = no_product_with_cta(
                snapshot.display_name,
                "tarjetas de crédito activas",
            )
        return "VALID_CONTRACT", [], msg, None

    if len(cards) == 1:
        card = cards[0]
        text = build_card_detail_response(raw_text, card, snapshot.display_name, display_label_in_context(card, cards))
        return "VALID_CONTRACT", [_card_detail_action(card.product_id)], text, build_product_suggestions(snapshot, focus_product_id=card.product_id)

    # Varias TC + pregunta agregada/comparativa → resumen de todas
    if is_multi_card_aggregate_question(raw_text):
        text = build_multi_card_aggregate_response(raw_text, list(cards), snapshot.display_name)
        return "VALID_CONTRACT", [_card_detail_action(None)], text, None

    # Match explícito (dígitos / nombre) ANTES de last_resolved — evita “Visa Joven” → Multicrédito en foco
    digit_hints = re.findall(r"\d{4,}", raw_text or "")
    if digit_hints:
        hits = _cards_for_hints(cards, digit_hints)
        if len(hits) == 1:
            card = hits[0]
            text = build_card_detail_response(
                raw_text, card, snapshot.display_name, display_label_in_context(card, cards),
            )
            return "VALID_CONTRACT", [_card_detail_action(card.product_id)], text, None
        if len(hits) >= 2:
            q = build_card_disambiguation_question(hits)
            return "CLARIFICATION_REQUIRED", [_card_detail_action(None)], q, None
        if any(_contains_token(raw_text.lower(), w) for w in _CARD_WORDS):
            greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
            msg = f"{greeting}no encontré esa tarjeta en tu portafolio activo."
            return "VALID_CONTRACT", [_card_detail_action(None)], msg, None

    t = raw_text.lower()
    from genesis_cognitive.router.deposit_guardrail import _find_text_candidates

    name_hits = _find_text_candidates(t, cards)
    if len(name_hits) == 1:
        card = name_hits[0]
        text = build_card_detail_response(
            raw_text, card, snapshot.display_name, display_label_in_context(card, cards),
        )
        return (
            "VALID_CONTRACT",
            [_card_detail_action(card.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=card.product_id),
        )

    if last_resolved_ref and any(c.product_id == last_resolved_ref for c in cards):
        card = next(c for c in cards if c.product_id == last_resolved_ref)
        text = build_card_detail_response(raw_text, card, snapshot.display_name, display_label_in_context(card, cards))
        return "VALID_CONTRACT", [_card_detail_action(card.product_id)], text, None

    if any(_contains_token(t, w) for w in ("visa", "mastercard", "pricesmart")) and len(cards) >= 2:
        brand = next(w for w in ("visa", "mastercard", "pricesmart") if _contains_token(t, w))
        brand_hits = [c for c in cards if brand in (c.alias or "").lower() or brand in (c.product_id or "").lower()]
        if len(brand_hits) == 1:
            card = brand_hits[0]
            text = build_card_detail_response(
                raw_text, card, snapshot.display_name, display_label_in_context(card, cards),
            )
            return "VALID_CONTRACT", [_card_detail_action(card.product_id)], text, None

    question = build_card_disambiguation_question(cards)
    from genesis_cognitive.context.app_channel import build_product_options

    opts = build_product_options(cards)
    return "CLARIFICATION_REQUIRED", [_card_detail_action(None)], question, opts


def apply_movements_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved_ref: str | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None]:
    if snapshot is None or not is_movements_question(raw_text):
        return status, actions, None, None

    t = raw_text.lower()
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""

    if any(s in t for s in ("prestamo", "préstamo")):
        loans = filter_active_by_type(snapshot, ("LOAN",))
        if len(loans) == 1:
            loan = next((ln for ln in snapshot.loans if ln.product_id == loans[0].product_id), None)
            if loan:
                text = build_loan_detail_response(raw_text, loan.to_detail_dict(), snapshot.display_name)
                return "VALID_CONTRACT", [{
                    "sequence": 1,
                    "intent_id": "LOAN_DETAIL_READ",
                    "capability_candidate": "LOAN_DETAIL",
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {"account_ref": loans[0].product_id},
                    "missing_requirements": [],
                    "depends_on": [],
                    "confidence": 1.0,
                }], text, None
        if len(loans) >= 2:
            q = build_loan_disambiguation_question(loans)
            return "CLARIFICATION_REQUIRED", [_movements_action(None)], q, None

    accounts = filter_active_by_type(snapshot, _DEPOSIT_TYPES)
    if len(accounts) == 1:
        text = f"{greeting}Ese dato no está disponible en este momento. No recibí el historial de movimientos de tu cuenta."
        return "VALID_CONTRACT", [_movements_action(accounts[0].product_id)], text, None

    if last_resolved_ref:
        prod = next((p for p in snapshot.products if p.product_id == last_resolved_ref), None)
        if prod and prod.product_type in _DEPOSIT_TYPES:
            text = f"{greeting}Ese dato no está disponible en este momento. No recibí el historial de movimientos."
            return "VALID_CONTRACT", [_movements_action(last_resolved_ref)], text, None

    if len(accounts) >= 2:
        from genesis_cognitive.context.product_display import build_clarification_accounts
        q = f"¿De qué cuenta deseas ver los movimientos? {build_clarification_accounts(accounts)}"
        return "CLARIFICATION_REQUIRED", [_movements_action(None)], q, None

    text = f"{greeting}Ese dato no está disponible en este momento. No recibí el historial de movimientos."
    return "VALID_CONTRACT", [_movements_action(None)], text, None


def apply_currency_switch_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_intent: str | None,
    last_ref: str | None,
    *,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None] | None:
    """Follow-up: 'revisa el de dólares' / 'ahora la de pesos' after a balance read."""
    if snapshot is None or last_intent != "ACCOUNT_BALANCE_READ" or not is_currency_switch_question(raw_text):
        return None

    from genesis_cognitive.brain.continuity import resolve_product_reference
    from genesis_cognitive.context.snapshot_freshness import annotate_portfolio_amount_text

    # Reutilizar resolución central (moneda / campo) para no divergir de continuity.py
    resolved = resolve_product_reference(raw_text, snapshot, session)
    if resolved is None:
        return None
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""

    if resolved.missing:
        text = f"{greeting}no encuentro un producto activo con esa referencia en tu portafolio."
        return "VALID_CONTRACT", [_multi_balance_action()], text
    if resolved.ambiguous:
        pool = [
            p for p in filter_active_by_type(snapshot, _DEPOSIT_TYPES)
            if p.product_id in resolved.candidates
        ] or filter_active_by_type(snapshot, _DEPOSIT_TYPES)
        q = build_account_disambiguation_question(pool)
        return "CLARIFICATION_REQUIRED", [_multi_balance_action()], q
    if not resolved.product_id:
        return None

    acct = next((p for p in snapshot.products if p.product_id == resolved.product_id), None)
    if acct is None:
        text = f"{greeting}no encuentro esa cuenta en tu portafolio."
        return "VALID_CONTRACT", [_multi_balance_action()], text

    accounts = filter_active_by_type(snapshot, _DEPOSIT_TYPES)
    label = display_label_in_context(acct, accounts)
    field = resolved.field
    if field == "balance":
        bal = acct.ledger_balance if acct.ledger_balance is not None else acct.available_balance
        label_field = "saldo actual"
    else:
        bal = acct.available_balance
        label_field = "saldo disponible"

    if bal is not None:
        text = f"{greeting}tu {label_field} en {label} es de {bal} {acct.currency}."
    else:
        text = (
            f"{greeting}el {label_field} de {label} no está disponible en el contexto "
            "actual (dato ausente, no cero)."
        )
    text = annotate_portfolio_amount_text(text, session=session)
    return (
        "VALID_CONTRACT",
        [{
            **_multi_balance_action(),
            "detected_entities": {
                **_multi_balance_action()["detected_entities"],
                "account_ref": acct.product_id,
            },
        }],
        text,
    )


def override_non_operational(
    status: str,
    raw_text: str,
) -> str:
    """Re-route obvious product questions misclassified as greetings."""
    if status != "NON_OPERATIONAL":
        return status
    if (
        is_generic_balance_question(raw_text)
        or is_portfolio_list_question(raw_text)
        or is_card_field_question(raw_text)
        or is_movements_question(raw_text)
        or is_transfer_question(raw_text)
        or is_loan_fastpath_question(raw_text)
    ):
        return "VALID_CONTRACT"
    return status


# ── Saludos / préstamos / fast-path unificado ──────────────────────────────

_GREETING_SIGNALS = (
    "hola",
    "buenos días",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "hey",
    "saludos",
    "buen día",
    "buen dia",
    "qué tal",
    "que tal",
)

_PORTFOLIO_SIGNALS = (
    "qué productos",
    "que productos",
    "mis productos",
    "mi portafolio",
    "qué cuentas tengo",
    "que cuentas tengo",
    "qué tarjetas tengo",
    "que tarjetas tengo",
    "lista de productos",
    "listado de productos",
    "listado de mis productos",
    "listaddo de mis productos",  # typo frecuente
    "dame el listado",
    "dame el lista",
    "dime el listado",
    "dime el lista",
    "dame mis productos",
    "ver mis productos",
    "información sobre mis productos",
    "informacion sobre mis productos",
    "info sobre mis productos",
    "información de mis productos",
    "informacion de mis productos",
    "dame información sobre mis productos",
    "dame informacion sobre mis productos",
    "dame informacion de mis productos",
    "dame información de mis productos",
    "dime informacion de mis productos",
    "dime información de mis productos",
    # RD: certificado de depósito = depósito a plazo / CDT / DAP
    "mis certificados",
    "mi certificado",
    "dame mis certificados",
    "dime mis certificados",
    "cuales son mis certificados",
    "cuáles son mis certificados",
    "listame mis certificados",
    "listar mis certificados",
    "certificados de deposito",
    "certificados de depósito",
    "mi certificado de deposito",
    "mi certificado de depósito",
    "mis cdt",
    "mis dap",
    "mis depositos a plazo",
    "mis depósitos a plazo",
    "dame mis depositos",
    "dame mis depósitos",
)


def is_bank_catalog_question(text: str) -> bool:
    """Catálogo / oferta del banco (no portafolio personal del cliente)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    # Posesivo personal → portafolio, no catálogo
    if any(
        s in t
        for s in (
            "mis productos",
            "mi portafolio",
            "mis cuentas",
            "mis tarjetas",
            "mis certificados",
            "mis depositos",
            "mis depósitos",
            "que tengo",
            "qué tengo",
            "dame mis",
            "listame mis",
            "listar mis",
        )
    ):
        return False
    # Catálogo específico de tarjetas del banco
    if any(s in t for s in ("tarjeta", "tarjetas", "visa", "mastercard")) and any(
        s in t
        for s in (
            "tiene el banco",
            "tiene banco",
            "ofrece el banco",
            "ofrece banco",
            "puedo solicitar",
            "puedo contratar",
            "puedo adquirir",
            "productos de tarjeta",
            "productos de tarjetas",
            "tipos de tarjeta",
            "tipos de tarjetas",
            "cuales tarjetas",
            "cuáles tarjetas",
            "que tarjetas tiene",
            "qué tarjetas tiene",
        )
    ):
        return True
    return any(
        s in t
        for s in (
            "tiene el banco",
            "tiene banco santa",
            "tiene bsc",
            "ofrece el banco",
            "ofrece banco",
            "productos del banco",
            "cuentas del banco",
            "productos que tiene",
            "cuentas que tiene",
            "productos que ofrece",
            "cuentas que ofrece",
            "puedo solicitar",
            "puedo contratar",
            "puedo adquirir",
            "puedo abrir",
            "catalogo de productos",
            "catálogo de productos",
            "tipos de productos",
            "tipos de cuenta",
            "que productos puedo",
            "qué productos puedo",
            "cuales son los productos del",
            "cuáles son los productos del",
            "cuales cuentas tiene",
            "cuáles cuentas tiene",
            "cuales son las cuentas del",
            "cuáles son las cuentas del",
        )
    )


def is_bank_card_catalog_question(text: str) -> bool:
    """Catálogo de tarjetas del banco (no 'todos los productos' ni portafolio personal)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(s in t for s in ("mis tarjetas", "mi tarjeta", "dame mis tarjetas", "qué tarjetas tengo", "que tarjetas tengo")):
        return False
    has_card = any(
        s in t
        for s in (
            "tarjeta", "tarjetas", "visa", "mastercard",
            "débito", "debito", "crédito", "credito",
        )
    )
    if not has_card:
        return False
    # Info de UNA tarjeta nombrada (Visa Joven…) ≠ catálogo del banco
    if any(
        s in t
        for s in (
            "joven",
            "multicredit",
            "multicrédito",
            "bravo",
            "clasica",
            "clásica",
            "pricesmart",
            "flotilla",
            "empresarial",
            "mi tarjeta",
            "mis tarjetas",
            "conversión",
            "conversion",
            "internacional",
            "cómo funciona",
            "como funciona",
        )
    ):
        return False
    return any(
        s in t
        for s in (
            "tiene el banco",
            "tiene banco",
            "ofrece el banco",
            "ofrece banco",
            "del banco",
            "puedo solicitar",
            "puedo contratar",
            "puedo adquirir",
            "productos de tarjeta",
            "productos de tarjetas",
            "tipos de tarjeta",
            "tipos de tarjetas",
            "cuales tarjetas",
            "cuáles tarjetas",
            "que tarjetas",
            "qué tarjetas",
            "tarjetas de debito",
            "tarjetas de débito",
            "tarjetas de credito",
            "tarjetas de crédito",
            "información de las tarjetas",
            "informacion de las tarjetas",
            "info de las tarjetas",
        )
    )


def is_affirmation(text: str) -> bool:
    t = re.sub(r"[¿?¡!.,;:]+", "", (text or "").strip().lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t in {
        "si", "sí", "ok", "okey", "dale", "claro", "yes",
        "si por favor", "sí por favor", "por favor",
        "listalos", "listame", "listame", "si listame", "sí listame",
        "si listalos", "sí listalos",
    }


def apply_affirmation_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """'Sí' confirma la última oferta (p. ej. listar certificados), no el saldo previo."""
    if snapshot is None or not is_affirmation(raw_text):
        return None

    pending = getattr(session, "pending_action", None) if session is not None else None
    topic = ""
    suggested = ""
    if pending is not None:
        topic = str((getattr(pending, "detected_entities", None) or {}).get("knowledge_topic") or "")
        suggested = str(getattr(pending, "suggested_question", "") or "")
    last_kb = str(getattr(session, "last_knowledge_topic", "") or "") if session is not None else ""
    blob = f"{topic} {suggested} {last_kb}".lower()
    if not any(s in blob for s in ("kb_ambiguity", "certificado", "deposito a plazo", "depósito a plazo", "dap")):
        return None

    prev = ""
    if session is not None:
        from genesis_cognitive.router.product_focus import focused_field_question
        prev = (focused_field_question(session) or "").lower()
    q = "saldo de mi deposito a plazo" if any(s in prev for s in ("saldo", "balance", "disponible")) else "dame mis certificados"
    return apply_dap_field_guardrail("VALID_CONTRACT", [], snapshot, q, session=session)


def is_ambiguous_product_noun_question(text: str) -> bool:
    """Nombre de producto solo (ej. CUENTAS CORRIENTES) sin verbo → aclarar definición vs portafolio."""
    t = (text or "").strip().lower()
    t = re.sub(r"[¿?¡!.,;:]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t) > 40:
        return False
    if any(s in t for s in ("qué es", "que es", "significa", "definición", "definicion", "mi ", "mis ", "saldo", "tengo", "contratar", "proceso")):
        return False
    bare = (
        "cuentas corrientes",
        "cuenta corriente",
        "cuentas de ahorro",
        "cuenta de ahorro",
        "cuentas de ahorros",
        "tarjetas de credito",
        "tarjetas de crédito",
        "tarjetas de debito",
        "tarjetas de débito",
        "credito diferido",
        "crédito diferido",
        "multicredito",
        "multicrédito",
        "depositos a plazo",
        "depósitos a plazo",
        "certificados",
    )
    return t in bare


def apply_kb_knowledge_ambiguity_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Ambigüedad KB (certificado inversión vs garantía préstamo, etc.)."""
    from genesis_cognitive.rag.foundry_kb_agent import build_knowledge_ambiguity_clarification
    from genesis_cognitive.router.product_focus import looks_like_product_option_selection

    t = (raw_text or "").strip()
    low = t.lower()
    # Si ya pregunta "qué es" + certificado, dejar que FAQ/Foundry definan (no bloquear)
    if re.search(r"\b(que es|qué es|definicion|definición)\b", low):
        return None
    # Selección de card APK / id de producto personal → no glosario
    if (
        looks_like_product_option_selection(t)
        or "deposito_plazo" in low
        or bool(re.search(r"(···|\.{2,}|…|\*{3,}|••••)\s*\d{3,}", low))
    ):
        return None
    name = snapshot.display_name if snapshot else None
    clarify = build_knowledge_ambiguity_clarification(t, name)
    if not clarify:
        return None
    action = {
        "sequence": 1,
        "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
        "capability_candidate": "BUSINESS_KNOWLEDGE",
        "selected_route": "BUSINESS_RAG",
        "detected_entities": {"account_ref": None, "knowledge_topic": "KB_AMBIGUITY"},
        "missing_requirements": ["knowledge_topic"],
        "depends_on": [],
        "confidence": 1.0,
    }
    return "CLARIFICATION_REQUIRED", [action], clarify, None


def apply_ambiguous_product_noun_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    if snapshot is None or not is_ambiguous_product_noun_question(raw_text):
        return None
    t = (raw_text or "").strip().lower()
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    if "corriente" in t:
        q = (
            f"{greeting}¿Quieres saber **qué es** una cuenta corriente, "
            "o consultar si **tienes** cuentas corrientes en tu portafolio?"
        )
        topic = "cuenta corriente"
    elif "ahorro" in t:
        q = (
            f"{greeting}¿Quieres la definición de cuenta de ahorro, "
            "o ver las cuentas de ahorro de tu portafolio?"
        )
        topic = "cuenta de ahorro"
    elif "debito" in t or "débito" in t:
        q = (
            f"{greeting}¿Quieres conocer las **tarjetas de débito que ofrece el banco**, "
            "o consultar **tus** tarjetas?"
        )
        topic = "tarjeta de debito"
    elif "credito" in t or "crédito" in t or "multicredit" in t:
        # Cancelación / requisitos / cargos del producto KB → no ambigüedad personal
        if any(
            s in t
            for s in (
                "cancel", "requisito", "cargo", "comision", "comisión",
                "consumo", "avance", "efectivo", "cómo lo", "como lo",
                "definición", "definicion", "qué es", "que es", "explícame", "explicame",
            )
        ):
            return None
        q = (
            f"{greeting}¿Quieres información del producto (definición/condiciones) "
            "o consultar un producto de tu portafolio?"
        )
        topic = "credito"
    else:
        q = (
            f"{greeting}¿Quieres la definición del producto según la información del banco, "
            "o consultar ese producto en tu portafolio?"
        )
        topic = "producto"
    action = {
        "sequence": 1,
        "intent_id": "AMBIGUOUS_PRODUCT_SCOPE",
        "capability_candidate": "BUSINESS_KNOWLEDGE",
        "selected_route": "BUSINESS_RAG",
        "detected_entities": {"account_ref": None, "knowledge_topic": topic},
        "missing_requirements": ["query_scope"],
        "depends_on": [],
        "confidence": 1.0,
    }
    return "CLARIFICATION_REQUIRED", [action], q, None


def is_greeting_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or len(t) > 50:
        return False
    if not any(g in t for g in _GREETING_SIGNALS):
        return False
    # Si también pide productos/saldo/etc., no tratarlo como saludo puro.
    if (
        is_portfolio_list_question(t)
        or is_generic_balance_question(t)
        or is_card_field_question(t)
        or is_movements_question(t)
        or is_transfer_question(t)
        or is_loan_fastpath_question(t)
    ):
        return False
    return True


def is_portfolio_list_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    # Catálogo institucional del banco ≠ listado del portafolio personal
    if is_bank_catalog_question(t):
        return False
    # Catálogo / contratar (no es "mis" productos del portafolio)
    catalog = any(
        s in t
        for s in (
            "puedo solicitar",
            "puedo contratar",
            "puedo adquirir",
            "puedo abrir",
            "ofrece el banco",
            "productos del banco",
            "tiene el banco",
            "cuentas del banco",
            "productos que tiene",
            "cuentas que tiene",
        )
    )
    mine = any(
        s in t
        for s in (
            "mis productos",
            "mi portafolio",
            "mis certificados",
            "mis depositos",
            "mis depósitos",
            "listado de mis",
            "listame mis",
            "listar mis",
            "que tengo",
            "qué tengo",
            "dame mis",
        )
    )
    if catalog and not mine:
        return False
    if ("listame" in t or "listar" in t) and (
        "producto" in t or "certificado" in t or "deposito" in t or "depósito" in t
    ):
        return True
    return any(s in t for s in _PORTFOLIO_SIGNALS)


def is_loan_fastpath_question(text: str) -> bool:
    from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question
    return is_loan_field_question(text)


def apply_greeting_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    if snapshot is None or not is_greeting_question(raw_text):
        return None
    name = snapshot.display_name or "Cliente"
    return "NON_OPERATIONAL", [], f"¡Hola, {name}! ¿En qué puedo ayudarte?", None


def apply_portfolio_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    if snapshot is None or not is_portfolio_list_question(raw_text):
        return None
    from genesis_cognitive.context.product_display import (
        build_portfolio_listing,
        display_label_in_context,
        filter_active,
    )
    from genesis_cognitive.context.response_formatting import build_rich_deposit_detail

    t = (raw_text or "").strip().lower()
    # Selección específica (dígitos / card APK) → no listar todo; deja pasar a DAP/card guardrail
    if re.search(r"\d{3,}", t) and not any(
        s in t
        for s in (
            "mis certificados",
            "mis depositos",
            "mis depósitos",
            "qué depósitos",
            "que depositos",
            "listame",
            "listar",
            "cuales son mis",
            "cuáles son mis",
            "dame mis",
        )
    ):
        return None

    active = filter_active(snapshot)
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""

    # Familia específica: certificados / DAP (RD)
    if any(
        s in t
        for s in (
            "certificado",
            "cdt",
            "dap",
            "deposito a plazo",
            "depósito a plazo",
            "mis depositos",
            "mis depósitos",
        )
    ) and not any(s in t for s in ("producto", "portafolio", "tarjeta", "prestamo", "préstamo", "cuenta")):
        deps = [p for p in active if p.product_type == "TERM_DEPOSIT"]
        if deps:
            # Varios DAP: resumen + pedir selección (options APK) en lugar de volcar todas las fichas
            if len(deps) >= 2:
                from genesis_cognitive.context.app_channel import (
                    build_dap_disambiguation_question,
                    build_product_options,
                )

                lines = [f"  - {display_label_in_context(p, deps)} ({p.currency})" for p in deps]
                text = (
                    f"{greeting}estos son tus certificados de depósito (depósitos a plazo):\n"
                    + "\n".join(lines)
                    + "\n\n"
                    + build_dap_disambiguation_question(deps)
                )
                action = {
                    "sequence": 1,
                    "intent_id": "TERM_DEPOSIT_DETAIL_READ",
                    "capability_candidate": "TERM_DEPOSIT_DETAIL",
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {
                        "account_ref": None,
                        "source_account_ref": None,
                        "destination_account_ref": None,
                        "amount": None,
                        "currency": None,
                        "knowledge_topic": None,
                    },
                    "missing_requirements": ["account_ref"],
                    "depends_on": [],
                    "confidence": 1.0,
                }
                return "CLARIFICATION_REQUIRED", [action], text, build_product_options(deps)
            blocks = [build_rich_deposit_detail(p) for p in deps]
            text = (
                f"{greeting}estos son tus certificados de depósito (depósitos a plazo):\n\n"
                + "\n\n".join(blocks)
            )
        else:
            text = f"{greeting}no tienes certificados de depósito (depósitos a plazo) activos en tu portafolio."
    elif any(s in t for s in ("mis cuentas", "qué cuentas", "que cuentas", "cuales cuentas", "cuáles cuentas")) and "banco" not in t:
        accts = [p for p in active if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")]
        if accts:
            lines = [f"  - {display_label_in_context(p, accts)} ({p.currency})" for p in accts]
            text = f"{greeting}tus cuentas activas son:\n" + "\n".join(lines)
        else:
            text = f"{greeting}no tienes cuentas activas en tu portafolio."
    else:
        text = build_portfolio_listing(snapshot)

    action = {
        "sequence": 1,
        "intent_id": "PORTFOLIO_LIST",
        "capability_candidate": "PORTFOLIO_LIST",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {
            "account_ref": None,
            "source_account_ref": None,
            "destination_account_ref": None,
            "amount": None,
            "currency": None,
            "knowledge_topic": None,
        },
        "missing_requirements": [],
        "depends_on": [],
        "confidence": 1.0,
    }
    return "VALID_CONTRACT", [action], text, build_product_suggestions(snapshot)


def is_compound_personal_query(text: str) -> bool:
    """True si el mensaje mezcla varias consultas personales (saldo + mínimo + disponible…)."""
    t = (text or "").strip().lower()
    if not t or len(t) < 25:
        return False
    fields = 0
    if any(
        s in t
        for s in (
            "cuanto debo", "cuánto debo", "cuanto adeud", "cuánto adeud",
            "debo de mi", "deuda de mi", "saldo de mi tarjeta", "lo que debo",
            "saldo actual", "saldo adeudado",
        )
    ) or (re.search(r"\bsaldo\b", t) and "disponible" not in t):
        fields += 1
    if any(s in t for s in ("pago minimo", "pago mínimo")) or (
        ("minimo" in t or "mínimo" in t) and "consumo" not in t
    ):
        fields += 1
    if any(
        s in t
        for s in (
            "disponible", "cupo", "limite de credito", "límite de crédito",
            "limite disponible", "límite disponible",
            "credito disponible", "crédito disponible", "cuanto tengo", "cuánto tengo",
        )
    ):
        fields += 1
    if any(
        s in t
        for s in (
            "fecha limite", "fecha límite", "fecha de pago", "limite de pago", "límite de pago",
            "cuando debo pagar", "cuándo debo pagar", "cuando pago", "cuándo pago",
            "fecha de corte",
        )
    ):
        fields += 1
    if fields >= 2:
        return True
    # Varias cláusulas separadas por coma o "y" con cual/cuanto
    asks = len(re.findall(r"\b(cuanto|cuánto|cuando|cuándo|cual|cuál|saldo|pago|limite|límite|disponible)\b", t))
    return asks >= 3 and ("," in t or " y " in t)


def apply_compound_card_query_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Responde varias preguntas de tarjeta en un solo mensaje; si no puede, None → Foundry/LLM."""
    if snapshot is None or not is_compound_personal_query(raw_text):
        return None
    t = (raw_text or "").lower()

    # Débito personal explícito → no listar TC ni pedir elegir
    if asks_personal_debit_cards(raw_text):
        return (
            "VALID_CONTRACT",
            [],
            _debit_cards_unavailable_message(snapshot.display_name),
            None,
        )

    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    has_card_word = any(s in t for s in ("tarjeta", "visa", "mastercard", "credito", "crédito"))
    # Sin palabra "tarjeta": permitir si hay 1 sola TC o foco de sesión en tarjeta
    if not has_card_word:
        focus = getattr(session, "product_focus", None) if session is not None else None
        lr = getattr(session, "last_resolved", None) if session is not None else None
        focused_card = False
        if focus is not None and getattr(focus, "kind", None) == "CARD":
            focused_card = True
        if lr is not None and getattr(lr, "intent_id", None) == "CREDIT_CARD_DETAIL_READ":
            focused_card = True
        if not focused_card and len(cards) != 1:
            return None

    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    if not cards:
        msg = (
            f"{greeting}no tienes tarjetas de crédito activas en tu portafolio para consultar. "
            "¿Quieres consultar otra información?"
        )
        return "VALID_CONTRACT", [], msg, None

    if len(cards) > 1 and not has_card_word:
        # Con foco de sesión, resolver a esa tarjeta
        ref = None
        focus = getattr(session, "product_focus", None) if session is not None else None
        lr = getattr(session, "last_resolved", None) if session is not None else None
        if focus is not None and getattr(focus, "kind", None) == "CARD":
            ref = getattr(focus, "product_id", None)
        if not ref and lr is not None and getattr(lr, "intent_id", None) == "CREDIT_CARD_DETAIL_READ":
            ref = getattr(lr, "account_ref", None)
        hit = next((c for c in cards if c.product_id == ref), None) if ref else None
        if hit is None:
            q = greeting + build_card_disambiguation_question(cards)
            from genesis_cognitive.context.app_channel import build_product_options

            return (
                "CLARIFICATION_REQUIRED",
                [_card_detail_action(None)],
                q,
                build_product_options(cards) or None,
            )
        cards = [hit]
    elif len(cards) > 1:
        # Varias TC: si pide resumen/comparación de todas → no clarificar
        if is_multi_card_aggregate_question(raw_text):
            text = build_multi_card_aggregate_response(raw_text, list(cards), snapshot.display_name)
            return "VALID_CONTRACT", [_card_detail_action(None)], text, None
        q = greeting + build_card_disambiguation_question(cards)
        from genesis_cognitive.context.app_channel import build_product_options

        return (
            "CLARIFICATION_REQUIRED",
            [_card_detail_action(None)],
            q,
            build_product_options(cards) or None,
        )

    card = cards[0]
    label = display_label_in_context(card, cards)
    from genesis_cognitive.router.final_response_agent import _build_card_multi_field_parts

    parts = _build_card_multi_field_parts(t, card, label)
    if len(parts) < 2:
        return None
    body_lines = [f"- {p.rstrip('.')}." for p in parts]
    greet = greeting.rstrip(", ").rstrip()
    if greet:
        text = f"{greet},\n\n" + "\n".join(body_lines)
    else:
        text = "\n".join(body_lines)
    return (
        "VALID_CONTRACT",
        [_card_detail_action(card.product_id)],
        text,
        build_product_suggestions(snapshot, focus_product_id=card.product_id),
    )


def is_upcoming_payment_scan_question(text: str) -> bool:
    """¿Hay préstamo/tarjeta con pago próximo? (resumen multi-producto, no un DAP)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    has_product = any(
        s in t
        for s in (
            "prestamo",
            "préstamo",
            "tarjeta",
            "visa",
            "mastercard",
            "credito",
            "crédito",
        )
    )
    if not has_product:
        return False
    # "próximo pago de mi préstamo" consulta el producto singular en foco;
    # no es un escaneo de todos los préstamos/tarjetas del portafolio.
    if any(
        s in t
        for s in (
            "mi prestamo",
            "mi préstamo",
            "mi credito",
            "mi crédito",
            "esta tarjeta",
            "mi tarjeta",
        )
    ) and not any(
        s in t
        for s in (
            "mis prestamos",
            "mis préstamos",
            "mis tarjetas",
            "alguno",
            "algún",
            "alguna",
        )
    ):
        return False
    # Excluir catálogo / definición
    if any(
        s in t
        for s in (
            "qué es",
            "que es",
            "definición",
            "definicion",
            "ofrece el banco",
            "del banco",
        )
    ):
        return False
    upcoming = any(
        s in t
        for s in (
            "pago proximo",
            "pago próximo",
            "proximo pago",
            "próximo pago",
            "pagos proximos",
            "pagos próximos",
            "proximo a vencer",
            "próximo a vencer",
            "por vencer",
            "vence pronto",
            "vence algo",
            "se me vence",
            "me vence",
            "estos dias",
            "estos días",
            "en estos dias",
            "en estos días",
            "con un pago",
            "con pago prox",
            "con pago próx",
            "pago cercano",
            "pagos cercanos",
        )
    )
    scan = any(
        s in t
        for s in (
            "tengo algun",
            "tengo algún",
            "tengo alguna",
            "hay algun",
            "hay algún",
            "algun prestamo",
            "algún préstamo",
            "alguna tarjeta",
            "alguno de mis",
        )
    )
    return upcoming or (
        scan and any(s in t for s in ("pago", "vencer", "vence", "cuota", "letra"))
    )


def apply_upcoming_payments_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    *,
    reference_date: str | None = None,
    window_days: int = 30,
    timezone: str = "America/Santo_Domingo",
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Resume pagos próximos dentro de una ventana temporal explícita; nunca DAP.

    Tener fecha de pago ≠ tener pago próximo. Solo clasifica como próximo lo que
    cae en [referencia, referencia+window_days] en la zona horaria indicada.
    """
    if snapshot is None or not is_upcoming_payment_scan_question(raw_text):
        return None

    from genesis_cognitive.context.product_display import display_label_in_context
    from genesis_cognitive.context.upcoming_payment_window import (
        card_due_from_cutoff,
        classify_due_date,
        parse_payment_date,
        resolve_payment_window,
        window_audit_dict,
    )

    t = (raw_text or "").lower()
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    wants_loan = any(s in t for s in ("prestamo", "préstamo", "cuota", "letra"))
    wants_card = any(s in t for s in ("tarjeta", "visa", "mastercard", "pricesmart"))
    if " o " in t and (wants_loan or wants_card):
        wants_loan = True if any(s in t for s in ("prestamo", "préstamo")) else wants_loan
        wants_card = True if "tarjeta" in t else wants_card

    loans = filter_active_by_type(snapshot, ("LOAN",))
    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    if wants_loan and not wants_card:
        cards = []
    elif wants_card and not wants_loan:
        loans = []

    window = resolve_payment_window(
        reference=reference_date, timezone=timezone, window_days=window_days,
    )
    upcoming_lines: list[str] = []
    other_dated: list[str] = []
    missing_lines: list[str] = []
    classifications: list[dict] = []

    for lp in loans:
        loan = next((ln for ln in snapshot.loans if ln.product_id == lp.product_id), None)
        due_raw = getattr(loan, "next_due_date", None) if loan else None
        due = parse_payment_date(due_raw)
        label = display_label_in_context(lp, list(loans) + list(cards))
        amount_bit = ""
        if loan and loan.installment_amount and loan.installment_amount > 0:
            from genesis_cognitive.context.response_formatting import format_money
            amount_bit = f", cuota **{format_money(loan.installment_amount, 'DOP')}**"
        bucket = classify_due_date(due, window)
        classifications.append({
            "product_id": lp.product_id, "kind": "loan",
            "due_date": due.isoformat() if due else None, "class": bucket,
        })
        if bucket == "upcoming":
            upcoming_lines.append(
                f"• **{label}**: pago próximo el **{due.isoformat()}**{amount_bit}"
            )
        elif bucket == "overdue":
            other_dated.append(
                f"• **{label}**: tiene fecha de pago **{due.isoformat()}** "
                f"(anterior a la referencia; no es pago próximo en esta ventana){amount_bit}"
            )
        elif bucket == "beyond":
            other_dated.append(
                f"• **{label}**: tiene fecha de pago **{due.isoformat()}** "
                f"(fuera del intervalo; no es pago próximo en esta ventana){amount_bit}"
            )
        else:
            missing_lines.append(
                f"• **{label}**: fecha de pago no disponible en este momento{amount_bit}"
            )

    for card in cards:
        label = display_label_in_context(card, list(loans) + list(cards))
        due_raw = getattr(card, "payment_due_date", None)
        due = parse_payment_date(due_raw)
        cutoff = getattr(card, "cutoff_day", None)
        if due is None and cutoff is not None:
            due = card_due_from_cutoff(cutoff, window)
        pay_bit = ""
        if getattr(card, "min_payment_rd", None) is not None:
            from genesis_cognitive.context.response_formatting import format_money
            pay_bit = f", pago mínimo **{format_money(card.min_payment_rd, 'DOP')}**"
        elif getattr(card, "ledger_balance", None) is not None:
            from genesis_cognitive.context.response_formatting import format_money
            pay_bit = f", saldo adeudado **{format_money(card.ledger_balance, 'DOP')}**"
        bucket = classify_due_date(due, window)
        classifications.append({
            "product_id": getattr(card, "product_id", None), "kind": "card",
            "due_date": due.isoformat() if due else None, "class": bucket,
            "cutoff_day": cutoff,
        })
        if bucket == "upcoming":
            upcoming_lines.append(
                f"• **{label}**: pago próximo / fecha límite **{due.isoformat()}**{pay_bit}"
            )
        elif bucket == "overdue":
            other_dated.append(
                f"• **{label}**: tiene fecha de pago **{due.isoformat()}** "
                f"(anterior a la referencia; no es pago próximo en esta ventana){pay_bit}"
            )
        elif bucket == "beyond":
            other_dated.append(
                f"• **{label}**: tiene fecha de pago **{due.isoformat()}** "
                f"(fuera del intervalo; no es pago próximo en esta ventana){pay_bit}"
            )
        else:
            if cutoff:
                missing_lines.append(
                    f"• **{label}**: corte día **{cutoff}** de cada mes "
                    f"(sin fecha límite concreta dentro de la ventana){pay_bit}"
                )
            else:
                missing_lines.append(
                    f"• **{label}**: fecha de pago no disponible en este momento{pay_bit}"
                )

    action = {
        "sequence": 1,
        "intent_id": "PAYMENT_DATE_READ",
        "capability_candidate": "PRODUCT_FIELD",
        "selected_route": "PERSONAL_READ",
        "detected_entities": {"account_ref": None},
        "missing_requirements": [],
        "depends_on": [],
        "confidence": 1.0,
        "payment_window": window_audit_dict(window),
        "payment_classifications": classifications,
    }

    parts: list[str] = [f"{greeting}{window.describe_es()}."]
    if upcoming_lines:
        parts.append("Sí: estos productos tienen **pago próximo** dentro de la ventana:")
        parts.extend(upcoming_lines)
    else:
        parts.append(
            "No tienes productos con **pago próximo** dentro de esa ventana "
            "(tener una fecha de pago registrada no implica que el pago sea próximo)."
        )
    if other_dated:
        parts.append("Fechas de pago registradas fuera de la ventana (no cuentan como próximo):")
        parts.extend(other_dated)
    if missing_lines and not upcoming_lines and not other_dated:
        parts.append("Detalle de productos sin fecha usable:")
        parts.extend(missing_lines)
    elif missing_lines and (upcoming_lines or other_dated):
        parts.append("Sin fecha usable en contexto:")
        parts.extend(missing_lines)

    return "VALID_CONTRACT", [action], "\n".join(parts), None


def is_personal_payment_date_question(text: str) -> bool:
    """Consulta personal de fecha de pago (no definición/glosario FAQ)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    # Escaneo multi-producto → path dedicado
    if is_upcoming_payment_scan_question(t):
        return False
    # Multi-pregunta (deuda + disponible + fecha) → otro path / Foundry
    if is_compound_personal_query(t):
        return False
    # Definición / glosario → FAQ (no path personal)
    if any(
        s in t
        for s in (
            "qué es",
            "que es",
            "qué significa",
            "que significa",
            "definición",
            "definicion",
            "explícame",
            "explicame",
            "cuéntame",
            "cuentame",
            "háblame",
            "hablame",
            "información sobre",
            "informacion sobre",
            "significa fecha",
            "en qué se diferencian",
            "en que se diferencian",
            "diferencia entre fecha",
        )
    ):
        return False
    # Señales explícitas de fecha de pago / límite
    if any(
        s in t
        for s in (
            "fecha de pago",
            "fecha límite de pago",
            "fecha limite de pago",
            "limite de pago",
            "límite de pago",
            "cuando pago",
            "cuándo pago",
            "cuando debo pagar",
            "cuándo debo pagar",
            "día de pago",
            "dia de pago",
            "próxima fecha de pago",
            "proxima fecha de pago",
            "vence el pago",
            "vencimiento del pago",
            "proxima fecha",
            "próxima fecha",
            "cuando me toca pagar",
            "cuándo me toca pagar",
        )
    ):
        return True
    # "fecha limite de mi prestamo" / "fecha límite" + producto personal
    if ("fecha limite" in t or "fecha límite" in t) and any(
        s in t
        for s in (
            "mi ",
            "mis ",
            "prestamo",
            "préstamo",
            "tarjeta",
            "pago",
            "cuota",
            "letra",
        )
    ):
        return True
    # Follow-up corto solo con "fecha límite" / "fecha limite" (contexto de sesión lo resuelve)
    if t in (
        "fecha limite",
        "fecha límite",
        "fecha limite?",
        "fecha límite?",
        "cual es la fecha limite",
        "cuál es la fecha límite",
        "cual es la fecha limite de pago",
        "cuál es la fecha límite de pago",
        "y la fecha limite",
        "y la fecha límite",
        "y la fecha limite de pago",
        "y la fecha límite de pago",
    ):
        return True
    return False


def apply_bank_catalog_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Catálogo institucional grounded; nunca confundirlo con productos del cliente."""
    if snapshot is None or not is_bank_catalog_question(raw_text):
        return None
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    if is_bank_card_catalog_question(raw_text):
        text = (
            f"{greeting}en Banco Santa Cruz puedes solicitar, según elegibilidad:\n\n"
            "• **Tarjetas de crédito**: Visa Clásica, Visa Joven, Visa Gold, "
            "Visa Platinum, Visa Infinite, Multicrédito BSC y otras modalidades "
            "según tu perfil.\n"
            "• **Tarjetas de débito**: Visa Clásica de débito, vinculada a una "
            "cuenta de ahorro, corriente o nómina.\n\n"
            "[Consulta y solicita productos en línea]"
            "(https://solicitudesdigitales.bsc.com.do/)"
        )
        topic = "BANK_CARD_CATALOG"
    else:
        text = (
            f"{greeting}en Banco Santa Cruz puedes solicitar, entre otros:\n\n"
            "• **Cuentas** de ahorro y corriente personales.\n"
            "• **Préstamos** personales, con garantía, de vehículos e hipotecarios.\n"
            "• **Tarjetas** de crédito y débito, según elegibilidad.\n"
            "• **Depósitos o certificados** a plazo.\n\n"
            "[Consulta y solicita productos en línea]"
            "(https://solicitudesdigitales.bsc.com.do/)"
        )
        topic = "BANK_PRODUCT_CATALOG"
    action = {
        "sequence": 1,
        "intent_id": "BUSINESS_KNOWLEDGE_QUERY",
        "capability_candidate": "BUSINESS_KNOWLEDGE",
        "selected_route": "BUSINESS_RAG",
        "detected_entities": {
            "account_ref": None,
            "knowledge_topic": topic,
        },
        "missing_requirements": [],
        "depends_on": [],
        "confidence": 1.0,
    }
    return "VALID_CONTRACT", [action], text, None


def apply_payment_date_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved_ref: str | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Fecha de pago: si hay préstamo y tarjeta (u varios), clarificar; no devolver glosario."""
    if snapshot is None or not is_personal_payment_date_question(raw_text):
        return None

    from genesis_cognitive.context.app_channel import build_product_options
    from genesis_cognitive.context.product_display import display_label_in_context

    t = (raw_text or "").lower()
    loans = filter_active_by_type(snapshot, ("LOAN",))
    cards = filter_active_by_type(snapshot, ("CREDIT_CARD",))
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""

    wants_loan = any(s in t for s in ("prestamo", "préstamo", "credito personal", "crédito personal", "cuota"))
    wants_card = any(s in t for s in ("tarjeta", "visa", "mastercard", "pricesmart"))

    # Resolver por last_resolved si apunta a loan/card
    if last_resolved_ref:
        hit_loan = next((p for p in loans if p.product_id == last_resolved_ref), None)
        hit_card = next((p for p in cards if p.product_id == last_resolved_ref), None)
        if hit_loan and not wants_card:
            wants_loan = True
            loans = [hit_loan]
        elif hit_card and not wants_loan:
            wants_card = True
            cards = [hit_card]

    # Ambiguo: tiene ambos tipos y no especificó
    if loans and cards and not wants_loan and not wants_card:
        pool = list(loans) + list(cards)
        labels = [display_label_in_context(p, pool) for p in pool]
        if len(labels) == 2:
            q = (
                f"{greeting}tienes fecha de pago en {labels[0]} y en {labels[1]}. "
                "¿De cuál producto deseas consultar la fecha de pago?"
            )
        else:
            joined = ", ".join(labels[:-1]) + f" o {labels[-1]}"
            q = f"{greeting}¿La fecha de pago de cuál producto deseas consultar: {joined}?"
        action = {
            "sequence": 1,
            "intent_id": "PAYMENT_DATE_READ",
            "capability_candidate": "PRODUCT_FIELD",
            "selected_route": "PERSONAL_READ",
            "detected_entities": {"account_ref": None},
            "missing_requirements": ["account_ref"],
            "depends_on": [],
            "confidence": 1.0,
        }
        return "CLARIFICATION_REQUIRED", [action], q, build_product_options(pool) or None

    # Solo préstamos / pidió préstamo
    if (wants_loan or (loans and not cards)) and loans:
        if len(loans) > 1 and not last_resolved_ref:
            from genesis_cognitive.context.app_channel import build_loan_disambiguation_question

            q = (
                f"{greeting}tienes varios préstamos con fecha de pago. "
                + build_loan_disambiguation_question(loans)
            )
            return (
                "CLARIFICATION_REQUIRED",
                [{
                    "sequence": 1,
                    "intent_id": "PAYMENT_DATE_READ",
                    "capability_candidate": "PRODUCT_FIELD",
                    "selected_route": "PERSONAL_READ",
                    "detected_entities": {"account_ref": None},
                    "missing_requirements": ["account_ref"],
                    "depends_on": [],
                    "confidence": 1.0,
                }],
                q,
                build_product_options(loans) or None,
            )
        loan_prod = loans[0]
        loan = next((ln for ln in snapshot.loans if ln.product_id == loan_prod.product_id), None)
        label = display_label_in_context(loan_prod, loans)
        due = getattr(loan, "next_due_date", None) if loan else None
        if due:
            text = f"{greeting}la próxima fecha de pago de tu {label} es **{due}**."
        else:
            text = f"{greeting}la fecha de pago de tu {label} no está disponible en este momento."
        return (
            "VALID_CONTRACT",
            [{
                "sequence": 1,
                "intent_id": "LOAN_DETAIL_READ",
                "capability_candidate": "LOAN_DETAIL",
                "selected_route": "PERSONAL_READ",
                "detected_entities": {"account_ref": loan_prod.product_id},
                "missing_requirements": [],
                "depends_on": [],
                "confidence": 1.0,
            }],
            text,
            build_product_suggestions(snapshot, focus_product_id=loan_prod.product_id),
        )

    # Solo tarjetas / pidió tarjeta
    if (wants_card or (cards and not loans)) and cards:
        if len(cards) > 1 and not last_resolved_ref:
            q = (
                f"{greeting}tienes varias tarjetas. "
                + build_card_disambiguation_question(cards)
            )
            return (
                "CLARIFICATION_REQUIRED",
                [_card_detail_action(None)],
                q,
                build_product_options(cards) or None,
            )
        card = cards[0]
        label = display_label_in_context(card, cards)
        due = getattr(card, "payment_due_date", None)
        cutoff = getattr(card, "cutoff_day", None)
        wants_cutoff = "corte" in t or "corta" in t
        wants_due = any(
            s in t
            for s in (
                "fecha limite", "fecha límite", "limite de pago", "límite de pago",
                "cuando debo pagar", "cuándo debo pagar", "cuando pago", "cuándo pago",
                "debo pagar", "fecha de pago",
            )
        )
        if wants_cutoff and cutoff:
            text = f"{greeting}la fecha de corte de tu {label} es el día **{cutoff}** de cada mes."
        elif due:
            text = f"{greeting}la fecha límite de pago de tu {label} es **{due}**."
        elif wants_due and cutoff:
            text = (
                f"{greeting}no tengo la fecha límite de pago exacta de tu {label} en este momento. "
                f"La fecha de corte es el día **{cutoff}** de cada mes; "
                "la fecha límite de pago aparece en tu estado de cuenta (normalmente unos días después del corte)."
            )
        elif cutoff:
            text = (
                f"{greeting}la fecha de corte de tu {label} es el día **{cutoff}** de cada mes. "
                "La fecha límite de pago aparece en tu estado de cuenta (normalmente unos días después del corte)."
            )
        else:
            text = f"{greeting}la fecha de pago de tu {label} no está disponible en este momento."
        return (
            "VALID_CONTRACT",
            [_card_detail_action(card.product_id)],
            text,
            build_product_suggestions(snapshot, focus_product_id=card.product_id),
        )

    # Sin productos con fecha de pago
    msg = (
        f"{greeting}no encontré préstamos ni tarjetas activos con fecha de pago en tu portafolio. "
        "¿Quieres consultar otra información?"
    )
    return "VALID_CONTRACT", [], msg, None


def apply_loan_fastpath_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved_ref: str | None = None,
    *,
    allow_deictic_fields: bool = False,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    from genesis_cognitive.router.snapshot_guardrails import is_loan_field_question

    if snapshot is None or not is_loan_field_question(
        raw_text, allow_deictic_fields=allow_deictic_fields,
    ):
        return None
    from genesis_cognitive.router.snapshot_guardrails import apply_loan_field_guardrail

    # Card APK tras clarificación: responder el campo pedido (fecha límite), no la ficha.
    field_q = raw_text
    if session is not None:
        from genesis_cognitive.router.product_focus import pending_field_question_for_selection

        oq = pending_field_question_for_selection(session, raw_text)
        if oq:
            field_q = oq

    status, actions, clars = apply_loan_field_guardrail(
        "VALID_CONTRACT", [], snapshot, raw_text, last_resolved_ref,
        allow_deictic_fields=allow_deictic_fields,
    )
    if status == "VALID_CONTRACT" and actions:
        ref = (actions[0].get("detected_entities") or {}).get("account_ref")
        if ref:
            loan = next((ln for ln in snapshot.loans if ln.product_id == ref), None)
            if loan:
                # Si el pending era fecha de pago, respuesta corta dedicada
                if is_personal_payment_date_question(field_q):
                    loans = [
                        p for p in snapshot.products
                        if p.product_type == "LOAN" and str(p.status).lower() == "active"
                    ]
                    prod = next((p for p in loans if p.product_id == ref), None)
                    label = display_label_in_context(prod, loans) if prod else f"préstamo ...{ref[-4:]}"
                    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
                    due = getattr(loan, "next_due_date", None)
                    if due:
                        text = f"{greeting}la próxima fecha de pago de tu {label} es **{due}**."
                    else:
                        text = f"{greeting}la fecha de pago de tu {label} no está disponible en este momento."
                    sug = build_product_suggestions(snapshot, focus_product_id=ref)
                    return status, actions, text, sug
                text = build_loan_detail_response(
                    field_q, loan.to_detail_dict(), snapshot.display_name,
                )
                sug = build_product_suggestions(snapshot, focus_product_id=ref)
                return status, actions, text, sug
            # Producto LOAN en portafolio sin LoanSnapshot enriquecido
            prod = next((p for p in snapshot.products if p.product_id == ref), None)
            if prod is not None:
                from genesis_cognitive.context.response_formatting import build_rich_loan_detail
                name = snapshot.display_name or ""
                greeting = f"{name}, " if name else ""
                text = greeting + build_rich_loan_detail(prod, None)
                return status, actions, text, build_product_suggestions(snapshot, focus_product_id=ref)
    if status == "CLARIFICATION_REQUIRED":
        q = (clars[0].get("suggested_question") if clars else None) or build_loan_disambiguation_question(
            [p for p in snapshot.products if p.product_type == "LOAN" and str(p.status).lower() == "active"]
        )
        return status, actions, q, None
    # Pregunta de préstamo personal sin préstamos activos → mensaje claro (no vacío)
    if is_loan_field_question(raw_text, allow_deictic_fields=allow_deictic_fields):
        active_loans = [
            p for p in snapshot.products
            if p.product_type == "LOAN" and str(p.status).lower() == "active"
        ]
        if not active_loans:
            name = snapshot.display_name or ""
            greeting = f"{name}, " if name else ""
            text = (
                f"{greeting}no tienes préstamos activos en tu portafolio para consultar. "
                "Si deseas conocer los tipos de préstamos que ofrece el banco, pregunta por "
                "\"préstamos que puedo contratar\"."
            )
            action = {
                "sequence": 1,
                "intent_id": "LOAN_DETAIL_READ",
                "capability_candidate": "LOAN_DETAIL",
                "selected_route": "PERSONAL_READ",
                "detected_entities": {
                    "account_ref": None,
                    "source_account_ref": None,
                    "destination_account_ref": None,
                    "amount": None,
                    "currency": None,
                    "knowledge_topic": None,
                },
                "missing_requirements": [],
                "depends_on": [],
                "confidence": 1.0,
            }
            return "VALID_CONTRACT", [action], text, None
    return None


def apply_other_loan_guardrail(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    current_ref: str | None,
    *,
    session: Any | None = None,
) -> tuple[str, list[dict], str | None, list[dict] | None] | None:
    """Resuelve “mi otro préstamo” respecto al préstamo actualmente enfocado."""
    t = (raw_text or "").strip().lower()
    if snapshot is None or not any(
        phrase in t
        for phrase in (
            "otro prestamo",
            "otro préstamo",
            "el otro prestamo",
            "el otro préstamo",
        )
    ):
        return None

    loans = filter_active_by_type(snapshot, ("LOAN",))
    alternatives = [
        product for product in loans
        if not current_ref or product.product_id != current_ref
    ]
    if len(alternatives) == 1:
        return apply_loan_fastpath_guardrail(
            snapshot,
            raw_text,
            alternatives[0].product_id,
            allow_deictic_fields=True,
            session=session,
        )

    if len(alternatives) >= 2:
        from genesis_cognitive.context.app_channel import (
            build_loan_disambiguation_question,
            build_product_options,
        )

        action = {
            "sequence": 1,
            "intent_id": "LOAN_DETAIL_READ",
            "capability_candidate": "LOAN_DETAIL",
            "selected_route": "PERSONAL_READ",
            "detected_entities": {"account_ref": None},
            "missing_requirements": ["account_ref"],
            "depends_on": [],
            "confidence": 1.0,
        }
        return (
            "CLARIFICATION_REQUIRED",
            [action],
            build_loan_disambiguation_question(alternatives),
            build_product_options(
                alternatives,
                question=raw_text,
                snapshot=snapshot,
            ),
        )

    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    return (
        "VALID_CONTRACT",
        [{
            "sequence": 1,
            "intent_id": "LOAN_DETAIL_READ",
            "capability_candidate": "LOAN_DETAIL",
            "selected_route": "PERSONAL_READ",
            "detected_entities": {"account_ref": current_ref},
            "missing_requirements": [],
            "depends_on": [],
            "confidence": 1.0,
        }],
        f"{greeting}no tienes otro préstamo activo en tu portafolio.",
        None,
    )


# status, actions, client_text, suggestions, trace_step, intent_id, account_ref
FastPathResult = tuple[str, list[dict], str, list[dict] | None, str, str | None, str | None]


def run_field_fastpath(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved: Any | None,
    *,
    pending_knowledge_topic: str | None = None,
    session: Any | None = None,
) -> FastPathResult | None:
    """Ejecuta guardrails deterministas en orden. None = continuar con LLM.

    Orden Fase 1: moderación → reclamación → portafolio → alcance → saludo → …
    → FAQ. Contenedores: umbrales/paths vía GENESIS_* env.
    """
    if snapshot is None or not (raw_text or "").strip():
        return None

    # Capa 0: moderación (puede limpiar texto si hay intención funcional)
    from genesis_cognitive.router.moderation import apply_moderation_guardrail, moderate_user_text
    from genesis_cognitive.brain.security_secrets import is_auth_secret_message

    mod_block = apply_moderation_guardrail(snapshot, raw_text)
    if mod_block is not None:
        st, acts, txt, sug = mod_block
        return st, acts, txt or "", sug, "moderation", None, None

    # Secretos de autenticación ANTES de dígitos de producto / LLM
    if is_auth_secret_message(raw_text):
        greeting = f"{snapshot.display_name}, " if snapshot and snapshot.display_name else ""
        msg = (
            f"{greeting}por seguridad, no compartas PIN, contraseña, CVV ni códigos de "
            "verificación en el chat. No los usaré para identificar productos."
        )
        return "VALID_CONTRACT", [], msg, None, "auth_secret", None, None

    mod = moderate_user_text(raw_text)
    text = mod.cleaned_text if mod.is_offensive and mod.has_functional_intent else raw_text

    lr_ref = last_resolved.account_ref if last_resolved else None
    lr_intent = last_resolved.intent_id if last_resolved else None

    if is_transfer_question(text):
        st, acts, msg = apply_transfer_guardrail("UNSUPPORTED", [], text)
        return st, acts, msg or "", None, "transfer_guardrail", None, None

    aff = apply_affirmation_guardrail(snapshot, text, session)
    if aff is not None and aff[2] is not None:
        st, acts, txt, sug = aff
        ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
        intent = acts[0].get("intent_id") if acts else None
        return st, acts, txt or "", sug, "affirmation", intent, ref

    if lr_intent == "ACCOUNT_BALANCE_READ":
        ccy = apply_currency_switch_guardrail(
            snapshot, text, lr_intent, lr_ref, session=session,
        )
        if ccy is not None:
            st, acts, txt = ccy
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            return st, acts, txt or "", None, "currency_switch", "ACCOUNT_BALANCE_READ", ref

    # Selección pendiente: resolución centralizada en continuity.py
    from genesis_cognitive.brain.continuity import try_pending_continuity_fastpath

    pending_hit = try_pending_continuity_fastpath(text, snapshot, session)
    if pending_hit is not None:
        st, acts, txt, intent, ref = pending_hit
        step = (
            "pending_continuity_missing"
            if ref is None and st == "VALID_CONTRACT" and "no encuentro" in (txt or "").lower()
            else "pending_continuity"
        )
        return st, acts, txt or "", None, step, intent, ref

    from genesis_cognitive.router.product_focus import (
        dap_ref_from_session,
        loan_ref_from_session,
        prefer_personal_loan_over_knowledge,
    )
    focus_loan_ref = loan_ref_from_session(session) if session is not None else None
    effective_loan_ref = focus_loan_ref or (
        lr_ref if lr_intent == "LOAN_DETAIL_READ" else None
    )
    # Preferir ref DAP de foco de sesión si last_resolved fue pisado por un saldo
    effective_dap_ref = dap_ref_from_session(session) or (
        lr_ref if lr_intent == "TERM_DEPOSIT_DETAIL_READ" else None
    )

    other_loan = apply_other_loan_guardrail(
        snapshot, text, effective_loan_ref, session=session,
    )
    if other_loan is not None and other_loan[2] is not None:
        st, acts, txt, sug = other_loan
        ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
        intent = acts[0].get("intent_id") if acts else None
        return st, acts, txt or "", sug, "other_loan", intent, ref

    # Follow-up corto "Y del 05809?" → mismo producto/tipo en foco + campo previo
    digit_out = apply_digit_followup_guardrail(snapshot, text, last_resolved, session)
    if digit_out is not None and digit_out[2] is not None:
        st, acts, txt, sug = digit_out
        ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
        intent = acts[0].get("intent_id") if acts else None
        return st, acts, txt or "", sug, "digit_followup", intent, ref

    # Follow-up KB ("como se usa", "y la del banco", guía CTX) → FAQ/RAG con tema de sesión
    from genesis_cognitive.router.knowledge_followup import (
        expand_knowledge_question,
        has_knowledge_session,
        is_kb_product_compare_question,
        is_knowledge_followup,
        prefer_foundry_for_faq_hit,
        should_block_personal_followup,
    )
    kb_followup_active = bool(
        session is not None
        and has_knowledge_session(session)
        and (is_knowledge_followup(text) or should_block_personal_followup(text, session))
    )
    kb_force_foundry = False
    # Multi-pregunta de tarjeta (saldo + mínimo + disponible + fecha…) ANTES de payment_date
    if is_compound_personal_query(text):
        compound = apply_compound_card_query_guardrail(snapshot, text, session=session)
        if compound is not None and compound[2] is not None:
            st, acts, txt, sug = compound
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            intent = acts[0].get("intent_id") if acts else None
            return st, acts, txt or "", sug, "compound_card", intent, ref
        # Solo escalar si parece multi-campo de tarjeta; si no, dejar seguir el fastpath
        tl = (text or "").lower()
        cardish = any(s in tl for s in ("tarjeta", "visa", "mastercard", "credito", "crédito", "pago minimo", "pago mínimo", "saldo actual", "limite disponible", "límite disponible"))
        if cardish and filter_active_by_type(snapshot, ("CREDIT_CARD",)):
            # Preferir respuesta multi vía build_card_detail_response en path card
            pass
        # no return None: el path card/loan puede resolver

    # Escaneo "¿tengo préstamo/tarjeta con pago próximo?" ANTES de fecha puntual / KB
    if is_upcoming_payment_scan_question(text):
        up = apply_upcoming_payments_guardrail(snapshot, text)
        if up is not None and up[2] is not None:
            st, acts, txt, sug = up
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            intent = acts[0].get("intent_id") if acts else None
            return st, acts, txt or "", sug, "upcoming_payments", intent, ref

    # Fecha de pago personal ANTES del hilo KB: no dejar que FAQ/Foundry
    # responda el glosario si el usuario pide su fecha (o hay préstamo/TC en foco).
    if is_personal_payment_date_question(text):
        pay = apply_payment_date_guardrail(snapshot, text, effective_loan_ref or lr_ref)
        if pay is not None and pay[2] is not None:
            st, acts, txt, sug = pay
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            intent = acts[0].get("intent_id") if acts else None
            return st, acts, txt or "", sug, "payment_date", intent, ref

    if kb_followup_active:
        from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail as _faq_kb
        kb_q = expand_knowledge_question(text, session)
        kb_faq = _faq_kb(snapshot, kb_q, session)
        if kb_faq is not None and kb_faq[2]:
            _kb_score = None
            try:
                if kb_faq[1]:
                    _kb_score = float((kb_faq[1][0] or {}).get("confidence") or 0)
            except Exception:
                _kb_score = None
            if prefer_foundry_for_faq_hit(kb_q, str(kb_faq[2]), score=_kb_score):
                kb_force_foundry = True
                kb_faq = None
            else:
                st, acts, txt, sug = kb_faq
                topic = (acts[0].get("detected_entities") or {}).get("knowledge_topic") if acts else None
                return st, acts, txt or "", sug, "knowledge_followup", "BUSINESS_KNOWLEDGE_QUERY", topic
        else:
            # Sin FAQ útil → Foundry/RAG con pregunta ampliada
            kb_force_foundry = True
        # Mantener hilo KB: ampliar pregunta y no caer a portafolio personal
        text = kb_q

    # Si el follow-up pide detalle que el FAQ no cubre, salir al Foundry (no faq_rest genérico)
    if kb_force_foundry:
        return None

    # Corrección "del deposito a plazo fue que te pregunte" → reanudar DAP en foco
    if not kb_followup_active:
        dap_corr = apply_dap_correction_guardrail(snapshot, text, last_resolved, session)
        if dap_corr is not None and dap_corr[2] is not None:
            st, acts, txt, sug = dap_corr
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            intent = acts[0].get("intent_id") if acts else None
            return st, acts, txt or "", sug, "dap_correction", intent, ref

    # Intent gate: campo del préstamo en foco (incl. tras cambio de tema) → snapshot, no FAQ
    if (not kb_followup_active) and prefer_personal_loan_over_knowledge(text, session) and effective_loan_ref:
        loan_out = apply_loan_fastpath_guardrail(
            snapshot, text, effective_loan_ref, allow_deictic_fields=True, session=session,
        )
        if loan_out is not None and loan_out[2] is not None:
            st, acts, txt, sug = loan_out
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            intent = acts[0].get("intent_id") if acts else None
            return st, acts, txt or "", sug, "loan_intent_resume", intent, ref

    if (not kb_followup_active) and lr_intent == "LOAN_DETAIL_READ" and lr_ref:
        loan_out = apply_loan_fastpath_guardrail(
            snapshot, text, lr_ref, allow_deictic_fields=True, session=session,
        )
        if loan_out is not None and loan_out[2] is not None:
            st, acts, txt, sug = loan_out
            ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
            intent = acts[0].get("intent_id") if acts else None
            return st, acts, txt or "", sug, "loan_followup", intent, ref

    _skip_personal_when_kb = {
        "portfolio", "dap", "card", "loan_fastpath", "balance", "movements",
        "greeting", "specific_balance", "card_digits", "personal_rate",
        # payment_date NO se salta: ya se resolvió arriba si aplica
    }
    for step, guard in (
        ("reclamacion", lambda: _apply_reclamacion(snapshot, text, pending_knowledge_topic)),
        ("payment_date", lambda: apply_payment_date_guardrail(snapshot, text, lr_ref)),
        ("mixed_pk", lambda: _apply_mixed_pk(snapshot, text, session)),
        ("personal_rate", lambda: _apply_personal_rate(snapshot, text, session)),
        ("dap", lambda: apply_dap_field_guardrail(
            "VALID_CONTRACT", [], snapshot, text, effective_dap_ref or lr_ref, session=session,
        )),
        ("ambiguous_noun", lambda: apply_ambiguous_product_noun_guardrail(snapshot, text)),
        ("kb_ambiguity", lambda: apply_kb_knowledge_ambiguity_guardrail(snapshot, text)),
        ("portfolio", lambda: apply_portfolio_guardrail(snapshot, text)),
        ("scope", lambda: _apply_scope(snapshot, text)),
        ("greeting", lambda: apply_greeting_guardrail(snapshot, text)),
        ("bank_catalog", lambda: apply_bank_catalog_guardrail(snapshot, text)),
        # Catálogo del banco / FAQ antes de detalle personal de TC
        ("faq", lambda: _apply_faq(snapshot, text, session) if (
            kb_followup_active
            or is_bank_catalog_question(text) or is_bank_card_catalog_question(text)
            or is_kb_product_compare_question(text)
            or any(s in (text or "").lower() for s in (
                "qué es", "que es", "significa", "definición", "definicion",
                "explícame", "explicame", "cuéntame", "cuentame", "háblame", "hablame",
                "contratar", "proceso", "condiciones", "cargos", "beneficios", "características",
                "caracteristicas", "requisito", "diferencia", "modalidad", "compar", "disting",
                "multicredit", "crédito diferido", "credito diferido", "responsabilidad",
                "información sobre", "informacion sobre", "visa joven", "visa platinum",
                "visa infinite", "consumo minimo", "consumo mínimo",
                # Institucional corto (tras préstamo / pending): no esperar "qué es"
                "misión", "mision", "visión", "vision", "valores",
                "misión del banco", "mision del banco",
                "visión del banco", "vision del banco",
            ))
        ) else None),
        ("card_digits", lambda: apply_card_digits_guardrail(snapshot, text)),
        ("card", lambda: None if (
            is_bank_card_catalog_question(text)
            or is_bank_catalog_question(text)
            or is_kb_product_compare_question(text)
            or any(
                s in (text or "").lower()
                for s in (
                    "conversión", "conversion", "internacional",
                    "cómo funciona", "como funciona", "qué es", "que es",
                    "explícame", "explicame", "háblame", "hablame",
                )
            )
        ) else apply_card_field_guardrail("VALID_CONTRACT", [], snapshot, text, lr_ref)),
        ("faq_rest", lambda: _apply_faq(snapshot, text, session)),
        ("loan_fastpath", lambda: apply_loan_fastpath_guardrail(
            snapshot, text, effective_loan_ref or lr_ref, session=session,
        )),
        ("specific_balance", lambda: apply_specific_deposit_balance_guardrail(snapshot, text)),
        ("movements", lambda: apply_movements_guardrail("VALID_CONTRACT", [], snapshot, text, lr_ref)),
        ("balance", lambda: apply_generic_balance_guardrail("VALID_CONTRACT", [], snapshot, text)),
    ):
        if kb_followup_active and step in _skip_personal_when_kb:
            continue
        out = guard()
        if out is None:
            continue
        st, acts, txt, sug = out
        if txt is None:
            continue
        ref = (acts[0].get("detected_entities") or {}).get("account_ref") if acts else None
        intent = acts[0].get("intent_id") if acts else None
        return st, acts, txt, sug, step, intent, ref

    return None


def _apply_faq(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
):
    from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail
    return apply_faq_guardrail(snapshot, raw_text, session=session)


def _apply_mixed_pk(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
):
    from genesis_cognitive.router.rate_context_guardrail import (
        apply_mixed_personal_knowledge_guardrail,
    )
    return apply_mixed_personal_knowledge_guardrail(snapshot, raw_text, session)


def _apply_personal_rate(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    session: Any | None = None,
):
    from genesis_cognitive.router.rate_context_guardrail import apply_personal_rate_guardrail
    return apply_personal_rate_guardrail(snapshot, raw_text, session)


def _apply_scope(snapshot: CustomerContextSnapshot | None, raw_text: str):
    from genesis_cognitive.router.scope_guardrail import apply_scope_guardrail
    return apply_scope_guardrail(snapshot, raw_text)


def _apply_reclamacion(
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    pending_knowledge_topic: str | None,
):
    from genesis_cognitive.router.reclamacion_guardrail import apply_reclamacion_guardrail
    return apply_reclamacion_guardrail(
        snapshot, raw_text, pending_topic=pending_knowledge_topic,
    )
