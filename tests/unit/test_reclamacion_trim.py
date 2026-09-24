"""Reclamaciones: no truncar a mitad de frase (p. ej. 'Los documentos deben…')."""

from __future__ import annotations

from genesis_cognitive.router.reclamacion_guardrail import (
    _kb_overview_answer,
    _trim_kb_answer_for_mobile,
    apply_reclamacion_guardrail,
)


def test_trim_keeps_importante_sentence() -> None:
    src = (
        "Apertura de reclamaciones\n\n"
        + ("Canal y proceso. " * 80)
        + "\n\nImportante:\n\n"
        "Los documentos deben ser enviados dentro de los 7 días calendario "
        "siguientes al registro de la reclamación.\n"
        "Si no se reciben las evidencias, podrá desestimarse.\n\n"
        "Seguimiento por Centro de Contacto."
    )
    assert len(src) > 1200
    out = _trim_kb_answer_for_mobile(src, max_chars=2200)
    assert "Los documentos deben ser enviados dentro de los 7 días" in out
    assert "deben…" not in out and "deben..." not in out


def test_trim_drops_incomplete_importante_block() -> None:
    # Simula el bug viejo: corte justo en "deben"
    broken_tail = (
        "Prefacio completo con canales de reclamación y correo serviciobancanet@bsc.com.do.\n\n"
        "Importante:\n\nLos documentos deben"
    )
    # Forzar ventana corta alrededor del bloque incompleto
    padded = ("Texto de canales. " * 40) + "\n\n" + broken_tail
    out = _trim_kb_answer_for_mobile(padded, max_chars=len(padded) - 5)
    assert "Los documentos deben…" not in out
    assert "Los documentos deben..." not in out
    # No debe quedar el encabezado Importante huérfano
    assert not out.rstrip().lower().endswith("importante:")


def test_reclamacion_overview_not_mid_sentence() -> None:
    out = _kb_overview_answer()
    assert out is not None
    assert "deben…" not in out and "deben..." not in out
    # Si aparece la frase, debe estar completa
    if "documentos deben" in out.lower():
        assert "7 días" in out or "7 dias" in out.lower() or "enviados" in out.lower()

    hit = apply_reclamacion_guardrail(None, "como hago una reclamacion")
    assert hit is not None
    text = hit[2] or ""
    assert "deben…" not in text and "deben..." not in text
    if "documentos deben" in text.lower():
        assert "enviados" in text.lower() or "7" in text
