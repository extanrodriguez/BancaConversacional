#!/usr/bin/env python3
"""Despliegue controlado capa cognitiva QA (:8447) con VPN.

- Empaqueta build corp (sin .env)
- Sube ZIP, backup remoto vía deploy_8447.sh
- Fusiona claves QA necesarias (sin sobrescribir secretos existentes)
- Copia módulos/works faltantes del candidato
- Reinicia solo genesis-cognitive-8447
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
APP = "/opt/genesis-cognitive-8447/Genesis_v2"
ZIP_LOCAL = ROOT / "deploy" / "corp-8446" / "dist" / "genesis_corp_8446.zip"
REMOTE_ZIP = "/tmp/genesis_corp_8447.zip"
EVID = ROOT / "works" / "azure_mejora" / "deploy_vpn_20260921"


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("NO SSH_DEPLOY_PASS")
    return pw


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run(client: paramiko.SSHClient, cmd: str, *, sudo: bool = False, pw: str = "", timeout: int = 900) -> tuple[int, str]:
    wrapped = f"sudo -S -p '' bash -lc {shlex.quote(cmd)}" if sudo else cmd
    stdin, stdout, stderr = client.exec_command(wrapped, get_pty=True, timeout=timeout)
    if sudo:
        stdin.write(pw + "\n")
        stdin.flush()
    out = (stdout.read() + stderr.read()).decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    safe = out.replace(pw, "***") if pw else out
    return code, safe


def ensure_remote_dir(sftp: paramiko.SFTPClient, remote: str) -> None:
    parts = remote.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sftp.stat(cur)
        except OSError:
            try:
                sftp.mkdir(cur)
            except OSError:
                pass


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    pw = password()
    if not ZIP_LOCAL.is_file():
        print(f"MISSING_ZIP {ZIP_LOCAL} — build first", file=sys.stderr)
        return 2

    manifest = {
        "started_utc": utc(),
        "host": HOST,
        "zip_local": str(ZIP_LOCAL),
        "zip_sha256": sha256_file(ZIP_LOCAL),
        "zip_bytes": ZIP_LOCAL.stat().st_size,
    }
    print(json.dumps({k: manifest[k] for k in ("started_utc", "zip_sha256", "zip_bytes")}, indent=2))

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    print("SSH_OK")

    # Baseline pre
    code, baseline = run(
        c,
        "curl -sS -m 8 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 8 http://127.0.0.1:8447/ready/redis; echo; "
        "systemctl is-active genesis-cognitive-8447; "
        "ls -1 /opt/genesis-cognitive-8447/backups 2>/dev/null | tail -5 || true",
        timeout=60,
    )
    (EVID / "baseline_pre.txt").write_text(baseline, encoding="utf-8")
    print("BASELINE_PRE\n", baseline[-1500:])

    sftp = c.open_sftp()
    print(f"UPLOAD {ZIP_LOCAL.name} -> {REMOTE_ZIP}")
    sftp.put(str(ZIP_LOCAL), REMOTE_ZIP)

    # Extra cognitive files / insumos not always in zip layout
    extras = [
        "src/genesis_cognitive/context/upcoming_payment_window.py",
        "src/genesis_cognitive/rag/azure_search_retrieve.py",
        "src/genesis_cognitive/rag/kb_package_ingest.py",
        "data/kb_faq_overlay_potenciacion_lunes.json",
        "data/catalogo_campos_mapeados.json",
        "works/insumos/BSC_Potenciacion_Lunes/catalogo/productos_alias.json",
        "works/insumos/BSC_Potenciacion_Lunes/kb/chunks_qa.jsonl",
        "works/insumos/BSC_Potenciacion_Lunes/evaluacion/casos_236.json",
        "works/insumos/BSC_Potenciacion_Lunes/evaluacion/aceptacion_p0.json",
    ]
    for rel in extras:
        local = ROOT / rel
        if not local.is_file():
            print("SKIP_MISSING", rel)
            continue
        remote = f"{APP}/{rel}"
        ensure_remote_dir(sftp, str(Path(remote).as_posix().rsplit("/", 1)[0]))
        sftp.put(str(local), remote)
        print("PUT_EXTRA", rel)
    sftp.close()

    deploy_cmd = (
        f"cd {APP} && unzip -oq {REMOTE_ZIP} && "
        "find . -name '*.sh' -exec sed -i 's/\\r$//' {} \\; && "
        "bash deploy/corp-8447/deploy_8447.sh"
    )
    code, deploy_out = run(c, deploy_cmd, sudo=True, pw=pw, timeout=1200)
    (EVID / "deploy_8447_out.txt").write_text(deploy_out, encoding="utf-8")
    print("DEPLOY_EXIT", code)
    print(deploy_out[-4000:])
    if code != 0:
        c.close()
        manifest["status"] = "DEPLOY_FAILED"
        (EVID / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return code

    # Merge env keys (values only if missing or force-safe flags)
    merge = r"""
