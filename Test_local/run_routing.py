"""Ejecuta Test_local/data/escenarios_routing.json contra la API local."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from orquestador_local import OrquestadorLocal, load_portfolio  # noqa: E402


def main() -> int:
    routing = json.loads((HERE / "data" / "escenarios_routing.json").read_text(encoding="utf-8"))
    catalog = json.loads((HERE / "data" / "escenarios.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in catalog["escenarios"]}
    endpoint = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8445"
    orch = OrquestadorLocal(endpoint=endpoint)
    fails = 0
    for spec in routing["casos"]:
        esc = by_id[spec["escenario"]]
        orch.nueva_sesion()
        load = orch.cargar_portafolio(load_portfolio(esc["portfolio"]))
        if load.get("status") not in ("CONTEXT_LOADED", "CONTEXT_REFRESHED"):
            print("FAIL load", spec["escenario"], load)
            fails += 1
            continue
        resp = orch.preguntar(spec["question"])
        app = resp.get("app_channel") or {}
        text = str(app.get("client_response") or "")
        reasons: list[str] = []
        if spec.get("expect_status") and app.get("status") != spec["expect_status"]:
            reasons.append(f"status={app.get('status')} esperado={spec['expect_status']}")
        if spec.get("expect_intent") and app.get("intent_id") != spec["expect_intent"]:
            reasons.append(f"intent={app.get('intent_id')} esperado={spec['expect_intent']}")
        token = spec.get("must_contain")
        if token and token.lower() not in text.lower():
            reasons.append(f"no contiene '{token}'")
        if "None" in text:
            reasons.append("contiene None")
        ok = not reasons
        if not ok:
            fails += 1
        mark = "PASS" if ok else "FAIL"
        print(f"{mark} [{spec['escenario']}] {spec['question']}")
        print(f"    {app.get('status')} / {app.get('intent_id')}")
        print(f"    {text[:220]}")
        if reasons:
            print(f"    {'; '.join(reasons)}")
        print()
    total = len(routing["casos"])
    print(f"Routing: {total - fails}/{total} OK")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
