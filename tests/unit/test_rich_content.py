"""Contrato rich_content y normalización para front."""

from genesis_cognitive.context.query_spec import build_query_spec, query_question
from genesis_cognitive.context.rich_content import (
    build_rich_content,
    normalize_client_markdown,
    safe_href,
)


def test_query_spec_survives_card_label() -> None:
    spec = build_query_spec(
        "dame la tasa de mis certificados",
        "TERM_DEPOSIT_DETAIL_READ",
    )
    assert spec["field"] == "rate"
    assert query_question(spec, "Certificado ...5511") == "cuál es la tasa de este producto"


def test_links_phone_email_web_are_structured() -> None:
    text = (
        "Centro de Contacto: 809.726.1000\n"
        "Correo: serviciobancanet@bsc.com.do\n"
        "Web: https://bsc.com.do/"
    )
    markdown = normalize_client_markdown(text)
    assert "tel:+18097261000" in markdown
    assert "mailto:serviciobancanet@bsc.com.do" in markdown
    rich = build_rich_content(markdown)
    links = [
        inline
        for block in rich["blocks"]
        for inline in block.get("content", [])
        if inline.get("type") == "link"
    ]
    assert {link["kind"] for link in links} == {"phone", "email", "web"}


def test_rejects_unsafe_links() -> None:
    assert safe_href("javascript:alert(1)") is None
    assert safe_href("data:text/html,x") is None
    assert safe_href("https://bsc.com.do/") is not None


def test_mask_cannot_break_markdown() -> None:
    out = normalize_client_markdown(
        "**Credito Joven (****6374)**: la fecha de corte es el día **8**."
    )
    assert "****" not in out
    assert "••••6374" in out
    assert out.count("**") == 4


def test_deceased_process_becomes_sections_and_lists() -> None:
    text = (
        "Proceso para familiares de un cliente fallecido. "
        "Etapas del Proceso Fase I – Notificación 1. Notificación inmediata: "
        "Visita una sucursal. 2. Bloqueo preventivo: El banco protege los fondos. "
        "Fase II – Retiro 1. Solicitud formal: Entrega los documentos."
    )
    markdown = normalize_client_markdown(text)
    assert "## Fase I" in markdown
    rich = build_rich_content(markdown)
    assert any(block["type"] == "section" for block in rich["blocks"])
    assert any(
        nested["type"] == "list"
        for block in rich["blocks"]
        for nested in block.get("blocks", [])
    )


def test_options_become_select_option_cards() -> None:
    rich = build_rich_content(
        "Selecciona:",
        options=[{
            "ref": "DEPOSITO_PLAZO_5511",
            "label": "Certificado ••••5511",
            "product_type": "term_deposit",
            "currency": "DOP",
        }],
    )
    cards = next(block for block in rich["blocks"] if block["type"] == "card_group")
    action = cards["cards"][0]["actions"][0]
    assert action == {
        "type": "select_option",
        "label": "Seleccionar",
        "selected_option_ref": "DEPOSITO_PLAZO_5511",
    }


def test_existing_official_subdomain_link_is_not_nested() -> None:
    text = (
        "[Solicita en línea]"
        "(https://solicitudesdigitales.bsc.com.do/)"
    )
    normalized = normalize_client_markdown(text)
    assert normalized == text
    rich = build_rich_content(text)
    link = rich["blocks"][0]["content"][0]
    assert link["href"] == "https://solicitudesdigitales.bsc.com.do/"


def test_existing_domain_label_link_is_not_nested() -> None:
    text = "[bsc.com.do](https://bsc.com.do/)"
    assert normalize_client_markdown(text) == text
