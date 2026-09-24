# Genera Test_local\BancaPruebas.exe (lanzador local de la interfaz /pruebas).
# Uso: powershell -ExecutionPolicy Bypass -File .\Test_local\build_pruebas_exe.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Falta .venv. Crea el entorno antes de generar el .exe."
}

& .\.venv\Scripts\python.exe -m pip install -q pyinstaller
$dist = Join-Path $PSScriptRoot ""
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --console `
    --name BancaPruebas `
    --distpath $PSScriptRoot `
    --workpath (Join-Path $PSScriptRoot "build_exe") `
    --specpath (Join-Path $PSScriptRoot "build_exe") `
    .\scripts\launch_pruebas.py

Write-Host "Listo: Test_local\BancaPruebas.exe"
Write-Host "Doble clic inicia la cognitiva y abre http://127.0.0.1:8445/pruebas"
