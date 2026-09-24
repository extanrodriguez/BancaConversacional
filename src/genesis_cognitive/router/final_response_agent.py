"""FinalResponseAgent — generates client-facing text from resolved data."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_framework import Agent, ChatOptions, Message

from genesis_cognitive.telemetry.llm_call_timer import LlmCallRecord, time_llm_call

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["client_response"],
    "properties": {
        "client_response": {"type": "string"},
    },
}

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "FinalResponse",
        "strict": True,
        "schema": _RESPONSE_SCHEMA,
    },
}


class FinalResponseAgent:
    """Generates a client-facing response using ONLY provided data."""

    def __init__(self, agent: Agent[Any]) -> None:
        self._agent = agent

    async def generate(
        self,
        *,
        status: str,
        intent_id: str | None,
        account_ref: str | None,
        loan_detail: dict[str, Any] | None,
        display_name: str | None,
        question: str | None = None,
    ) -> str:
        """Generate client_response text. Returns string."""
        context = json.dumps({
            "status": status,
            "intent_id": intent_id,
            "account_ref": account_ref,
            "loan_detail": loan_detail,
            "display_name": display_name,
            "user_question": question,
        }, ensure_ascii=False)

        messages: list[Message] = [
            Message(role="user", contents=[context]),
        ]
        options = ChatOptions(response_format=_RESPONSE_FORMAT, temperature=0.3)

        try:
            response = await self._agent.run(messages, options=options)
            value = response.value
            if isinstance(value, dict):
                return value.get("client_response", "")
            return ""
        except Exception:
            return ""

    async def generate_timed(
        self,
        *,
        status: str,
        intent_id: str | None,
        account_ref: str | None,
        loan_detail: dict[str, Any] | None,
        display_name: str | None,
        question: str | None = None,
        deployment: str = "gpt-4o-mini",
    ) -> tuple[str, LlmCallRecord | None]:
        """Generate client_response with timing. Returns (text, call_record)."""
        import time as _time_mod

        context = json.dumps({
            "status": status,
            "intent_id": intent_id,
            "account_ref": account_ref,
            "loan_detail": loan_detail,
            "display_name": display_name,
            "user_question": question,
        }, ensure_ascii=False)

        messages: list[Message] = [
            Message(role="user", contents=[context]),
        ]
        options = ChatOptions(response_format=_RESPONSE_FORMAT, temperature=0.3)

        start = _time_mod.perf_counter()
        try:
            record, response = await time_llm_call(
                name="final_response",
                coro=self._agent.run(messages, options=options),
                deployment=deployment,
            )
            value = response.value
            if isinstance(value, dict):
                return value.get("client_response", ""), record
            return "", record
        except Exception:
            elapsed_ms = round((_time_mod.perf_counter() - start) * 1000)
            fail_record = LlmCallRecord(
                name="final_response", duration_ms=elapsed_ms,
                deployment=deployment, ok=False, error_type="Other",
            )
            return "", fail_record


def build_client_response_no_llm(
    *,
    status: str,
    clarifications: list[dict[str, Any]],
    display_name: str | None,
) -> str | None:
    """Build client_response WITHOUT LLM for non-VALID_CONTRACT cases.

    Returns the response string, or None if LLM should handle it.
    """
    if status == "CLARIFICATION_REQUIRED":
        if clarifications:
            suggested = (clarifications[0].get("suggested_question") or "").strip()
            generic = suggested.lower() in {
                "",
                "¿puedo ayudarte con algo más?",
                "puedo ayudarte con algo más?",
                "necesito mas informacion.",
                "necesito más información.",
            }
            if suggested and not generic:
                return suggested
        return None

    if status in ("UNSUPPORTED",):
        return (
            "Lo siento, aún no tengo habilitados los canales para realizar transferencias, "
            "retiros u otras operaciones. Puedo ayudarte con consultas de saldos, préstamos, "
            "tarjetas o información del banco."
        )

    if status == "NON_OPERATIONAL":
        name = display_name or ""
        if name:
            return f"¡Hola, {name}! ¿En qué puedo ayudarte?"
        return "¡Hola! ¿En qué puedo ayudarte?"

    return None  # Needs LLM (VALID_CONTRACT with data)


_UNAVAILABLE = "Ese dato no está disponible en este momento."


def _greeting(display_name: str | None) -> str:
    name = (display_name or "").strip()
    return f"{name}, " if name else ""


def _safe_loan_mask(loan_detail: dict[str, Any] | None) -> str:
    if not loan_detail:
        return ""
    raw = str(loan_detail.get("last_four") or "")
    if "-" in raw or not raw.isdigit() or len(raw) != 4:
        pid = str(loan_detail.get("product_id") or "")
        digits = "".join(ch for ch in pid if ch.isdigit())
        raw = digits[-4:] if len(digits) >= 4 else ""
    return f" terminado en {raw}" if raw else ""


def build_loan_detail_response(
    question: str | None,
    loan_detail: dict[str, Any] | None,
    display_name: str | None,
) -> str:
    """Deterministic loan answer. Never invents amounts or uses a date as mask.

    Consulta general → ficha markdown (APK). Campo puntual → frase corta.
    """
    hello = _greeting(display_name)
    q = (question or "").lower()
    if not loan_detail:
        return f"{hello}{_UNAVAILABLE}"

    mask = _safe_loan_mask(loan_detail)
    cuota = loan_detail.get("installment_amount")
    deuda = loan_detail.get("outstanding_principal")
    tasa = loan_detail.get("annual_interest_rate")
    proxima = loan_detail.get("next_due_date")
    vence = loan_detail.get("maturity_date")
    desembolso = loan_detail.get("disbursed_amount")
    cancelacion = loan_detail.get("payoff_amount")
    mora = loan_detail.get("overdue_amount")
    estado = loan_detail.get("status_label") or "al dia"

    # Campo puntual → respuesta corta (no ficha completa)
    specific = any(
        s in q
        for s in (
            "transaccion", "transacción", "movimiento", "historial",
            "ultimos pagos", "últimos pagos", "ultimo pago", "último pago",
            "cancelar", "saldar", "liquidar", "saldo de cancelacion", "saldo de cancelación",
            "para saldar", "total adeudado",
            "prestaron", "desembols", "monto original", "cuanto me dieron", "cuánto me dieron",
            "tasa", "interes", "interés",
            "proxima", "próxima", "proximo pago", "próximo pago",
            "cuando me toca", "cuándo me toca", "proxima fecha", "próxima fecha",
            "fecha de pago", "fecha límite de pago", "fecha limite de pago",
            "fecha limite", "fecha límite", "limite de pago", "límite de pago",
            "cuando pago", "cuándo pago", "cuando debo pagar", "cuándo debo pagar",
            "cuando termina", "cuándo termina", "fecha de vencimiento", "vencimiento del",
            "hasta cuando", "hasta cuándo", "vence", "vencimiento",
            "mora", "atrasado", "vencid", "en atraso",
            "cuota", "letra", "mensualidad", "pago al mes", "pago mensual", "cuanto pago", "cuánto pago",
            "al dia", "al día", "atraso", "estado",
            "debo", "deuda", "capital", "saldo pendiente", "cuanto me falta", "cuánto me falta",
            "saldo actual", "saldo de mi prestamo", "saldo de mi préstamo",
            "balance", "balance de mi prestamo", "balance de mi préstamo",
            "el balance de mi", "dime el balance", "dame el balance",
        )
    )

    if not specific:
        from genesis_cognitive.context.response_formatting import build_rich_loan_from_detail

        rich = build_rich_loan_from_detail(loan_detail)
        return f"{hello.rstrip(', ')}\n{rich}" if hello else rich

    if any(s in q for s in ("transaccion", "transacción", "movimiento", "historial", "ultimos pagos", "últimos pagos", "ultimo pago", "último pago")):
        return (
            f"{hello}{_UNAVAILABLE} Puedo indicarte el capital pendiente, "
            f"la tasa o la próxima fecha de pago de tu préstamo{mask}."
        )
    if any(s in q for s in ("cancelar", "saldar", "liquidar", "saldo de cancelacion", "saldo de cancelación", "para saldar", "total adeudado")):
        if cancelacion:
            return f"{hello}el saldo de cancelación de tu préstamo{mask} es {cancelacion} DOP."
        if deuda:
            return f"{hello}el capital pendiente de tu préstamo{mask} es {deuda} DOP."
        return f"{hello}{_UNAVAILABLE}"
    if any(s in q for s in ("prestaron", "desembols", "monto original", "cuanto me dieron", "cuánto me dieron")):
        if desembolso:
            return f"{hello}el monto desembolsado de tu préstamo{mask} es {desembolso} DOP."
        return f"{hello}{_UNAVAILABLE}"
    if "tasa" in q or (("interes" in q or "interés" in q) and "cuota" not in q and "generado" not in q):
        if tasa:
            return f"{hello}la tasa de tu préstamo{mask} es {tasa}% anual."
        return f"{hello}{_UNAVAILABLE}"

    # Monto de cuota ANTES de "próxima" (evita "cuánto es mi próxima cuota" → fecha)
    wants_cuota_monto = (
        any(s in q for s in ("cuota", "letra", "mensualidad", "pago al mes", "pago mensual"))
        and any(s in q for s in ("cuanto", "cuánto", "monto", "valor", "de cuanto", "de cuánto", "cual es", "cuál es"))
        and not any(s in q for s in ("cuando", "cuándo", "fecha", "vence"))
    ) or any(s in q for s in ("cuanto pago", "cuánto pago", "monto de la cuota", "valor de la cuota"))
    if wants_cuota_monto and "cancelar" not in q:
        cuota_ok = cuota not in (None, "", "0", "0.0", "0.00")
        try:
            if cuota_ok and float(str(cuota).replace(",", "")) <= 0:
                cuota_ok = False
        except (TypeError, ValueError):
            pass
        if cuota_ok:
            return f"{hello}la cuota de tu préstamo{mask} es {cuota} DOP."
        bits: list[str] = []
        if proxima:
            bits.append(f"próxima fecha de pago **{proxima}**")
        if deuda:
            bits.append(f"capital pendiente **{deuda} DOP**")
        if tasa:
            bits.append(f"tasa **{tasa}%** anual")
        if mora:
            bits.append(f"mora reportada **{mora} DOP** (no es la cuota contractual)")
        offer = (" Sí puedo indicarte: " + "; ".join(bits) + ".") if bits else ""
        return (
            f"{hello}no tengo el monto de la cuota contractual de tu préstamo{mask} "
            f"en el contexto disponible en este momento.{offer} "
            "También puedes consultarlo en BSC en Línea o en el Centro de Contacto (809.726.1000)."
        )

    if any(s in q for s in (
        "proxima fecha", "próxima fecha", "proximo pago", "próximo pago",
        "cuando me toca", "cuándo me toca",
        "fecha de pago", "fecha límite de pago", "fecha limite de pago",
        "fecha limite", "fecha límite", "limite de pago", "límite de pago",
        "cuando pago", "cuándo pago", "cuando debo pagar", "cuándo debo pagar",
        "cuando es mi proxima", "cuándo es mi próxima", "cuando es la proxima", "cuándo es la próxima",
    )) or (
        # "próxima" solo como fecha si NO pide monto de cuota
        any(s in q for s in ("proxima", "próxima"))
        and not any(s in q for s in ("cuanto", "cuánto", "monto", "valor"))
        and (
            any(s in q for s in ("cuando", "cuándo", "fecha", "pago", "vence"))
            or ("cuota" not in q and "letra" not in q)
        )
    ):
        if proxima:
            return f"{hello}la próxima fecha de pago de tu préstamo{mask} es **{proxima}**."
        return f"{hello}la fecha de pago de tu préstamo{mask} no está disponible en este momento."
    if any(s in q for s in ("cuando termina", "cuándo termina", "fecha de vencimiento", "vencimiento del", "hasta cuando", "hasta cuándo")):
        if vence:
            return f"{hello}tu préstamo{mask} vence el {vence}."
        return f"{hello}{_UNAVAILABLE}"
    if "vence" in q and "cuota" in q:
        if proxima:
            return f"{hello}la próxima cuota de tu préstamo{mask} vence el {proxima}."
        return f"{hello}{_UNAVAILABLE}"
    if "vence" in q or "vencimiento" in q:
        if vence:
            return f"{hello}tu préstamo{mask} vence el {vence}."
        return f"{hello}{_UNAVAILABLE}"
    if any(s in q for s in ("mora", "atrasado", "vencid", "en atraso")) and "estado" not in q:
        if mora:
            return f"{hello}tienes {mora} DOP en mora en tu préstamo{mask}."
        return f"{hello}tu préstamo{mask} no presenta monto en mora reportado."
    if any(s in q for s in ("cuota", "letra", "mensualidad", "pago al mes", "pago mensual", "cuanto pago", "cuánto pago", "monto de la cuota", "valor de la cuota")) and "cancelar" not in q:
        # "0" / vacío no cuentan como cuota (API de portafolio no trae cuota contractual)
        cuota_ok = cuota not in (None, "", "0", "0.0", "0.00")
        try:
            if cuota_ok and float(str(cuota).replace(",", "")) <= 0:
                cuota_ok = False
        except (TypeError, ValueError):
            pass
        if cuota_ok:
            return f"{hello}la cuota de tu préstamo{mask} es {cuota} DOP."
        # No inventar con mora (pendingBalancePr). Ofrecer lo que sí hay en el snapshot.
        bits = []
        if proxima:
            bits.append(f"próxima fecha de pago **{proxima}**")
        if deuda:
            bits.append(f"capital pendiente **{deuda} DOP**")
        if tasa:
            bits.append(f"tasa **{tasa}%** anual")
        if mora:
            bits.append(f"mora reportada **{mora} DOP** (no es la cuota contractual)")
        offer = (" Sí puedo indicarte: " + "; ".join(bits) + ".") if bits else ""
        return (
            f"{hello}no tengo el monto de la cuota contractual de tu préstamo{mask} "
            f"en el contexto disponible en este momento.{offer} "
            "También puedes consultarlo en BSC en Línea o en el Centro de Contacto (809.726.1000)."
        )
    if any(s in q for s in ("al dia", "al día", "atraso", "estado")):
        if mora:
            return f"{hello}tu préstamo{mask} está {estado} (mora: {mora} DOP)."
        return f"{hello}tu préstamo{mask} está {estado}."
    if any(s in q for s in (
        "debo", "deuda", "capital", "saldo pendiente", "cuanto me falta", "cuánto me falta",
        "saldo actual", "saldo de mi prestamo", "saldo de mi préstamo",
        "balance", "el balance",
    )):
        if deuda:
            return f"{hello}el capital pendiente de tu préstamo{mask} es {deuda} DOP."
        return f"{hello}{_UNAVAILABLE}"

    # Fallback seguro: ficha completa (no inventar narrativa)
    from genesis_cognitive.context.response_formatting import build_rich_loan_from_detail

    rich = build_rich_loan_from_detail(loan_detail)
    return f"{hello.rstrip(', ')}\n{rich}" if hello else rich


def _build_card_multi_field_parts(q: str, card: Any, label: str) -> list[str]:
    """Detecta varios campos de TC en una sola pregunta y arma frases cortas."""
    from genesis_cognitive.context.response_formatting import format_money

    t = (q or "").lower()
    wants_balance = any(
        s in t
        for s in (
            "saldo actual", "saldo adeudado", "cuanto debo", "cuánto debo",
            "lo que debo", "adeud", "e k debo", "k debo", "debo d ", "debo de",
            "balance actual", "balance adeudado",
        )
    ) or bool(re.search(r"\bsaldo\b", t) and "disponible" not in t.split("saldo", 1)[-1][:20])
    wants_min = any(s in t for s in ("pago minimo", "pago mínimo")) or (
        ("minimo" in t or "mínimo" in t) and "consumo" not in t
    )
    wants_avail = any(
        s in t
        for s in (
            "disponible", "cupo", "limite disponible", "límite disponible",
            "credito disponible", "crédito disponible",
            "balance disponible", "saldo disponible",
        )
    )
    wants_limit = (
        any(s in t for s in ("limite de credito", "límite de crédito", "limite de la tarjeta", "límite de la tarjeta"))
        or (
            ("limite" in t or "límite" in t)
            and "pago" not in t
            and "fecha" not in t
            and "disponible" not in t
        )
    )
    wants_due = any(
        s in t
        for s in (
            "fecha limite", "fecha límite", "fecha de pago", "limite de pago", "límite de pago",
            "cuando debo pagar", "cuándo debo pagar", "cuando pago", "cuándo pago",
            "cuando me toca", "cuándo me toca", "me toca pagar",
        )
    )
    wants_cutoff = ("fecha de corte" in t) or (("corte" in t or "corta" in t) and "pago" not in t)
    wants_expiry = any(
        s in t
        for s in (
            "expira", "expiracion", "expiración", "fecha de expiracion", "fecha de expiración",
            "vence mi tarjeta", "vencimiento de la tarjeta",
        )
    ) or (
        any(s in t for s in ("cuando vence", "cuándo vence", "fecha de vencimiento"))
        and "pago" not in t
    )

    flags = (wants_balance, wants_min, wants_avail, wants_limit, wants_due, wants_cutoff, wants_expiry)
    if sum(1 for x in flags if x) < 2:
        return []

    parts: list[str] = []
    if wants_balance:
        val = format_money(getattr(card, "ledger_balance", None), getattr(card, "currency", "DOP"))
        parts.append(
            f"el balance actual / saldo adeudado de tu {label} es **{val}**"
            if val is not None
            else f"el balance actual de tu {label} no está disponible"
        )
    if wants_min:
        val = format_money(getattr(card, "min_payment_rd", None), "DOP")
        parts.append(
            f"el pago mínimo es **{val}**"
            if val is not None
            else "el pago mínimo no está disponible"
        )
    if wants_avail:
        val = format_money(
            getattr(card, "available_purchases_domestic", None) or getattr(card, "available_balance", None),
            "DOP",
        )
        parts.append(
            f"tienes **{val}** disponibles para compras en tu {label}"
            if val is not None
            else f"el disponible de tu {label} no está disponible en este momento"
        )
    if wants_limit:
        val = format_money(getattr(card, "credit_limit", None), "DOP")
        parts.append(
            f"el límite de crédito de tu {label} es **{val}**"
            if val is not None
            else f"el límite de crédito de tu {label} no está disponible"
        )
    if wants_due:
        due = getattr(card, "payment_due_date", None)
        day = getattr(card, "cutoff_day", None)
        if due:
            parts.append(f"la fecha límite de pago de tu {label} es **{due}**")
        elif day:
            parts.append(
                f"no tengo la fecha límite exacta de tu {label} "
                f"(corte día **{day}**; la límite aparece en el estado de cuenta)"
            )
        else:
            parts.append(f"la fecha límite de pago de tu {label} no está disponible")
    if wants_cutoff:
        day = getattr(card, "cutoff_day", None)
        parts.append(
            f"la fecha de corte es el día **{day}** de cada mes"
            if day
            else "la fecha de corte no está disponible"
        )
    if wants_expiry:
        expiry = getattr(card, "card_expiry", None)
        parts.append(
            f"la fecha de expiración de tu {label} es **{expiry}**"
            if expiry
            else f"la fecha de expiración de tu {label} no está disponible"
        )
    return parts


def build_multi_card_aggregate_response(
    question: str | None,
    cards: list[Any],
    display_name: str | None,
) -> str:
    """Resumen de varias TC (deuda / disponible / cuál tiene más) sin forzar elección."""
    from decimal import Decimal

    from genesis_cognitive.context.product_display import display_label_in_context
    from genesis_cognitive.context.response_formatting import format_money

    t = (question or "").lower()
    hello = f"{display_name}, " if display_name else ""
    wants_debt = any(
        s in t for s in ("cuanto debo", "cuánto debo", "adeud", "debo en", "debo de", "lo que debo")
    ) or ("saldo" in t and "disponible" not in t)
    wants_avail = any(
        s in t
        for s in (
            "disponible",
            "cupo",
            "credito disponible",
            "crédito disponible",
            "limite disponible",
            "límite disponible",
        )
    )
    wants_which_more = any(
        s in t
        for s in (
            "cual de ellas",
            "cuál de ellas",
            "cual tiene mas",
            "cuál tiene más",
            "cual tiene más",
            "cuál tiene mas",
            "cual tiene mayor",
            "cuál tiene mayor",
            "mas credito",
            "más credito",
            "mas crédito",
            "más crédito",
            "mas disponible",
            "más disponible",
            "mayor disponible",
        )
    )
    if not wants_debt and not wants_avail:
        wants_debt = True
        wants_avail = True

    lines: list[str] = []
    best_label: str | None = None
    best_fmt: str | None = None
    best_val: Decimal | None = None

    for card in cards:
        label = display_label_in_context(card, cards)
        bits: list[str] = []
        if wants_debt:
            debt = format_money(getattr(card, "ledger_balance", None), getattr(card, "currency", "DOP") or "DOP")
            bits.append(f"adeudas **{debt}**" if debt is not None else "saldo adeudado no disponible")
        raw_avail = getattr(card, "available_purchases_domestic", None) or getattr(card, "available_balance", None)
        if wants_avail:
            avail = format_money(raw_avail, "DOP")
            bits.append(f"disponible **{avail}**" if avail is not None else "disponible no reportado")
        lines.append(f"• **{label}**: " + "; ".join(bits))
        if raw_avail is not None:
            try:
                val = Decimal(str(raw_avail))
            except Exception:
                continue
            if best_val is None or val > best_val:
                best_val = val
                best_label = label
                best_fmt = format_money(raw_avail, "DOP")

    body = "\n".join(lines)
    extra = ""
    if wants_which_more and wants_avail and best_label and best_fmt:
        extra = f"\nLa que tiene más crédito disponible es **{best_label}** ({best_fmt})."
    return f"{hello}aquí tienes el resumen de tus tarjetas de crédito:\n{body}{extra}"


def build_card_detail_response(question: str | None, card: Any, display_name: str | None, label: str) -> str:
    """Respuesta TC: ficha completa markdown por defecto; campo puntual si la pregunta lo pide."""
    from genesis_cognitive.context.response_formatting import build_rich_card_detail, format_money

    hello = _greeting(display_name)
    q = (question or "").lower()

    multi_parts = _build_card_multi_field_parts(q, card, label)
    if len(multi_parts) >= 2:
        body_lines = [f"- {p.rstrip('.')}." for p in multi_parts]
        greet = hello.rstrip(", ").rstrip()
        if greet:
            return f"{greet},\n\n" + "\n".join(body_lines)
        return "\n".join(body_lines)

    specific = any(
        s in q
        for s in (
            "punto",
            "transaccion",
            "transacción",
            "movimiento",
            "historial",
            "pago minimo",
            "pago mínimo",
            "minimo",
            "mínimo",
            "limite",
            "límite",
            "fecha de pago",
            "fecha limite",
            "fecha límite",
            "cuando pago",
            "cuándo pago",
            "cuando debo pagar",
            "cuándo debo pagar",
            "debo pagar",
            "vence el pago",
            "vencimiento",
            "vence mi tarjeta",
            "cuando vence",
            "cuándo vence",
            "expira",
            "expiracion",
            "expiración",
            "cuando expira",
            "cuándo expira",
            "fecha de expiracion",
            "fecha de expiración",
            "cuando me toca",
            "cuándo me toca",
            "me toca pagar",
            "monto a pagar",
            "cuanto pago",
            "cuánto pago",
            "ultimo corte",
            "último corte",
            "balance al",
            "cerro",
            "cerró",
            "saldo actual",
            "saldo adeudado",
            "balance actual",
            "balance disponible",
            "cuanto debo",
            "cuánto debo",
            "lo que debo",
            "disponible",
            "fecha de corte",
        )
    ) or ("corte" in q or "corta" in q)

    # Preguntas generales / selección de producto → ficha tipográfica completa
    # Labels de opción APK (···6374 / credit_card) no cuentan como ficha pedida
    # "Dame info de X" sin campo → ficha completa con todos los campos de portafolio
    if not specific:
        if any(
            s in q
            for s in (
                "info ",
                "info de",
                "información",
                "informacion",
                "dame info",
                "detalle de",
                "datos de",
                "toda la",
                "ficha",
                "resumen",
            )
        ):
            rich = build_rich_card_detail(card)
            return f"{hello.rstrip(', ')}\n{rich}" if hello else rich
        rich = build_rich_card_detail(card)
        return f"{hello.rstrip(', ')}\n{rich}" if hello else rich

    if any(s in q for s in ("punto",)):
        pts = getattr(card, "loyalty_points", None)
        if pts is not None:
            return f"{hello}tus Puntos Santa Cruz son **{pts}**."
        return f"{hello}los Puntos Santa Cruz no están disponibles en este momento."
    if any(s in q for s in ("transaccion", "transacción", "movimiento", "historial")):
        return f"{hello}{_UNAVAILABLE} No recibí las últimas transacciones de tu {label}."
    if any(s in q for s in ("pago minimo", "pago mínimo", "minimo", "mínimo")):
        val = format_money(getattr(card, "min_payment_rd", None), "DOP")
        return (
            f"{hello}el pago mínimo de tu {label} es **{val}**."
            if val is not None
            else f"{hello}el pago mínimo de tu {label} no está disponible en este momento."
        )
    # Fecha límite / cuándo pagar ANTES de "límite" de crédito (evita confusión con "fecha límite")
    if any(
        s in q
        for s in (
            "fecha de pago",
            "fecha limite",
            "fecha límite",
            "cuando pago",
            "cuándo pago",
            "cuando debo pagar",
            "cuándo debo pagar",
            "debo pagar",
            "vence el pago",
            "limite de pago",
            "límite de pago",
            "cuando me toca",
            "cuándo me toca",
            "me toca pagar",
        )
    ):
        due = getattr(card, "payment_due_date", None)
        day = getattr(card, "cutoff_day", None)
        if due:
            return f"{hello}la fecha límite de pago de tu {label} es **{due}**."
        if day:
            return (
                f"{hello}no tengo la fecha límite de pago exacta de tu {label} en este momento. "
                f"La fecha de corte es el día **{day}** de cada mes; "
                "la fecha límite de pago aparece en tu estado de cuenta (normalmente unos días después del corte)."
            )
        return f"{hello}la fecha límite de pago de tu {label} no está disponible en este momento."
    if "corte" in q or "corta" in q:
        day = getattr(card, "cutoff_day", None)
        return (
            f"{hello}la fecha de corte de tu {label} es el día **{day}** de cada mes."
            if day
            else f"{hello}la fecha de corte no está disponible en este momento."
        )
    if any(s in q for s in ("limite", "límite")):
        val = format_money(getattr(card, "credit_limit", None), "DOP")
        return (
            f"{hello}el límite de tu {label} es **{val}**."
            if val is not None
            else f"{hello}el límite no está disponible en este momento."
        )
    if any(
        s in q
        for s in (
            "vencimiento",
            "vence mi tarjeta",
            "cuando vence",
            "cuándo vence",
            "expira",
            "expiracion",
            "expiración",
            "cuando expira",
            "cuándo expira",
            "fecha de expiracion",
            "fecha de expiración",
        )
    ) and "pago" not in q:
        expiry = getattr(card, "card_expiry", None)
        return (
            f"{hello}tu {label} vence en **{expiry}**."
            if expiry
            else f"{hello}la fecha de vencimiento de tu {label} no está disponible en este momento."
        )
    if any(s in q for s in ("monto a pagar", "cuanto pago", "cuánto pago", "ultimo corte", "último corte", "balance al", "cerro", "cerró")):
        val = format_money(getattr(card, "statement_balance_rd", None), "DOP")
        return (
            f"{hello}el balance al corte de tu {label} es **{val}**."
            if val is not None
            else f"{hello}el balance al corte no está disponible en este momento."
        )
    if any(s in q for s in ("saldo actual", "saldo adeudado", "balance actual", "cuanto debo", "cuánto debo", "lo que debo")):
        val = format_money(getattr(card, "ledger_balance", None), getattr(card, "currency", "DOP"))
        return (
            f"{hello}el balance actual (adeudado) de tu {label} es **{val}**."
            if val is not None
            else f"{hello}el balance actual no está disponible en este momento."
        )
    if any(s in q for s in ("balance disponible", "saldo disponible", "disponible")):
        val = format_money(
            getattr(card, "available_purchases_domestic", None) or getattr(card, "available_balance", None),
            "DOP",
        )
        limit = format_money(getattr(card, "credit_limit", None), "DOP")
        if val is not None and limit is not None and "limite" not in q and "límite" not in q:
            return (
                f"{hello}tu {label} tiene **{val}** disponibles para compras "
                f"(límite de crédito **{limit}**)."
            )
        return (
            f"{hello}tu {label} tiene **{val}** disponibles."
            if val is not None
            else f"{hello}el disponible de tu {label} no está disponible en este momento."
        )
    # Fallback: ficha completa tipográfica
    rich = build_rich_card_detail(card)
    return f"{hello.rstrip(', ')}\n{rich}" if hello else rich


def build_deposit_detail_response(question: str | None, dep: Any, display_name: str | None, label: str) -> str:
    from genesis_cognitive.context.response_formatting import build_rich_deposit_detail, format_money

    hello = _greeting(display_name)
    q = (question or "").lower()
    plazo = None
    alias = str(getattr(dep, "alias", "") or "")
    match = re.search(r"(\d+)\s*mes", alias.lower())
    if match:
        plazo = match.group(1)

    wants_rate = "tasa" in q or (
        any(s in q for s in ("interés", "interes"))
        and not any(s in q for s in ("generad", "acumulad", "intereses"))
    )
    wants_interest = any(
        s in q
        for s in (
            "intereses", "interes acumulad", "interés acumulad",
            "generad", "acumulad", "ha generado", "me ha generado",
            "interes generado", "interés generado",
        )
    )
    wants_maturity = any(s in q for s in ("vence", "vencimiento", "madurez"))
    wants_capital = any(
        s in q for s in ("invert", "monto original", "cuanto puse", "cuánto puse", "capital")
    )

    # Multi-campo CD: tasa + intereses (+ vencimiento) en una sola respuesta
    multi_bits: list[str] = []
    if wants_rate:
        rate = getattr(dep, "interest_rate", None)
        multi_bits.append(
            f"la tasa de interés de tu {label} es **{rate}%**"
            if rate is not None
            else f"la tasa de tu {label} no está disponible"
        )
    if wants_interest:
        amount = getattr(dep, "interest_amount", None)
        fmt = format_money(amount, getattr(dep, "currency", "DOP"))
        multi_bits.append(
            f"los intereses acumulados de tu {label} son **{fmt}**"
            if fmt is not None
            else f"los intereses acumulados de tu {label} no están disponibles"
        )
    if wants_maturity and (wants_rate or wants_interest or wants_capital):
        date = getattr(dep, "maturity_date", None)
        multi_bits.append(
            f"vence el **{str(date)[:10] if date else 'n/d'}**"
            if date
            else "la fecha de vencimiento no está disponible"
        )
    if wants_capital and (wants_rate or wants_interest):
        val = getattr(dep, "available_balance", None) or getattr(dep, "ledger_balance", None)
        fmt = format_money(val, getattr(dep, "currency", "DOP"))
        multi_bits.append(
            f"el capital invertido es **{fmt}**"
            if fmt is not None
            else "el capital invertido no está disponible"
        )
    if len(multi_bits) >= 2:
        body = "\n".join(f"- {b}." for b in multi_bits)
        greet = hello.rstrip(", ").rstrip()
        return f"{greet},\n\n{body}" if greet else body

    if any(s in q for s in ("apertura", "cuando lo abri", "cuándo lo abrí", "fecha de apertura", "abri", "abrí")):
        return f"{hello}la fecha de apertura de tu {label} no está disponible en este momento."
    if any(s in q for s in ("modalidad", "como me pagan", "cómo me pagan", "pago de intereses", "capitaliz")):
        return f"{hello}la modalidad de pago de intereses de tu {label} no está disponible en este momento."
    if wants_rate and not wants_interest:
        rate = getattr(dep, "interest_rate", None)
        return (
            f"{hello}la tasa de interés de tu {label} es **{rate}%**."
            if rate is not None
            else f"{hello}la tasa no está disponible en este momento."
        )
    if wants_maturity:
        date = getattr(dep, "maturity_date", None)
        return (
            f"{hello}tu {label} vence el **{str(date)[:10]}**."
            if date
            else f"{hello}la fecha de vencimiento no está disponible en este momento."
        )
    if wants_interest:
        amount = getattr(dep, "interest_amount", None)
        fmt = format_money(amount, getattr(dep, "currency", "DOP"))
        return (
            f"{hello}los intereses acumulados de tu {label} son **{fmt}**."
            if fmt is not None
            else f"{hello}los intereses acumulados no están disponibles en este momento."
        )
    if wants_capital:
        val = getattr(dep, "available_balance", None) or getattr(dep, "ledger_balance", None)
        fmt = format_money(val, getattr(dep, "currency", "DOP"))
        return (
            f"{hello}el monto invertido en tu {label} es **{fmt}**."
            if fmt is not None
            else f"{hello}el monto invertido no está disponible en este momento."
        )
    plazo_asked = any(s in q for s in ("plazo contractual", "a cuantos meses", "a cuántos meses", "duracion", "duración")) or (
        "plazo" in q
        and "tasa" not in q
        and "depósito a plazo" not in q
        and "deposito a plazo" not in q
        and "deposito_plazo" not in q
    )
    if plazo_asked:
        return (
            f"{hello}el plazo de tu {label} es {plazo} meses."
            if plazo
            else f"{hello}el plazo contractual no está disponible en este momento."
        )
    val = getattr(dep, "ledger_balance", None) or getattr(dep, "available_balance", None)
    if any(s in q for s in ("saldo", "balance", "disponible")) and "deposito_plazo" not in q:
        fmt = format_money(val, getattr(dep, "currency", "DOP"))
        return (
            f"{hello}el saldo de tu {label} es **{fmt}**."
            if fmt is not None
            else f"{hello}el saldo de tu {label} no está disponible en este momento."
        )
    # Consulta amplia / selección APK → ficha completa con tasa + intereses
    is_apk_selection = (
        "deposito_plazo" in q
        or bool(re.search(r"(···|\.{2,}|…|••••|\*{4})\s*\d{3,}", q))
    )
    if is_apk_selection or any(
        s in q
        for s in (
            "mas informacion",
            "más información",
            "mas info",
            "más info",
            "detalle",
            "detalles",
            "toda la informacion",
            "toda la información",
            "resumen",
            "integral",
            "certificado",
            "deposito",
            "depósito",
        )
    ) or not any(
        s in q
        for s in (
            "tasa", "vence", "vencimiento", "interes", "interés", "apertura",
            "modalidad", "invert",
        )
    ):
        rich = build_rich_deposit_detail(dep)
        return f"{hello.rstrip(', ')}\n{rich}" if hello else rich
    fmt = format_money(val, getattr(dep, "currency", "DOP"))
    return (
        f"{hello}el balance de tu {label} es **{fmt}**."
        if fmt is not None
        else f"{hello}el balance no está disponible en este momento."
    )
