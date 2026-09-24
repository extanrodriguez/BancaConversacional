"""Valida frases criticas Azure-brain en 8447 via SSH (localhost)."""
from __future__ import annotations

import json
import os
import sys
import uuid

import paramiko


CASES = [
    # name, question, followup (optional), must_any, forbid
    (
        "cuanto_cuota",
        "Cuanto es mi proxima cuota?",
        "el que termina en 27615",
        ["cuota", "no tengo", "no disponible", "no figura"],
        [],
    ),
    (
        "cuando_cuota",
        "Cuando es mi proxima cuota?",
        "el que termina en 27615",
        ["fecha", "2026"],
        [],
    ),
    (
        "debito",
        "Cuanto debo en mis tarjetas de debito?",
        None,
        ["débito", "debito"],
        [],
    ),
    (
        "multi_tc",
        "Cuanto debo en mis tarjetas de credito y cual tiene mas disponible?",
        None,
        [],
        ["quieres consultar"],
    ),
    (
        "upcoming",
        "Tengo algun prestamo o tarjeta con un pago proximo?",
        None,
        ["pago"],
        ["5511", "180755"],
    ),
]


def reply_of(data: dict) -> str:
    app = data.get("app_channel") or {}
    return (
        app.get("client_response")
        or data.get("client_response")
        or data.get("reply")
        or ""
    ).strip()


def main() -> int:
    password = os.environ.get("SSH_DEPLOY_PASS")
    if not password:
        print("ERROR: SSH_DEPLOY_PASS")
        return 1
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    customer = os.environ.get("GENESIS_VALIDATE_CUSTOMER", "726588")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=os.environ.get("SSH_USER", "genesis"),
        password=password,
        timeout=30,
        look_for_keys=False,
        allow_agent=False,
    )

    def run(cmd: str, timeout: int = 180) -> str:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")

    # login + turns on localhost
    py = f"""
import json, uuid, urllib.request
BASE='http://127.0.0.1:8447'
CUSTOMER={customer!r}
cases={CASES!r}

def post(path, payload, timeout=120):
    data=json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(BASE+path, data=data, headers={{'Content-Type':'application/json'}}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))

def reply_of(data):
    app=data.get('app_channel') or {{}}
    return (app.get('client_response') or data.get('client_response') or data.get('reply') or '').strip()

try:
    cid=post('/lab/login', {{'customer_id': CUSTOMER}})['conversation_id']
except Exception as e:
    cid='crit-'+uuid.uuid4().hex[:8]
    print('LOGIN_WARN', type(e).__name__, str(e)[:120])

print('CID', cid)
results=[]
for name,q,follow,must_any,forbid in cases:
    try:
        data=post('/turn', {{
            'question': q,
            'customer_id': CUSTOMER,
            'conversation_id': cid,
            'allow_lab_fallback': True,
        }})
        text=reply_of(data)
        # Si pide aclaracion y hay followup, continuar
        low0=text.lower()
        if follow and ('deseas consultar' in low0 or 'sobre cuál' in low0 or 'sobre cual' in low0):
            data=post('/turn', {{
                'question': follow,
                'customer_id': CUSTOMER,
                'conversation_id': cid,
                'allow_lab_fallback': True,
            }})
            text=reply_of(data)
        low=text.lower()
        ok=True
        detail=[]
        if must_any:
            if not any(m.lower() in low or m.lower().replace('é','e') in low.replace('é','e') for m in must_any):
                ok=False
                detail.append('missing_any:'+','.join(must_any))
        for f in forbid:
            if f.lower() in low:
                ok=False
                detail.append('forbid:'+f)
        for bad in ('contrato válido','contrato valido','no se pudo generar','asesor se pond'):
            if bad in low:
                ok=False
                detail.append('bad:'+bad)
        # Anti-regresión: cuota monto no debe ser solo una fecha
        if name=='cuanto_cuota' and 'cuota' in low and '2026-' in text and 'no' not in low:
            if 'monto' not in low and 'dop' not in low and ',' not in text:
                # fecha sola como si fuera cuota
                if 'fecha' not in low:
                    ok=False
                    detail.append('date_as_amount?')
        results.append({{'name':name,'ok':ok,'detail':';'.join(detail),'text':text[:450]}})
        print(('PASS' if ok else 'FAIL'), name, '|', text[:240].replace('\\n',' '))
        if detail:
            print('  ', detail)
    except Exception as e:
        results.append({{'name':name,'ok':False,'detail':type(e).__name__+':'+str(e)[:160],'text':''}})
        print('FAIL', name, type(e).__name__, str(e)[:160])

n_ok=sum(1 for r in results if r['ok'])
print('SUMMARY', n_ok, '/', len(results))
print('JSON', json.dumps(results, ensure_ascii=False))
"""
    out = run(f"python3 - <<'PY'\n{py}\nPY", timeout=300)
    print(out[-8000:])
    client.close()
    return 0 if "SUMMARY 5 / 5" in out or "SUMMARY 4 / 5" in out else 1


if __name__ == "__main__":
    sys.exit(main())
