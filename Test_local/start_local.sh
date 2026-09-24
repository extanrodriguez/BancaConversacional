#!/usr/bin/env bash
# Levanta Genesis Cognitive en local (puerto 8445) para Test_local.
# Uso:  bash Test_local/start_local.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creando .venv..."
  python3.12 -m venv .venv || python3 -m venv .venv
fi

.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev]"

export GENESIS_HOST="${GENESIS_HOST:-0.0.0.0}"
export GENESIS_PORT="${GENESIS_PORT:-8445}"
export GENESIS_ENV="${GENESIS_ENV:-dev}"
export GENESIS_SERVE_UI="${GENESIS_SERVE_UI:-false}"

echo "Cognitiva local en http://127.0.0.1:${GENESIS_PORT}"
echo "Interfaz de prueba: http://127.0.0.1:${GENESIS_PORT}/pruebas"
exec .venv/bin/python scripts/run_contract_inspector.py
