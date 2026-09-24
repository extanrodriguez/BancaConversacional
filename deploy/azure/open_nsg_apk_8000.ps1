# Abre TCP 8000 (endpoint APK /chat/front) en el NSG de vm-test002-genesis.
# Uso:
#   az login
#   powershell -ExecutionPolicy Bypass -File .\deploy\azure\open_nsg_apk_8000.ps1
#   powershell ... -IpAddress 181.61.204.113
#
# Nota: el APK apunta a http://20.127.25.24:8000/... El NSG hoy solo abre 8440-8449,
# por eso desde internet el APK se queda "pensando" (timeout) mientras /pruebas en :8447 sí funciona.

param(
    [string]$ResourceGroup = "RG_BSC_PRJ_GENESIS",
    [string]$NsgName = "vm-test002-genesis-nsg",
    [string]$RuleName = "Allow-APK-Front-8000",
    [int]$Priority = 118,
    [string]$IpAddress = ""
)

$ErrorActionPreference = "Stop"
$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
if (-not (Test-Path $az)) {
    $az = (Get-Command az -ErrorAction SilentlyContinue).Source
}
if (-not $az) {
    throw "Azure CLI no instalado. winget install -e --id Microsoft.AzureCLI"
}

if (-not $IpAddress) {
    $IpAddress = (Invoke-RestMethod "https://api.ipify.org?format=json" -TimeoutSec 15).ip
}
$cidr = "$IpAddress/32"
Write-Host "IP origen a permitir: $cidr"
Write-Host "Regla: $RuleName priority $Priority puerto 8000"

& $az account show *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ejecuta: az login --use-device-code"
    throw "No hay sesion Azure activa"
}

# Prefijos ya usados en la regla QA 8440-8449 (misma audiencia)
$existing = @()
try {
    $qa = & $az network nsg rule show -g $ResourceGroup --nsg-name $NsgName -n Allow-QA-To-Dev-8440-8449 -o json | ConvertFrom-Json
    if ($qa.sourceAddressPrefixes) { $existing = @($qa.sourceAddressPrefixes) }
    elseif ($qa.sourceAddressPrefix) { $existing = @($qa.sourceAddressPrefix) }
} catch {}

$prefixes = @($existing + $cidr | Select-Object -Unique)
Write-Host "Source prefixes: $($prefixes -join ', ')"

$show = & $az network nsg rule show -g $ResourceGroup --nsg-name $NsgName -n $RuleName -o json 2>$null
if ($LASTEXITCODE -eq 0 -and $show) {
    Write-Host "Actualizando regla existente..."
    & $az network nsg rule update `
        --resource-group $ResourceGroup `
        --nsg-name $NsgName `
        --name $RuleName `
        --source-address-prefixes $prefixes `
        --destination-port-ranges 8000 `
        --access Allow `
        --protocol Tcp `
        --direction Inbound
} else {
    Write-Host "Creando regla nueva..."
    & $az network nsg rule create `
        --resource-group $ResourceGroup `
        --nsg-name $NsgName `
        --name $RuleName `
        --priority $Priority `
        --direction Inbound `
        --access Allow `
        --protocol Tcp `
        --source-address-prefixes $prefixes `
        --destination-port-ranges 8000 `
        --destination-address-prefix '*' `
        --description "APK Banca Conversacional /chat/front -> genesis-rag :8000"
}

if ($LASTEXITCODE -ne 0) { throw "az nsg rule fallo" }

Write-Host ""
Write-Host "OK — puerto 8000 permitido para: $($prefixes -join ', ')" -ForegroundColor Green
Write-Host "Prueba desde tu PC:"
Write-Host "  Test-NetConnection 20.127.25.24 -Port 8000"
Write-Host "  curl http://20.127.25.24:8000/health"
