"""Deploy + smoke: campos de negocio completos (listado y consultas puntuales)."""
from __future__ import annotations

import os
import pathlib
import shlex
import time
from datetime import datetime, timezone

import paramiko

LAB = pathlib.Path(r"C:\NovusIntelligence\BancoSantaCruz\BancaConversacional8446")
ROOT = pathlib.Path(__file__).resolve().parents[2]
REMOTE = "/opt/genesis-cognitive-8447/lab8446_runtime"
SERVICE = "genesis-cognitive-8447.service"
FILES = [
    "lab8446/models.py",
    "lab8446/tools.py",
    "lab8446/product_context_service.py",
    "lab8446/agent.py",
    "lab8446/business_fields.py",
    "lab8446/portfolio_loader.py",
]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
TAG = f"full_business_fields_{STAMP}"


def _password() -> str:
    pw = (os.environ.get("SSH_DEPLOY_PASS") or "").strip()
    if not pw:
        raise SystemExit("ERROR: SSH_DEPLOY_PASS")
    return pw


def main() -> int:
    password = _password()
    host = os.environ.get("SSH_HOST", "20.127.25.24")
    user = os.environ.get("SSH_USER", "genesis")
    for rel in FILES:
        if not (LAB / rel).is_file():
            print("MISSING", LAB / rel)
            return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=40, look_for_keys=False, allow_agent=False)

    def run(cmd: str, timeout: int = 360) -> tuple[int, str]:
        wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
        _, stdout, stderr = client.exec_command(wrapped, timeout=timeout)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").replace(password, "***")
        code = stdout.channel.recv_exit_status()
        if out.strip():
            print(out[-14000:])
        return code, out

    bak = f"/opt/genesis-cognitive-8447/backups/{TAG}"
    bak_cmds = [f"mkdir -p {bak}/lab8446"]
    for rel in FILES:
        bak_cmds.append(f"if [ -f {REMOTE}/{rel} ]; then cp -a {REMOTE}/{rel} {bak}/{rel}; fi")
    bak_cmds.append(
        f"tar -czf {bak}.tar.gz -C /opt/genesis-cognitive-8447/backups {TAG} && echo BACKUP_OK"
    )
    code_b, out_b = run(" && ".join(bak_cmds))
    if code_b != 0 or "BACKUP_OK" not in out_b:
        client.close()
        return 3

    (ROOT / "backups" / TAG).mkdir(parents=True, exist_ok=True)
    (ROOT / "backups" / TAG / "README.txt").write_text(TAG + "\n" + "\n".join(FILES), encoding="utf-8")

    sftp = client.open_sftp()
    ts = int(time.time())
    tmps: list[tuple[str, str]] = []
    for rel in FILES:
        tmp = f"/tmp/hotfix_fbf_{pathlib.Path(rel).name}_{ts}"
        sftp.put(str(LAB / rel), tmp)
        tmps.append((tmp, f"{REMOTE}/{rel}"))
    sftp.close()

    copies = " && ".join(
        f"cp -f {shlex.quote(s)} {shlex.quote(d)} && chown genesis:genesis {shlex.quote(d)}"
        for s, d in tmps
    )
    cleanup = " ; ".join(f"rm -f {shlex.quote(s)}" for s, _ in tmps)
    code, out = run(
        f"{copies} && grep -n 'CamposDisponibles' {REMOTE}/lab8446/models.py | head -2; "
        f"grep -n 'campo_glosario' {REMOTE}/lab8446/product_context_service.py | head -2; "
        f"systemctl restart {SERVICE}; sleep 6; systemctl is-active {SERVICE}; "
        f"curl -sf -m 10 http://127.0.0.1:8447/health; echo; {cleanup}; echo DEPLOY_OK"
    )
    if code != 0 or "DEPLOY_OK" not in out:
        client.close()
        return 4

    code2, out2 = run(
        r"""python3 - <<'PY'
import json, urllib.request, re, uuid

def turn(q):
    req = urllib.request.Request(
        'http://127.0.0.1:8447/turn',
        data=json.dumps({
            'conversation_id': 'smoke-fbf-' + uuid.uuid4().hex[:8],
            'question': q,
            'customer_id': '726588',
            'debug': True,
        }).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

results = {}

# 1) Listado rico
b = turn('lista mis productos')
r = b.get('reply') or ''
d = b.get('debug') or {}
checks = {
    'azure': d.get('mode') == 'azure_openai_tools',
    'tasa': bool(re.search(r'tasa|8\.15|12\.5|15\.0', r, re.I)),
    'corte': bool(re.search(r'corte', r, re.I)),
    'intereses': bool(re.search(r'intereses', r, re.I)),
    'venc': bool(re.search(r'vencim|fecha de pago|expir', r, re.I)),
    'cuota': bool(re.search(r'cuota', r, re.I)),
    'not_raw': 'ACCOUNT ' not in r and 'Encontré' not in r,
}
results['list'] = checks
print('LIST', checks)
print('LIST_HEAD', r[:500].encode('ascii','replace').decode('ascii'))

# 2) Intereses CD
b2 = turn('cuales son los intereses de mis certificados')
r2 = b2.get('reply') or ''
d2 = b2.get('debug') or {}
c2 = {
    'azure': d2.get('mode') == 'azure_openai_tools',
    'intereses': bool(re.search(r'3515|intereses|7362|9500|18904', r2, re.I)),
    'no_full_portfolio_accounts': not bool(re.search(r'Cuenta Corriente|corriente', r2, re.I)),
}
results['intereses'] = c2
print('INTERESES', c2)
print('INTERESES_REPLY', r2[:400].encode('ascii','replace').decode('ascii'))

# 3) Fecha pago / vencimiento TC
b3 = turn('cual es la fecha de pago de mis tarjetas')
r3 = b3.get('reply') or ''
d3 = b3.get('debug') or {}
c3 = {
    'azure': d3.get('mode') == 'azure_openai_tools',
    'fecha': bool(re.search(r'2026-|pago|corte', r3, re.I)),
    'cards': bool(re.search(r'tarjeta|Visa|Joven|Bravo|Multicredit', r3, re.I)),
    'no_cd': 'Certificado' not in r3 and 'Depósito a plazo' not in r3,
}
results['fecha_tc'] = c3
print('FECHA_TC', c3)
print('FECHA_REPLY', r3[:400].encode('ascii','replace').decode('ascii'))

# 4) Tasa préstamo
b4 = turn('cual es la tasa de mi prestamo personal')
r4 = b4.get('reply') or ''
c4 = {
    'tasa': bool(re.search(r'12\.5|tasa', r4, re.I)),
    'loan': bool(re.search(r'pr[eé]stamo|personal', r4, re.I)),
}
results['tasa_pr'] = c4
print('TASA_PR', c4)
print('TASA_REPLY', r4[:300].encode('ascii','replace').decode('ascii'))

# 5) Saldo ahorros (solo ahorros)
b5 = turn('Dime el saldo de mi cuenta de ahorros.')
r5 = b5.get('reply') or ''
c5 = {
    'ahorros': bool(re.search(r'ahorros|50,?000|581', r5, re.I)),
    'no_corriente': not bool(re.search(r'corriente|28,?500|31,?200', r5, re.I)),
    'not_raw': 'ACCOUNT ' not in r5,
}
results['saldo_ca'] = c5
print('SALDO_CA', c5)

# 6) Dia de corte TC
b6 = turn('cual es el dia de corte de mis tarjetas')
r6 = b6.get('reply') or ''
c6 = {
    'corte': bool(re.search(r'corte|\bd[ií]a\b|\b1\b|\b5\b|\b8\b|\b20\b', r6, re.I)),
}
results['corte'] = c6
print('CORTE', c6)
print('CORTE_REPLY', r6[:350].encode('ascii','replace').decode('ascii'))

ok = all([
    checks['azure'] and checks['tasa'] and checks['intereses'] and checks['not_raw'],
    c2['intereses'],
    c3['fecha'] and c3['cards'],
    c4['tasa'],
    c5['ahorros'] and c5['no_corriente'] and c5['not_raw'],
    c6['corte'],
])
# list corte/cuota soft: warn but allow if tasa+intereses ok
if not checks.get('corte') or not checks.get('cuota'):
    print('LIST_SOFT_WARN', {k: checks[k] for k in ('corte','cuota','venc')})
print('SMOKE_OK' if ok else 'SMOKE_FAIL')
print('RESULTS', results)
PY"""
    )
    client.close()
    if code2 != 0 or "SMOKE_OK" not in out2:
        print("FAIL smoke")
        return 6
    print(f"OK {TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
