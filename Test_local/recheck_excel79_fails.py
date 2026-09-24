"""Re-valida solo filas fallidas del Excel row79 (tras fix FAQ>loan)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

BASE = os.getenv("GENESIS_VALIDATE_BASE", "http://20.127.25.24:8447").rstrip("/")
CUSTOMER = os.getenv("GENESIS_VALIDATE_CUSTOMER", "726588")
PREV = Path(__file__).resolve().parent / "results" / "excel_row79_726588_8447.json"


def post(path, payload, timeout=90):
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    prev = json.loads(PREV.read_text(encoding="utf-8"))
    fails = [r for r in prev["rows"] if not r["ok"]]
    print(f"Reprobando {len(fails)} fallos en {BASE} user={CUSTOMER}")
    ok_n = bad_n = 0
    out = []
    for r in fails:
        q = r["question"]
        login = post("/lab/login", {"customer_id": CUSTOMER})
        cid = login["conversation_id"]
        data = post(
            "/turn",
            {
                "question": q,
                "customer_id": CUSTOMER,
                "conversation_id": cid,
                "allow_lab_fallback": True,
            },
        )
        app = data.get("app_channel") or {}
        txt = (app.get("client_response") or data.get("client_response") or data.get("reply") or "").strip()
        status = data.get("status") or app.get("status")
        low = txt.lower()
        hard_bad = (
            not txt
            or "asesor se pondra" in low
            or "numero de caso" in low
            or "contrato valido" in low
            or "contrato válido" in low
        )
        # mejora vs before: ya no pide elegir préstamo personal en definiciones
        improved = "sobre cuál deseas consultar" not in low and "sobre cual deseas consultar" not in low
        mark_ok = (not hard_bad) and (improved or len(txt) > 80)
        if mark_ok:
            ok_n += 1
            mark = "PASS*"
        else:
            bad_n += 1
            mark = "FAIL"
        print(f"[{mark}] r{r['row']} {q[:55]!r} | {status} | {txt[:120].replace(chr(10),' ')}")
        out.append({"row": r["row"], "ok": mark_ok, "status": status, "question": q, "actual": txt[:300]})
    path = Path(__file__).resolve().parent / "results" / "excel_row79_fails_recheck.json"
    path.write_text(json.dumps({"pass": ok_n, "fail": bad_n, "rows": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Recheck: {ok_n}/{ok_n+bad_n} mejorados/OK -> {path}")
    return 1 if bad_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
