"""Tests sanitización de metadatos KB y CTA digital."""

from __future__ import annotations

from genesis_cognitive.context.response_formatting import (
    DIGITAL_ONBOARDING_URL,
    append_digital_onboarding_link,
    sanitize_client_facing_text,
)
from genesis_cognitive.router.faq_guardrail import apply_faq_guardrail, clear_faq_cache


def test_sanitize_strips_matriz_metadata() -> None:
    raw = (
        "usuario 1, - Producto: Depósito a Plazo\n"
        "- Intencion: Consultar información integral del depósito\n"
        "- Funcionalidad: Consulta de Saldo de Depósito a Plazo\n"
        "- Expresiones del cliente: Dame toda la información de mi certificado\n"
        "### Respuesta / contexto aprobado\n"
        "Tu depósito en pesos terminado en 5511: monto de apertura RD$500,000.00."
    )
    clean = sanitize_client_facing_text(raw)
    low = clean.lower()
    assert "producto:" not in low
    assert "intencion:" not in low and "intención:" not in low
    assert "funcionalidad:" not in low
    assert "expresiones" not in low
    assert "contexto aprobado" not in low
    assert "5511" in clean
    assert "500,000" in clean or "500000" in clean.replace(",", "")


def test_digital_onboarding_link_on_catalog() -> None:
    clear_faq_cache()
    gr = apply_faq_guardrail(None, "dime cuales productos de cuentas puedo contratar en el banco", None)
    assert gr is not None
    text = gr[2] or ""
    assert DIGITAL_ONBOARDING_URL in text
    assert "ahorro" in text.lower() or "cuenta" in text.lower()
    assert "](" in text  # link markdown accionable
    # no duplicar
    once = append_digital_onboarding_link(text)
    assert once.count("solicitudesdigitales.bsc.com.do") == 1


def test_dame_mas_informacion_not_faq_matriz() -> None:
    clear_faq_cache()
    gr = apply_faq_guardrail(None, "DAME MAS INFORMACION", None)
    assert gr is None
