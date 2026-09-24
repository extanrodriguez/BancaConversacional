"""Snapshot guardrails — deterministic POST-pipeline corrections based on customer context."""

from __future__ import annotations

import re

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


def apply_loan_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
) -> list[dict]:
    """Apply loan unicidad guardrail AFTER pipeline resolution.

    Only modifies the result when:
    - intent_id == LOAN_DETAIL_READ
    - account_ref is null
    - Customer has exactly 1 LOAN in portfolio

    Does NOT touch:
    - ACCOUNT_BALANCE_READ or any other intent
    - Cases with 2+ LOANs (pipeline already produces CLARIFICATION)
    - Cases where account_ref is already resolved

    Returns: modified actions list (or original if no change needed).
    """
    if snapshot is None:
        return actions

    if status != "VALID_CONTRACT":
        return actions

    if not actions:
        return actions

    action = actions[0]
    intent_id = action.get("intent_id")

    # Only intervene for LOAN_DETAIL_READ
    if intent_id != "LOAN_DETAIL_READ":
        return actions

    entities = action.get("detected_entities", {})
    account_ref = entities.get("account_ref")

    # Only if account_ref is null (not already resolved)
    if account_ref is not None:
        return actions

    # Count LOANs in snapshot
    loans = [p for p in snapshot.products if p.product_type == "LOAN"]

    # Guardrail: exactly 1 LOAN → force ref
    if len(loans) == 1:
        # Create modified action with the single LOAN's product_id
        modified_entities = dict(entities)
        modified_entities["account_ref"] = loans[0].product_id
        modified_action = dict(action)
        modified_action["detected_entities"] = modified_entities
        return [modified_action] + actions[1:]

    # 2+ LOANs: do not force (pipeline handles via CLARIFICATION)
    # 0 LOANs: do not force (shouldn't happen for LOAN_DETAIL_READ)
    return actions


_LOAN_HINTS: tuple[tuple[str, ...], ...] = (
    ("hipotec", "vivienda"),
    ("vehic", "carro", "auto", "motor"),
    ("personal", "consumo", "libre"),
)


def _fold_loan_text(value: str) -> str:
    """Normaliza acentos para matching robusto (vehículo ≈ vehiculo)."""
    t = (value or "").lower()
    for src, dst in (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"), ("ñ", "n"),
    ):
        t = t.replace(src, dst)
    return t


def _loan_text_matches(text: str, product) -> bool:
    alias = _fold_loan_text(product.alias or "")
    text_n = _fold_loan_text(text)
    pid = (product.product_id or "").lower()
    if pid and pid in text_n:
        return True

    digits_pid = "".join(ch for ch in (product.product_id or "") if ch.isdigit())
    last4 = digits_pid[-4:] if len(digits_pid) >= 4 else digits_pid
    last5 = digits_pid[-5:] if len(digits_pid) >= 5 else digits_pid
    digit_hints = re.findall(r"\d{4,}", text_n)

    if digit_hints:
        # Con dígitos en el texto: solo máscara/id (el alias "Préstamo" no desambigua).
        for hint in digit_hints:
            if digits_pid.endswith(hint) or hint in (last4, last5):
                return True
        return False

    for group in _LOAN_HINTS:
        folded = tuple(_fold_loan_text(h) for h in group)
        if any(h in text_n for h in folded) and any(h in alias for h in folded):
            return True
    # Alias genérico no cuenta como identificación única
    if alias and alias in text_n and alias not in ("prestamo", "credito", "loan"):
        return True
    return False