set -e
ENV=/opt/genesis-cognitive-8447/Genesis_v2/.env
_ensure() {
  local key="$1" val="$2"
  if grep -q "^${key}=" "$ENV"; then
    # actualizar flags no secretos
    case "$key" in
      GENESIS_ENV|GENESIS_SEMANTIC_MODE|GENESIS_AZURE_BRAIN|GENESIS_SEARCH_RETRIEVE|GENESIS_SESSION_BACKEND|GENESIS_REDIS_REQUIRED|GENESIS_REDIS_AUTH_MODE|GENESIS_FAQ_POTENCIACION_OVERLAY_PATH|GENESIS_KB_PACKAGE_ROOT|AZURE_SEARCH_INDEX)
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENV"
        ;;
    esac
  else
    echo "${key}=${val}" >> "$ENV"
  fi
}
_ensure GENESIS_ENV qa
_ensure GENESIS_SEMANTIC_MODE azure_plan
_ensure GENESIS_AZURE_BRAIN 1
_ensure GENESIS_SEARCH_RETRIEVE 1
_ensure GENESIS_SESSION_BACKEND redis
_ensure GENESIS_REDIS_REQUIRED 1
_ensure GENESIS_REDIS_AUTH_MODE entra_managed_identity
_ensure GENESIS_FAQ_POTENCIACION_OVERLAY_PATH /opt/genesis-cognitive-8447/Genesis_v2/data/kb_faq_overlay_potenciacion_lunes.json
_ensure GENESIS_KB_PACKAGE_ROOT /opt/genesis-cognitive-8447/Genesis_v2/works/insumos/BSC_Potenciacion_Lunes
# No pisar AZURE_SEARCH_INDEX si ya existe; solo asegurar default
if ! grep -q '^AZURE_SEARCH_INDEX=' "$ENV"; then
  echo 'AZURE_SEARCH_INDEX=bsc-kb-conocimiento' >> "$ENV"
fi
chmod 600 "$ENV"
chown genesis:genesis "$ENV"
# keys only
grep -E '^(GENESIS_ENV|GENESIS_SEMANTIC_MODE|GENESIS_AZURE_BRAIN|GENESIS_SEARCH_RETRIEVE|GENESIS_SESSION_BACKEND|GENESIS_REDIS_|AZURE_SEARCH_INDEX|GENESIS_FAQ_POTENCIACION|GENESIS_KB_PACKAGE)=' "$ENV" | sed 's/=.*/=***/'
"""
    code, merge_out = run(c, merge, sudo=True, pw=pw, timeout=60)
    (EVID / "env_merge_keys.txt").write_text(merge_out, encoding="utf-8")
    print("ENV_MERGE\n", merge_out)

    # Restart only cognitive service
    restart = (
        "systemctl kill -s SIGKILL genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl reset-failed genesis-cognitive-8447.service 2>/dev/null || true; "
        "systemctl start genesis-cognitive-8447.service; "
        "sleep 8; "
        "systemctl is-active genesis-cognitive-8447; "
        "curl -sS -m 10 http://127.0.0.1:8447/health; echo; "
        "curl -sS -m 10 http://127.0.0.1:8447/ready/redis; echo; "
        "test -f /opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive/context/upcoming_payment_window.py && echo HAS_P12_WINDOW || echo NO_P12_WINDOW; "
        "sha256sum /opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive/brain/plan_executor.py | awk '{print $1}'"
    )
    code, post = run(c, restart, sudo=True, pw=pw, timeout=120)
    (EVID / "post_restart.txt").write_text(post, encoding="utf-8")
    print("POST\n", post)

    # Smoke /turn from VM localhost
    smoke = r"""
python3 - <<'PY'
import json, urllib.request
payload={
  "customer_id":"726588",
  "conversation_id":"deploy-smoke-vpn",
  "text":"Hola",
  "lab_fallback": True,
}
req=urllib.request.Request(
  "http://127.0.0.1:8447/turn",
  data=json.dumps(payload).encode(),
  headers={"Content-Type":"application/json"},
  method="POST",
)
with urllib.request.urlopen(req, timeout=90) as resp:
  body=json.loads(resp.read().decode())
print("http", resp.status)
print("keys", sorted(body.keys())[:20])
reply=str(body.get("reply") or body.get("message") or (body.get("app_channel") or {}).get("client_response") or "")[:200]
print("reply_prefix", reply.replace("\n"," ")[:200])
PY
"""
    code, smoke_out = run(c, smoke, timeout=120)
    (EVID / "smoke_turn.txt").write_text(smoke_out, encoding="utf-8")
    print("SMOKE\n", smoke_out[-1200:])

    c.close()
    manifest.update({"finished_utc": utc(), "status": "QA_DESPLEGADO_CANDIDATO", "post_excerpt": post[-500:]})
    (EVID / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("DONE", manifest["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
