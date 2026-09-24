# Instala el APK passkey-test en un dispositivo/emulador conectado por adb.
param(
    [string]$ApkPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $ApkPath) {
    $ApkPath = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) "app-release-passkey-test.apk"
}
if (-not (Test-Path $ApkPath)) {
    throw "APK no encontrado: $ApkPath"
}

$adb = $null
foreach ($candidate in @(
        (Get-Command adb -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "$env:ANDROID_HOME\platform-tools\adb.exe",
        "$env:ANDROID_SDK_ROOT\platform-tools\adb.exe"
    )) {
    if ($candidate -and (Test-Path $candidate)) {
        $adb = $candidate
        break
    }
}
if (-not $adb) {
    throw @"
adb no esta en PATH ni en Android SDK.
Instala platform-tools o agrega adb al PATH, luego:
  adb devices
  adb install -r `"$ApkPath`"
"@
}

Write-Host "adb: $adb"
Write-Host "apk: $ApkPath"
Write-Host ""
& $adb devices
Write-Host ""
Write-Host "Instalando (reemplaza si ya existe)..."
& $adb install -r $ApkPath
if ($LASTEXITCODE -ne 0) { throw "adb install fallo con codigo $LASTEXITCODE" }

Write-Host ""
Write-Host "Lanzando com.appconversacionalbsc ..."
& $adb shell monkey -p com.appconversacionalbsc -c android.intent.category.LAUNCHER 1
Write-Host "Listo."
