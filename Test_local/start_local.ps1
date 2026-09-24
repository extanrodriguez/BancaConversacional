# Levanta Genesis Cognitive en local (puerto 8445) para Test_local.
# Uso:  powershell -ExecutionPolicy Bypass -File .\Test_local\start_local.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creando .venv..."
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install -q --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -q -e ".[dev]"

$env:GENESIS_HOST = "0.0.0.0"
$env:GENESIS_PORT = "8445"
$env:GENESIS_ENV = "dev"
$env:GENESIS_SERVE_UI = "false"

Write-Host "Cognitiva local (mismo pipeline Azure OpenAI que 8447) en http://127.0.0.1:8445"
Write-Host "Interfaz de prueba: http://127.0.0.1:8445/pruebas"
Write-Host "EXE local: Test_local\BancaPruebas.exe  (o python scripts\launch_pruebas.py)"
& .\.venv\Scripts\python.exe .\scripts\run_contract_inspector.py
