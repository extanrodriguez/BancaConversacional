"""Formato tipográfico de respuestas de productos (markdown para APK / UI).

El API retorna ``content_format: "markdown"``. El frontend debe renderizar:
- ``**texto**`` → negrita
- saltos de línea ``\\n``
- viñetas ``•``

Semántica alineada a Documentacion_API_Productos:
- TC availableBalance = límite; currentBalance = adeudado; statement* = último corte
- CD interest 0 = N/A (no mostrar)
- PR pendingBalancePr = mora (no cuota contractual)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def format_money(amount: Decimal | float | int | str | None, currency: str | None = "DOP") -> str | None:
    """Formatea montos estilo banca: RD$50,000.00 / USD$50.19."""
    if amount is None:
        return None
    try:
        value = Decimal(str(amount))
    except Exception:
        return None
    ccy = (currency or "DOP").upper()
    prefix = "RD$" if ccy in ("DOP", "214") else ("USD$" if ccy in ("USD", "840") else f"{ccy}$")
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    abs_q = abs(quantized)
    whole, _, frac = f"{abs_q:.2f}".partition(".")
    grouped = ""
    while len(whole) > 3:
        grouped = "," + whole[-3:] + grouped
        whole = whole[:-3]
    grouped = whole + grouped
    return f"{sign}{prefix}{grouped}.{frac}"


def _last4(card: Any) -> str:
    mask = str(getattr(card, "card_mask", None) or "")
    digits = "".join(ch for ch in mask if ch.isdigit())
    if len(digits) >= 4:
        return digits[-4:]
    last = getattr(card, "last_four", None)
    if last:
        return str(last)[-4:]
    pid = str(getattr(card, "product_id", "") or "")
    digits = "".join(ch for ch in pid if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else pid[-4:]


def _line(label: str, value: str | None, *, bold_value: bool = True) -> str | None:
    if value is None or value == "":
        return None
    rendered = f"**{value}**" if bold_value else value
    return f"• {label}: {rendered}"


def _as_dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def build_rich_card_detail(card: Any, *, title: str | None = None) -> str:
    """Ficha completa de tarjeta con negrita (markdown).

    Incluye todos los campos de portafolio disponibles (API Productos).
    Semántica: availableBalance→límite; currentBalance→balance actual/adeudado;
    availablePurchases*→disponible compras; statementCutoffDay; cardExpiryDate.
    """
    last4 = _last4(card)
    alias = str(getattr(card, "alias", None) or "").strip() or "Tarjeta de Crédito"
    header = title or f"**{alias} - {last4}**"
    lines: list[str] = [header]

    credit_limit = format_money(getattr(card, "credit_limit", None), "DOP")
    if credit_limit:
        lines.append(_line("Límite de crédito", credit_limit) or "")

    # currentBalance → balance actual / saldo adeudado
    adeudado = format_money(getattr(card, "ledger_balance", None), "DOP")
    if adeudado is not None:
        lines.append(_line("Balance actual", adeudado) or "")
        lines.append(_line("Saldo adeudado", adeudado) or "")

    disp_dop = format_money(
        getattr(card, "available_purchases_domestic", None)
        or getattr(card, "available_balance", None),
        "DOP",
    )
    if disp_dop is not None:
        lines.append(_line("Disponible para compras (DOP)", disp_dop) or "")

    ultimo_corte = format_money(getattr(card, "statement_balance_rd", None), "DOP")
    if ultimo_corte is not None:
        lines.append(_line("Último corte / balance estado (DOP)", ultimo_corte) or "")

    pago_min = format_money(getattr(card, "min_payment_rd", None), "DOP")
    if pago_min is not None:
        lines.append(_line("Pago mínimo (DOP)", pago_min) or "")

    # Bloque USD (multimoneda o datos foreign presentes)
    foreign_owed = getattr(card, "foreign_currency_balance", None)
    stmt_us = getattr(card, "statement_balance_us", None)
    disp_us = getattr(card, "available_purchases_foreign", None)
    min_us = getattr(card, "min_payment_us", None)
    multi = getattr(card, "multi_currency", None)
    show_usd = bool(multi) or any(v is not None for v in (foreign_owed, stmt_us, disp_us, min_us))

    if show_usd:
        if foreign_owed is not None:
            lines.append(_line("Saldo adeudado (USD)", format_money(foreign_owed, "USD")) or "")
        if disp_us is not None:
            lines.append(_line("Disponible para compras (USD)", format_money(disp_us, "USD")) or "")
        if stmt_us is not None:
            lines.append(_line("Último corte (USD)", format_money(stmt_us, "USD")) or "")
        if min_us is not None:
            lines.append(_line("Pago mínimo (USD)", format_money(min_us, "USD")) or "")

    cutoff = getattr(card, "cutoff_day", None)
    if cutoff:
        lines.append(f"• Fecha de corte: día **{int(cutoff)}** de cada mes")

    expiry = getattr(card, "card_expiry", None)
    if expiry:
        lines.append(f"• Fecha de expiración / vencimiento: **{expiry}**")

    payment_due = getattr(card, "payment_due_date", None)
    if payment_due:
        lines.append(_line("Fecha límite de pago", str(payment_due)) or "")

    points = getattr(card, "loyalty_points", None)
    if points is not None:
        lines.append(f"• Puntos Santa Cruz: {points}")

    return "\n".join(line for line in lines if line)


def build_rich_account_detail(account: Any, *, title: str | None = None) -> str:
    """Ficha de cuenta de ahorro/corriente con negrita."""
    last4 = _last4(account)
    alias = str(getattr(account, "alias", None) or "Cuenta")
    ccy = str(getattr(account, "currency", "DOP") or "DOP")
    header = title or f"**{alias} - {last4}**"
    lines = [header]
    avail = format_money(getattr(account, "available_balance", None), ccy)
    current = format_money(
        getattr(account, "ledger_balance", None) or getattr(account, "available_balance", None),
        ccy,
    )
    if current:
        lines.append(_line("Saldo actual", current) or "")
    if avail:
        lines.append(_line("Saldo disponible", avail) or "")
    lines.append(f"• Moneda: **{ccy}**")
    return "\n".join(line for line in lines if line)


def build_rich_loan_detail(loan_product: Any, loan: Any | None = None, *, title: str | None = None) -> str:
    """Ficha de un préstamo (markdown) para consulta general.

    Formato APK::

        **Préstamo - 7615**
        • Monto original: **RD$185,000.00**
        • Capital pendiente: **RD$185,000.00**
        • Total Adeudado: **RD$185,000.00**
        • Tasa Anual: **12.5%**
        • Próximo pago: **2026-09-01**
        • Vencimiento del préstamo: **2028-09-01**
    """
    last4 = _last4(loan_product)
    if loan is not None and getattr(loan, "last_four", None):
        last4 = str(loan.last_four)[-4:]
    header = title or f"**Préstamo - {last4}**"
    lines: list[str] = [header]
    ccy = str(getattr(loan_product, "currency", "DOP") or "DOP")

    principal = None
    rate = None
    next_due = None
    disbursed = None
    payoff = None
    maturity = None

    if loan is not None:
        principal = getattr(loan, "outstanding_principal", None)
        rate = getattr(loan, "annual_interest_rate", None)
        next_due = getattr(loan, "next_due_date", None)
        disbursed = getattr(loan, "disbursed_amount", None)
        payoff = getattr(loan, "payoff_amount", None)
        maturity = getattr(loan, "maturity_date", None)
    else:
        principal = getattr(loan_product, "ledger_balance", None)
        disbursed = getattr(loan_product, "available_balance", None)

    if disbursed is not None:
        lines.append(_line("Monto original", format_money(disbursed, ccy)) or "")
    if principal is not None:
        lines.append(_line("Capital pendiente", format_money(principal, ccy)) or "")
    if payoff is not None:
        lines.append(_line("Total Adeudado", format_money(payoff, ccy)) or "")

    rate_dec = _as_dec(rate)
    if rate_dec is not None and rate_dec > 0:
        lines.append(_line("Tasa Anual", f"{rate_dec}%") or "")
    if next_due:
        lines.append(_line("Próximo pago", str(next_due)) or "")
    if maturity:
        lines.append(_line("Vencimiento del préstamo", str(maturity)) or "")
    return "\n".join(line for line in lines if line)


def build_rich_loan_from_detail(loan_detail: dict[str, Any], *, currency: str = "DOP") -> str:
    """Misma ficha a partir de ``LoanSnapshot.to_detail_dict()``."""
    last4 = str(loan_detail.get("last_four") or "")
    if not last4:
        pid = str(loan_detail.get("product_id") or "")
        digits = "".join(ch for ch in pid if ch.isdigit())
        last4 = digits[-4:] if len(digits) >= 4 else pid[-4:]
    header = f"**Préstamo - {last4}**"
    lines: list[str] = [header]
    ccy = currency or "DOP"

    if loan_detail.get("disbursed_amount") is not None:
        lines.append(_line("Monto original", format_money(loan_detail.get("disbursed_amount"), ccy)) or "")
    if loan_detail.get("outstanding_principal") is not None:
        lines.append(
            _line("Capital pendiente", format_money(loan_detail.get("outstanding_principal"), ccy)) or ""
        )
    if loan_detail.get("payoff_amount") is not None:
        lines.append(_line("Total Adeudado", format_money(loan_detail.get("payoff_amount"), ccy)) or "")

    rate_dec = _as_dec(loan_detail.get("annual_interest_rate"))
    if rate_dec is not None and rate_dec > 0:
        lines.append(_line("Tasa Anual", f"{rate_dec}%") or "")
    if loan_detail.get("next_due_date"):
        lines.append(_line("Próximo pago", str(loan_detail.get("next_due_date"))) or "")
    if loan_detail.get("maturity_date"):
        lines.append(
            _line("Vencimiento del préstamo", str(loan_detail.get("maturity_date"))) or ""
        )
    return "\n".join(line for line in lines if line)


def build_rich_deposit_detail(dep: Any, *, title: str | None = None) -> str:
    """Ficha CDT / depósito a plazo con negrita.

    Incluye todos los campos de portafolio disponibles: capital, tasa (interestRateCd),
    intereses acumulados (interestAmountCd) y vencimiento (maturityDate).
    """
    last4 = _last4(dep)
    alias = str(getattr(dep, "alias", None) or "Certificado de Depósito")
    ccy = str(getattr(dep, "currency", "DOP") or "DOP")
    header = title or f"**{alias} - {last4}**"
    lines = [header]
    capital = format_money(
        getattr(dep, "available_balance", None) or getattr(dep, "ledger_balance", None),
        ccy,
    )
    if capital:
        lines.append(_line("Capital invertido", capital) or "")
    rate = _as_dec(getattr(dep, "interest_rate", None))
    if rate is not None and rate > 0:
        lines.append(_line("Tasa de interés", f"{rate}%") or "")
        lines.append(_line("Tasa anual", f"{rate}%") or "")
    interest_amt = _as_dec(getattr(dep, "interest_amount", None))
    if interest_amt is not None and interest_amt > 0:
        lines.append(_line("Intereses acumulados", format_money(interest_amt, ccy)) or "")
    maturity = getattr(dep, "maturity_date", None)
    if maturity:
        lines.append(_line("Fecha de vencimiento", str(maturity)[:10] if len(str(maturity)) >= 10 else str(maturity)) or "")
    lines.append(f"• Moneda: **{ccy}**")
    return "\n".join(line for line in lines if line)


def looks_like_markdown_product(text: str | None) -> bool:
    t = text or ""
    return "**" in t or "• " in t or t.count("\n") >= 2


# Link oficial para contratación digital de productos BSC (markdown accionable en APK/web)
DIGITAL_ONBOARDING_URL = "https://solicitudesdigitales.bsc.com.do/"
DIGITAL_ONBOARDING_MD = f"[Para contratar de forma digital, ingresa aquí]({DIGITAL_ONBOARDING_URL})"

_DIGITAL_CTA = f"\n\n{DIGITAL_ONBOARDING_MD}"


def append_digital_onboarding_link(text: str | None) -> str:
    """Añade CTA de contratación digital como link markdown accionable."""
    import re

    body = (text or "").rstrip()
    if not body:
        return DIGITAL_ONBOARDING_MD
    # Ya hay link markdown o URL cruda → normalizar a markdown si hace falta
    if "solicitudesdigitales.bsc.com.do" in body.lower():
        if "](" in body and "solicitudesdigitales.bsc.com.do" in body.lower():
            return body
        # Sustituir URL suelta / "ingresa a: URL" por link markdown
        body = re.sub(
            r"(?im)(?:para contratar de forma digital,?\s*)?(?:ingresa a:?\s*)?"
            r"https?://solicitudesdigitales\.bsc\.com\.do/?",
            DIGITAL_ONBOARDING_MD,
            body,
            count=1,
        )
        if "solicitudesdigitales.bsc.com.do" in body.lower() and "](" not in body:
            body = re.sub(
                r"https?://solicitudesdigitales\.bsc\.com\.do/?",
                DIGITAL_ONBOARDING_MD,
                body,
                count=1,
                flags=re.I,
            )
        return body
    return body + _DIGITAL_CTA


def no_product_with_cta(display_name: str | None, product_phrase: str) -> str:
    """No tiene el producto: informar y ofrecer el canal digital para adquirirlo."""
    hello = f"{display_name}, " if display_name else ""
    text = (
        f"{hello}no tienes {product_phrase} en tu portafolio actual. "
        "Para adquirirlo, puedes hacerlo a través de este enlace."
    )
    return append_digital_onboarding_link(text)


def unknown_turn_reply(display_name: str | None = None) -> str:
    """Respuesta controlada cuando el turno falla o no hay interpretación usable."""
    hello = f"{display_name}, " if display_name else ""
    return (
        f"{hello}no logré interpretar esa consulta. "
        "Puedes preguntarme por el saldo de tus cuentas, la fecha de pago de un préstamo, "
        "tus tarjetas o información del banco. Si quieres, reformula la pregunta."
    )


def sanitize_client_facing_text(text: str | None) -> str:
    """Quita metadatos de la matriz KB que nunca deben verse en el chat del cliente.

    Evita fugas tipo:
    - Producto / Intencion / Funcionalidad / Expresiones del cliente
    - ### Respuesta / contexto aprobado
    """
    if not text:
        return ""
    import re

    out = str(text)
    # Si hay encabezado de respuesta aprobada, quedarse solo con lo posterior
    m = re.search(
        r"(?im)^(?:#{1,6}\s*)?respuesta\s*/\s*contexto\s+aprobado\s*$",
        out,
    )
    if m:
        out = out[m.end() :].lstrip("\n :-\t")

    drop_line = re.compile(
        r"(?im)^\s*(?:[-*•]\s*)?"
        r"(?:\*\*)?(?:producto|intenci[oó]n(?:\s+funcional)?|funcionalidad|"
        r"expresiones(?:\s+del\s+cliente)?|canal|dimensi[oó]n|"
        r"dato\s*/\s*subintenci[oó]n|escenario\s*/\s*condici[oó]n|"
        r"contexto\s+previo|criterio\s+de\s+aceptaci[oó]n)"
        r"(?:\*\*)?\s*:.*$"
    )
    lines = [ln for ln in out.splitlines() if not drop_line.match(ln)]
    out = "\n".join(lines)

    out = re.sub(
        r"(?im)^#{1,6}\s*respuesta\s*/\s*contexto\s+aprobado\s*$",
        "",
        out,
    )
    # Bloques de índice MD: solo encabezado + viñetas de pregunta, no el cuerpo
    lines_out: list[str] = []
    skip_ejemplo = False
    for ln in out.splitlines():
        if re.match(r"(?i)^\s*preguntas\s+ejemplo\s*:\s*$", ln):
            skip_ejemplo = True
            continue
        if skip_ejemplo:
            if not ln.strip():
                continue
            if re.match(r"^\s*[-*•]\s+", ln) and "?" in ln:
                continue
            skip_ejemplo = False
        lines_out.append(ln)
    out = "\n".join(lines_out)
    out = re.sub(
        r"(?i)\b(?:producto|intenci[oó]n|funcionalidad|expresiones del cliente)\s*:\s*",
        "",
        out,
    )
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    out = re.sub(r"^[,\s\-•]+", "", out).strip()

    # Citas Foundry / dumps numéricos (nunca visibles al cliente)
    out = re.sub(
        r"\[\s*\d{1,4}(?:\s*[|/]\s*\d{1,4}){2,}(?:\s*[|/]\s*)?\]?",
        "",
        out,
    )
    out = re.sub(r"(?m)^(?:\s*\|\s*\d{1,4}\s*){3,}\|?\s*$", "", out)
    out = re.sub(
        r"(?:\[\s*)?(?:\d{1,4}\s*[|/]\s*){5,}\d{0,4}"
        r"(?:\s*:\s*\d+\s*[†‡+]?\s*source\s*\]?)?"
        r"(?:\s*[】\]])?",
        "",
        out,
    )
    out = re.sub(
        r"[【\[]\s*\d+\s*:\s*\d+\s*[†‡+]?\s*source\s*[】\]]",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"[【\[][^】\]]{0,80}†source[】\]]?", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\b\d+\s*:\s*\d+\s*[†‡+]\s*source\s*\]?", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out
