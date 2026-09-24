"""Valida fixes: certificados, catálogo banco, fallecido en 8447."""
from __future__ import annotations

import json
import os
import shlex

import paramiko


def main() -> int:
    pw = os.environ["SSH_DEPLOY_PASS"]
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username="genesis", password=pw, timeout=30, look_for_keys=False, allow_agent=False)

    def run(cmd: str, timeout: int = 120) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", errors="replace")

    cases = [
        ("fallecido", "PROCESO DE RETIRO DE FONDO DEL CLIENTE FALLECIDO", ("fallecid", "sucesor", "defunci"), ("habilitados los canales",)),
        ("catalogo", "cuales son los productos que tiene el banco", ("cuentas", "préstamos", "prestamos", "solicitar"), ("tus productos activos", "disponible **")),
        ("cuentas_banco", "cuales cuentas tiene el banco", ("ahorro", "corriente", "contratar"), ("tus cuentas activas",)),
        ("certificados", "dame mis certificados", ("certificado", "depósito", "deposito", "no tienes"), ("garantía certificados",)),
    ]

    ok = 0
    for name, q, must, must_not in cases:
        body = json.dumps({"question": q, "allow_lab_fallback": True}, ensure_ascii=False)
        cmd = (
            "curl -sS -m 90 -X POST http://127.0.0.1:8447/orch/webhook/chat "
            "-H 'Content-Type: application/json' -H 'ClientId: 726588' "
            f"-d {shlex.quote(body)}"
        )
        out = run(cmd)
        try:
            reply = json.loads(out).get("reply") or ""
        except Exception:
            reply = out[:500]
        low = reply.lower()
        hit_must = any(m in low for m in must)
        hit_bad = any(m in low for m in must_not)
        passed = hit_must and not hit_bad
        ok += int(passed)
        print(("PASS" if passed else "FAIL"), name)
        print("  Q:", q)
        print("  reply:", reply[:350].replace("\n", " | "))
        print("---")

    # Local FAQ on VM for fallecido
    py = r"""
from genesis_cognitive.router.faq_guardrail import clear_faq_cache, apply_faq_guardrail, match_faq
from genesis_cognitive.router.field_guardrails import is_transfer_question, is_portfolio_list_question, is_bank_catalog_question
clear_faq_cache()
q='PROCESO DE RETIRO DE FONDO DEL CLIENTE FALLECIDO'
print('transfer?', is_transfer_question(q))
print('faq id', (match_faq(q) or {}).get('id'), (match_faq(q) or {}).get('topic'))
print('bank_cat productos', is_bank_catalog_question('cuales son los productos que tiene el banco'))
print('portfolio certificados', is_portfolio_list_question('dame mis certificados'))
"""
    print("==== VM unit checks ====")
    print(run("cd /opt/genesis-cognitive-8447/Genesis_v2 && .venv/bin/python -c " + shlex.quote(py)))

    c.close()
    print(f"TOTAL {ok}/{len(cases)}")
    return 0 if ok == len(cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
