#!/usr/bin/env python3
"""Activa GPT-5 (o la variante disponible) en QA :8447.

En el recurso actual `testbsc0001` solo se detectó `gpt-4o-mini`.
Este script:
  1) Prueba deployments candidatos (gpt-5*, gpt-4.1*, …)
  2) Si existe uno usable, actualiza .env en la VM y reinicia :8447
  3) Si no existe, sale con instrucciones para crear el deployment en Azure

Uso:
  .\\.venv\\Scripts\\python.exe scripts\\activate_gpt5_qa.py
  .\\.venv\\Scripts\\python.exe scripts\\activate_gpt5_qa.py --prefer gpt-5.4
  .\\.venv\\Scripts\\python.exe scripts\\activate_gpt5_qa.py --probe-only
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import httpx
import paramiko
from openai import AzureOpenAI

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
ENV = f"{APP}/.env"

CANDIDATES = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-chat",
    "gpt-5.1-chat",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
]


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("NO SSH_DEPLOY_PASS")
    return pw


def probe(name: str, client: AzureOpenAI) -> tuple[bool, str]:
    try:
        r = client.chat.completions.create(
            model=name,
            messages=[{"role": "user", "content": "di OK"}],
            max_completion_tokens=8,
        )
        txt = (r.choices[0].message.content or "")[:40]
        return True, txt
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "DeploymentNotFound" in msg or "404" in msg or "does not exist" in msg.lower():
            return False, "not_found"
        return False, msg[:160]


def run_ssh(client: paramiko.SSHClient, cmd: str, *, sudo: bool, pw: str, timeout: int = 180) -> tuple[int, str]:
    wrapped = f"sudo -S -p '' bash -lc {shlex.quote(cmd)}" if sudo else cmd
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=timeout)
    if sudo:
        stdin.write(pw + "\n")
        stdin.flush()
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***")
    return stdout.channel.recv_exit_status(), out


def activate_on_vm(deployment: str) -> None:
    pw = password()
    ts = str(int(time.time()))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    remote = f"""
set -euo pipefail
test -f '{ENV}'
cp -a '{ENV}' '{APP}/.env.bak_model_{ts}'
# chat + semantic deployment
for KEY in AZURE_OPENAI_CHAT_DEPLOYMENT GENESIS_AZURE_DEPLOYMENT AZURE_OPENAI_DEPLOYMENT; do
  if grep -q "^${{KEY}}=" '{ENV}'; then
    sed -i "s/^${{KEY}}=.*/${{KEY}}={deployment}/" '{ENV}'
  else
    printf '\\n%s=%s\\n' "$KEY" '{deployment}' >> '{ENV}'
  fi
done
grep -E '^(AZURE_OPENAI_CHAT_DEPLOYMENT|GENESIS_AZURE_DEPLOYMENT|AZURE_OPENAI_DEPLOYMENT)=' '{ENV}'
systemctl restart genesis-cognitive-8447
sleep 6
systemctl is-active genesis-cognitive-8447
"""
    code, out = run_ssh(c, remote, sudo=True, pw=pw)
    print(out)
    c.close()
    if code != 0:
        raise SystemExit(f"activate_failed code={code}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefer", default="", help="Nombre exacto de deployment a priorizar")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--activate", action="store_true", help="Activar en VM si hay deployment usable")
    args = parser.parse_args()

    ep = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/") + "/"
    key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    ver = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    if not (ep and key):
        raise SystemExit("Faltan AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY")

    client = AzureOpenAI(azure_endpoint=ep, api_key=key, api_version=ver)
    order = list(CANDIDATES)
    if args.prefer:
        order = [args.prefer] + [x for x in order if x != args.prefer]

    found: list[str] = []
    print("Probing deployments on", ep)
    for name in order:
        ok, detail = probe(name, client)
        print(("OK " if ok else "NO "), name, "->", detail)
        if ok:
            found.append(name)

    evidence = Path("works/azure_mejora/model_activation")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "probe.json").write_text(
        json.dumps({"endpoint": ep, "found": found, "prefer": args.prefer}, indent=2) + "\n",
        encoding="utf-8",
    )

    gpt5 = [x for x in found if x.startswith("gpt-5")]
    chosen = None
    if args.prefer and args.prefer in found:
        chosen = args.prefer
    elif gpt5:
        chosen = gpt5[0]
    elif found:
        chosen = found[0]

    if not gpt5:
        print("\n=== GPT-5 NO DISPONIBLE en este recurso ===")
        print("Solo hay:", ", ".join(found) or "(ninguno)")
        print("Para implementar GPT-5 hay que CREAR el deployment en Azure OpenAI")
        print("  recurso: testbsc0001")
        print("  Portal Foundry / Azure OpenAI → Deployments → Create → modelo gpt-5 / gpt-5.4 / gpt-5-mini")
        print("  Luego: python scripts/activate_gpt5_qa.py --activate --prefer <nombre>")
        print("Bloqueo: falta az login / permisos de creación de deployment desde esta PC.")
        if args.probe_only or not args.activate:
            return 2

    if args.probe_only:
        print("probe-only: chosen would be", chosen)
        return 0 if chosen else 2

    if not args.activate:
        print("\nUse --activate para escribir el deployment en la VM.")
        print("chosen=", chosen)
        return 0 if chosen else 2

    if not chosen:
        return 2

    print("\nActivating on VM:", chosen)
    activate_on_vm(chosen)

    # smoke
    time.sleep(2)
    h = httpx.get(f"http://{HOST}:8447/health", timeout=15)
    print("health", h.status_code, h.text[:120])
    t = httpx.post(
        f"http://{HOST}:8447/turn",
        json={
            "question": "qué significa saldo disponible",
            "conversation_id": f"gpt5-smoke-{int(time.time())}",
            "client_id": "726588",
        },
        timeout=90,
    )
    print("turn", t.status_code)
    data = t.json() if t.headers.get("content-type", "").startswith("application/json") else {}
    print("reply_prefix", str(data.get("reply") or data.get("answer") or "")[:250])
    (evidence / "activation.json").write_text(
        json.dumps({"deployment": chosen, "turn": t.status_code}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
