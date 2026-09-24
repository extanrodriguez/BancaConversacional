#Requires -Version 5.1
<#
.SYNOPSIS
  Script para ADMIN de Azure — provisiona Genesis Cognitive en Azure Container Apps.

.DESCRIPTION
  Crea (idempotente vía Bicep):
    - Log Analytics: log-genesis-aca
    - ACR:          acrgenesis871a5b
    - Redis:        redis-genesis-lab (Basic C1)
    - Key Vault:    kv-genesis-cognitive
    - CAE:          cae-genesis-eus
    - Container App genesis-api (min 2 / max 10, scale HTTP concurrency 50)

  NO toca la VM Cognitiva QA (20.127.25.24:8447).

.REQUISITOS
  - Azure CLI instalado (az)
  - Permisos sugeridos en la suscripción/RG:
      Contributor + User Access Administrator
      (o Owner) — hace falta Role Assignments en ACR y Key Vault
  - Secretos OpenAI + AI Search (pasarlos por parámetro; no commitear)

.EJEMPLO
  az login
  cd <ruta-del-repo>
  .\deploy\aca\deploy_aca_admin.ps1 `
    -OpenAiApiKey "<clave>" `
    -SearchApiKey "<clave>"
#>
[CmdletBinding()]
param(
  [string]$SubscriptionId = "871a5b90-0204-450e-b968-3190e9143faf",
  [string]$ResourceGroup = "rg-genesis-cognitive-mvp-eus",
  [string]$Location = "eastus",
  [Parameter(Mandatory = $true)]
  [string]$OpenAiApiKey,
  [Parameter(Mandatory = $true)]
  [string]$SearchApiKey,
  [string]$ImageTag = "",
  [switch]$SkipBuild,
  [switch]$InfraOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$BicepFile = Join-Path $RepoRoot "PlanContainerizacion\FASE_2\containerapp.bicep"
$Dockerfile = Join-Path $RepoRoot "Dockerfile"

if (-not (Test-Path $BicepFile)) { throw "No existe Bicep: $BicepFile" }
if (-not (Test-Path $Dockerfile)) { throw "No existe Dockerfile: $Dockerfile" }
if (-not $ImageTag) { $ImageTag = Get-Date -Format "yyyyMMdd-HHmmss" }

function Invoke-Bicep([string]$Name, [hashtable]$Params) {
  $azArgs = @(
    "deployment", "group", "create",
    "--name", $Name,
    "--resource-group", $ResourceGroup,
    "--template-file", $BicepFile
  )
  foreach ($k in $Params.Keys) {
    $azArgs += "--parameters"
    $azArgs += "$k=$($Params[$k])"
  }
  $azArgs += @("--query", "properties.outputs", "-o", "json")
  $json = & az @azArgs
  if ($LASTEXITCODE -ne 0) { throw "Fallo deployment $Name" }
  return ($json | ConvertFrom-Json)
}

Write-Host "=== Genesis ACA — deploy admin ==="
Write-Host "Repo: $RepoRoot"
Write-Host "Tag:  $ImageTag"
Write-Host "RG:   $ResourceGroup / $Location"
Write-Host "Sub:  $SubscriptionId"

az account show -o none 2>$null
if ($LASTEXITCODE -ne 0) { throw "Ejecuta primero: az login" }
az account set --subscription $SubscriptionId

$rgExists = az group exists -n $ResourceGroup | ConvertFrom-Json
if (-not $rgExists) {
  Write-Host "==> Creando RG $ResourceGroup"
  az group create -n $ResourceGroup -l $Location -o none
}

Write-Host "==> Fase 1/3: infra (ACR, Redis, KV, CAE) — sin Container App"
$outs = Invoke-Bicep -Name "genesis-aca-infra-$ImageTag" -Params @{
  imageTag = $ImageTag
  deployContainerApp = "false"
}
$acrLogin = $outs.acrLoginServer.value
$acrName = $outs.acrNameOut.value
$kvName = $outs.keyVaultNameOut.value
$appName = $outs.containerAppNameOut.value
Write-Host "    ACR=$acrLogin  KV=$kvName"

Write-Host "==> RBAC: Key Vault Secrets Officer al usuario actual"
$me = az ad signed-in-user show --query id -o tsv
az role assignment create `
  --assignee-object-id $me `
  --assignee-principal-type User `
  --role "Key Vault Secrets Officer" `
  --scope "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.KeyVault/vaults/$kvName" `
  -o none 2>$null

Write-Host "==> Esperando propagacion RBAC (45s)"
Start-Sleep -Seconds 45

Write-Host "==> Secretos en Key Vault (openai-api-key, search-api-key)"
$ok = $false
for ($i = 1; $i -le 8; $i++) {
  az keyvault secret set --vault-name $kvName --name openai-api-key --value $OpenAiApiKey -o none 2>$null
  if ($LASTEXITCODE -eq 0) {
    az keyvault secret set --vault-name $kvName --name search-api-key --value $SearchApiKey -o none
    if ($LASTEXITCODE -ne 0) { throw "Fallo al escribir search-api-key" }
    $ok = $true
    break
  }
  Write-Host "    reintento $i/8 en 20s (RBAC pendiente)..."
  Start-Sleep -Seconds 20
}
if (-not $ok) { throw "No se pudieron escribir secretos en KV. Revisar permisos RBAC." }

if ($InfraOnly) {
  Write-Host "InfraOnly: fin (sin build ni Container App)."
  return
}

if (-not $SkipBuild) {
  Write-Host "==> Fase 2/3: az acr build (varios minutos)"
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
  finally { Pop-Location }
}

Write-Host "==> Fase 3/3: Container App genesis-api + RBAC (AcrPull + KV Secrets User)"
$outs2 = Invoke-Bicep -Name "genesis-aca-app-$ImageTag" -Params @{
  imageTag = $ImageTag
  deployContainerApp = "true"
}
$fqdn = $outs2.containerAppFqdn.value
$principalId = $outs2.containerAppPrincipalId.value

Write-Host "==> Esperando revision (60s)"
Start-Sleep -Seconds 60

$healthUrl = "https://$fqdn/health"
Write-Host "==> Smoke: $healthUrl"
try {
  $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 90
  Write-Host "HEALTH $($resp.StatusCode) $($resp.Content)"
}
catch {
  Write-Warning "Health fallo: $_"
  Write-Host "Logs: az containerapp logs show -n $appName -g $ResourceGroup --tail 100"
}

Write-Host ""
Write-Host "=== LISTO ==="
Write-Host "API:     https://$fqdn"
Write-Host "Health:  https://$fqdn/health"
Write-Host "Pruebas: https://$fqdn/pruebas/"
Write-Host "Tag:     $ImageTag"
Write-Host "MI:      $principalId"
Write-Host "Nota:    Cognitiva QA :8447 en VM NO se modifica."
