<#
Runs only the guarded STS validation and prints a sanitized PASS/FAIL result.
It never prints the raw STS response, credentials, tokens or ARN.
#>

[CmdletBinding()]
param(
    [string] $CredentialFile = "C:\Users\boris\Documents\Genesis\Genesis_v1.env"
)

$scriptPath = Join-Path $PSScriptRoot "Invoke-AwsGuarded.ps1"

& powershell `
  -NoProfile `
  -ExecutionPolicy Bypass `
  -File $scriptPath `
  -CredentialFile $CredentialFile `
  -AwsArguments @("sts", "get-caller-identity", "--query", "Account", "--output", "text") |
  ForEach-Object {
      if ($_ -eq "256274921338") {
          "AWS guarded identity test: PASS"
      } elseif ($_ -notmatch "AWS preflight|Authorized account") {
          "AWS guarded identity test returned an unexpected sanitized result."
      }
  }

exit $LASTEXITCODE
