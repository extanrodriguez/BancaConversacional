# Verifica conectividad del camino APK (:8000) y cognitiva (:8447).
param(
    [string]$HostAddress = "20.127.25.24",
    [string]$ApiKey = "genesis-rag-temp-c04f313048e160f088601c96"
)

$ErrorActionPreference = "Continue"
Write-Host "IP publica de esta PC:" -NoNewline
try {
    $ip = (Invoke-RestMethod "https://api.ipify.org?format=json" -TimeoutSec 10).ip
    Write-Host " $ip"
} catch {
    Write-Host " (no se pudo obtener)"
}

Write-Host ""
Write-Host "=== TCP ==="
foreach ($port in 8000, 8447) {
    $r = Test-NetConnection $HostAddress -Port $port -WarningAction SilentlyContinue
    $ok = if ($r.TcpTestSucceeded) { "OK" } else { "FAIL" }
    Write-Host ("  {0}:{1}  {2}" -f $HostAddress, $port, $ok)
}

Write-Host ""
Write-Host "=== HTTP health ==="
foreach ($port in 8000, 8447) {
    $url = "http://{0}:{1}/health" -f $HostAddress, $port
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        Write-Host ("  {0}  HTTP {1}  {2}" -f $url, $resp.StatusCode, $resp.Content.Substring(0, [Math]::Min(120, $resp.Content.Length)))
    } catch {
        Write-Host ("  {0}  FAIL  {1}" -f $url, $_.Exception.Message)
    }
}

Write-Host ""
Write-Host "=== Contrato APK POST /chat/front ==="
$chatUrl = "http://{0}:8000/chat/front?x-api-key={1}" -f $HostAddress, $ApiKey
$body = @{
    question        = "hola"
    top_k           = 3
    conversation_id = ("apk-check-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    client_id       = "TEST-QA-001"
} | ConvertTo-Json
try {
    $resp = Invoke-WebRequest -Uri $chatUrl -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 45
    $json = $resp.Content | ConvertFrom-Json
    Write-Host ("  HTTP {0}" -f $resp.StatusCode)
    Write-Host ("  reply: {0}" -f (($json.reply) + "").Substring(0, [Math]::Min(160, (($json.reply) + "").Length)))
    Write-Host ("  conversation_id: {0}" -f $json.conversation_id)
} catch {
    Write-Host ("  FAIL  {0}" -f $_.Exception.Message)
    Write-Host "  Si 8000 TCP=FAIL: ejecuta .\abrir_nsg_8000.ps1 (requiere az login)."
}

Write-Host ""
Write-Host "Referencia UI cognitiva: http://$HostAddress`:8447/pruebas"
