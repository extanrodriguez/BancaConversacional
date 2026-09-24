"""Diagnóstico 8447: servicio, código desplegado, orch, flujos clave."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import paramiko

HOST = os.environ.get("SSH_HOST", "20.127.25.24")
USER = os.environ.get("SSH_USER", "genesis")
PASS = os.environ.get("SSH_DEPLOY_PASS")
BASE_PUBLIC = f"http://{HOST}:8447"
BASE_PRIV = "http://192.168.150.5:8447"
CUSTOMER = os.environ.get("GENESIS_VALIDATE_CUSTOMER", "726588")
ROOT = Path(__file__).resolve().parents[1]

LOCAL_MARKERS = {
    "product_focus.py": ROOT / "src/genesis_cognitive/router/product_focus.py",
    "snapshot_guardrails.py": ROOT / "src/genesis_cognitive/router/snapshot_guardrails.py",
    "response_formatting.py": ROOT / "src/genesis_cognitive/context/response_formatting.py",
    "final_response_agent.py": ROOT / "src/genesis_cognitive/router/final_response_agent.py",
    "field_guardrails.py": ROOT / "src/genesis_cognitive/router/field_guardrails.py",
    "faq_guardrail.py": ROOT / "src/genesis_cognitive/router/faq_guardrail.py",
}

REMOTE_DIR = "/opt/genesis-cognitive-8447/Genesis_v2/src/genesis_cognitive"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def http_json(url: str, payload: dict | None = None, timeout: int = 45) -> tuple[int, dict | str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body[:500]
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body[:500]
    except Exception as e:
        return 0, str(e)


def reply_of(data: dict) -> str:
    if not isinstance(data, dict):
        return str(data)[:200]
    app = data.get("app_channel") or {}
    return (
        app.get("client_response")
        or data.get("client_response")
        or data.get("reply")
        or data.get("content")
        or data.get("message")
        or ""
    ).strip()


def options_of(data: dict) -> list:
    if not isinstance(data, dict):
        return []
    app = data.get("app_channel") or {}
    return app.get("options") or data.get("options") or []


def main() -> int:
    if not PASS:
        print("ERROR: SSH_DEPLOY_PASS missing")
        return 2

    print("=== A) Reachability from this PC ===")
    for label, url in (("public_health", f"{BASE_PUBLIC}/health"), ("priv_health", f"{BASE_PRIV}/health")):
        t0 = time.time()
        code, body = http_json(url, timeout=8)
        ms = int((time.time() - t0) * 1000)
        print(f"  {label}: code={code} ms={ms} body={str(body)[:120]}")

    print("\n=== B) SSH inspect VM ===")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30, look_for_keys=False, allow_agent=False)

    def run(cmd: str) -> str:
        _, out, err = client.exec_command(cmd, timeout=60)
        return (out.read() + err.read()).decode("utf-8", errors="replace")

    print(run("systemctl is-active genesis-cognitive-8447.service; ss -ltnp | grep -E ':8447|:8080' || true"))
    print(run("curl -sf -m 3 http://127.0.0.1:8447/health; echo; curl -sf -m 3 http://127.0.0.1:8080/health || curl -sf -m 3 http://127.0.0.1:8080/ || echo ORCH_FAIL"))
    print(run("grep -E '^GENESIS_(HOST|PORT|ORCH)' /opt/genesis-cognitive-8447/Genesis_v2/.env | head -20"))

    print("\n=== C) Code markers local vs remote ===")
    sftp = client.open_sftp()
    remote_map = {
        "product_focus.py": f"{REMOTE_DIR}/router/product_focus.py",
        "snapshot_guardrails.py": f"{REMOTE_DIR}/router/snapshot_guardrails.py",
        "response_formatting.py": f"{REMOTE_DIR}/context/response_formatting.py",
        "final_response_agent.py": f"{REMOTE_DIR}/router/final_response_agent.py",
        "field_guardrails.py": f"{REMOTE_DIR}/router/field_guardrails.py",
        "faq_guardrail.py": f"{REMOTE_DIR}/router/faq_guardrail.py",
    }
    drift = []
    for name, local_path in LOCAL_MARKERS.items():
        local_hash = sha256_bytes(local_path.read_bytes())
        rpath = remote_map[name]
        try:
            with sftp.open(rpath, "rb") as rf:
                remote_hash = sha256_bytes(rf.read())
            ok = local_hash == remote_hash
            print(f"  {name}: local={local_hash} remote={remote_hash} {'OK' if ok else 'DRIFT'}")
            if not ok:
                drift.append(name)
        except Exception as e:
            print(f"  {name}: REMOTE_MISSING ({e})")
            drift.append(name)

    # Marker strings for key features
    print("\n=== D) Feature strings on remote ===")
    checks = [
        (f"{REMOTE_DIR}/router/product_focus.py", "prefer_personal_loan_over_knowledge"),
        (f"{REMOTE_DIR}/context/response_formatting.py", "Total Adeudado"),
        (f"{REMOTE_DIR}/context/reactive_store.py", "product_focus"),
        (f"{REMOTE_DIR}/demo/contract_inspector_app.py", "loan_intent_resume"),
    ]
    for path, needle in checks:
        try:
            with sftp.open(path, "r") as rf:
                txt = rf.read().decode("utf-8", errors="replace")
            print(f"  {needle} in {path.split('/')[-1]}: {'YES' if needle in txt else 'NO'}")
            if needle not in txt:
                drift.append(f"missing:{needle}")
        except Exception as e:
            print(f"  {path}: ERR {e}")
            drift.append(path)

    print("\n=== E) Functional tests via SSH curl (localhost:8447) ===")
    # Run validation from inside the VM to avoid NSG issues
    remote_py = r"""
