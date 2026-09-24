# Abre NSG QA para IP actual: puertos 8440-8449 y SSH 22
# Uso: powershell -ExecutionPolicy Bypass -File .\deploy\azure\open_nsg_qa_current_ip.ps1

param(
    [string]$ResourceGroup = "RG_BSC_PRJ_GENESIS",
    [string]$NsgName = "vm-test002-genesis-nsg",
    [string]$HttpRuleName = "Allow-QA-To-Dev-8440-8449",
    [string]$SshRuleName = "Allow-QA-SSH-22",
    [string]$IpAddress = ""
)

$ErrorActionPreference = "Stop"
$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
if (-not (Test-Path $az)) {
    $az = (Get-Command az -ErrorAction SilentlyContinue).Source
}
if (-not $az) { throw "Azure CLI no instalado" }

if (-not $IpAddress) {
    $IpAddress = (Invoke-RestMethod "https://api.ipify.org?format=json" -TimeoutSec 15).ip
}
$cidr = "$IpAddress/32"
Write-Host "IP a autorizar: $cidr"

& $az account show *> $null
if ($LASTEXITCODE -ne 0) { throw "Sin sesion Azure. Ejecuta: az login --use-device-code" }

function Add-IpToRule {
    param([string]$RuleName, [string]$DefaultPort, [int]$Priority)
    $exists = & $az network nsg rule show -g $ResourceGroup --nsg-name $NsgName -n $RuleName -o json 2>$null
    if (-not $exists) {
        Write-Host "Creando regla $RuleName ($DefaultPort) ..."
        & $az network nsg rule create `
            --resource-group $ResourceGroup `
            --nsg-name $NsgName `
            --name $RuleName `
            --priority $Priority `
            --direction Inbound `
            --access Allow `
            --protocol Tcp `
            --source-address-prefixes $cidr `
            --source-port-ranges "*" `
            --destination-address-prefixes "*" `
            --destination-port-ranges $DefaultPort `
            --description "QA temporary access $DefaultPort"
        return
    }
    $rule = $exists | ConvertFrom-Json
    $prefixes = @()
    if ($rule.sourceAddressPrefixes) { $prefixes = @($rule.sourceAddressPrefixes) }
    elseif ($rule.sourceAddressPrefix -and $rule.sourceAddressPrefix -ne "*") { $prefixes = @($rule.sourceAddressPrefix) }
    if ($prefixes -contains $cidr) {
        Write-Host "OK ya estaba en $RuleName"
        return
    }
    $newPrefixes = $prefixes + $cidr
    Write-Host "Actualizando $RuleName -> $($newPrefixes -join ', ')"
    & $az network nsg rule update `
        --resource-group $ResourceGroup `
        --nsg-name $NsgName `
        --name $RuleName `
        --source-address-prefixes $newPrefixes
}

Add-IpToRule -RuleName $HttpRuleName -DefaultPort "8440-8449" -Priority 119
Add-IpToRule -RuleName $SshRuleName -DefaultPort "22" -Priority 118

Write-Host ""
Write-Host "Listo. Prueba:" -ForegroundColor Green
Write-Host "  Test-NetConnection 20.127.25.24 -Port 22"
Write-Host "  Test-NetConnection 20.127.25.24 -Port 8447"
Write-Host "  http://20.127.25.24:8447/pruebas"
