"""Fuerza GENESIS_SEMANTIC_MODE=legacy en QA :8447 (comportamiento tipo 8446).

Conserva Redis WRITE PATH / Entra. Apaga capas de evolución que no tenía el legacy.
NO toca :8446.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import sys

import paramiko

ENV_PATH = "/opt/genesis-cognitive-8447/Genesis_v2/.env"
SERVICE = "genesis-cognitive-8447.service"

# legacy-like: sin azure_plan V4; Foundry KB/brain opcionales off para acercar 8446
SETS = {
    "GENESIS_SEMANTIC_MODE": "legacy",
    "GENESIS_FOUNDRY_PRODUCT_TOOLS": "0",
    # Capas de evolución 8447 que no están en el path legacy 8446
    "GENESIS_FOUNDRY_KB_AGENT": "0",
    "GENESIS_KB_CONFIDENCE_GATE": "0",
    "GENESIS_AZURE_BRAIN": "0",
    "GENESIS_AZURE_DRAFT": "0",
}


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
            try:
                once.unlink()
            except OSError:
                pass
    if not pw:
        raise SystemExit("ERROR: define SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host} (solo 8447)...")
    client.connect(
        host, username=user, password=password, timeout=40,
        look_for_keys=False, allow_agent=False,
    )
    print("SSH OK")

    # Diagnóstico 8446 (solo lectura — no tocar)
    def run(cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        if sudo:
            wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        else:
            wrapped = cmd
        _i, stdout, stderr = client.exec_command(wrapped, timeout=180)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        out = out.replace(password, "***")
        return stdout.channel.recv_exit_status(), out

    print("--- estado 8446 (solo lectura) ---")
    _, out = run(
        "systemctl is-active genesis-cognitive-8446.service 2>/dev/null || echo inactive; "
        "systemctl is-enabled genesis-cognitive-8446.service 2>/dev/null || true; "
        "curl -sf -m 2 http://127.0.0.1:8446/health || echo '8446_HEALTH_FAIL'"
    )
    print(out[-1500:])

    # Upsert env keys
    py = (
        "import pathlib\n"
        f"p=pathlib.Path({ENV_PATH!r})\n"
        "text=p.read_text(encoding='utf-8') if p.is_file() else ''\n"
        "lines=text.splitlines()\n"
        f"sets={SETS!r}\n"
        "keys=set(sets)\n"
        "out=[]\n"
        "seen=set()\n"
        "for line in lines:\n"
        "    if not line.strip() or line.lstrip().startswith('#') or '=' not in line:\n"
        "        out.append(line); continue\n"
        "    k=line.split('=',1)[0].strip()\n"
        "    if k in sets:\n"
        "        out.append(f'{k}={sets[k]}'); seen.add(k)\n"
        "    else:\n"
        "        out.append(line)\n"
        "for k,v in sets.items():\n"
        "    if k not in seen:\n"
        "        out.append(f'{k}={v}')\n"
        "p.write_text('\\n'.join(out)+'\\n', encoding='utf-8')\n"
        "print('UPDATED')\n"
        "for k in sets:\n"
        "    print(next(x for x in out if x.startswith(k+'=')))\n"
    )
    remote_py = "/tmp/force_legacy_8447.py"
    sftp = client.open_sftp()
    with sftp.file(remote_py, "w") as f:
        f.write(py)
    sftp.close()

    code, out = run(
        f"python3 {remote_py} && "
        f"chown genesis:genesis {ENV_PATH} && chmod 600 {ENV_PATH} && "
        f"systemctl restart {SERVICE} && sleep 4 && "
        f"systemctl is-active {SERVICE} && "
        "curl -sf -m 8 http://127.0.0.1:8447/health; echo && "
        "curl -sf -m 8 http://127.0.0.1:8447/ready; echo && "
        f"grep -E '^(GENESIS_SEMANTIC_MODE|GENESIS_FOUNDRY_KB_AGENT|GENESIS_AZURE_BRAIN|GENESIS_FOUNDRY_PRODUCT_TOOLS|GENESIS_SESSION_BACKEND)=' {ENV_PATH} && "
        f"rm -f {remote_py}",
        sudo=True,
    )
    print(out[-4000:])
    client.close()
    if code != 0:
        print(f"FAIL {code}")
        return code
    print("OK — 8447 en modo legacy (tipo 8446). 8446 no modificado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
