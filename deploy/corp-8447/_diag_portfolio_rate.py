"""Diagnóstico remoto: portafolio 726588 + interpret_turn_plan tasa/tarjeta."""
from __future__ import annotations

import os
import shlex
import textwrap

import paramiko

BASE = "/opt/genesis-cognitive-8447/Genesis_v2"
SCRIPT = textwrap.dedent(
    r"""
    import json
    from pathlib import Path
    from genesis_cognitive.context.core_portfolio_mapper import map_core_portfolio_to_snapshot
    from genesis_cognitive.brain.plan_interpreter import (
        interpret_turn_plan,
        _product_bears_rate,
        _active_products,
        _match_portfolio_by_text,
    )

    raw = json.loads(Path("data/lab_portfolios/qa_726588_contract_demo.json").read_text())
    print("file_products", len(raw.get("products", [])))
    for x in raw.get("products", []):
        print(
            "FILE",
            x.get("productCategory"),
            x.get("productIdentification"),
            (x.get("productDescription") or "")[:48],
        )

    snap = map_core_portfolio_to_snapshot("726588", raw)
    print("snap_n", len(snap.products))
    for p in snap.products:
        print(
            "SNAP",
            p.product_type,
            p.product_id,
            getattr(p, "alias", None),
            "rate",
            getattr(p, "interest_rate", None) or getattr(getattr(p, "loan", None), "annual_interest_rate", None),
            "mat",
            getattr(p, "maturity_date", None),
            "status",
            p.status,
        )
    active = _active_products(snap)
    print("active", len(active), "rate_bearers", [p.product_id for p in active if _product_bears_rate(p)])
    print("match_joven", [(p.product_id, p.alias) for p in _match_portfolio_by_text("tarjeta joven", snap)])

    for q in (
        "cual es mi tasa de interes",
        "cual es el saldo de mi tarjeta joven",
        "cual es la tasa de mi tarjeta joven",
    ):
        plan = interpret_turn_plan(q, None, snapshot=snap)
        print("Q", q)
        for t in plan.tasks:
            print(
                " ",
                t.object,
                t.fields,
                t.status,
                t.entity_ref,
                (t.filters or {}).get("candidate_ids"),
            )
    """
)


def main() -> int:
    pw = os.environ["SSH_DEPLOY_PASS"].strip()
    qa = paramiko.SSHClient()
    qa.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    qa.connect(
        "20.127.25.24",
        username="genesis",
        password=pw,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )
    remote = "/tmp/diag_portfolio_rate.py"
    sftp = qa.open_sftp()
    with sftp.open(remote, "w") as fh:
        fh.write(SCRIPT)
    sftp.close()

    cmd = f"cd {BASE} && .venv/bin/python {remote}"
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}"
    stdin, stdout, stderr = qa.exec_command(wrapped, get_pty=True, timeout=120)
    stdin.write(pw + "\n")
    stdin.flush()
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace")
    print(out[-4000:].encode("ascii", "replace").decode("ascii"))
    qa.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
