# Webhook orquestador — ClientId en cabecera

Endpoints en cognitiva **8447** que replican el camino APK/webhook:

`ClientId` → carga sesión/contexto → orquestador `:8080/chat/front` → cognitiva `/turn`

## Base URL

- Pública: `http://20.127.25.24:8447`
- Privada: `http://192.168.150.5:8447`

## 1) Solo crear sesión

`POST /orch/webhook/session`

```bash
curl -sS -X POST "http://20.127.25.24:8447/orch/webhook/session" \
  -H "Content-Type: application/json" \
  -H "ClientId: 726588" \
  -d "{\"allow_lab_fallback\": true}"
```

Respuesta (ejemplo):

```json
{
  "status": "CONTEXT_LOADED",
  "client_id": "726588",
  "customer_id": "726588",
  "conversation_id": "a1b2c3d4-....",
  "display_name": "Felix Prestamos",
  "context_source": "core_websocket"
}
```

Guarda `conversation_id` para los siguientes turnos.

## 2) Preguntar (sesión automática)

`POST /orch/webhook/chat`

Primer mensaje (sin conversation_id → se crea sola):

```bash
curl -sS -X POST "http://20.127.25.24:8447/orch/webhook/chat" \
  -H "Content-Type: application/json" \
  -H "ClientId: 726588" \
  -d "{\"question\": \"hola\"}"
```

Multi-turno (reusa la sesión):

```bash
curl -sS -X POST "http://20.127.25.24:8447/orch/webhook/chat" \
  -H "Content-Type: application/json" \
  -H "ClientId: 726588" \
  -H "X-Conversation-Id: a1b2c3d4-...." \
  -d "{\"question\": \"cuales son mis prestamos\"}"
```

PowerShell:

```powershell
$base = "http://20.127.25.24:8447"
$headers = @{ ClientId = "726588"; "Content-Type" = "application/json" }
$r1 = Invoke-RestMethod -Method POST -Uri "$base/orch/webhook/chat" -Headers $headers `
  -Body '{"question":"hola"}'
$r1.reply
$cid = $r1.conversation_id

$headers2 = @{ ClientId = "726588"; "Content-Type" = "application/json"; "X-Conversation-Id" = $cid }
$r2 = Invoke-RestMethod -Method POST -Uri "$base/orch/webhook/chat" -Headers $headers2 `
  -Body '{"question":"cuales son mis prestamos"}'
$r2.reply
$r2.content_format
```

## Cabeceras aceptadas

| Uso | Nombres |
|-----|---------|
| Cliente | `ClientId`, `X-Client-Id`, `client_id` |
| Sesión | `X-Conversation-Id`, `conversation_id` |

## Respuesta de `/orch/webhook/chat`

```json
{
  "client_id": "726588",
  "customer_id": "726588",
  "conversation_id": "...",
  "reply": "texto o markdown",
  "content_format": "markdown",
  "status": "VALID_CONTRACT",
  "options": [],
  "suggested_questions": [],
  "app_channel": { },
  "orchestrator": { }
}
```

## Equivalente ya existente (sin auto-sesión)

Si prefieres el contrato APK crudo:

```bash
# 1) contexto
curl -X POST http://20.127.25.24:8447/orch/context \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"726588","allow_lab_fallback":true}'

# 2) chat vía orquestador
curl -X POST http://20.127.25.24:8447/orch/chat/front \
  -H "Content-Type: application/json" \
  -d '{"question":"hola","client_id":"726588","customer_id":"726588","subject_token":"726588","conversation_id":"<CID>"}'
```
