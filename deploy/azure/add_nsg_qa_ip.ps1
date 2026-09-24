# Agrega IP de QA a la regla NSG Allow-QA-To-Dev-8440-8449 (Opción C)
# Uso:
#   1) az login   (o ya autenticado)
#   2) powershell -ExecutionPolicy Bypass -File .\deploy\azure\add_nsg_qa_ip.ps1
#   3) powershell ... -IpAddress 181.61.204.113

param(
    [string]$ResourceGroup = "RG_BSC_PRJ_GENESIS",
    [string]$NsgName = "vm-test002-genesis-nsg",
    [string]$RuleName = "Allow-QA-To-Dev-8440-8449",
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
Write-Host "IP a agregar: $cidr"

& $az account show *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ejecuta: az login --use-device-code"
    throw "No hay sesion Azure activa"
}

$ruleJson = & $az network nsg rule show `
    --resource-group $ResourceGroup `
    --nsg-name $NsgName `
    --name $RuleName `
    -o json | ConvertFrom-Json

if (-not $ruleJson) {
    throw "Regla $RuleName no encontrada en $NsgName"
}

$prefixes = @()
if ($ruleJson.sourceAddressPrefixes) {
    $prefixes = @($ruleJson.sourceAddressPrefixes)
} elseif ($ruleJson.sourceAddressPrefix -and $ruleJson.sourceAddressPrefix -ne "*") {
    $prefixes = @($ruleJson.sourceAddressPrefix)
}

if ($prefixes -contains $cidr) {
    Write-Host "La IP $cidr ya esta en la regla. Nada que hacer."
    exit 0
}

$newPrefixes = $prefixes + $cidr
Write-Host "Prefijos actuales: $($prefixes -join ', ')"
Write-Host "Nuevos prefijos:   $($newPrefixes -join ', ')"

& $az network nsg rule update `
    --resource-group $ResourceGroup `
    --nsg-name $NsgName `
    --name $RuleName `
    --source-address-prefixes $newPrefixes

if ($LASTEXITCODE -ne 0) { throw "az update fallo" }

Write-Host ""
Write-Host "OK — regla actualizada." -ForegroundColor Green
Write-Host "Prueba: http://20.127.25.24:8447/pruebas"
Write-Host "       http://20.127.25.24:8446/pruebas"
