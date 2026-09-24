"""Ventana temporal explícita para «pago próximo» (no basta tener fecha de pago)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

DEFAULT_TZ = "America/Santo_Domingo"
DEFAULT_WINDOW_DAYS = 30
# AST (UTC-4) — fallback cuando zoneinfo/tzdata no está disponible (p. ej. Windows).
_AST = timezone(timedelta(hours=-4))


def _zone(timezone_name: str = DEFAULT_TZ):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(timezone_name)
    except Exception:
        return _AST


@dataclass(frozen=True)
class PaymentWindow:
    reference_date: date
    timezone: str
    window_days: int

    @property
    def end_date(self) -> date:
        return self.reference_date + timedelta(days=self.window_days)

    def describe_es(self) -> str:
        return (
            f"ventana temporal: fecha de referencia **{self.reference_date.isoformat()}**, "
            f"zona horaria **{self.timezone}**, intervalo **próximos {self.window_days} días** "
            f"(hasta **{self.end_date.isoformat()}**, inclusive)"
        )


def resolve_payment_window(
    *,
    reference: date | datetime | str | None = None,
    timezone: str = DEFAULT_TZ,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> PaymentWindow:
    tz = _zone(timezone)
    if reference is None:
        ref_date = datetime.now(tz).date()
    elif isinstance(reference, datetime):
        ref_date = reference.astimezone(tz).date() if reference.tzinfo else reference.date()
    elif isinstance(reference, date):
        ref_date = reference
    else:
        ref_date = date.fromisoformat(str(reference)[:10])
    return PaymentWindow(reference_date=ref_date, timezone=timezone, window_days=int(window_days))


def parse_payment_date(raw: Any) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def classify_due_date(due: date | None, window: PaymentWindow) -> str:
    """Clasifica una fecha de pago respecto a la ventana.

    - upcoming: dentro de [referencia, fin] (incluye hoy)
    - overdue: anterior a la referencia (tiene fecha, no es «próximo»)
    - beyond: posterior al fin de ventana (tiene fecha, no es «próximo» en esta ventana)
    - missing: sin fecha parseable
    """
    if due is None:
        return "missing"
    if due < window.reference_date:
        return "overdue"
    if due > window.end_date:
        return "beyond"
    return "upcoming"


def _safe_month_day(year: int, month: int, day: int) -> date:
    while day >= 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, max(1, day))


def card_due_from_cutoff(cutoff_day: int | None, window: PaymentWindow) -> date | None:
    """Aproxima la próxima fecha de corte/pago del mes a partir del día de corte."""
    if cutoff_day is None:
        return None
    try:
        day = int(cutoff_day)
    except (TypeError, ValueError):
        return None
    if day < 1 or day > 31:
        return None
    ref = window.reference_date
    for month_offset in (0, 1, 2):
        y = ref.year + (ref.month + month_offset - 1) // 12
        m = (ref.month + month_offset - 1) % 12 + 1
        candidate = _safe_month_day(y, m, day)
        if candidate >= ref:
            return candidate
    return None


def window_audit_dict(window: PaymentWindow) -> dict[str, Any]:
    return {
        "payment_window_reference_date": window.reference_date.isoformat(),
        "payment_window_timezone": window.timezone,
        "payment_window_days": window.window_days,
        "payment_window_end_date": window.end_date.isoformat(),
        "payment_window_rule": "upcoming_only_within_inclusive_interval",
    }
