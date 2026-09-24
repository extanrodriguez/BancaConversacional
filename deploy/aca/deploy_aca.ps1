#Requires -Version 5.1
<#
.SYNOPSIS
  Provisiona Azure Container Apps (Bicep) + secretos KV + build ACR + smoke.

.NOTES
  - No apaga Cognitiva QA :8447 (VM).
  - Lee secretos desde .env en la raíz del repo (no los imprime).
  - Orden: infra -> secretos KV -> acr build -> Container App -> smoke.
#>
[CmdletBinding()]
param(
  [string]$SubscriptionId = "871a5b90-0204-450e-b968-3190e9143faf",
  [string]$ResourceGroup = "rg-genesis-cognitive-mvp-eus",
  [string]$Location = "eastus",
  [string]$ImageTag = "",
  [string]$BicepFile = "",
  [switch]$SkipBuild,
  [switch]$InfraOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not $BicepFile) {
  $BicepFile = Join-Path $RepoRoot "PlanContainerizacion\FASE_2\containerapp.bicep"
}
if (-not $ImageTag) {
  $ImageTag = (Get-Date -Format "yyyyMMdd-HHmmss")
}

function Read-DotEnv([string]$Path) {
  $map = @{}
  if (-not (Test-Path $Path)) { throw "No se encontro .env en $Path" }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $k = $line.Substring(0, $idx).Trim()
    $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
    $map[$k] = $v
  }
  return $map
}

function Invoke-Bicep([string]$Name, [hashtable]$Params) {
  $args = @(
    "deployment", "group", "create",
    "--name", $Name,
    "--resource-group", $ResourceGroup,
    "--template-file", $BicepFile
  )
  foreach ($k in $Params.Keys) {
    $args += "--parameters"
    $args += "$k=$($Params[$k])"
  }
  $args += @("--query", "properties.outputs", "-o", "json")
  $json = & az @args
  if ($LASTEXITCODE -ne 0) { throw "Fallo deployment $Name" }
  return ($json | ConvertFrom-Json)
}

Write-Host "==> Repo: $RepoRoot"
Write-Host "==> Image tag: $ImageTag"

az account show -o none 2>$null
if ($LASTEXITCODE -ne 0) {
  throw "Ejecuta 'az login' primero (device code o interactivo)."
}

az account set --subscription $SubscriptionId
Write-Host "==> Subscription: $SubscriptionId"

$rgExists = az group exists -n $ResourceGroup | ConvertFrom-Json
if (-not $rgExists) {
  Write-Host "==> Creando resource group $ResourceGroup ($Location)"
  az group create -n $ResourceGroup -l $Location -o none
}

$envMap = Read-DotEnv (Join-Path $RepoRoot ".env")
$openaiKey = $envMap["AZURE_OPENAI_API_KEY"]
$searchKey = $envMap["AZURE_SEARCH_API_KEY"]
if (-not $openaiKey -or -not $searchKey) {
  throw "Faltan AZURE_OPENAI_API_KEY / AZURE_SEARCH_API_KEY en .env"
}

Write-Host "==> Fase 1: infra (ACR / Redis / KV / CAE) sin Container App"
$outs = Invoke-Bicep -Name "genesis-aca-infra-$ImageTag" -Params @{
  imageTag = $ImageTag
  deployContainerApp = "false"
}

$acrLogin = $outs.acrLoginServer.value
$acrName = $outs.acrNameOut.value
$kvName = $outs.keyVaultNameOut.value
$appName = $outs.containerAppNameOut.value
Write-Host "==> ACR: $acrLogin | KV: $kvName"

Write-Host "==> Rol Key Vault Secrets Officer para el usuario actual"
$me = az ad signed-in-user show --query id -o tsv
az role assignment create `
  --assignee-object-id $me `
  --assignee-principal-type User `
  --role "Key Vault Secrets Officer" `
  --scope "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.KeyVault/vaults/$kvName" `
  -o none 2>$null

Write-Host "==> Esperando propagacion RBAC KV (45s)..."
Start-Sleep -Seconds 45

Write-Host "==> Escribiendo secretos en Key Vault (sin echo)"
$ok = $false
for ($i = 1; $i -le 6; $i++) {
  az keyvault secret set --vault-name $kvName --name openai-api-key --value $openaiKey -o none 2>$null
  if ($LASTEXITCODE -eq 0) {
    az keyvault secret set --vault-name $kvName --name search-api-key --value $searchKey -o none
    $ok = $true
    break
  }
  Write-Host "  reintento $i/6 en 20s..."
  Start-Sleep -Seconds 20
}
if (-not $ok) { throw "No se pudieron escribir secretos en Key Vault (RBAC pendiente?)" }

if ($InfraOnly) {
  Write-Host "InfraOnly: fin."
  return
}

if (-not $SkipBuild) {
  Write-Host "==> Fase 2: az acr build (varios minutos)"
  Push-Location $RepoRoot
  try {
    az acr build `
      --registry $acrName `
      --image "genesis-api:$ImageTag" `
      --image "genesis-api:latest" `
      --file Dockerfile `
      .
    if ($LASTEXITCODE -ne 0) { throw "az acr build fallo" }
  }
  finally {
    Pop-Location
  }
}

Write-Host "==> Fase 3: Container App + RBAC"
$outs2 = Invoke-Bicep -Name "genesis-aca-app-$ImageTag" -Params @{
  imageTag = $ImageTag
  deployContainerApp = "true"
}
$fqdn = $outs2.containerAppFqdn.value
$principalId = $outs2.containerAppPrincipalId.value
Write-Host "==> FQDN: https://$fqdn"

Write-Host "==> Esperando revision lista (60s)..."
Start-Sleep -Seconds 60

$healthUrl = "https://$fqdn/health"
Write-Host "==> Smoke: $healthUrl"
try {
  $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 90
  Write-Host "HEALTH $($resp.StatusCode) $($resp.Content)"
}
catch {
  Write-Warning "Health check fallo: $_"
  Write-Host "Logs: az containerapp logs show -n $appName -g $ResourceGroup --tail 100"
}

Write-Host ""
Write-Host "Listo."
Write-Host "  API:     https://$fqdn"
Write-Host "  Health:  https://$fqdn/health"
Write-Host "  Pruebas: https://$fqdn/pruebas/"
Write-Host "  Tag:     $ImageTag"
Write-Host "  MI:      $principalId"
Write-Host "  Cognitiva QA :8447 permanece activa en la VM."
