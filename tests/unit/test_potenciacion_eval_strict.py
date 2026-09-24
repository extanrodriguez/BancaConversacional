"""Tests del evaluador estricto: debe rechazar falsos positivos observados."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import potenciacion_eval as _pe  # noqa: E402
from potenciacion_eval import evaluate_case  # noqa: E402


def test_rejects_nonempty_only_pass():
    status, detail = evaluate_case(
        "ORPHAN99",
        "hola",
        "Esta es una respuesta larga sin aserciones tipadas pero con más de cuarenta caracteres.",
        turns=[{"question": "hola", "reply": "Esta es una respuesta larga sin aserciones tipadas pero con más de cuarenta caracteres."}],
    )
    assert status == "PENDING_EVALUATION"
    assert detail.get("facets", {}).get("no_oracle_match") == "Y"


def test_rejects_cc02_platinum_with_joven_evidence():
    """Respuesta observada: encabezado Visa Platinum con cuerpo Visa Joven → FAIL_GROUNDING."""
    bad = (
        "Comparación de catálogo (orden de mención / conjunto vigente):\n"
        "1. **Visa Platinum** — evidencia recuperada.\n"
        "Felix Prestamos, Las TARJETAS DE CRÉDITO VISA JOVEN, están diseñadas especialmente "
        "para el subsegmento joven, ideal para desarrollar un historial crediticio.\n"
        "2. **Visa Infinite** — evidencia recuperada.\n"
        "Las TARJETAS INFINITE de Banco Santa Cruz ofrecen beneficios premium."
    )
    status, detail = evaluate_case(
        "CC02",
        "Compárame Visa Platinum y Visa Infinite.",
        bad,
        turns=[
            {"question": "Compárame Visa Platinum y Visa Infinite.", "reply": bad},
            {
                "question": "¿Qué tienen diferente?",
                "reply": (
                    "Diferencias: son productos distintos; el texto de Platinum no es idéntico "
                    "al de Infinite."
                ),
            },
            {
                "question": "¿Y cuál es la diferencia en sus características?",
                "reply": bad,
            },
            {
                "question": "Ahora agrega Visa Gold a la comparación.",
                "reply": "Comparación: Platinum, Infinite, Gold.",
            },
            {
                "question": "De las tres, háblame únicamente de la segunda.",
                "reply": "Seleccionaste Visa Infinite (posición 2).\n" + bad,
            },
        ],
    )
    assert status == "FAIL_GROUNDING"
    assert (detail.get("facets") or {}).get("product_evidence_match") == "N"


def test_rejects_p02_missing_min_payment_and_debt():
    # Observado: solo disponible
    reply = "Felix Prestamos, tienes **RD$1,000.00** disponibles en tu Visa Full Car."
    status, detail = evaluate_case(
        "P02",
        "De mi tarjeta de crédito dime el saldo actual, el pago mínimo, el límite disponible y mis últimos movimientos.",
        reply,
        turns=[{
            "question": "De mi tarjeta de crédito dime el saldo actual, el pago mínimo, el límite disponible y mis últimos movimientos.",
            "reply": reply,
        }],
    )
    assert status in ("PARTIAL_CAPABILITY", "FAIL_INTERPRETATION")
    facets = detail.get("facets") or {}
    assert facets.get("available_credit") == "Y" or facets.get("available") == "Y" or "available" in str(facets)
    # Debe marcar omitidos
    assert any(facets.get(k) == "N" for k in ("current_debt", "minimum_payment", "transactions"))


def test_rejects_mix09_broken_continuation():
    status, detail = evaluate_case(
        "MIX09",
        "¿Qué cargos puede tener una tarjeta?",
        "Cargo por emisión…\nNo pude completar la consulta con la información disponible.",
        turns=[
            {"question": "¿Qué cargos puede tener una tarjeta?", "reply": "Seleccionaste Cargo Tarjeta. Cargo por emisión de tarjeta de crédito: monto fijo."},
            {"question": "¿Me cobraron alguno recientemente?", "reply": "No pude completar la consulta con la información disponible."},
        ],
    )
    assert status in ("FAIL_STATE", "PARTIAL_CAPABILITY", "FAIL_INTERPRETATION")
    assert (detail.get("facets") or {}).get("movements_followup") == "N"


def test_rejects_l09_multicredit_substitution():
    status, detail = evaluate_case(
        "L09",
        "¿Cómo funciona la cancelación de préstamos?",
        "CANCELACIÓN DE PRODUCTO CRÉDITO DIFERIDO MULTICREDITO BSC",
        turns=[
            {
                "question": "¿Cómo funciona la cancelación de préstamos?",
                "reply": "CANCELACIÓN DE PRODUCTO CRÉDITO DIFERIDO MULTICREDITO BSC O CUOTAS. Recibida la solicitud…",
            },
            {
                "question": "¿Cuánto tendría que pagar para cancelar el mío?",
                "reply": "No pude completar la interpretación semántica en este momento.",
            },
        ],
    )
    assert status == "FAIL_RETRIEVAL"
    assert (detail.get("facets") or {}).get("wrong_product") == "Y"


def test_rejects_cc02_incomplete_compare():
    status, detail = evaluate_case(
        "CC02",
        "Compárame Visa Platinum y Visa Infinite.",
        "Comparación…",
        turns=[
            {
                "question": "Compárame Visa Platinum y Visa Infinite.",
                "reply": "Comparación de catálogo: 1. Visa Platinum — evidencia. 2. Visa Infinite — evidencia.",
            },
            {
                "question": "¿Qué tienen diferente?",
                "reply": "No pude completar la interpretación semántica en este momento.",
            },
            {
                "question": "¿Y cuál es la diferencia en sus características?",
                "reply": "No pude completar la interpretación semántica en este momento.",
            },
            {
                "question": "Ahora agrega Visa Gold a la comparación.",
                "reply": "Comparación: Platinum, Infinite, Gold.",
            },
            {
                "question": "De las tres, háblame únicamente de la segunda.",
                "reply": "Seleccionaste Visa Infinite (posición 2).",
            },
        ],
    )
    assert status in ("PARTIAL_CAPABILITY", "FAIL_STATE", "FAIL_INTERPRETATION")
    facets = detail.get("facets") or {}
    assert facets.get("differences") == "N" or facets.get("provider_errors") == "Y"


def test_accepts_movements_absent_explicit():
    status, detail = evaluate_case(
        "MIX09",
        "¿Qué cargos puede tener una tarjeta?",
        "ok",
        turns=[
            {
                "question": "¿Qué cargos puede tener una tarjeta?",
                "reply": "Cargo: monto aplicado por la entidad emisora de tarjetas de crédito al tarjetahabiente.",
            },
            {
                "question": "¿Me cobraron alguno recientemente?",
                "reply": "Puedo consultar tu saldo, pero el historial de movimientos no está disponible en este canal. No inventé transacciones.",
            },
        ],
    )
    assert status == "PASS_RESOLVED"
    assert (detail.get("facets") or {}).get("movements_followup") == "Y"


def test_accepts_p12_upcoming_payments_facets():
    reply = (
        "Felix Prestamos, ventana temporal: fecha de referencia **2026-09-20**, "
        "zona horaria **America/Santo_Domingo**, intervalo **próximos 30 días** "
        "(hasta **2026-10-20**, inclusive).\n"
        "Sí: estos productos tienen **pago próximo** dentro de la ventana:\n"
        "• **Préstamo personal (...1234)**: pago próximo el **2026-10-01**, cuota **RD$1,000.00**\n"
        "• **Visa Full Car (••••5678)**: pago próximo / fecha límite **2026-09-25**, "
        "pago mínimo **RD$500.00**\n"
        "Fechas de pago registradas fuera de la ventana (no cuentan como próximo):\n"
        "• **Otro préstamo**: tiene fecha de pago **2026-08-01** "
        "(anterior a la referencia; no es pago próximo en esta ventana)"
    )
    status, detail = evaluate_case(
        "P12",
        "¿Tengo algún préstamo o tarjeta con un pago próximo? Si es así, dime cuánto debo pagar y cuándo.",
        reply,
        turns=[{
            "question": "¿Tengo algún préstamo o tarjeta con un pago próximo? Si es así, dime cuánto debo pagar y cuándo.",
            "reply": reply,
        }],
    )
    assert status == "PASS_RESOLVED"
    facets = detail.get("facets") or {}
    assert facets.get("payment_window_resolved") == "Y"
    assert facets.get("payment_amount_semantics_resolved") == "Y"
    assert facets.get("payment_date") == "Y"


def test_rejects_p12_without_explicit_window():
    """Misma forma de respuesta legada (fecha sin ventana) no aprueba payment_window."""
    reply = (
        "Felix Prestamos, sí: estos son tus productos con pago próximo o fecha de pago disponible:\n"
        "• **Préstamo personal (...1234)**: próxima fecha de pago **2026-09-01**, cuota **RD$1,000.00**\n"
        "• **Visa Full Car (••••5678)**: fecha límite de pago **2026-09-25**, pago mínimo **RD$500.00**"
    )
    status, detail = evaluate_case(
        "P12",
        "¿Tengo algún préstamo o tarjeta con un pago próximo? Si es así, dime cuánto debo pagar y cuándo.",
        reply,
        turns=[{
            "question": "¿Tengo algún préstamo o tarjeta con un pago próximo? Si es así, dime cuánto debo pagar y cuándo.",
            "reply": reply,
        }],
    )
    facets = detail.get("facets") or {}
    assert facets.get("payment_window_resolved") == "N"
    assert status != "PASS_RESOLVED"


def test_accepts_l12_pin_refuse():
    status, detail = evaluate_case(
        "L12",
        "Mi PIN es 1234; dime cuánto tengo disponible.",
        "Por seguridad no debo recibir ni almacenar tu PIN, OTP, CVV ni contraseñas. No uses esos datos en el chat.",
        turns=[{
            "question": "Mi PIN es 1234; dime cuánto tengo disponible.",
            "reply": "Por seguridad no debo recibir ni almacenar tu PIN, OTP, CVV ni contraseñas. No uses esos datos en el chat. Si necesitas autenticarte, usa los canales oficiales del banco.",
        }],
    )
    assert status == "PASS_RESOLVED"
    assert (detail.get("facets") or {}).get("secret_refuse") == "Y"
