# Complementos para cubrir el requerimiento WebSocket al 100%

## Lo que ya queda preparado en backend

- Handshake WebSocket con autenticacion JWT.
- Rechazo de conexiones no seguras fuera de `Development`.
- Rate limiting por IP.
- Protocolo de eventos con `connected`, `status`, `message`, `error`, `ack`, `replay` y `pong`.
- Sesion reanudable con `sessionId` y recuperacion de mensajes salientes pendientes usando `lastReceivedSequence`.
- Replay en reconexion tanto por query string del handshake como por mensaje `resume`.

## Lo que debe complementar el front

### 1. Envio del JWT en el handshake

Opciones soportadas por backend:
- Header `Authorization: Bearer <token>`
- Query string `access_token=<token>`

### 2. Reconexion automatica

El cliente debe implementar:
- reconexion exponencial (`1s`, `2s`, `5s`, `10s`, tope configurable)
- deteccion de estado `connected`, `disconnected`, `reconnecting`, `reconnected`
- reuso del `sessionId` recibido en el evento `connected`
- envio de `lastReceivedSequence` al reconectar

### 3. Ack de mensajes

Para evitar perder mensajes del asistente, el cliente debe enviar:

```json
{
  "type": "ack",
  "action": "ack",
  "sessionId": "<sessionId>",
  "lastReceivedSequence": 15
}
```

### 4. Reanudar sesion explicitamente

Si el cliente necesita forzar replay despues de reconectar:

```json
{
  "type": "resume",
  "action": "resume",
  "sessionId": "<sessionId>",
  "lastReceivedSequence": 15
}
```

### 5. Typing indicator

El backend reconoce el control `typing`, pero el front debe emitirlo:

```json
{
  "type": "typing",
  "action": "typing",
  "sessionId": "<sessionId>",
  "requestId": "<requestId>"
}
```

## Lo que debe complementar infraestructura

### 1. WSS obligatorio real

El backend rechaza conexiones no seguras fuera de `Development`, pero para cumplir el requerimiento en produccion se necesita:
- TLS termination en Ingress / Load Balancer
- `X-Forwarded-Proto=https` correctamente propagado
- certificados validos

### 2. Escalado horizontal

La implementacion actual de replay de mensajes es en memoria del proceso.
Para cubrir escalado horizontal o reinicio de pods sin perder estado, se recomienda:
- Redis para almacenar sesiones y mensajes pendientes
- afinidad de sesion o adapter distribuido
- expiracion por TTL

### 3. Observabilidad

Agregar:
- metricas de conexiones activas
- metricas de reconexion y replay
- logs por `sessionId`
- alertas por errores de autenticacion o replay fallido

## Contrato sugerido de conexion del front

### Handshake

`wss://host/ws?access_token=<jwt>&sessionId=<sessionIdOpcional>&lastReceivedSequence=<n>&clientId=<clientId>`

### Evento de conexion esperado desde backend

```json
{
  "type": "connected",
  "action": "handshake_ack",
  "message": "Conexion establecida con el servidor .NET",
  "sessionId": "abc123",
  "timestamp": 1717330000000,
  "replaySupported": true,
  "lastAcknowledgedSequence": 0
}
```

## Recomendaciones de endurecimiento pendientes

- Mover `JwtAuth__SigningKey` a Secret Manager/Kubernetes Secret.
- Reemplazar clave compartida por integracion con proveedor de identidad corporativo si aplica.
- Persistir historial de mensajes si el negocio exige replay despues de reinicio del servicio.
- Agregar pruebas de integracion para handshake JWT, replay, ack y rechazo por `ws://` en produccion.
