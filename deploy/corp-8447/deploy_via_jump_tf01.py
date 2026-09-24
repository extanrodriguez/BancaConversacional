"""Deploy 8447 a vm-genesis-bc-tf-01 (192.168.150.6) vía jump 20.127.25.24.

Requiere:
  SSH_DEPLOY_PASS  — password usuario genesis en el jump
  SSH_TARGET_PASS  — password usuario genesis en el target (o misma si no se setea)

No imprime secretos. Copia .env QA del jump al target (primera instalación).
"""
from __future__ import annotations

import os
import pathlib
import shlex
import sys
import time

import paramiko


JUMP_HOST = os.environ.get("SSH_JUMP_HOST", "20.127.25.24")
TARGET_HOST = os.environ.get("SSH_TARGET_HOST", "192.168.150.6")
USER = os.environ.get("SSH_USER", "genesis")
REMOTE_ZIP = "/tmp/genesis_corp_8447.zip"
REMOTE_ENV = "/tmp/genesis_8447.env.from_qa"
DEPLOY_DIR = "/opt/genesis-cognitive-8447/Genesis_v2"
QA_ENV = "/opt/genesis-cognitive-8447/Genesis_v2/.env"


def _connect(host: str, password: str, sock=None) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=USER,
        password=password,
        sock=sock,
        timeout=40,
        look_for_keys=False,
        allow_agent=False,
    )
    return client


def _run(client: paramiko.SSHClient, cmd: str, password: str, *, sudo: bool = False, timeout: int = 1200) -> tuple[int, str]:
    wrapped = f"sudo -S bash -lc {shlex.quote(cmd)}" if sudo else cmd
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=timeout)
    if sudo:
        stdin.write(password + "\n")
        stdin.flush()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    text = (out + err).strip()
    if text:
        try:
            print(text[-10000:])
        except UnicodeEncodeError:
            print(text[-10000:].encode("ascii", "replace").decode("ascii"))
    return code, text


def main() -> int:
    jump_pass = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    target_pass = (os.environ.get("SSH_TARGET_PASS") or jump_pass).strip()
    if not jump_pass:
        print("ERROR: define SSH_DEPLOY_PASS (jump)")
        return 1
    if not target_pass:
        print("ERROR: define SSH_TARGET_PASS (target)")
        return 1

    zip_local = (
        pathlib.Path(__file__).resolve().parents[1]
        / "corp-8446"
        / "dist"
        / "genesis_corp_8446.zip"
    )
    if not zip_local.is_file():
        print(f"ERROR: falta {zip_local} — ejecuta deploy/corp-8446/build_corp_package.py")
        return 1

    print(f"[1] Jump {USER}@{JUMP_HOST} ...")
    jump = _connect(JUMP_HOST, jump_pass)
    print("JUMP_SSH_OK")

    print(f"[2] Leyendo .env QA del jump ({QA_ENV}) ...")
    jsftp = jump.open_sftp()
    try:
        with jsftp.file(QA_ENV, "r") as f:
            env_bytes = f.read()
    except OSError as e:
        print(f"ERROR: no se pudo leer .env QA en jump: {e}")
        jump.close()
        return 2
    if not env_bytes or len(env_bytes) < 40:
        print("ERROR: .env QA vacío o demasiado corto")
        jump.close()
        return 2
    print(f"ENV_QA_BYTES={len(env_bytes)}")

    print(f"[3] Target via proxy {USER}@{TARGET_HOST} ...")
    channel = jump.get_transport().open_channel(
        "direct-tcpip", (TARGET_HOST, 22), ("127.0.0.1", 0)
    )
    target = _connect(TARGET_HOST, target_pass, sock=channel)
    print("TARGET_SSH_OK")

    code, _ = _run(target, "hostname; whoami; python3.12 --version; df -h / | tail -1", target_pass)

    print("[4] Paquetes base (unzip/curl/python3.12-venv) ...")
    _run(
        target,
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update -qq; "
        "apt-get install -y -qq unzip curl python3.12-venv python3.12-dev build-essential; "
        "command -v unzip && command -v curl && python3.12 -m venv /tmp/venvtest "
        "&& rm -rf /tmp/venvtest && echo DEPS_OK",
        target_pass,
        sudo=True,
        timeout=600,
    )

    print(f"[5] Subiendo ZIP ({zip_local.stat().st_size / 1e6:.1f} MB) ...")
    tsftp = target.open_sftp()
    tsftp.put(str(zip_local), REMOTE_ZIP)
    with tsftp.file(REMOTE_ENV, "w") as f:
        f.write(env_bytes)
    tsftp.close()
    print("UPLOAD_OK")

    print("[6] Preparando árbol + .env y deploy_8447.sh ...")
    deploy_cmd = (
        f"mkdir -p {DEPLOY_DIR} && "
        f"cp {REMOTE_ENV} {DEPLOY_DIR}/.env && "
        f"chmod 600 {DEPLOY_DIR}/.env && "
        f"chown -R {USER}:{USER} /opt/genesis-cognitive-8447 && "
        f"cd {DEPLOY_DIR} && "
        f"unzip -oq {REMOTE_ZIP} && "
        f"find . -name '*.sh' -exec sed -i 's/\\r$//' {{}} \\; && "
        f"bash deploy/corp-8447/deploy_8447.sh"
    )
    code, _ = _run(target, deploy_cmd, target_pass, sudo=True, timeout=1800)
    if code != 0:
        print(f"DEPLOY_FAIL exit={code}")
        _run(
            target,
            "sudo journalctl -u genesis-cognitive-8447 -n 60 --no-pager || true; "
            "ls -la /opt/genesis-cognitive-8447/Genesis_v2 | head",
            target_pass,
            sudo=True,
        )
        target.close()
        jump.close()
        return code

    print("[7] Validación health/pruebas ...")
    time.sleep(2)
    _run(
        target,
        "curl -sS -m 8 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 8 -o /dev/null -w 'pruebas_http=%{http_code}\\n' http://127.0.0.1:8447/pruebas/; "
        "systemctl is-active genesis-cognitive-8447; "
        "hostname -I | awk '{print \"PRIV_IP=\"$1}'",
        target_pass,
    )

    # Limpieza remota del env temporal (el ZIP puede quedar)
    _run(target, f"rm -f {REMOTE_ENV}; echo CLEAN_ENV_TMP", target_pass, sudo=True)

    print(f"=== Deploy OK → http://{TARGET_HOST}:8447/pruebas (vía VNet) ===")
    print("Nota: Redis Entra usa MI de la VM; si el OID nuevo no está autorizado, /ready/redis fallará hasta dar acceso.")

    target.close()
    jump.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
