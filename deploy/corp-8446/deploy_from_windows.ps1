# Deploy Genesis Cognitive 8446 desde Windows
param(
    [string]$ServerHost = "192.168.150.5",
    [string]$SshUser = "genesis",
    [string]$PublicUrl = "http://20.127.25.24:8446",
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

Write-Host "=== Genesis 8446 - Deploy desde Windows ===" -ForegroundColor Cyan

Write-Host "[1/4] Construyendo paquete..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe .\deploy\corp-8446\build_corp_package.py
$Zip = Join-Path $Root "deploy\corp-8446\dist\genesis_corp_8446.zip"
if (-not (Test-Path $Zip)) {
    throw "No se genero el ZIP"
}
$sizeMb = [math]::Round((Get-Item $Zip).Length / 1MB, 2)
Write-Host "  Paquete listo:" $Zip "- tamaño:" $sizeMb "MB"

if ($BuildOnly) {
    Write-Host "BuildOnly completado." -ForegroundColor Green
    exit 0
}

$Target = "$SshUser@$ServerHost"
Write-Host "[2/4] Probando SSH a $Target ..." -ForegroundColor Yellow
ssh -o BatchMode=yes -o ConnectTimeout=15 $Target "hostname; whoami"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Sin conectividad SSH. Pasos manuales:" -ForegroundColor Red
    Write-Host "  scp `"$Zip`" ${Target}:/tmp/genesis_corp_8446.zip"
    Write-Host "  ssh $Target"
    Write-Host "  sudo bash /opt/genesis-cognitive-8446/Genesis_v2/deploy/corp-8446/deploy_8446.sh"
    Write-Host "  Abrir: $PublicUrl/pruebas"
    exit 2
}

Write-Host "[3/4] Subiendo paquete..." -ForegroundColor Yellow
scp -o ConnectTimeout=30 $Zip "${Target}:/tmp/genesis_corp_8446.zip"
if ($LASTEXITCODE -ne 0) {
    throw "scp fallo"
}

Write-Host "[4/4] Deploy remoto..." -ForegroundColor Yellow
$remoteCmd = 'if [ -f /opt/genesis-cognitive-8446/Genesis_v2/deploy/corp-8446/deploy_8446.sh ]; then sudo bash /opt/genesis-cognitive-8446/Genesis_v2/deploy/corp-8446/deploy_8446.sh; else sudo mkdir -p /opt/genesis-cognitive-8446/Genesis_v2; sudo chown -R genesis:genesis /opt/genesis-cognitive-8446; cd /opt/genesis-cognitive-8446/Genesis_v2; unzip -oq /tmp/genesis_corp_8446.zip; chmod +x deploy/corp-8446/*.sh; sudo bash deploy/corp-8446/deploy_8446.sh; fi'
ssh $Target $remoteCmd
if ($LASTEXITCODE -ne 0) {
    throw "Deploy remoto fallo"
}

Write-Host "=== Deploy OK ===" -ForegroundColor Green
Write-Host "  Health:  $PublicUrl/health"
Write-Host "  Pruebas: $PublicUrl/pruebas"
Write-Host "  Usuario: TEST-QA-001 (Andres David)"