import json, urllib.request

BASE='http://127.0.0.1:8447'
CUST='726588'

def post(path, payload, timeout=60):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(BASE+path, data=data, headers={'Content-Type':'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def reply(d):
    app=d.get('app_channel') or {}
    return (app.get('client_response') or d.get('client_response') or d.get('reply') or '').strip()

def opts(d):
    app=d.get('app_channel') or {}
    return app.get('options') or d.get('options') or []

results=[]
# 1) orch health proxy
try:
    req=urllib.request.Request(BASE+'/orch/health')
    with urllib.request.urlopen(req, timeout=10) as r:
        body=r.read().decode()
    results.append(('orch_health', True, body[:160]))
except Exception as e:
    results.append(('orch_health', False, str(e)[:160]))

# 2) loan flow direct /turn
cid=post('/lab/login',{'customer_id':CUST})['conversation_id']
r1=post('/turn',{'question':'dame informacion sobre mis prestamos','customer_id':CUST,'conversation_id':cid,'allow_lab_fallback':True})
o=opts(r1)
pick=None
for x in o:
    lab=str(x.get('label') or '')
    if '7615' in lab or '27615' in lab:
        pick=lab; break
if not pick and o: pick=str(o[0].get('label') or '')
r2=post('/turn',{'question':pick or 'Préstamo ...27615','customer_id':CUST,'conversation_id':cid,'allow_lab_fallback':True})
ans2=reply(r2)
ok2=('Préstamo -' in ans2 or 'Préstamo -' in ans2) and 'Tasa Anual' in ans2 and '**' in ans2
results.append(('loan_card_markdown', ok2, ans2[:220]))

r3=post('/turn',{'question':'que tasa de interes tiene','customer_id':CUST,'conversation_id':cid,'allow_lab_fallback':True})
ans3=reply(r3)
ok3=('12.5' in ans3) and ('tarifario' not in ans3.lower())
results.append(('loan_tasa_followup', ok3, ans3[:220]))

# 3) topic switch resume
cid2=post('/lab/login',{'customer_id':CUST})['conversation_id']
post('/turn',{'question':'dame informacion sobre mis prestamos','customer_id':CUST,'conversation_id':cid2,'allow_lab_fallback':True})
post('/turn',{'question':pick or 'Préstamo ...27615','customer_id':CUST,'conversation_id':cid2,'allow_lab_fallback':True})
post('/turn',{'question':'cual es la mision del banco','customer_id':CUST,'conversation_id':cid2,'allow_lab_fallback':True})
r4=post('/turn',{'question':'que tasa de interes tiene','customer_id':CUST,'conversation_id':cid2,'allow_lab_fallback':True})
ans4=reply(r4)
ok4=('12.5' in ans4) and ('tarifario' not in ans4.lower())
results.append(('resume_after_mision', ok4, ans4[:220]))

# 4) orch proxy path if available
try:
    # lab login then orch/chat/front
    cid3=post('/lab/login',{'customer_id':CUST})['conversation_id']
    payload={
      'message':'hola',
      'conversation_id':cid3,
      'customer_id':CUST,
      'client_id':CUST,
    }
    # try common shapes
    for p in (
      {'question':'hola','conversation_id':cid3,'customer_id':CUST},
      {'message':'hola','conversation_id':cid3,'customer_id':CUST},
      {'text':'hola','conversation_id':cid3,'client_id':CUST},
    ):
      try:
        ro=post('/orch/chat/front', p, timeout=90)
        results.append(('orch_chat_front', True, str(reply(ro) or ro)[:220]))
        break
      except Exception as e:
        last=str(e)
    else:
        results.append(('orch_chat_front', False, last[:220]))
except Exception as e:
    results.append(('orch_chat_front', False, str(e)[:220]))

print(json.dumps(results, ensure_ascii=False, indent=2))
"""
    # upload and run
    remote_path = "/tmp/diag_8447_flows.py"
    with sftp.open(remote_path, "w") as rf:
        rf.write(remote_py)
    sftp.close()
    out = run(f"/opt/genesis-cognitive-8447/Genesis_v2/.venv/bin/python {remote_path}")
    print(out[-8000:])

    client.close()

    print("\n=== SUMMARY ===")
    print(f"code_drift={drift or 'none'}")
    return 0 if not drift else 1


if __name__ == "__main__":
    raise SystemExit(main())
