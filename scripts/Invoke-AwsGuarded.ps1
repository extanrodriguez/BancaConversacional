<#
.SYNOPSIS
Loads AWS credentials in the current process, validates STS identity, and only then runs an AWS CLI command.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\Invoke-AwsGuarded.ps1 -AwsArguments @("s3","ls")

IMPORTANT:
- Never pass a command that prints credentials or environment variables.
- The credential file is parsed without printing its content.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]] $AwsArguments,

    [string] $CredentialFile = "C:\Users\boris\Documents\Genesis\Genesis_v1.env",

    [string] $ExpectedAccountId = "256274921338",

    [string] $ForbiddenAccountId = "928118643958",

    [string] $ExpectedPrincipalName = "BorisReina",

    [string] $Region = "us-east-1"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-Safely {
    param([string] $Message)
    Write-Error $Message
    exit 1
}

function Import-EnvFileSecurely {
    param([Parameter(Mandatory = $true)][string] $Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Stop-Safely "AWS credential file was not found."
    }

    foreach ($line in [System.IO.File]::ReadLines($Path)) {
        $trimmed = $line.Trim()

        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
            continue
        }

        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) {
            continue
        }

        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()

        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            [System.Environment]::SetEnvironmentVariable(
                $name,
                $value,
                [System.EnvironmentVariableTarget]::Process
            )
        }
    }
}

# Prevent accidental selection of a different local profile.
Remove-Item Env:AWS_PROFILE -ErrorAction SilentlyContinue
Remove-Item Env:AWS_DEFAULT_PROFILE -ErrorAction SilentlyContinue

Import-EnvFileSecurely -Path $CredentialFile

# Enforce the approved region in the same process.
$env:AWS_REGION = $Region
$env:AWS_DEFAULT_REGION = $Region

# Validate that credentials were loaded without printing them.
if ([string]::IsNullOrWhiteSpace($env:AWS_ACCESS_KEY_ID)) {
    Stop-Safely "AWS_ACCESS_KEY_ID was not loaded."
}
if ([string]::IsNullOrWhiteSpace($env:AWS_SECRET_ACCESS_KEY)) {
    Stop-Safely "AWS_SECRET_ACCESS_KEY was not loaded."
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Stop-Safely "AWS CLI is not installed or is not available in PATH."
}

# Mandatory preflight before the AWS command block.
$identityJson = & aws sts get-caller-identity --region $Region --output json 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityJson)) {
    Stop-Safely "STS identity validation failed."
}

try {
    $identity = $identityJson | ConvertFrom-Json
} catch {
    Stop-Safely "STS returned an invalid identity response."
}

$account = [string]$identity.Account
$arn = [string]$identity.Arn

if ($account -eq $ForbiddenAccountId) {
    Stop-Safely "Blocked: the active credentials belong to the forbidden AWS account."
}

if ($account -ne $ExpectedAccountId) {
    Stop-Safely "Blocked: the active AWS account is not the authorized account."
}

if ($arn -notmatch [regex]::Escape($ExpectedAccountId)) {
    Stop-Safely "Blocked: caller ARN does not belong to the authorized account."
}

if ($arn -notmatch [regex]::Escape($ExpectedPrincipalName)) {
    Stop-Safely "Blocked: caller ARN does not contain the expected principal name."
}

Write-Host "AWS preflight: PASS" -ForegroundColor Green
Write-Host "Authorized account verified. Executing approved command." -ForegroundColor Green

# Execute only after validation, in this same process.
& aws @AwsArguments
$commandExitCode = $LASTEXITCODE

# Remove sensitive variables from the process before exit.
Remove-Item Env:AWS_ACCESS_KEY_ID -ErrorAction SilentlyContinue
Remove-Item Env:AWS_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue
Remove-Item Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue

exit $commandExitCode
