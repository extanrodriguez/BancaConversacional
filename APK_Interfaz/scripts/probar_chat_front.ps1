# Smoke test del endpoint exacto que consume el APK.
param(
    [string]$HostAddress = "20.127.25.24",
    [string]$ApiKey = "genesis-rag-temp-c04f313048e160f088601c96",
    [string]$ClientId = "TEST-QA-001",
    [string]$Question = "dame un balance de mis cuentas"
)

$ErrorActionPreference = "Stop"
$url = "http://{0}:8000/chat/front?x-api-key={1}" -f $HostAddress, $ApiKey
$cid = "apk-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 10)
$body = @{
    question        = $Question
    top_k           = 3
    conversation_id = $cid
    client_id       = $ClientId
} | ConvertTo-Json -Compress

Write-Host "POST $url"
Write-Host "body: $body"
Write-Host ""

try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-WebRequest -Uri $url -Method POST -Body $body -ContentType "application/json; charset=utf-8" -Headers @{ Accept = "application/json" } -UseBasicParsing -TimeoutSec 60
    $sw.Stop()
    Write-Host ("HTTP {0}  {1} ms" -f $resp.StatusCode, $sw.ElapsedMilliseconds)
    $json = $resp.Content | ConvertFrom-Json
    Write-Host ("status: {0}" -f $json.status)
    Write-Host ("conversation_id: {0}" -f $json.conversation_id)
    Write-Host ("options: {0}" -f @($json.options).Count)
    Write-Host "reply:"
    Write-Host $json.reply
} catch {
    Write-Host "FAIL:" $_.Exception.Message -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Host $reader.ReadToEnd()
    }
    exit 1
}
