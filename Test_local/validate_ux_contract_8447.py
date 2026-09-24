"""Valida continuidad de cards y rich_content contra QA :8447."""

from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")


def get(path: str) -> str:
    with urlopen(f"{BASE}{path}", timeout=30) as response:
        return response.read().decode("utf-8")


def post(path: str, payload: dict, timeout: int = 120) -> dict:
    request = Request(
        f"{BASE}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def login(customer: str, portfolio: str) -> str:
    return post(
        "/lab/login",
        {"customer_id": customer, "portfolio": portfolio},
    )["conversation_id"]


def turn(customer: str, conversation: str, question: str, ref: str | None = None) -> dict:
    payload = {
        "customer_id": customer,
        "conversation_id": conversation,
        "question": question,
    }
    if ref:
        payload["selected_option_ref"] = ref
    return post("/turn", payload)


def app(data: dict) -> dict:
    return data.get("app_channel") or {}


def rich_links(data: dict) -> list[dict]:
    result: list[dict] = []

    def walk(blocks: list[dict]) -> None:
        for block in blocks:
            result.extend(
                item for item in block.get("content", []) if item.get("type") == "link"
            )
            for item in block.get("items", []):
                result.extend(
                    inline
                    for inline in item.get("content", [])
                    if inline.get("type") == "link"
                )
            walk(block.get("blocks", []))

    rich = app(data).get("rich_content") or data.get("rich_content") or {}
    walk(rich.get("blocks", []))
    return result


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(("PASS" if ok else "FAIL"), name, ("| " + detail[:220]) if detail else "")
    return ok


def main() -> int:
    passed: list[bool] = []

    # 1) DAP: tasa debe sobrevivir al click de la card.
    customer = "UX-DAP"
    cid = login(customer, "mvp_dap_multi.json")
    first = turn(customer, cid, "dame la tasa de mis certificados")
    a1 = app(first)
    opts = a1.get("options") or []
    text1 = a1.get("client_response") or ""
    passed.append(check(
        "dap_options_rich",
        len(opts) >= 2
        and text1.count("\n• **") >= 2
        and any(b.get("type") == "card_group" for b in (a1.get("rich_content") or {}).get("blocks", []))
        and all((o.get("context") or {}).get("field") == "rate" for o in opts)
        and all("Moneda:" in (o.get("subtitle") or "") for o in opts),
        text1,
    ))
    if opts:
        selected = turn(customer, cid, opts[0]["label"], opts[0]["ref"])
        selected_text = app(selected).get("client_response") or ""
        low = selected_text.lower()
        passed.append(check(
            "dap_selection_keeps_rate",
            "tasa" in low
            and "fecha de vencimiento" not in low
            and "intereses acumulados" not in low,
            selected_text,
        ))
    else:
        passed.append(check("dap_selection_keeps_rate", False, "sin opciones"))

    cid = login(customer, "mvp_dap_multi.json")
    maturity = turn(customer, cid, "cuándo vence mi depósito a plazo")
    maturity_options = app(maturity).get("options") or []
    passed.append(check(
        "dap_options_maturity_and_currency",
        len(maturity_options) >= 2
        and all((o.get("context") or {}).get("field") == "maturity" for o in maturity_options)
        and all("Vence:" in (o.get("subtitle") or "") for o in maturity_options)
        and all("Moneda:" in (o.get("subtitle") or "") for o in maturity_options),
        json.dumps(maturity_options, ensure_ascii=False),
    ))

    # 2) Tarjetas: lista/negrita/máscara segura + fecha límite tras selección.
    customer = "UX-CARDS"
    cid = login(customer, "mvp_tarjetas_multi.json")
    first = turn(customer, cid, "cual es mi fecha limite de pago")
    a2 = app(first)
    opts = a2.get("options") or []
    text2 = a2.get("client_response") or ""
    passed.append(check(
        "card_options_markdown_safe",
        len(opts) >= 2 and text2.count("\n• **") >= 2 and "****" not in text2,
        text2,
    ))
    if opts:
        selected = turn(customer, cid, opts[0]["label"], opts[0]["ref"])
        selected_app = app(selected)
        selected_text = selected_app.get("client_response") or ""
        passed.append(check(
            "payment_date_rich_no_mask_conflict",
            "****" not in selected_text
            and (selected_app.get("rich_content") or {}).get("version") == "1.0"
            and ("fecha límite" in selected_text.lower() or "fecha limite" in selected_text.lower()),
            selected_text,
        ))
    else:
        passed.append(check("payment_date_rich_no_mask_conflict", False, "sin opciones"))

    # 3) Contactos accionables.
    customer = "UX-KB"
    cid = login(customer, "mvp_cuenta_unica.json")
    claim = turn(customer, cid, "como hago una reclamacion")
    links = rich_links(claim)
    passed.append(check(
        "claim_phone_link",
        any(link.get("href") == "tel:+18097261000" for link in links),
        app(claim).get("client_response") or "",
    ))

    # 4) Respuesta larga organizada.
    deceased = turn(customer, cid, "cual es el proceso de clientes fallecidos")
    blocks = (app(deceased).get("rich_content") or {}).get("blocks", [])
    passed.append(check(
        "deceased_sections",
        sum(block.get("type") == "section" for block in blocks) >= 2
        and any(
            nested.get("type") == "list"
            for block in blocks
            for nested in block.get("blocks", [])
        ),
        (app(deceased).get("client_response") or "")[:220],
    ))

    # 5) Simulador actualizado.
    js = get("/pruebas/app.js?v=13")
    passed.append(check(
        "simulator_rich_renderer",
        "renderRichContent" in js and "selected_option_ref" in js,
    ))

    print(f"SUMMARY {sum(passed)}/{len(passed)}")
    return 0 if all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
