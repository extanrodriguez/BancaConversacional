import os, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
os.environ["PYTHONPATH"] = str(ROOT / "src")
py = str(ROOT / ".venv" / "Scripts" / "python.exe")
base = "http://20.127.25.24:8447"
# Wait until current p0 runner (if any) finishes by watching active pid file
active = ROOT / "works" / "qa_runs" / "_p0_retest_active.txt"
if active.exists():
    txt = active.read_text(encoding="utf-8", errors="replace")
    pid = None
    for part in txt.split():
        if part.startswith("PID="):
            try:
                pid = int(part.split("=",1)[1])
            except ValueError:
                pass
    if pid:
        print(f"waiting for p0 pid={pid}", flush=True)
        while True:
            try:
                os.kill(pid, 0)
                time.sleep(15)
            except OSError:
                break
        print("p0 finished", flush=True)
# Run all-scope
print("starting all-scope", flush=True)
rc = subprocess.call([py, str(ROOT / "scripts" / "run_potenciacion_qa.py"), "--scope", "all", "--base", base])
print("all-scope exit", rc, flush=True)
sys.exit(rc)
