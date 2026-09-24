from genesis_cognitive.router.final_response_agent import build_loan_detail_response


DETAIL = {
    "product_id": "227615",
    "loan_type": "Préstamo Personal",
    "installment_amount": "32000.39",
    "annual_interest_rate": "10",
    "outstanding_principal": "29255.87",
    "delinquency_days": 0,
    "next_due_date": "2026-04-07",
    "disbursed_amount": "800000",
    "payoff_amount": None,
    "maturity_date": "2027-04-07",
    "last_four": "7615",
    "status_label": "al dia",
}


def test_debt_uses_principal() -> None:
    text = build_loan_detail_response("¿Cuánto debo de mi préstamo?", DETAIL, "Mario")
    assert "29255.87" in text
    assert "2027-04-07" not in text.split("terminado")[-1][:20]


def test_cancel_without_payoff_does_not_use_installment_as_payoff() -> None:
    text = build_loan_detail_response("¿Cuánto necesito para cancelar el préstamo?", DETAIL, "Mario")
    # Sin payoff: capital pendiente (no inventar con la cuota)
    assert "29255.87" in text
    assert "saldo de cancelación de tu préstamo terminado en 7615 es 32000" not in text


def test_next_due_not_maturity() -> None:
    text = build_loan_detail_response("¿Cuándo vence mi próxima cuota?", DETAIL, "Mario")
    assert "2026-04-07" in text
    assert "2027-04-07" not in text


def test_payoff_phrase_saldar() -> None:
    text = build_loan_detail_response("¿Cuánto tengo que pagar para saldar?", DETAIL, "Mario")
    assert "29255.87" in text
    assert "32000.39" not in text


def test_when_loan_ends() -> None:
    text = build_loan_detail_response("¿Cuándo termina mi préstamo?", DETAIL, "Mario")
    assert "2027-04-07" in text
    assert "2026-04-07" not in text


def test_loan_movements_unavailable() -> None:
    text = build_loan_detail_response("Muéstrame los últimos movimientos del préstamo", DETAIL, "Mario")
    assert "no está disponible" in text.lower()


def test_maturity_not_next_due() -> None:
    text = build_loan_detail_response("¿Cuál es la fecha de vencimiento del préstamo?", DETAIL, "Mario")
    assert "2027-04-07" in text


def test_mask_ignores_date_last_four() -> None:
    dirty = dict(DETAIL, last_four="2027-04-07")
    text = build_loan_detail_response("¿Cuánto debo?", dirty, "Mario")
    assert "terminado en 7615" in text
    assert "terminado en 2027" not in text


def test_cuota_missing_no_core_jargon_offers_alternatives() -> None:
    detail = dict(DETAIL, installment_amount=None)
    text = build_loan_detail_response("Cual es el monto de la cuota?", detail, "usuario 1")
    low = text.lower()
    assert "cuota contractual" in low or "monto de la cuota" in low
    assert "core" not in low
    assert "2026-04-07" in text  # próxima fecha disponible
    assert "29255.87" in text or "capital" in low
    assert "bsc en línea" in low or "809.726.1000" in text


def test_cuota_zero_treated_as_missing() -> None:
    detail = dict(DETAIL, installment_amount="0")
    text = build_loan_detail_response("cuanto es mi cuota", detail, "Felix")
    assert "core" not in text.lower()
    assert "32000.39" not in text
    assert "no tengo el monto de la cuota" in text.lower() or "no está disponible" in text.lower()


def test_cuota_present_returns_amount() -> None:
    detail = dict(DETAIL, installment_amount="32000.39", last_four="0658")
    text = build_loan_detail_response("cuanto es mi cuota", detail, "usuario 1")
    assert "32000.39" in text
    assert "cuota" in text.lower()


def test_cuanto_proxima_cuota_is_amount_not_date() -> None:
    detail = dict(DETAIL, installment_amount=None, next_due_date="2026-08-25", last_four="0658")
    for q in (
        "Cuanto es mi proxima cuota?",
        "De cuanto es mi proxima cuota?",
        "cual es mi proxima cuota?",
    ):
        text = build_loan_detail_response(q, detail, "usuario 1")
        low = text.lower()
        assert "próxima fecha de pago de tu préstamo" not in low
        assert "proxima fecha de pago de tu préstamo" not in low
        assert "cuota" in low or "capital" in low
        # No debe afirmar que la fecha ES la cuota
        assert "la próxima fecha de pago de tu préstamo terminado en 0658 es **2026-08-25**" not in text

    # Cuando sí pide fecha
    text_when = build_loan_detail_response("cuando es mi proxima cuota?", detail, "usuario 1")
    assert "2026-08-25" in text_when
    assert "fecha" in text_when.lower()

    text_fecha = build_loan_detail_response("cual es la fecha de mi proxima cuota", detail, "usuario 1")
    assert "2026-08-25" in text_fecha
