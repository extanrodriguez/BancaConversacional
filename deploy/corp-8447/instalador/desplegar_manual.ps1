# Despliegue 8447 desde esta carpeta (requiere VPN → 192.168.150.5)
# Uso:
#   .\desplegar_manual.ps1
#   .\desplegar_manual.ps1 -Password "..."
param(
    [string]$ServerHost = "192.168.150.5",
    [string]$SshUser = "genesis",
    [string]$Password = $env:SSH_DEPLOY_PASS
)

$ErrorActionPreference = "Stop"
$Here = $PSScriptRoot
$Zip = Join-Path $Here "genesis_corp_8447.zip"
if (-not (Test-Path $Zip)) { throw "Falta $Zip" }

Write-Host "=== Despliegue 8447 (manual SCP + SSH) ===" -ForegroundColor Cyan
Write-Host "ZIP: $Zip"
Write-Host "Destino: ${SshUser}@${ServerHost}:/tmp/genesis_corp_8447.zip"

Write-Host "`n[1/3] Subiendo ZIP..." -ForegroundColor Yellow
scp -o ConnectTimeout=30 $Zip "${SshUser}@${ServerHost}:/tmp/genesis_corp_8447.zip"
if ($LASTEXITCODE -ne 0) { throw "scp fallo — ¿VPN conectada?" }

$remote = @'
set -euo pipefail
echo "[2/3] Preparando y desplegando..."
sudo mkdir -p /opt/genesis-cognitive-8447/Genesis_v2
cd /opt/genesis-cognitive-8447/Genesis_v2
sudo unzip -oq /tmp/genesis_corp_8447.zip
sudo find . -name "*.sh" -exec sed -i "s/\r$//" {} \;
sudo chmod +x deploy/corp-8447/deploy_8447.sh
sudo bash deploy/corp-8447/deploy_8447.sh
echo "[3/3] Validacion webhook..."
curl -sS -m 8 -X POST "http://127.0.0.1:8447/orch/webhook/chat" \
  -H "Content-Type: application/json" \
  -H "ClientId: 726588" \
  -d "{\"question\":\"hola\"}" | head -c 500
echo
'@

Write-Host "`n[2/3] Ejecutando deploy en VM..." -ForegroundColor Yellow
ssh -o ConnectTimeout=30 "${SshUser}@${ServerHost}" $remote
if ($LASTEXITCODE -ne 0) { throw "Deploy remoto fallo" }

Write-Host "`n=== OK ===" -ForegroundColor Green
Write-Host "  Privada: http://${ServerHost}:8447/pruebas"
Write-Host "  Publica: http://20.127.25.24:8447/pruebas"
Write-Host "  Webhook: POST http://${ServerHost}:8447/orch/webhook/chat  (header ClientId)"
