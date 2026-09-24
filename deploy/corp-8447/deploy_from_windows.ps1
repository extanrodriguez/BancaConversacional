# Deploy Genesis 8447 desde Windows (no toca 8446)
param(
    [string]$ServerHost = "192.168.150.5",
    [string]$SshUser = "genesis",
    [string]$PublicUrl = "http://20.127.25.24:8447",
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

Write-Host "=== Genesis 8447 Deploy (paralelo a 8446) ===" -ForegroundColor Cyan

Write-Host "[1/4] Construyendo paquete..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe .\deploy\corp-8446\build_corp_package.py
$Zip = Join-Path $Root "deploy\corp-8446\dist\genesis_corp_8446.zip"
$RemoteZip = "genesis_corp_8447.zip"
if (-not (Test-Path $Zip)) { throw "ZIP no generado" }

if ($BuildOnly) {
    Write-Host "BuildOnly OK: $Zip" -ForegroundColor Green
    exit 0
}

$Target = "$SshUser@$ServerHost"
Write-Host "[2/4] SSH $Target ..." -ForegroundColor Yellow
ssh -o BatchMode=yes -o ConnectTimeout=20 $Target "hostname; whoami"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Sin SSH. Manual:" -ForegroundColor Red
    Write-Host "  scp `"$Zip`" ${Target}:/tmp/$RemoteZip"
    Write-Host "  ssh $Target 'sudo bash /opt/genesis-cognitive-8447/Genesis_v2/deploy/corp-8447/deploy_8447.sh'"
    exit 2
}

Write-Host "[3/4] Subiendo..." -ForegroundColor Yellow
scp -o ConnectTimeout=30 $Zip "${Target}:/tmp/$RemoteZip"

Write-Host "[4/4] Deploy remoto 8447..." -ForegroundColor Yellow
$remoteCmd = 'ZIP=/tmp/genesis_corp_8447.zip; if [ -f /opt/genesis-cognitive-8447/Genesis_v2/deploy/corp-8447/deploy_8447.sh ]; then sudo bash /opt/genesis-cognitive-8447/Genesis_v2/deploy/corp-8447/deploy_8447.sh; else sudo mkdir -p /opt/genesis-cognitive-8447/Genesis_v2; cd /opt/genesis-cognitive-8447/Genesis_v2; unzip -oq /tmp/genesis_corp_8447.zip; chmod +x deploy/corp-8447/deploy_8447.sh; sudo bash deploy/corp-8447/deploy_8447.sh; fi'
ssh $Target $remoteCmd
if ($LASTEXITCODE -ne 0) { throw "Deploy fallo" }

Write-Host "=== OK ===" -ForegroundColor Green
Write-Host "  Pruebas: $PublicUrl/pruebas"
Write-Host "  Legacy:  http://20.127.25.24:8446 (sin cambios)"
