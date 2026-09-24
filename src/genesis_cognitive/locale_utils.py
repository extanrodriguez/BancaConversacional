"""Locale utilities — deterministic language derivation."""

import re

_LOCALE_PATTERN = re.compile(r"^([a-z]{2,3})(?:-[A-Z]{2})?$")


def language_from_locale(locale: str) -> str:
    """Derive the primary language component from a BCP-47 simplified locale.

    Rules:
    - es-DO → es
    - en-US → en
    - es → es
    - Rejects invalid formats (raises ValueError).
    - Does not invent languages or use defaults.
    """
    match = _LOCALE_PATTERN.match(locale)
    if not match:
        msg = f"Invalid locale format: '{locale}'. Expected pattern like 'es', 'es-DO', 'en-US'."
        raise ValueError(msg)
    return match.group(1)
