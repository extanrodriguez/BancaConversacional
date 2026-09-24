"""Product display helpers — masks, active filters, listing rules.

Rules:
- Default listing: only active products
- CA (SAVINGS/CHECKING/PAYROLL): "Cuenta" + mask last 5 of product_id
  (description from Core is often generic/repeated → always mask)
- TC (CREDIT_CARD): description + card_mask; never CVV/expiry
- PR (LOAN): "Prestamo" + mask last 5 of product_id
  (description from Core is often generic/repeated → always mask)
- installment_amount=0 → omit cuota (Core doesn't provide it)
- Currencies: label DOP/USD, no FX conversion
"""

from __future__ import annotations

from genesis_cognitive.context.customer_context_snapshot import (
    CustomerContextSnapshot,
    LoanSnapshot,
    ProductSnapshot,
)

# Descriptions considered generic (case-insensitive, stripped)
_GENERIC_DESCRIPTIONS: set[str] = {
    "cuenta de ahorros",
    "cuenta de ahorro",
    "cuenta corriente",
    "cuenta",
    "préstamo",
    "prestamo",
    "tarjeta",
    "loan",
    "savings",
    "checking",
    "",
}


def _is_generic(description: str | None) -> bool:
    """Check if a product description is generic/unhelpful."""
    if not description:
        return True
    return description.strip().lower() in _GENERIC_DESCRIPTIONS


def mask_product_id(product_id: str, length: int = 5) -> str:
    """Mask a product ID showing only last N characters: ...XXXXX."""
    if len(product_id) <= 5:
        return product_id
    return "..." + product_id[-length:]


def _mask_unique(product_id: str, sibling_ids: list[str]) -> str:
    """Produce a masked ID that is unique among siblings.

    Strategy:
    1. Try last-5: if unique among siblings → ...XXXXX
    2. If collides: show first 2 + ... + last 5 → XX...XXXXX
    """
    suffix5 = product_id[-5:] if len(product_id) > 5 else product_id
    # Check if last-5 is unique among siblings
    collides = sum(1 for sid in sibling_ids if (sid[-5:] if len(sid) > 5 else sid) == suffix5) > 1
    if not collides:
        return "..." + suffix5 if len(product_id) > 5 else product_id
    # Collision: use prefix(2) + ... + suffix(5)
    prefix = product_id[:2] if len(product_id) >= 2 else product_id
    return f"{prefix}...{suffix5}"


def _compute_mask_length(product_ids: list[str], base: int = 5, max_len: int = 10) -> int:
    """Find minimum mask length that produces unique suffixes for all IDs.
    
    If still not unique at max_len, returns max_len (caller uses _mask_unique fallback).
    """
    length = base
    while length <= max_len:
        suffixes = [pid[-length:] if len(pid) >= length else pid for pid in product_ids]
        if len(set(suffixes)) == len(suffixes):
            return length
        length += 1
    return max_len


def _type_prefix(product: ProductSnapshot) -> str:
    """Human-friendly type prefix for CA products."""
    pt = product.product_type
    if pt == "CHECKING":
        return "Cuenta corriente"
    elif pt == "PAYROLL":
        return "Cuenta nómina"
    elif pt == "SAVINGS":
        return "Cuenta de ahorros"
    return "Cuenta"


