# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shlex
import sys

import paramiko

password = os.environ["SSH_DEPLOY_PASS"]
host = os.environ.get("SSH_HOST", "20.127.25.24")
user = os.environ.get("SSH_USER", "genesis")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=password, timeout=40, look_for_keys=False, allow_agent=False)


def run(cmd: str) -> tuple[int, str]:
    wrapped = f"echo {shlex.quote(password)} | sudo -S -p '' bash -lc {shlex.quote(cmd)}"
    _i, o, e = client.exec_command(wrapped, timeout=180)
    out = (o.read() + e.read()).decode("utf-8", "replace").replace(password, "***")
    return o.channel.recv_exit_status(), out


code, out = run(
    "rm -rf /opt/genesis-cognitive-8447/Genesis_v2/data/cache/foundry_kb "
    "/opt/genesis-cognitive-8447/lab8446_runtime/data/cache/foundry_kb 2>/dev/null; "
    "echo CACHE_CLEARED; "
    "grep -n strip_foundry /opt/genesis-cognitive-8447/lab8446_runtime/lab8446/reply_format.py | head -3; "
    "grep -n _strip_foundry /opt/genesis-cognitive-8447/lab8446_runtime/sibling_src/genesis_cognitive/rag/foundry_kb_agent.py | head -3"
)
sys.stdout.buffer.write((out + "\n").encode("utf-8", "replace"))

smoke = r"""python3 - <<'PY'
import json, urllib.request, re
req = urllib.request.Request(
    'http://127.0.0.1:8447/turn',
    data=json.dumps({
        'conversation_id': 'smoke-fecha-corte-cite2',
        'question': 'Fecha de corte',
        'customer_id': '726588',
        'debug': True,
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=120) as r:
    body = json.loads(r.read().decode())
reply = body.get('reply') or body.get('message') or ''
safe = reply.encode('ascii', 'replace').decode('ascii')
print('REPLY_LEN', len(reply))
print('REPLY_PREFIX', safe[:500].replace('\n', ' | '))
print('HAS_PIPE_DUMP', bool(re.search(r'\|\s*\d{2,}\s*\|', reply)))
print('HAS_SOURCE_MARK', ('source' in reply.lower()) and any(ch in reply for ch in '\u2020\u2021\u3010\u3011'))
print('HAS_CORTE', 'corte' in reply.lower())
print('HAS_NUM_WALL', bool(re.search(r'(?:\|\s*\d+\s*){8,}', reply)))
dbg = body.get('debug') or {}
print('DEBUG_KEYS', sorted(list(dbg.keys()))[:20])
print('DEBUG_MODE', dbg.get('mode'))
PY"""
code2, out2 = run(smoke)
sys.stdout.buffer.write((out2 + f"\nEXIT {code2}\n").encode("utf-8", "replace"))
client.close()
raise SystemExit(0 if code2 == 0 else code2)
