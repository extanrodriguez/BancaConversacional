# Carga contexto REAL de Presentation Product hacia cognitiva :8447.
# Ejecutar desde VM del banco:
#   powershell -ExecutionPolicy Bypass -File .\load_real_context_8447.ps1

param(
    [string]$CustomerId = "726588",
    [string]$CognitiveBase = "http://20.127.25.24:8447",
    [string]$PresentationUrl = "https://apigateway-gen.qa.bsc.com.do/api/presentation/product/{customerId}"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

$url = $PresentationUrl.Replace("{customerId}", $CustomerId)
Write-Host "Paso 1 - GET Presentation Product"
Write-Host $url

$pres = Invoke-RestMethod -Uri $url -Method GET -TimeoutSec 60

$data = $null
$names = @($pres.PSObject.Properties.Name)
if ($names -contains "data" -and (($names -contains "isSucceded") -or ($names -contains "code"))) {
    $data = $pres.data
} elseif ($names -contains "products") {
    $data = $pres
} elseif ($names -contains "data") {
    $data = $pres.data
} else {
    $data = $pres
}

if (-not $data.primerNombre) {
    $data | Add-Member -NotePropertyName primerNombre -NotePropertyValue "Cliente" -Force
}
if ($null -eq $data.resultCode) {
    $data | Add-Member -NotePropertyName resultCode -NotePropertyValue 0 -Force
}

$prodCount = 0
if ($data.products) { $prodCount = @($data.products).Count }
Write-Host ("products={0} primerNombre={1}" -f $prodCount, $data.primerNombre)

$conversationId = [guid]::NewGuid().ToString()
$payloadObj = [ordered]@{
    question        = $null
    customer_id     = $CustomerId
    conversation_id = $conversationId
    context_info    = $true
    context_op      = "load"
    context         = @{ data = $data }
}
$payload = $payloadObj | ConvertTo-Json -Depth 30

Write-Host "Paso 2 - POST turn context_info=true"
Write-Host ("conversation_id={0}" -f $conversationId)

$loaded = Invoke-RestMethod -Uri ($CognitiveBase.TrimEnd("/") + "/turn") -Method POST -Body $payload -ContentType "application/json; charset=utf-8" -TimeoutSec 90
Write-Host ("status={0} products_count={1} display={2}" -f $loaded.status, $loaded.products_count, $loaded.display_name)

Write-Host "Paso 3 - Pregunta de prueba"
$qObj = [ordered]@{
    question        = "Que productos tengo?"
    customer_id     = $CustomerId
    conversation_id = $conversationId
    context_info    = $false
}
$qBody = $qObj | ConvertTo-Json -Compress
$ans = Invoke-RestMethod -Uri ($CognitiveBase.TrimEnd("/") + "/turn") -Method POST -Body $qBody -ContentType "application/json; charset=utf-8" -TimeoutSec 120

$reply = $ans.reply
if (-not $reply -and $ans.app_channel) { $reply = $ans.app_channel.client_response }
Write-Host ("REPLY: {0}" -f $reply)
Write-Host "OK - contexto real cargado"
Write-Host ("Guarda este conversation_id: {0}" -f $conversationId)
