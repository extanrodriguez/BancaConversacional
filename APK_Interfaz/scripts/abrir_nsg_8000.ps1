# Abre TCP 8000 en el NSG para que el APK alcance /chat/front.
# Requiere: az login
param(
    [string]$IpAddress = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$script = Join-Path $repoRoot "deploy\azure\open_nsg_apk_8000.ps1"

if (-not (Test-Path $script)) {
    throw "No se encontro $script"
}

Write-Host "Usando: $script"
if ($IpAddress) {
    & $script -IpAddress $IpAddress
} else {
    & $script
}

Write-Host ""
Write-Host "Siguiente: .\verificar_conectividad.ps1"
