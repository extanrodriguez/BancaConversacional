"""Genera Test_local/data/matriz_casos.json desde mvp_preguntas + matriz_mapping."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREGUNTAS = ROOT / "interfaz Prueba" / "mvp_preguntas.json"
MAPPING = ROOT / "Test_local" / "data" / "matriz_mapping.json"
OUT = ROOT / "Test_local" / "data" / "matriz_casos.json"


def _expect_status(caso: dict, mapping: dict) -> str | None:
    cid = caso["id"]
    amb = (caso.get("ambiguedad") or "").strip().lower()
    if cid in mapping["requires_selection_ids"]:
        return "requires_selection"
    if amb == "sí" or amb.startswith("sí,"):
        return "requires_selection"
    if cid in mapping.get("clarify_ids", []) and amb == "sí":
        return "requires_selection"
    if cid in mapping["no_product_ids"]:
        return None
    if cid in mapping["unavailable_ids"]:
        return "VALID_CONTRACT"
    return "VALID_CONTRACT"


def _must_contain(caso: dict) -> list[str]:
    return []


def main() -> None:
    preguntas = json.loads(PREGUNTAS.read_text(encoding="utf-8"))["casos"]
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    case_scenario = {int(k): v for k, v in mapping["case_scenario"].items()}
    prior = {int(k): v for k, v in mapping.get("prior_turn", {}).items()}

    casos = []
    for caso in preguntas:
        cid = caso["id"]
        esc = case_scenario.get(cid, "real_core")
        expect = _expect_status(caso, mapping)
        entry = {
            "id": cid,
            "escenario": esc,
            "producto": caso.get("producto"),
            "intencion": caso.get("intencion"),
            "ambiguedad": caso.get("ambiguedad"),
            "expresiones": list(caso.get("expresiones") or []),
            "prior_turn": prior.get(cid),
            "expect_status": expect,
            "expect_options_min": 2 if expect == "requires_selection" else 0,
            "must_contain_any": _must_contain(caso),
            "must_not_show_balance": cid in mapping["requires_selection_ids"],
        }
        casos.append(entry)

    payload = {
        "source": str(PREGUNTAS),
        "total": len(casos),
        "casos": casos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(casos)} casos -> {OUT}")


if __name__ == "__main__":
    main()
