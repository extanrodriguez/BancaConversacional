"""Unit tests: Presentation Product normalize (bootstrap orch .NET)."""

from __future__ import annotations

from genesis_cognitive.context.presentation_product import (
    normalize_presentation_payload,
    presentation_product_url,
)


def test_presentation_url_template_customer():
    url = presentation_product_url(
        "726588",
        "https://apigateway-gen.qa.bsc.com.do/api/presentation/product/{customerId}",
    )
    assert url.endswith("/726588")
    assert "apigateway-gen.qa.bsc.com.do" in url


def test_normalize_transport_wrapper():
    raw = {
        "isSucceded": True,
        "code": "OK",
        "message": "ok",
        "data": {
            "resultCode": 0,
            "resultMessage": "ok",
            "primerNombre": "Maria",
            "products": [
                {
                    "productCategory": "CA",
                    "productIdentification": "1",
                    "productStatus": "3",
                    "currencyCode": "214",
                }
            ],
        },
    }
    data = normalize_presentation_payload(raw)
    assert data["primerNombre"] == "Maria"
    assert len(data["products"]) == 1
    assert "isSucceded" not in data
    assert data["resultCode"] == 0


def test_normalize_data_array_to_products():
    raw = {
        "isSucceded": True,
        "data": [
            {
                "productCategory": "PR",
                "productIdentification": "99",
                "productStatus": "1",
                "currencyCode": "214",
            }
        ],
    }
    data = normalize_presentation_payload(raw)
    assert len(data["products"]) == 1
    assert data["products"][0]["productIdentification"] == "99"
    assert data["primerNombre"] == "Cliente"


def test_normalize_already_flat():
    raw = {
        "primerNombre": "Ana",
        "products": [{"productCategory": "CA", "productIdentification": "2"}],
    }
    data = normalize_presentation_payload(raw)
    assert data["primerNombre"] == "Ana"
    assert len(data["products"]) == 1
