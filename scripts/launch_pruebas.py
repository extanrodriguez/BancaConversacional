"""Arranca la cognitiva local y abre la interfaz de prueba en el navegador.

Uso:
  python scripts/launch_pruebas.py
  Test_local\\BancaPruebas.exe
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
        for candidate in (here, here.parent, here.parent.parent):
            if (candidate / "scripts" / "run_contract_inspector.py").exists():
                return candidate
        return here
    return Path(__file__).resolve().parent.parent


def python_bin(root: Path) -> Path:
    win = root / ".venv" / "Scripts" / "python.exe"
    nix = root / ".venv" / "bin" / "python"
    if win.is_file():
        return win
    if nix.is_file():
        return nix
    return Path(sys.executable)


def wait_health(url: str, timeout_s: float = 60.0) -> None:
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(0.4)
    raise RuntimeError(f"La cognitiva no respondió en {url}: {last_err}")


def main() -> int:
    root = project_root()
    os.chdir(root)
    host = os.getenv("GENESIS_HOST", "127.0.0.1")
    port = os.getenv("GENESIS_PORT", "8445")
    os.environ["GENESIS_HOST"] = host if host != "127.0.0.1" else "0.0.0.0"
    os.environ["GENESIS_PORT"] = port
    os.environ["GENESIS_ENV"] = os.getenv("GENESIS_ENV", "dev")
    os.environ["GENESIS_SERVE_UI"] = "false"

    py = python_bin(root)
    script = root / "scripts" / "run_contract_inspector.py"
    if not script.is_file():
        print(f"No encuentro {script}. Coloca el .exe en la carpeta del proyecto.")
        return 1

    ui = f"http://127.0.0.1:{port}/pruebas"
    print("Iniciando Banca conversacional (pruebas)...")
    print(f"Interfaz: {ui}")
    print("Login = POST /turn con context_info (el JSON de Core). Luego chat o script QA.")
    already_up = False
    try:
        wait_health(f"http://127.0.0.1:{port}/health", timeout_s=1.5)
        already_up = True
        print("La cognitiva ya estaba en marcha.")
    except Exception:
        already_up = False

    proc = None
    if not already_up:
        proc = subprocess.Popen([str(py), str(script)], cwd=str(root))
        try:
            wait_health(f"http://127.0.0.1:{port}/health")
        except Exception as exc:  # noqa: BLE001
            print(exc)
            proc.terminate()
            return 1

    webbrowser.open(ui)
    if proc is None:
        print("Navegador abierto. El servidor sigue en el otro proceso.")
        return 0
    print("Servidor listo. Cierra esta ventana para detenerlo.")
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