def display_label(product: ProductSnapshot, *, sibling_aliases: set[str] | None = None, mask_len: int = 5, sibling_ids: list[str] | None = None) -> str:
    """Build a display label for a product following business rules.

    CA/PR: always use mask to distinguish when descriptions repeat or are generic.
    TC: description + card_mask.

    sibling_aliases: set of aliases from other products in same listing.
    If the alias is duplicated among siblings, treat as generic → use mask.
    mask_len: number of trailing digits to show (default 5, increased if collisions).
    sibling_ids: all product_ids in the same group (for _mask_unique fallback).
    """
    alias = product.alias

    # Check if alias is duplicated among siblings (same text for multiple products)
    alias_is_duplicate = False
    if sibling_aliases is not None and alias:
        alias_is_duplicate = True  # If passed, caller already determined it's a dup context

    if product.product_type == "CREDIT_CARD":
        base = alias or "Tarjeta"
        if product.card_mask:
            return f"{base} ({product.card_mask})"
        suffix = product.product_id[-4:] if len(product.product_id) >= 4 else product.product_id
        return f"{base} (****{suffix})"

    if product.product_type == "TERM_DEPOSIT":
        # Compute masked ID — use _mask_unique if sibling_ids provided, else simple mask
        if sibling_ids:
            masked = _mask_unique(product.product_id, sibling_ids)
        else:
            masked = mask_product_id(product.product_id, mask_len)
        if alias and not _is_generic(alias) and not alias_is_duplicate:
            return f"{alias} ({masked})"
        return f"Certificado de depósito ({masked})"

    # Compute masked ID — use _mask_unique if sibling_ids provided, else simple mask
    if sibling_ids:
        masked = _mask_unique(product.product_id, sibling_ids)
    else:
        masked = mask_product_id(product.product_id, mask_len)

    if product.product_type == "LOAN":
        if alias and not _is_generic(alias) and not alias_is_duplicate:
            return f"{alias} ({masked})"
        return f"Préstamo {masked}"

    # CA types: SAVINGS, CHECKING, PAYROLL
    prefix = _type_prefix(product)
    if alias and not _is_generic(alias) and not alias_is_duplicate:
        return f"{alias} ({masked})"
    return f"{prefix} {masked}"


def _detect_duplicate_aliases(products: list[ProductSnapshot]) -> set[str]:
    """Return set of aliases that appear more than once in the list."""
    from collections import Counter
    aliases = [p.alias.strip().lower() for p in products if p.alias]
    counts = Counter(aliases)
    return {a for a, c in counts.items() if c > 1}


def display_label_in_context(product: ProductSnapshot, all_products: list[ProductSnapshot]) -> str:
    """Display label considering sibling products for duplicate detection and mask collision."""
    dup_aliases = _detect_duplicate_aliases(all_products)
    is_dup = product.alias and product.alias.strip().lower() in dup_aliases
    ids = [p.product_id for p in all_products]
    mask_len = _compute_mask_length(ids)
    return display_label(product, sibling_aliases=dup_aliases if is_dup else None, mask_len=mask_len, sibling_ids=ids)


def filter_active(snapshot: CustomerContextSnapshot) -> list[ProductSnapshot]:
    """Return only active products from the snapshot."""
    return [p for p in snapshot.products if p.status.lower() == "active"]


def filter_active_by_type(
    snapshot: CustomerContextSnapshot,
    product_types: tuple[str, ...],
) -> list[ProductSnapshot]:
    """Return active products filtered by product_type."""
    return [
        p for p in snapshot.products
        if p.status.lower() == "active" and p.product_type in product_types
    ]


