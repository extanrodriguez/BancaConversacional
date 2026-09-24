$ErrorActionPreference = "Stop"

Write-Host "Configurando Git hooks del repositorio..."

if (!(Test-Path ".githooks")) {
    Write-Error "No existe la carpeta .githooks"
    exit 1
}

git config core.hooksPath .githooks

Write-Host "Hooks configurados correctamente."
Write-Host "core.hooksPath = $(git config core.hooksPath)"

Write-Host ""
Write-Host "Validando gitleaks..."

$gitleaks = Get-Command gitleaks -ErrorAction SilentlyContinue

if ($null -eq $gitleaks) {
    Write-Warning "gitleaks no está instalado o no está en el PATH."
    Write-Warning "El hook pre-push fallará hasta que instales gitleaks."
} else {
    Write-Host "gitleaks encontrado en: $($gitleaks.Source)"
    gitleaks version
}

Write-Host ""
Write-Host "Instalación de hooks finalizada."