r"""Strict decimal string types for monetary values.

NonNegativeDecimalString: pattern ^\d+(\.\d+)?$ — amounts, reserves
SignedDecimalString: pattern ^-?\d+(\.\d+)?$ — balances (can be negative)

In JSON: accepts only string. Rejects JSON numbers.
Internally stores as Decimal. Serializes as string.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema

_NON_NEGATIVE_RE = re.compile(r"^\d+(\.\d+)?$")
_SIGNED_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _validate_non_negative(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        if not v.is_finite() or v < 0:
            msg = "Value must be a finite non-negative decimal."
            raise ValueError(msg)
        return v
    if isinstance(v, str):
        if not _NON_NEGATIVE_RE.match(v):
            msg = f"Value '{v}' does not match ^\\d+(\\.\\d+)?$"
            raise ValueError(msg)
        try:
            return Decimal(v)
        except InvalidOperation as e:
            raise ValueError(f"Cannot parse: '{v}'") from e
    if isinstance(v, int | float):
        msg = f'Monetary values must be strings, not {type(v).__name__}. Use "{v}" instead.'
        raise ValueError(msg)
    msg = f"Expected string or Decimal, got {type(v).__name__}"
    raise ValueError(msg)


def _validate_signed(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        if not v.is_finite():
            msg = "Value must be a finite decimal."
            raise ValueError(msg)
        return v
    if isinstance(v, str):
        if not _SIGNED_RE.match(v):
            msg = f"Value '{v}' does not match ^-?\\d+(\\.\\d+)?$"
            raise ValueError(msg)
        try:
            return Decimal(v)
        except InvalidOperation as e:
            raise ValueError(f"Cannot parse: '{v}'") from e
    if isinstance(v, int | float):
        msg = f'Monetary values must be strings, not {type(v).__name__}. Use "{v}" instead.'
        raise ValueError(msg)
    msg = f"Expected string or Decimal, got {type(v).__name__}"
    raise ValueError(msg)


def _serialize_decimal(v: Decimal) -> str:
    return str(v)


NonNegativeDecimalString = Annotated[
    Decimal,
    BeforeValidator(_validate_non_negative),
    PlainSerializer(_serialize_decimal, return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^\d+(\.\d+)?$"}),
]

SignedDecimalString = Annotated[
    Decimal,
    BeforeValidator(_validate_signed),
    PlainSerializer(_serialize_decimal, return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$"}),
]

# Backward compat
DecimalString = NonNegativeDecimalString