def build_portfolio_listing(snapshot: CustomerContextSnapshot) -> str:
    """Build a client-friendly portfolio listing (active only, grouped, markdown)."""
    from genesis_cognitive.context.response_formatting import (
        build_rich_account_detail,
        build_rich_card_detail,
        build_rich_deposit_detail,
        build_rich_loan_detail,
        format_money,
    )

    display_name = snapshot.display_name
    greeting = f"{display_name}," if display_name else ""

    active = filter_active(snapshot)
    if not active:
        return f"{greeting} no tienes productos activos visibles en tu portafolio.".lstrip()

    deposits = [p for p in active if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL")]
    cards = [p for p in active if p.product_type == "CREDIT_CARD"]
    loans = [p for p in active if p.product_type == "LOAN"]
    daps = [p for p in active if p.product_type == "TERM_DEPOSIT"]

    blocks: list[str] = []
    if greeting:
        blocks.append(f"{greeting} estos son tus productos activos:")
    else:
        blocks.append("Estos son tus productos activos:")

    if deposits:
        blocks.append("\n**Cuentas**")
        for p in deposits:
            bal = format_money(p.available_balance, p.currency)
            label = display_label_in_context(p, deposits)
            line = f"• **{label}**"
            if bal:
                line += f" — disponible **{bal}**"
            blocks.append(line)

    if cards:
        blocks.append("\n**Tarjetas de crédito**")
        for p in cards:
            blocks.append(build_rich_card_detail(p))

    if loans:
        blocks.append("\n**Préstamos**")
        loans_by_id = {ln.product_id: ln for ln in snapshot.loans}
        for p in loans:
            blocks.append(build_rich_loan_detail(p, loans_by_id.get(p.product_id)))

    if daps:
        blocks.append("\n**Certificados / CDT**")
        for p in daps:
            blocks.append(build_rich_deposit_detail(p))

    return "\n".join(blocks)


def build_clarification_accounts(accounts: list[ProductSnapshot]) -> str:
    """Build clarification text for multiple deposit accounts (masked)."""
    descriptions = [display_label_in_context(p, accounts) for p in accounts]
    return f"Tienes {len(accounts)} cuentas activas: {', '.join(descriptions)}. ¿De cuál deseas consultar?"


def build_clarification_loans(loans: list[ProductSnapshot]) -> str:
    """Build clarification text for multiple loans."""
    descriptions = [display_label_in_context(p, loans) for p in loans]
    return f"Tienes {len(loans)} préstamos activos: {', '.join(descriptions)}. ¿A cuál te refieres?"


def build_clarification_cards(cards: list[ProductSnapshot]) -> str:
    """Build clarification text for multiple credit cards."""
    descriptions = [display_label_in_context(p, cards) for p in cards]
    return f"Tienes {len(cards)} tarjetas activas: {', '.join(descriptions)}. ¿Cuál deseas consultar?"


def build_multi_account_balance_response(
    snapshot: CustomerContextSnapshot,
    accounts: list[ProductSnapshot],
) -> str:
    """List balance for each active deposit account (generic saldo question)."""
    greeting = f"{snapshot.display_name}, " if snapshot.display_name else ""
    parts: list[str] = []
    for p in accounts:
        label = _type_prefix(p)
        mask = mask_product_id(p.product_id, 5)
        bal = p.available_balance
        if bal is not None:
            parts.append(f"tu saldo disponible en {label} número {mask} es de {bal} {p.currency}")
        else:
            parts.append(f"tu {label} número {mask} está disponible para consulta")
    if not parts:
        return f"{greeting}no encontré cuentas activas para consultar saldo."
    if len(parts) == 1:
        joined = parts[0]
    elif len(parts) == 2:
        joined = f"{parts[0]} y {parts[1]}"
    else:
        joined = ", ".join(parts[:-1]) + f" y {parts[-1]}"
    return (
        f"{greeting}{joined}. "
        "¿Necesitas una consulta más específica de alguno de tus productos?"
    )


def build_product_suggestions(
    snapshot: CustomerContextSnapshot,
    *,
    focus_product_id: str | None = None,
    limit: int = 4,
) -> list[dict[str, str]]:
    """Pre-built follow-up questions for chat chips (instant if user taps)."""
    suggestions: list[dict[str, str]] = []
    active = filter_active(snapshot)

    def add(question: str, ref: str, intent: str) -> None:
        if len(suggestions) >= limit:
            return
        suggestions.append({"question": question, "ref": ref, "intent": intent})

    for p in active:
        if focus_product_id and p.product_id != focus_product_id:
            continue
        label = display_label_in_context(p, active)
        if p.product_type in ("SAVINGS", "CHECKING", "PAYROLL"):
            add(f"¿Cuál es el saldo de {label}?", p.product_id, "ACCOUNT_BALANCE_READ")
        elif p.product_type == "CREDIT_CARD":
            add(f"¿Cuál es mi límite en {label}?", p.product_id, "CREDIT_CARD_DETAIL_READ")
            add(f"¿Cuándo corta {label}?", p.product_id, "CREDIT_CARD_DETAIL_READ")
        elif p.product_type == "LOAN":
            add(f"¿Cuánto debo de {label}?", p.product_id, "LOAN_DETAIL_READ")
        elif p.product_type == "TERM_DEPOSIT":
            add(f"¿Cuándo vence {label}?", p.product_id, "TERM_DEPOSIT_DETAIL_READ")

    if not focus_product_id:
        if any(p.product_type in ("SAVINGS", "CHECKING", "PAYROLL") for p in active):
            add("¿Cuáles son mis productos?", "", "PORTFOLIO_LIST")
    return suggestions[:limit]
