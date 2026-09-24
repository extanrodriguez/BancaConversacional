"""Integration-style: presentation envelope → map_core_portfolio (sin red)."""

from __future__ import annotations

from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio
from genesis_cognitive.context.presentation_product import normalize_presentation_payload
from genesis_cognitive.demo.contract_inspector_app import (  # may be heavy
    create_app,
)


def test_presentation_like_orch_maps_to_snapshot():
    # Shape típico API gateway (isSucceded + data)
    raw = {
        "isSucceded": True,
        "code": "00",
        "message": "OK",
        "data": {
            "resultCode": 0,
            "resultMessage": "Consulta realizada exitosamente.",
            "primerNombre": "UsuarioQA",
            "products": [
                {
                    "productCategory": "CA",
                    "productIdentification": "11082009999",
                    "productDescription": "Cuenta de Ahorros",
                    "currencyCode": "214",
                    "productStatus": "3",
                    "availableBalance": 1000.0,
                    "currentBalance": 1000.0,
                },
                {
                    "productCategory": "PR",
                    "productIdentification": "227700",
                    "productDescription": "Préstamo",
                    "currencyCode": "214",
                    "productStatus": "1",
                    "availableBalance": 50000,
                    "currentBalance": 48000.0,
                    "interestRatePr": 12.0,
                },
            ],
        },
    }
    data = normalize_presentation_payload(raw)
    mapped = map_core_portfolio(data)
    assert mapped.total_count == 2
    assert mapped.active_count == 2
    assert mapped.snapshot.display_name == "UsuarioQA"
