# Initializes .env safely on Windows.
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File .\scripts\initialize_env.ps1

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Example = Join-Path $RepoRoot ".env.example"
$Target = Join-Path $RepoRoot ".env"

if (-not (Test-Path $Example)) {
    throw ".env.example was not found at $Example"
}

if (Test-Path $Target) {
    Write-Host ".env already exists. It was not overwritten." -ForegroundColor Yellow
    exit 0
}

Copy-Item $Example $Target
Write-Host "Created $Target from .env.example." -ForegroundColor Green
Write-Host "AWS static credential values remain empty." -ForegroundColor Yellow
Write-Host "Preferred setup:" -ForegroundColor Cyan
Write-Host "  aws configure --profile genesis-cognitive"
