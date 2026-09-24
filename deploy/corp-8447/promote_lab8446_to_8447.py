"""Despliega BancaConversacional8446 como servicio :8447 preservando Redis WRITE PATH."""
from __future__ import annotations

import os
import pathlib
import shlex
import sys
import time
import zipfile

import paramiko

ROOT_LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
REMOTE_PARENT = "/opt/genesis-cognitive-8447"
REMOTE_LAB = f"{REMOTE_PARENT}/lab8446_runtime"
REMOTE_LEGACY = f"{REMOTE_PARENT}/Genesis_v2"
SERVICE = "genesis-cognitive-8447.service"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    once = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
    if not pw and once.is_file():
        pw = once.read_text(encoding="utf-8").strip()
        once.unlink(missing_ok=True)
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def _build_zip(path: pathlib.Path) -> pathlib.Path:
    out = pathlib.Path(os.environ["TEMP"]) / f"lab8446_promote_{int(time.time())}.zip"
    skip = {".venv", "__pycache__", ".git", "_tmp_guia_analisis"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in path.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(path)
            if any(part in skip for part in rel.parts):
                continue
            if p.name == ".env.8446":
                continue
            zf.write(p, rel.as_posix())
    return out


PATCH_ENV = r'''
from pathlib import Path
import shutil
lab = Path("/opt/genesis-cognitive-8447/lab8446_runtime")
legacy_env = Path("/opt/genesis-cognitive-8447/Genesis_v2/.env")
lab_env_src = Path("/tmp/lab8446_env_source")
dst = lab / ".env.8446"

# Base: lab AOAI/Foundry; Redis/session desde Genesis_v2
if lab_env_src.is_file():
    shutil.copy2(lab_env_src, dst)
elif legacy_env.is_file():
    shutil.copy2(legacy_env, dst)
else:
    dst.write_text("", encoding="utf-8")

def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out

legacy = _parse(legacy_env)
redis_keys = (
    "GENESIS_REDIS_URL",
    "GENESIS_REDIS_AUTH_MODE",
    "GENESIS_REDIS_REQUIRED",
    "GENESIS_SESSION_BACKEND",
    "GENESIS_SESSION_TTL_S",
)
sets = {
    "GENESIS_PORT": "8447",
    "GENESIS_HOST": "0.0.0.0",
    "GENESIS_ENV": "qa_lab8446_on_8447",
    "GENESIS_SERVE_UI": "1",
    "LAB8446_PROMOTE_8447": "1",
    "LAB8446_KEY_PREFIX": "",
    "GENESIS_SESSION_BACKEND": "redis",
    "GENESIS_REDIS_REQUIRED": "1",
    "LAB8446_SIBLING_SRC": str(lab / "sibling_src"),
    "LAB8446_PORTFOLIOS_DIR": str(lab / "data" / "lab_portfolios"),
}
for k in redis_keys:
    if k in legacy and legacy[k]:
        sets[k] = legacy[k]
sets["GENESIS_SESSION_BACKEND"] = "redis"
sets["GENESIS_REDIS_REQUIRED"] = "1"
sets["LAB8446_KEY_PREFIX"] = ""

text = dst.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()
out = []
seen = set()
for line in lines:
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k = line.split("=", 1)[0].strip()
    if k in sets:
        out.append(f"{k}={sets[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in sets.items():
    if k not in seen:
        out.append(f"{k}={v}")
dst.write_text("\n".join(out) + "\n", encoding="utf-8")
print("ENV_OK deployment=", _parse(dst).get("AZURE_OPENAI_CHAT_DEPLOYMENT"))
'''


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    zip_path = _build_zip(ROOT_LAB)
    print(f"ZIP {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando {user}@{host}...")
    client.connect(
        host, username=user, password=password, timeout=40,
        look_for_keys=False, allow_agent=False,
    )
    print("SSH OK")

    sftp = client.open_sftp()
    sftp.put(str(zip_path), "/tmp/lab8446_promote.zip")
    lab_env = ROOT_LAB / ".env.8446"
    if lab_env.is_file():
        sftp.put(str(lab_env), "/tmp/lab8446_env_source")
    with sftp.file("/tmp/patch_lab8446_env.py", "w") as f:
        f.write(PATCH_ENV)
    sftp.close()

    def run_sudo(cmd: str) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _i, stdout, stderr = client.exec_command(wrapped, timeout=900)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        out = out.replace(password, "***")
        code = stdout.channel.recv_exit_status()
        print(out[-7000:])
        return code, out

    ts = time.strftime("%Y%m%d_%H%M%S")
    unit = f"""[Unit]
Description=Genesis Cognitive API - Lab8446 Foundry+Redis on 8447
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=genesis
WorkingDirectory={REMOTE_LAB}
Environment=GENESIS_PORT=8447
Environment=LAB8446_PROMOTE_8447=1
EnvironmentFile={REMOTE_LAB}/.env.8446
ExecStart={REMOTE_LAB}/.venv/bin/python scripts/run_lab8446.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    sftp = client.open_sftp()
    with sftp.file("/tmp/genesis-cognitive-8447.lab8446.service", "w") as f:
        f.write(unit)
    sftp.close()

    cmd = f"""
set -euo pipefail
echo '=== BACKUP ==='
mkdir -p {REMOTE_PARENT}/backups
if [ -d {REMOTE_LEGACY} ]; then
  tar -czf {REMOTE_PARENT}/backups/genesis_v2_pre_lab8446_{ts}.tar.gz -C {REMOTE_PARENT} --exclude='Genesis_v2/.venv' Genesis_v2 || true
  cp -a {REMOTE_LEGACY}/.env {REMOTE_PARENT}/backups/env_pre_lab8446_{ts} || true
  chmod 600 {REMOTE_PARENT}/backups/env_pre_lab8446_{ts} || true
  echo BACKUP_OK
fi
echo '=== EXTRACT ==='
rm -rf {REMOTE_LAB}
mkdir -p {REMOTE_LAB}
cd {REMOTE_LAB}
unzip -oq /tmp/lab8446_promote.zip
mkdir -p {REMOTE_LAB}/sibling_src
if [ -d {REMOTE_LEGACY}/src/genesis_cognitive ]; then
  cp -a {REMOTE_LEGACY}/src/genesis_cognitive {REMOTE_LAB}/sibling_src/
fi
echo '=== VENV ==='
python3.12 -m venv {REMOTE_LAB}/.venv
{REMOTE_LAB}/.venv/bin/pip install -q --upgrade pip
{REMOTE_LAB}/.venv/bin/pip install -q -r {REMOTE_LAB}/requirements.txt
python3 /tmp/patch_lab8446_env.py
chmod 600 {REMOTE_LAB}/.env.8446
chown -R genesis:genesis {REMOTE_LAB}
echo '=== SYSTEMD ==='
cp /tmp/genesis-cognitive-8447.lab8446.service /etc/systemd/system/{SERVICE}
systemctl daemon-reload
systemctl restart {SERVICE}
sleep 6
systemctl is-active {SERVICE}
curl -sf -m 10 http://127.0.0.1:8447/health; echo
curl -sf -m 10 http://127.0.0.1:8447/ready; echo
# never touch legacy 8446
echo -n 'legacy8446='; systemctl is-active genesis-cognitive-8446.service 2>/dev/null || echo inactive
echo DONE
"""
    code, _ = run_sudo(cmd)
    client.close()
    try:
        zip_path.unlink()
    except OSError:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
