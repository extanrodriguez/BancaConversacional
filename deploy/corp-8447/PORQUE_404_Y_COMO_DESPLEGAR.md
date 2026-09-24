# Por qué da 404 y cómo desplegar YA (vm-genesis-rag-01 / 20.127.25.24)

## Causa del 404

```
POST http://192.168.150.5:8447/orch/webhook/chat  →  {"detail":"Not Found"}
```

La VM **sí responde** (8447 está arriba), pero el código del webhook
**nunca se subió**. Solo está en el repo local. Por eso FastAPI dice Not Found.

Los deploys anteriores funcionaban cuando el **NSG** permitía la IP de esta PC.
Ahora la IP pública de Cursor es `191.156.176.161` y el NSG la bloquea
(timeout en 22 y 8447). Sin SSH no hay deploy.

## Opción A — Abrir NSG (recomendado, 2 minutos)

En Azure Portal → **vm-genesis-rag-01** → **Red** / Networking:

1. Regla inbound que permita **8440-8449** (o al menos **8447**) y **22**
   desde tu IP / la de Cursor: `191.156.176.161/32`
2. Suele llamarse `Allow-QA-To-Dev-8440-8449` (prioridad ~119).
3. Guarda.

Luego avisa y se ejecuta:

```powershell
cd C:\NovusIntelligence\BancoSantaCruz\BancaConversacional
$env:SSH_DEPLOY_PASS = "<pass>"
$env:SSH_HOST = "20.127.25.24"
.\.venv\Scripts\python.exe .\deploy\corp-8446\build_corp_package.py
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_ssh_password.py
```

## Opción B — Desde una máquina con VPN (alcanza 192.168.150.5)

Si Postman llega a la privada, esa misma red puede hacer SSH:

```powershell
$env:SSH_HOST = "192.168.150.5"
$env:SSH_DEPLOY_PASS = "<pass>"
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_via_private_ip.py
```

## Probar cuando esté desplegado

```bash
curl -sS -X POST "http://192.168.150.5:8447/orch/webhook/chat" \
  -H "Content-Type: application/json" \
  -H "ClientId: 726588" \
  -d "{\"question\": \"hola\"}"
```

Si responde `reply` / `conversation_id` (no `Not Found`), el APK puede usar esa URL.
