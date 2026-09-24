"""Detección de secretos de autenticación (PIN/OTP/CVV/contraseña).

Debe ejecutarse ANTES de extracción de sufijos de producto, follow-ups
por dígitos y llamadas al modelo. No suprime cifras de producto explícitas
sin marco de secreto (p. ej. \"cuenta terminada en 1234\").
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_SECRET_WORD = re.compile(
    r"(?i)\b("
    r"pin|otp|cvv|cvc|cvv2|"
    r"contrase(?:ñ|n)a|password|clave\s+de\s+acceso|"
    r"c[oó]digo\s+(?:de\s+)?(?:seguridad|verificaci[oó]n|otp|sms)|"
    r"token\s+(?:sms|otp)|"
    r"one[\s-]?time\s+password"
    r")\b"
)

_SECRET_CONTEXT = re.compile(
    r"(?i)("
    r"(?:mi|el|la|este|esta|ese|esa)\s+(?:pin|otp|cvv|contrase(?:ñ|n)a)|"
    r"(?:pin|otp|cvv|contrase(?:ñ|n)a)\s*(?:es|:|=)\s*\d{3,8}|"
    r"(?:te\s+paso|aqui\s+esta|aqu[ií]\s+est[aá]|mi)\s+(?:pin|otp|cvv)|"
    r"c[oó]digo\s+que\s+me\s+(?:lleg[oó]|envio|envi[oó])"
    r")"
)

_EXPLICIT_PRODUCT_SUFFIX = re.compile(
    r"(?i)\b("
    r"terminad[oa]\s+en|terminaci[oó]n|finalizad[oa]\s+en|"
    r"cuenta\s+\d|tarjeta\s+\d|pr[eé]stamo\s+\d|"
    r"n[uú]mero\s+de\s+(?:cuenta|tarjeta|pr[eé]stamo)"
    r")\b"
)


@dataclass(frozen=True)
class SecretScan:
    has_secret_frame: bool
    digits: tuple[str, ...]
    should_block_product_digit_match: bool


def scan_auth_secrets(text: str) -> SecretScan:
    """Analiza el mensaje en busca de marco de secreto de autenticación."""
    t = text or ""
    digits = tuple(re.findall(r"\d{3,8}", t))
    has_word = bool(_SECRET_WORD.search(t))
    has_ctx = bool(_SECRET_CONTEXT.search(t))
    has_secret = has_word or has_ctx
    explicit_product = bool(_EXPLICIT_PRODUCT_SUFFIX.search(t))
    # Bloquear match por dígitos si hay marco de secreto, salvo sufijo de producto
    # explícito SIN palabra de secreto (cuenta terminada en…).
    block = has_secret and not (explicit_product and not has_word and not has_ctx)
    # Si dice PIN y dígitos juntos, siempre bloquear
    if has_secret and digits:
        block = True
    return SecretScan(
        has_secret_frame=has_secret,
        digits=digits,
        should_block_product_digit_match=block,
    )


def is_auth_secret_message(text: str) -> bool:
    return scan_auth_secrets(text).has_secret_frame


_SECRET_CLAUSE = re.compile(
    r"(?i)("
    r"(?:mi|el|la|este|esta|ese|esa)\s+(?:pin|otp|cvv|cvc|contrase(?:ñ|n)a)\s*(?:es|:|=)?\s*[A-Za-z0-9@#_\\-]{0,32}"
    r"|"
    r"(?:pin|otp|cvv|cvc|contrase(?:ñ|n)a|password)\s*(?:es|:|=)\s*[A-Za-z0-9@#_\\-]{3,32}"
    r"|"
    r"el\s+c[oó]digo\s+que\s+me\s+(?:lleg[oó]|envio|envi[oó])\s*(?:es|:|=)?\s*\d{3,8}"
    r"|"
    r"c[oó]digo\s+que\s+me\s+(?:lleg[oó]|envio|envi[oó])\s*(?:es|:|=)?\s*\d{3,8}"
    r"|"
    r"(?:te\s+paso|aqu[ií]\s+est[aá])\s+(?:mi\s+)?(?:pin|otp|cvv)\s*[A-Za-z0-9@#_\\-]{0,32}"
    r"|"
    r",?\s*(?:[uú]salo|[uú]sala|util[ií]zalo|util[ií]zala)\s+para\b"
    r")"
)


def strip_auth_secret_clauses(text: str) -> str:
    """Quita cláusulas de PIN/OTP/CVV y deja la intención bancaria legítima.

    No elimina sufijos de producto explícitos sin marco de secreto.
    """
    if not text or not is_auth_secret_message(text):
        return text or ""
    out = _SECRET_CLAUSE.sub(" ", text)
    # Dígitos del secreto ya no deben quedar sueltos como candidatos de producto
    scan = scan_auth_secrets(text)
    for d in scan.digits:
        out = re.sub(rf"\b{re.escape(d)}\b", " ", out)
    out = re.sub(r"\s*[,;:]+\s*", " ", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;.-")
    # Muletillas residuales
    out = re.sub(r"(?i)^\s*(ahora|entonces|ok|oki|por\s+favor|el|la|los|las)\s+", "", out).strip()
    out = re.sub(r"(?i)^\s*(ahora|entonces)\s+", "", out).strip()
    return out


def redact_secret_digits_for_logs(text: str) -> str:
    """Enmascara secretos cuando hay marco PIN/OTP/CVV/contraseña (logs/historial).

    Cubre dígitos y tokens alfanuméricos adyacentes al marco (p. ej. Ab12xy).
    """
    scan = scan_auth_secrets(text)
    if not scan.has_secret_frame:
        return text or ""
    out = text or ""
    for d in scan.digits:
        out = out.replace(d, "***")
    # Alfanuméricos tras "pin/otp/cvv/contraseña es|=|:"
    out = re.sub(
        r"(?i)((?:pin|otp|cvv|cvc|contrase(?:ñ|n)a|password)\s*(?:es|:|=)\s*)([A-Za-z0-9@#_\\-]{3,32})",
        r"\1***",
        out,
    )
    out = re.sub(
        r"(?i)((?:mi|el|la)\s+(?:pin|otp|cvv|contrase(?:ñ|n)a)\s+)([A-Za-z0-9@#_\\-]{3,32})",
        r"\1***",
        out,
    )
    return out