def resolve_loan_type_hint(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict]]:
    """If the user named a unique loan type, resolve CLARIFICATION to that loan."""
    if snapshot is None or status != "CLARIFICATION_REQUIRED":
        return status, actions
    text = (raw_text or "").lower()
    loans = [
        p
        for p in snapshot.products
        if p.product_type == "LOAN" and str(p.status).lower() == "active"
    ]
    matches = [p for p in loans if _loan_text_matches(text, p)]
    if len(matches) != 1:
        return status, actions
    resolved = matches[0]
    return "VALID_CONTRACT", [
        {
            "sequence": 1,
            "intent_id": "LOAN_DETAIL_READ",
            "capability_candidate": "LOAN_DETAIL",
            "selected_route": "PERSONAL_READ",
            "detected_entities": {
                "account_ref": resolved.product_id,
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
    ]


_UNIQUE_INTENTS: dict[str, str] = {
    "CREDIT_CARD_DETAIL_READ": "CREDIT_CARD",
    "TERM_DEPOSIT_DETAIL_READ": "TERM_DEPOSIT",
    "LOAN_DETAIL_READ": "LOAN",
}

_CARD_WORD = re.compile(r"\btarjeta|\bvisa\b|\bmastercard\b", re.I)

_LOAN_FIELD_SIGNALS = (
    "cuota",
    "letra",
    "mensualidad",
    "saldar",
    "cancelar",
    "liquidar",
    "cancelacion",
    "cancelación",
    "hipotec",
    "debo",
    "deuda",
    "desembols",
    "me prestaron",
    "vence",
    "vencimiento",
    # No usar "termina" suelto: choca con "terminada en 63641" (máscara de cuenta).
    "cuando termina",
    "termina de pagar",
    "fecha en que termina",
    "en que termina",
    "en qué termina",
    "me toca pagar",
    "pago mensual",
    "pago al mes",
    "saldo de mi préstamo",
    "saldo de mi prestamo",
    "saldo de cancel",
    "todos los detalles",
    "toda la informacion",
    "toda la información",
    "informacion completa",
    "información completa",
    "detalles de mi préstamo",
    "detalles de mi prestamo",
    "resumen del préstamo",
    "resumen del prestamo",
    "como esta mi préstamo",
    "cómo está mi préstamo",
    "como esta mi prestamo",
    "está al día",
    "esta al dia",
    "tengo atrasos",
    "debo todavía",
    "debo todavia",
)

# Campos del préstamo en contexto (deíxis): "qué tasa tiene", "y la mora?"
# No van en _LOAN_FIELD_SIGNALS sueltos para no robar definiciones FAQ sin contexto.
_LOAN_DEICTIC_FIELD_SIGNALS = (
    "tasa",
    "interes",
    "interés",
    "mora",
    "capital",
    "adeudado",
    "cuota",
    "letra",
    "deuda",
    "debo",
    "saldo",
    "balance",
    "vence",
    "vencimiento",
    "proxima",
    "próxima",
    "fecha de pago",
    "fecha limite",
    "fecha límite",
    "limite de pago",
    "límite de pago",
    "saldar",
    "cancelar",
    "liquidar",
)


def _is_loan_definition_question(text: str) -> bool:
    t = (text or "").lower()
    return any(
        s in t
        for s in (
            "qué es", "que es", "qué significa", "que significa",
            "definición", "definicion", "explícame qué es", "explicame que es",
            "explícame", "explicame", "cuéntame", "cuentame", "háblame", "hablame",
            "tipos de préstamo", "tipos de prestamo", "préstamos que ofrece",
            "prestamos que ofrece", "puedo contratar", "puedo solicitar",
            "cómo se pagan", "como se pagan", "cómo se paga", "como se paga",
            "cómo pago las cuotas", "como pago las cuotas",
            "diferencia", "con garantía", "con garantia", "sin garantía", "sin garantia",
            "qué tipos de préstamo", "que tipos de prestamo",
        )
    )


def is_loan_deictic_field_question(text: str) -> bool:
    """True para follow-ups de campo sobre el préstamo ya resuelto (sin decir 'préstamo')."""
    t = (text or "").lower().strip()
    if not t or _is_loan_definition_question(t):
        return False
    if any(s in t for s in _LOAN_KNOWLEDGE_SIGNALS):
        return False
    # Evitar catálogo institucional / tarifario genérico
    if any(
        s in t
        for s in (
            "tarifario", "www.bsc", "banco ofrece", "el banco",
            "puedo contratar", "requisito",
        )
    ):
        return False
    return any(s in t for s in _LOAN_DEICTIC_FIELD_SIGNALS) and len(t) < 120

_LOAN_KNOWLEDGE_SIGNALS = (
    "requisito",
    "documento",
    "solicitar",
    "precalif",
    "como pido",
    "cómo pido",
    "para un crédito hipotecario",
    "para un credito hipotecario",
)

_LOAN_SWITCH_PREFIXES = (
    "cambia al",
    "cambia a la",
    "cambia a el",
    "cambia a ",
    "cambiar al",
    "cambiar a ",
    "ahora el",
    "ahora la",
    "ahora revisa",
    "revisa el",
    "revisa la",
    "revisar el",
    "revisar la",
    "y del",
    "y de la",
    "y de el",
    "¿y del",
    "¿y de",
    "y el préstamo",
    "y el prestamo",
)

_LOAN_TYPE_HINTS = (
    "personal",
    "hipotec",
    "vehic",
    "consumo",
    "vivienda",
    "auto",
    "carro",
    "motor",
)


def _is_loan_context_switch(text: str) -> bool:
    """Matriz filas 63-64 — tipo de préstamo o cambio explícito en contexto."""
    t = (text or "").lower()
    has_type = any(h in t for h in _LOAN_TYPE_HINTS)
    has_loan_word = "prestamo" in t or "préstamo" in t
    has_prefix = any(p in t for p in _LOAN_SWITCH_PREFIXES)
    if has_type and (has_prefix or has_loan_word):
        return True
    if has_prefix and (has_type or has_loan_word):
        return True
    return False


def is_loan_field_question(text: str, *, allow_deictic_fields: bool = False) -> bool:
    """True when the client is asking for a loan data field, not catalog knowledge.

    Con allow_deictic_fields=True (hay last_resolved de préstamo), también acepta
    "qué tasa tiene" / "y la mora?" sin repetir la palabra préstamo.
    """
    t = (text or "").lower()
    # Multicrédito / Cuotas BSC / Crédito Diferido = conocimiento (salvo "mi cuota")
    if any(
        s in t
        for s in (
            "multicredit",
            "multicrédito",
            "cuotas bsc",
            "credito diferido",
            "crédito diferido",
        )
    ) and not any(s in t for s in ("mi cuota", "mi prestamo", "mi préstamo", "mi credito", "mi crédito")):
        return False
    if any(s in t for s in ("compar", "diferenc", "disting", "versus", " vs ")):
        return False
    if any(s in t for s in _LOAN_KNOWLEDGE_SIGNALS):
        return False
    # Definiciones / catálogo ("¿qué es un préstamo personal?") → FAQ/RAG, no portafolio
    if _is_loan_definition_question(t):
        return False
    # Máscara de producto ("terminada en 1234") no es señal de préstamo.
    if re.search(r"terminad[oa]\s+en\b", t) and not any(
        s in t for s in ("prestamo", "préstamo", "cuota", "letra", "credito", "crédito", "hipotec")
    ):
        return False
    # Saldo de cuenta/ahorro con dígitos → balance, no préstamo.
    if any(s in t for s in ("cuenta", "ahorro", "ahorros", "corriente", "nomina", "nómina")) and any(
        s in t for s in ("saldo", "balance", "disponible")
    ):
        if not any(s in t for s in ("prestamo", "préstamo", "cuota", "letra", "credito", "crédito")):
            return False
    if _is_loan_context_switch(t):
        return True
    if any(s in t for s in ("tarjeta", "deposito", "depósito", "certificado", "dap")) and not any(
        s in t for s in ("prestamo", "préstamo", "cuota", "letra")
    ):
        return False
    if any(s in t for s in _LOAN_FIELD_SIGNALS):
        return True
    # Nota: "cuál es mi tasa?" genérica NO se fuerza a préstamo aquí;
    # rate_context_guardrail decide por portafolio + foco.
    if any(s in t for s in ("movimiento", "transaccion", "transacción", "historial")) and any(
        s in t for s in ("prestamo", "préstamo", "cuota", "letra")
    ):
        return True
    if any(s in t for s in ("prestamo", "préstamo")) and any(
        s in t
        for s in (
            "cuanto", "cuánto", "cual", "cuál", "cuando", "cuándo", "saldo", "balance",
            "tasa",
            "interes", "interés", "mora", "capital", "adeudado",
            "detalle", "info", "informacion", "información", "estado", "atras",
            "dame", "muestr", "consultar", "consulta", "tiene", "dime",
        )
    ):
        return True
    # Selección de card/opción APK: "Préstamo ···7615" / "Préstamo ...27615" / PRESTAMO_7615
    if any(s in t for s in ("prestamo", "préstamo")) and (
        re.search(r"\d{4,}", t)
        or "prestamo_" in t.replace("é", "e")
        or "préstamo_" in t
    ):
        return True
    if allow_deictic_fields and is_loan_deictic_field_question(t):
        return True
    return False


def _loan_detail_action(account_ref: str | None) -> dict:
    return {
        "sequence": 1,
        "intent_id": "LOAN_DETAIL_READ",
        "capability_candidate": "LOAN_DETAIL",
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


def apply_loan_field_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
    last_resolved_ref: str | None = None,
    *,
    allow_deictic_fields: bool = False,
) -> tuple[str, list[dict], list[dict] | None]:
    """Force loan resolution/clarification for loan-field questions.

    Returns (status, actions, clarifications). clarifications is None when
    this guardrail should not replace existing clarification text.
    """
    if snapshot is None or not is_loan_field_question(
        raw_text, allow_deictic_fields=allow_deictic_fields,
    ):
        return status, actions, None
    intent = actions[0].get("intent_id") if actions else None
    if intent == "BUSINESS_KNOWLEDGE_QUERY":
        return status, actions, None

    loans = [
        p
        for p in snapshot.products
        if p.product_type == "LOAN" and str(p.status).lower() == "active"
    ]
    if not loans:
        return status, actions, None

    ref = (actions[0].get("detected_entities") or {}).get("account_ref") if actions else None
    loan_ids = {p.product_id for p in loans}
    if ref in loan_ids and status == "VALID_CONTRACT":
        if intent == "LOAN_DETAIL_READ":
            return status, actions, None
        return "VALID_CONTRACT", [_loan_detail_action(ref)], []

    if len(loans) == 1:
        return "VALID_CONTRACT", [_loan_detail_action(loans[0].product_id)], []

    matches = [p for p in loans if _loan_text_matches(raw_text or "", p)]
    if len(matches) == 1:
        return "VALID_CONTRACT", [_loan_detail_action(matches[0].product_id)], []

    if last_resolved_ref in loan_ids and len(matches) == 0:
        # Listado / "mis préstamos" → no reusar el foco; pedir o listar
        from genesis_cognitive.router.product_focus import is_loan_list_question

        if not is_loan_list_question(raw_text or ""):
            return "VALID_CONTRACT", [_loan_detail_action(last_resolved_ref)], []

    from genesis_cognitive.context.app_channel import build_loan_disambiguation_question

    question = build_loan_disambiguation_question(loans)
    clarifications = [
        {
            "target_action_sequence": 1,
            "missing_requirements": ["account_ref"],
            "suggested_question": question,
            "already_known": [],
        }
    ]
    return "CLARIFICATION_REQUIRED", [_loan_detail_action(None)], clarifications


def apply_unique_product_guardrail(
    status: str,
    actions: list[dict],
    snapshot: CustomerContextSnapshot | None,
    raw_text: str,
) -> tuple[str, list[dict]]:
    """If the user asked a product family that has exactly one active item, resolve it."""
    if snapshot is None:
        return status, actions
    text = (raw_text or "").lower()
    intent = actions[0].get("intent_id") if actions else None
    wanted_type = _UNIQUE_INTENTS.get(intent or "")
    if wanted_type is None:
        if _CARD_WORD.search(text):
            wanted_type, intent = "CREDIT_CARD", "CREDIT_CARD_DETAIL_READ"
        elif any(s in text for s in ("deposito", "depósito", "certificado", "dap", "cdt", "capitaliz", "modalidad")):
            wanted_type, intent = "TERM_DEPOSIT", "TERM_DEPOSIT_DETAIL_READ"
        elif is_loan_field_question(text):
            wanted_type, intent = "LOAN", "LOAN_DETAIL_READ"
        else:
            return status, actions
    actives = [
        p for p in snapshot.products
        if p.product_type == wanted_type and str(p.status).lower() == "active"
    ]
    if len(actives) != 1:
        return status, actions
    if status not in ("VALID_CONTRACT", "CLARIFICATION_REQUIRED", "NON_OPERATIONAL", "INVALID_MODEL_OUTPUT"):
        return status, actions
    ref = (actions[0].get("detected_entities") or {}).get("account_ref") if actions else None
    if status == "VALID_CONTRACT" and ref:
        return status, actions
    resolved = actives[0]
    cap = {
        "CREDIT_CARD": "CREDIT_CARD_DETAIL",
        "TERM_DEPOSIT": "TERM_DEPOSIT_DETAIL",
        "LOAN": "LOAN_DETAIL",
    }[wanted_type]
    return "VALID_CONTRACT", [
        {
            "sequence": 1,
            "intent_id": intent,
            "capability_candidate": cap,
            "selected_route": "PERSONAL_READ",
            "detected_entities": {
                "account_ref": resolved.product_id,
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
    ]
