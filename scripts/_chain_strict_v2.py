import os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ["PYTHONPATH"] = str(ROOT / "src")
os.environ["PYTHONUNBUFFERED"] = "1"
py = str(ROOT / ".venv" / "Scripts" / "python.exe")
base = "http://20.127.25.24:8447"
print("starting p0 strict_v2", flush=True)
rc1 = subprocess.call([py, "-u", str(ROOT / "scripts" / "run_potenciacion_qa.py"), "--scope", "p0", "--base", base], cwd=str(ROOT))
print("p0 exit", rc1, flush=True)
print("starting all strict_v2", flush=True)
rc2 = subprocess.call([py, "-u", str(ROOT / "scripts" / "run_potenciacion_qa.py"), "--scope", "all", "--base", base], cwd=str(ROOT))
print("all exit", rc2, flush=True)
sys.exit(rc2 if rc1 == 0 else rc1)
