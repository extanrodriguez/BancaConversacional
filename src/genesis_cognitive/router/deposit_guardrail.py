"""Deposit unicidad guardrail — forces CLARIFICATION when 2+ accounts and no unique match."""

from __future__ import annotations

from typing import Any

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot

# Spanish type names for matching (no regex on business logic — just lookup table)
_TYPE_SPANISH = {
    "checking": ("corriente",),
    "savings": ("ahorro", "ahorros"),
    "payroll": ("nomina", "nómina"),
    "term_deposit": ("certificado", "deposito", "depósito", "dap", "cdt", "plazo"),
    "credit_card": ("tarjeta", "visa", "mastercard"),
    "loan": ("prestamo", "préstamo", "credito", "crédito"),
}


def enforce_deposit_clarification(
    status: str,
    actions_dump: list[dict[str, Any]],
    snapshot: CustomerContextSnapshot,
    raw_text: str,
    has_pending: bool,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Force CLARIFICATION if ACCOUNT_BALANCE_READ with 2+ deposits and no unique match.

    Returns (status, actions_dump, clarifications_dump).

    Exceptions (do NOT force):
      1. has_pending=True (continuation turn T2).
      2. raw_text uniquely identifies 1 product via alias/product_id/type match.
    """
    # Exception 1: continuation turn
    if has_pending:
        return status, actions_dump, []

    # If model returned CLARIFICATION but text uniquely identifies 1 deposit → resolve
    if status == "CLARIFICATION_REQUIRED":
        all_deposits = [
            p for p in snapshot.products
            if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL")
            and p.status.lower() == "active"
        ]
        # Apply currency hint filter
        _text_clar = raw_text.strip().lower()
        _DOP_SIG = ("pesos", "dop", "peso", "rd$")
        _USD_SIG = ("dolares", "dólares", "usd", "dollar", "us$")
        _ccy_hint_clar: str | None = None
        if any(s in _text_clar for s in _DOP_SIG):
            _ccy_hint_clar = "DOP"
        elif any(s in _text_clar for s in _USD_SIG):
            _ccy_hint_clar = "USD"
        else:
            # No currency hint → default currency only
            _ccy_hint_clar = snapshot.default_currency

        if _ccy_hint_clar:
            all_deposits = [p for p in all_deposits if p.currency == _ccy_hint_clar]

        if len(all_deposits) >= 2:
            cands = _find_text_candidates(_text_clar, all_deposits)
            if len(cands) == 1:
                # Unique match → resolve to VALID_CONTRACT
                resolved = cands[0]
                resolved_action = [{
                    "sequence": 1,
                    "intent_id": "ACCOUNT_BALANCE_READ",
                    "capability_candidate": "ACCOUNT_BALANCE",
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
                }]
                return "VALID_CONTRACT", resolved_action, []
        return status, actions_dump, []

    if status != "VALID_CONTRACT" or not actions_dump:
        return status, actions_dump, []

    action = actions_dump[0]
    if action.get("intent_id") != "ACCOUNT_BALANCE_READ":
        return status, actions_dump, []

    # Exception 3: if question is clearly about cards/loans, don't force deposit clarification
    _text = raw_text.strip().lower()
    _CARD_SIGNALS_GR = ("tarjeta", "visa", "mastercard", "pricesmart", "gold", "platinum", "black")
    _LOAN_SIGNALS_GR = ("prestamo", "préstamo", "credito", "crédito", "cuota", "fecha de pago")
    _LIST_SIGNALS_GR = ("que tarjetas", "qué tarjetas", "que productos", "portafolio", "que cuentas tengo", "qué cuentas tengo")
    if any(s in _text for s in _CARD_SIGNALS_GR + _LOAN_SIGNALS_GR + _LIST_SIGNALS_GR):
        return status, actions_dump, []

    ref = action.get("detected_entities", {}).get("account_ref")
    if ref is None:
        return status, actions_dump, []

    # Detect currency hint from user text
    _text = raw_text.strip().lower()
    _currency_hint: str | None = None
    _DOP_SIGNALS = ("pesos", "dop", "peso", "rd$")
    _USD_SIGNALS = ("dolares", "dólares", "usd", "dollar", "us$")
    if any(s in _text for s in _DOP_SIGNALS):
        _currency_hint = "DOP"
    elif any(s in _text for s in _USD_SIGNALS):
        _currency_hint = "USD"

    # Get visible deposit accounts (ACTIVE only, all currencies)
    deposits = [
        p for p in snapshot.products
        if p.product_type in ("CHECKING", "SAVINGS", "PAYROLL")
        and p.status.lower() == "active"
    ]

    # Filter by currency hint if user specified one; else default currency
    if _currency_hint:
        deposits = [p for p in deposits if p.currency == _currency_hint]
    else:
        text_lower_ccy = raw_text.strip().lower()
        type_hits = _find_text_candidates(text_lower_ccy, deposits)
        currencies = {p.currency for p in type_hits}
        if len(currencies) >= 2:
            deposits = type_hits
        else:
            deposits = [p for p in deposits if p.currency == snapshot.default_currency]

    if len(deposits) < 2:
        return status, actions_dump, []  # Only 1 deposit → OK

    # Tipo explícito sin productos de ese tipo (ej. corriente sin CHECKING)
    from genesis_cognitive.router.field_guardrails import _deposit_type_filter, _TYPE_LABEL_PLURAL
    _type_hint = _deposit_type_filter(raw_text)
    if _type_hint:
        _typed = [p for p in deposits if p.product_type == _type_hint]
        if not _typed:
            _greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
            _msg = f"{_greeting}no tienes cuentas {_TYPE_LABEL_PLURAL.get(_type_hint, 'de ese tipo')} activas en tu portafolio."
            _action = [{
                "sequence": 1,
                "intent_id": "ACCOUNT_BALANCE_READ",
                "capability_candidate": "ACCOUNT_BALANCE",
                "selected_route": "PERSONAL_READ",
                "detected_entities": {"account_ref": None},
                "missing_requirements": [],
                "depends_on": [],
                "confidence": 1.0,
            }]
            clar = [{
                "target_action_sequence": 1,
                "missing_requirements": [],
                "suggested_question": _msg,
                "already_known": [],
            }]
            return "VALID_CONTRACT", _action, clar

    # Exception 2: check if raw_text uniquely identifies 1 product
    text_lower = raw_text.strip().lower()
    candidates = _find_text_candidates(text_lower, deposits)

    if len(candidates) == 1:
        # User typed something that matches exactly 1 product → override ref if model picked wrong one
        matched = candidates[0]
        if actions_dump and actions_dump[0].get("detected_entities", {}).get("account_ref") != matched.product_id:
            actions_dump[0]["detected_entities"]["account_ref"] = matched.product_id
        return status, actions_dump, []

    # 2+ deposits, no unique text match → FORCE CLARIFICATION
    from genesis_cognitive.context.app_channel import build_account_disambiguation_question
    question = build_account_disambiguation_question(deposits)
    clar = [{
        "target_action_sequence": 1,
        "missing_requirements": ["account_ref"],
        "suggested_question": question,
        "already_known": [],
    }]
    return "CLARIFICATION_REQUIRED", [], clar


def _product_last_digits(product: Any, n: int = 4) -> str:
    if getattr(product, "card_mask", None):
        digits = "".join(ch for ch in str(product.card_mask) if ch.isdigit())
        if len(digits) >= n:
            return digits[-n:]
    if getattr(product, "last_four", None) and len(str(product.last_four)) >= n:
        return str(product.last_four)[-n:]
    pid = "".join(ch for ch in str(getattr(product, "product_id", "") or "") if ch.isdigit())
    return pid[-n:] if len(pid) >= n else pid


def _find_text_candidates(
    text_lower: str,
    deposits: list,
) -> list:
    """Find products by alias, product_id, last digits, option-ref or type in text.

    Returns matching products. Exactly 1 ⇒ selección única (card / dígitos / alias).
    """
    import re

    digit_hints = sorted(set(re.findall(r"\d{3,}", text_lower or "")), key=len, reverse=True)
    candidates = []
    for p in deposits:
        matched = False
        last4 = _product_last_digits(p, 4)
        last5 = _product_last_digits(p, 5)
        if last4 and (
            f"_{last4}" in text_lower
            or f"- {last4}" in text_lower
            or f"-{last4}" in text_lower
            or f"···{last4}" in text_lower
            or f"...{last4}" in text_lower
            or f"…{last4}" in text_lower
            or f"••••{last4}" in text_lower
            or f"****{last4}" in text_lower
            or ("terminad" in text_lower and last4 in text_lower)
        ):
            matched = True
        if not matched and digit_hints:
            for hint in digit_hints:
                if last4 and hint.endswith(last4):
                    matched = True
                    break
                if last5 and len(hint) >= 5 and hint.endswith(last5):
                    matched = True
                    break
                pid_digits = "".join(ch for ch in str(p.product_id) if ch.isdigit())
                if len(hint) >= 4 and hint in pid_digits:
                    matched = True
                    break
        if not matched and p.alias:
            alias_lower = p.alias.lower()
            generic = alias_lower in {
                "certificado de depósito",
                "certificado de deposito",
                "depósito a plazo",
                "deposito a plazo",
                "préstamo",
                "prestamo",
                "tarjeta",
                "tarjeta de crédito",
                "tarjeta de credito",
            }
            if not generic and (alias_lower in text_lower or text_lower in alias_lower):
                matched = True
            elif not generic:
                # Tokens significativos del nombre comercial (Visa Joven, Multicrédito…)
                tokens = [
                    tok
                    for tok in re.split(r"[^\wáéíóúñü]+", alias_lower, flags=re.I)
                    if len(tok) >= 4 and tok not in {"tarjeta", "credito", "crédito", "visa", "cuenta", "deposito", "depósito"}
                ]
                if tokens and all(tok in text_lower for tok in tokens[-2:]):
                    matched = True
                elif any(len(tok) >= 5 and tok in text_lower for tok in tokens):
                    matched = True
            elif generic and last4 and last4 in text_lower:
                matched = True
        if not matched and p.product_id.lower() in text_lower:
            matched = True
        if not matched:
            type_key = p.product_type.lower()
            for sname in _TYPE_SPANISH.get(type_key, ()):
                if sname in text_lower:
                    same_type = [x for x in deposits if x.product_type == p.product_type]
                    if len(same_type) == 1:
                        matched = True
                    break
        if matched:
            candidates.append(p)

    if len(candidates) > 1 and digit_hints:
        narrowed = [
            p
            for p in candidates
            if any(
                h.endswith(_product_last_digits(p, 4))
                for h in digit_hints
                if _product_last_digits(p, 4)
            )
        ]
        if narrowed:
            return narrowed

    # Varios alias comparten token (p. ej. "joven") → preferir el más específico
    if len(candidates) > 1:
        def _alias_score(p) -> int:
            alias = (p.alias or "").lower().strip()
            if not alias:
                return 0
            score = 0
            if alias in text_lower:
                score += 100 + len(alias)
            # Frase completa sin genéricos
            compact = re.sub(r"\s+", " ", alias)
            if compact and compact in text_lower:
                score += 80
            toks = [
                tok
                for tok in re.split(r"[^\wáéíóúñü]+", alias, flags=re.I)
                if len(tok) >= 3 and tok not in {"de", "del", "la", "el", "tarjeta"}
            ]
            hit_toks = [tok for tok in toks if tok in text_lower]
            score += sum(len(tok) for tok in hit_toks) * 3
            # Penalizar tokens compartidos sueltos si faltan otros del alias
            if toks and len(hit_toks) < len(toks):
                score -= 15 * (len(toks) - len(hit_toks))
            return score

        ranked = sorted((( _alias_score(p), p) for p in candidates), key=lambda x: x[0], reverse=True)
        best_score = ranked[0][0]
        winners = [p for s, p in ranked if s == best_score and s > 0]
        if len(winners) == 1:
            return winners
        # Empate: preferir alias más corto contenido en el texto (más específico comercial)
        contained = [p for p in winners if (p.alias or "").lower() in text_lower]
        if len(contained) == 1:
            return contained
    return candidates
