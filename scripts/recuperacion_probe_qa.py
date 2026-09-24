#!/usr/bin/env python3
"""P0 contención: comparar fingerprints locales vs QA :8447."""
from __future__ import annotations

import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "works" / "recuperacion_integral"
RELS = [
    "src/genesis_cognitive/brain/azure_plan_turn.py",
    "src/genesis_cognitive/brain/plan_executor.py",
    "src/genesis_cognitive/brain/plan_interpreter.py",
    "src/genesis_cognitive/brain/semantic_mode.py",
    "src/genesis_cognitive/brain/azure_plan_adapter.py",
    "src/genesis_cognitive/agents/agent_framework_turn_resolver.py",
    "src/genesis_cognitive/agents/semantic_verifier.py",
    "src/genesis_cognitive/rag/azure_search_retrieve.py",
    "src/genesis_cognitive/rag/grounding_verifier.py",
    "src/genesis_cognitive/router/field_guardrails.py",
    "src/genesis_cognitive/router/domain_classifier.py",
    "src/genesis_cognitive/demo/contract_inspector_app.py",
]


def password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        once = Path(os.environ.get("TEMP", "/tmp")) / "genesis_ssh_pass_once.txt"
        if once.is_file():
            pw = once.read_text(encoding="utf-8").strip()
    if not pw:
        raise SystemExit("NO_PASSWORD")
    return pw


def main() -> int:
    snap_txt = OUT / "LATEST_SNAPSHOT.txt"
    if not snap_txt.is_file():
        raise SystemExit("NO_SNAPSHOT")
    snap = Path(snap_txt.read_text(encoding="utf-8").strip())
    local_meta = json.loads((snap / "LOCAL_SNAPSHOT.json").read_text(encoding="utf-8"))

    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    app = "/opt/genesis-cognitive-8447/Genesis_v2"
    pw = password()

    files_q = " ".join(shlex.quote(r) for r in RELS)
    remote_script = f"""
set -e
cd {shlex.quote(app)}
echo '===ENV==='
for k in AZURE_SEARCH_INDEX AZURE_OPENAI_CHAT_DEPLOYMENT GENESIS_AZURE_DEPLOYMENT AZURE_OPENAI_DEPLOYMENT GENESIS_SEMANTIC_MODE GENESIS_AZURE_BRAIN GENESIS_SEARCH_RETRIEVE GENESIS_SEARCH_RERANK_LOCAL; do
  v=$(grep -E "^$k=" .env 2>/dev/null | head -1 | cut -d= -f2- || true)
  echo "CFG $k=$v"
done
echo '===SERVICE==='
systemctl is-active genesis-cognitive-8447 || true
echo '===HASHES==='
for f in {files_q}; do
  if [ -f "$f" ]; then
    sha=$(sha256sum "$f" | awk '{{print $1}}')
    sz=$(stat -c%s "$f")
    echo "HASH $f $sha $sz"
  else
    echo "MISSING $f"
  fi
done
echo '===HEALTH==='
curl -sS -m 8 http://127.0.0.1:8447/health || true
echo
curl -sS -m 8 http://127.0.0.1:8447/ready/redis || true
echo
"""
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=pw, timeout=40, look_for_keys=False, allow_agent=False)
    wrapped = f"echo {shlex.quote(pw)} | sudo -S -p '' bash -lc {shlex.quote(remote_script)}"
    _i, stdout, stderr = c.exec_command(wrapped, timeout=90)
    raw = (stdout.read() + stderr.read()).decode("utf-8", "replace").replace(pw, "***")
    c.close()
    (snap / "QA_REMOTE_PROBE.txt").write_text(raw, encoding="utf-8")

    remote: dict = {}
    cfg: dict = {}
    for line in raw.splitlines():
        if line.startswith("HASH "):
            parts = line.split()
            if len(parts) >= 4:
                remote[parts[1]] = {"sha256": parts[2], "bytes": int(parts[3]), "exists": True}
        elif line.startswith("CFG "):
            k, v = line[4:].split("=", 1)
            cfg[k] = v
        elif line.startswith("MISSING "):
            remote[line.split(" ", 1)[1]] = {"exists": False}

    diffs = []
    for rel, loc in local_meta["local_fingerprints"].items():
        rem = remote.get(rel)
        if not loc.get("exists"):
            diffs.append({"file": rel, "status": "LOCAL_MISSING"})
            continue
        if not rem or not rem.get("exists", True):
            diffs.append({"file": rel, "status": "QA_MISSING", "local_sha": loc.get("sha256")})
            continue
        same = loc["sha256"] == rem.get("sha256")
        diffs.append(
            {
                "file": rel,
                "status": "MATCH" if same else "DIVERGED",
                "local_sha": loc["sha256"],
                "qa_sha": rem.get("sha256"),
                "local_bytes": loc["bytes"],
                "qa_bytes": rem.get("bytes"),
            }
        )

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": snap.name,
        "qa_host": host,
        "qa_app": app,
        "qa_cfg": cfg,
        "file_diffs": diffs,
        "diverged": [d for d in diffs if d["status"] == "DIVERGED"],
        "matched": [d["file"] for d in diffs if d["status"] == "MATCH"],
    }
    (snap / "LOCAL_VS_QA.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# BASELINE_Y_DIFERENCIAS",
        "",
        f"Generado: {report['created_utc']}",
        "",
        f"Snapshot: `{snap.name}`",
        "",
        "## Config QA efectiva",
        "",
    ]
    for k, v in cfg.items():
        lines.append(f"- `{k}` = `{v}`")
    lines += [
        "",
        "## Local vs QA (archivos cognitivos críticos)",
        "",
        "| Archivo | Estado |",
        "|---|---|",
    ]
    for d in diffs:
        lines.append(f"| `{d['file']}` | **{d['status']}** |")
    lines += [
        "",
        f"- MATCH: {len(report['matched'])}",
        f"- DIVERGED: {len(report['diverged'])}",
        "",
        "## Nota",
        "",
        "Sin repositorio Git: versionado por snapshot SHA256 + copia en `works/recuperacion_integral/snapshots/`.",
        "Promociones de ejemplos / ranking experimental: **pospuestas** durante P0.",
        "",
    ]
    (OUT / "BASELINE_Y_DIFERENCIAS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"cfg": cfg, "diverged_n": len(report["diverged"]), "matched_n": len(report["matched"]), "diverged_files": [d["file"] for d in report["diverged"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
