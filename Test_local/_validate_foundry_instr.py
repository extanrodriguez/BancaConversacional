import os
import paramiko

qs = [
    "que es un certificado de deposito",
    "explica la diferencia entre fecha de corte y fecha limite de pago",
    "cual es la responsabilidad del banco como institucion",
]

host = os.environ.get("SSH_HOST", "20.127.25.24")
user = os.environ.get("SSH_USER", "genesis")
pw = os.environ["SSH_DEPLOY_PASS"]

remote_py = r"""
from genesis_cognitive.rag.foundry_kb_agent import ask_foundry_kb_agent
qs = __QS__
for q in qs:
    out = ask_foundry_kb_agent(q, display_name=None, prefer_clarify_ambiguous=False)
    print("===", q)
    print("status", out.get("status"), "ok", out.get("ok"))
    print("err", (out.get("error") or "")[:180])
    ans = (out.get("answer") or "").replace("\n", " ")
    print("answer", ans[:320])
    print()
""".replace("__QS__", repr(qs))

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, username=user, password=pw, timeout=25, look_for_keys=False, allow_agent=False)
sftp = c.open_sftp()
with sftp.file("/tmp/foundry_validate_instr.py", "w") as f:
    f.write(remote_py)
sftp.close()

cmd = (
    "bash -lc 'cd /opt/genesis-cognitive-8447/Genesis_v2 && "
    "source .venv/bin/activate && set -a && source .env && set +a && "
    "python /tmp/foundry_validate_instr.py'"
)
stdin, stdout, stderr = c.exec_command(cmd, timeout=180)
print(stdout.read().decode("utf-8", "replace"))
err = stderr.read().decode("utf-8", "replace")
if err:
    print("STDERR", err[-800:])
c.close()
