# Banca Conversacional Backend

Backend de un asistente bancario conversacional con WebSocket, inteligencia artificial (Azure OpenAI) y conexión a APIs bancarias propias. Construido en **.NET 8** con arquitectura limpia por capas.

---

## Requisitos del sistema

| Herramienta         | Versión mínima    | Enlace de descarga                             |
| ------------------- | ----------------- | ---------------------------------------------- |
| .NET SDK            | 8.0               | https://dotnet.microsoft.com/download/dotnet/8 |
| Windows             | 10 / 11 (64-bit)  | —                                              |
| PowerShell          | 5.1+              | Incluido en Windows                            |
| winget _(opcional)_ | cualquier versión | Incluido en Windows 11                         |

> Si no tienes el SDK instalado, puedes instalarlo sin permisos de administrador con el script oficial:
>
> ```powershell
> $installDir = "$env:USERPROFILE\dotnet"
> Invoke-WebRequest -Uri https://dot.net/v1/dotnet-install.ps1 -OutFile "$env:TEMP\dotnet-install.ps1"
> & "$env:TEMP\dotnet-install.ps1" -Channel 8.0 -InstallDir $installDir -NoPath
> ```
>
> El ejecutable quedará en `C:\Users\<tu-usuario>\dotnet\dotnet.exe`.

---

## Variables de entorno

Crea un archivo `.env` en la raíz del proyecto con el siguiente contenido:

```env
ExternalServices__AzureApiKey=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ExternalServices__AzureEndpoint=https://bancaconversacionalbsc-resource.services.ai.azure.com/api/projects/bancaconversacionalbsc
ExternalServices__DeploymentName=o4-mini
```

> La API key se obtiene desde el recurso de Azure AI / Azure OpenAI.

El resto de la configuración se gestiona en `src/BancaConversacional.Api/appsettings.json`:

```json
{
  "Banking": {
    "ClientId": "JEISON-001"
  },
  "ExternalServices": {
    "AzureApiKey": "",
    "AzureEndpoint": "https://bancaconversacionalbsc-resource.services.ai.azure.com/api/projects/bancaconversacionalbsc",
    "DeploymentName": "o4-mini",
    "BankingApiBase": "https://zqp02jwv1j.execute-api.us-east-1.amazonaws.com/poc"
  }
}
```

Los valores de `ExternalServices` se pueden sobreescribir con variables de entorno usando doble guion bajo como separador:

```
ExternalServices__AzureApiKey=azure-xxx
ExternalServices__AzureEndpoint=https://bancaconversacionalbsc-resource.services.ai.azure.com/api/projects/bancaconversacionalbsc
ExternalServices__DeploymentName=o4-mini
ExternalServices__BankingApiBaseDev=https://zqp02jwv1j.execute-api.us-east-1.amazonaws.com/poc
ExternalServices__BankingApiBaseQa=https://zqp02jwv1j.execute-api.us-east-1.amazonaws.com/poc
ExternalServices__BankingApiBaseProduction=https://zqp02jwv1j.execute-api.us-east-1.amazonaws.com/poc
ExternalServices__DashboardApiBaseDev=http://172.27.4.20:4429
ExternalServices__DashboardApiBaseQa=http://172.27.4.20:4429
ExternalServices__DashboardApiBaseProduction=http://172.27.4.20:4429
# Fallback opcional si no coincide el nombre del entorno
ExternalServices__BankingApiBase=https://zqp02jwv1j.execute-api.us-east-1.amazonaws.com/poc
ExternalServices__DashboardApiBase=http://172.27.4.20:4429
Banking__ClientId=OTRO-001
```

Selección de URL base bancaria por entorno en tiempo de ejecución:

- `ASPNETCORE_ENVIRONMENT=Development` o `DEV` -> `ExternalServices__BankingApiBaseDev`
- `ASPNETCORE_ENVIRONMENT=QA` -> `ExternalServices__BankingApiBaseQa`
- `ASPNETCORE_ENVIRONMENT=Production` o `PROD` -> `ExternalServices__BankingApiBaseProduction`
- Si la del entorno no está definida, usa `ExternalServices__BankingApiBase` como fallback.

---

## Arquitectura del proyecto

```
BancaConversacional.sln
└── src/
    ├── BancaConversacional.Domain/          ← Entidades y enumeraciones del dominio
    ├── BancaConversacional.Application/     ← Casos de uso, interfaces, orquestación
    ├── BancaConversacional.Infrastructure/  ← Clientes HTTP: Azure OpenAI + API bancaria
    └── BancaConversacional.Api/             ← Host ASP.NET Core: WebSocket + rutas
```

### Capas y responsabilidades

#### Domain

Contiene el modelo de dominio puro, sin dependencias externas.

- `IntentType.cs` — Enumeración de intenciones: `Normal`, `Balance`, `Movements`, `Transfer`

#### Application

Lógica de negocio y contratos. No depende de infraestructura ni de ASP.NET.

- **Abstractions/** — Interfaces: `IIntentClassifier`, `IBankingClient`, `IChatResponder`, `IConversationOrchestrator`
- **Services/ConversationOrchestrator** — Orquestador principal: recibe mensajes, detecta intención, ejecuta herramienta y genera respuesta
- **Prompts/PromptCatalog** — Todos los system prompts del modelo de IA centralizados
- **Models/** — DTOs internos: `ChatMessage`, `MovementsFilter`, `TransferCommand`, `ConversationResult`
- **Configuration/BankingOptions** — Configuración tipada del cliente activo

#### Infrastructure

Implementaciones concretas de los contratos de Application. Aquí viven los clientes HTTP.

- `NvidiaChatClient` — Implementa `IIntentClassifier` + `IChatResponder`. Llama a NVIDIA NIM para:
  - Clasificar la intención del usuario (`BALANCE`, `MOVEMENTS`, `TRANSFER`, `NORMAL`)
  - Extraer parámetros estructurados (filtros de movimientos, monto/tipo de transferencias)
  - Generar la respuesta final al usuario con los datos bancarios
- `BankingApiClient` — Implementa `IBankingClient`. Llama a los endpoints del API bancaria:
  - `GET /balance/{clientId}` — Consultar saldo
  - `GET /movements/{clientId}?type=&limit=` — Consultar movimientos
  - `POST /transaction` — Ejecutar transacción (depósito o retiro)

#### Api

Host ASP.NET Core 8 con Kestrel.

- `Program.cs` — Configura DI, rate limiting, WebSocket y rutas
- `Services/ChatWebSocketHandler` — Maneja el ciclo de vida de cada conexión WebSocket: recibe, parsea, llama al orquestador y responde
- `Contracts/SocketEnvelope` — DTO de entrada del front

---

## Flujo de una conversación

```
Front (React Native)
  │  WebSocket → ws://localhost:8080/ws
  │  JSON: { "data": { "message": "quiero ver mi saldo" } }
  ▼
ChatWebSocketHandler
  │  Normaliza payload y extrae mensajes del usuario
  ▼
ConversationOrchestrator
  │
  ├─ [Fase 1] NvidiaChatClient.ClassifyAsync()
  │    LLM responde: BALANCE / MOVEMENTS / TRANSFER / NORMAL
  │
  ├─ [Fase 2 - si aplica] Extraer parámetros con LLM
  │    MovementsFilter → { type, limit }
  │    TransferCommand → { type, amount, description }
  │
  ├─ [Fase 3 - si aplica] BankingApiClient llama al endpoint bancario
  │    GetBalanceAsync / GetMovementsAsync / CreateTransactionAsync
  │
  └─ [Fase 4] NvidiaChatClient.ReplyAsync()
       LLM genera respuesta amigable en español con los datos reales
  ▼
ChatWebSocketHandler
  │  Envía respuesta al front
  ▼
Front recibe:
  {
    "type": "message",
    "action": "bot_response",
    "data": { "content": "Tu saldo actual es $2.475.000 COP", "message": "..." },
    "intent": "Balance",
    "requestId": "...",
    "timestamp": 1717330000000,
    "toolData": { ... }
  }
```

---

## Iniciar el servicio

### Comando rápido (recomendado)

Ejecuta este bloque completo en PowerShell desde la raíz del proyecto:

```powershell
cd "c:\Users\jessi\App BancaConversacional Backend"

# 1. Liberar puerto 8080 si está ocupado
$pids = @(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
          Select-Object -ExpandProperty OwningProcess -Unique)
$pids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

# 2. Apuntar al ejecutable dotnet (instalado en perfil de usuario)
$dotnet = "$env:USERPROFILE\dotnet\dotnet.exe"

# 3. Cargar variables desde .env
Get-Content .env | Where-Object { $_ -match '=' -and -not $_.Trim().StartsWith('#') } | ForEach-Object {
  $parts = $_ -split '=', 2
  if ($parts.Count -eq 2) {
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
  }
}

# 4. Iniciar servidor (escucha en todas las interfaces de red)
& $dotnet run --project .\src\BancaConversacional.Api\BancaConversacional.Api.csproj
```

Cuando veas `Now listening on: http://0.0.0.0:8080` el servidor está listo.

### Conectar desde dispositivos externos (celular, tablet, otra PC)

1. **Obtén la IP local** de tu máquina Windows:

   ```powershell
   ipconfig | findstr "IPv4"
   ```

   Ejemplo: `192.168.1.8`

2. **Asegúrate de que el firewall permita el puerto 8080** (requiere ejecutar PowerShell como **Administrador**):

   ```powershell
   New-NetFirewallRule -DisplayName "Banca Conversacional API" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow
   ```

   **Alternativa manual (si no tienes permisos de administrador)**:
   - Abre "Firewall de Windows Defender" → "Configuración avanzada"
   - Click en "Reglas de entrada" → "Nueva regla..."
   - Tipo: **Puerto** → TCP → Puerto específico: **8080**
   - Acción: **Permitir la conexión**
   - Perfiles: Marca **Dominio**, **Privado** y **Público**
   - Nombre: `Banca Conversacional API`

3. **Conecta desde el front** usando la IP local:
   - WebSocket: `ws://192.168.1.8:8080/ws`
   - Health check: `http://192.168.1.8:8080/health`

### Detener el servicio

Presiona `Ctrl + C` en la terminal donde corre el servidor.

---

## Endpoints disponibles

### Desde localhost (desarrollo)

| Endpoint                           | Tipo      | Descripción                    |
| ---------------------------------- | --------- | ------------------------------ |
| `ws://localhost:8080/ws`           | WebSocket | Canal conversacional del front |
| `GET http://localhost:8080/health` | HTTP      | Estado del servicio            |

### Desde dispositivos en la misma red (usa tu IP local)

| Endpoint                         | Tipo      | Ejemplo                          |
| -------------------------------- | --------- | -------------------------------- |
| `ws://<TU_IP>:8080/ws`           | WebSocket | `ws://192.168.1.8:8080/ws`       |
| `GET http://<TU_IP>:8080/health` | HTTP      | `http://192.168.1.8:8080/health` |

Para conocer tu IP local ejecuta: `ipconfig` (Windows) o `ifconfig` (Linux/Mac).

---

## Formato de mensajes WebSocket

### Entrada (front → backend)

**Formato 1** — Compatible con la app React Native actual:

```json
{
  "requestId": "1717330000000",
  "type": "message",
  "action": "send_message",
  "clientId": "JEISON-001",
  "data": {
    "message": "quiero ver mis movimientos",
    "content": "quiero ver mis movimientos",
    "timestamp": 1717330000000
  },
  "timestamp": 1717330000000
}
```

**Formato 2** — Con historial de conversación:

```json
{
  "requestId": "1717330000001",
  "clientId": "JEISON-001",
  "messages": [{ "role": "user", "content": "quiero hacer un retiro de 50000" }]
}
```

**Formato 3** — ClientId dentro de data (también soportado):

```json
{
  "requestId": "1717330000002",
  "data": {
    "message": "cuál es mi saldo",
    "clientId": "JEISON-001"
  }
}
```

> **Importante**: Si no se envía `clientId`, el backend usará el valor por defecto configurado en `Banking:ClientId` del `appsettings.json` (actualmente `JEISON-001`).

### Salida (backend → front)

**Mensaje del asistente:**

```json
{
  "type": "message",
  "action": "bot_response",
  "data": {
    "content": "Tu saldo actual es $2.475.000 COP y tu cuenta está activa.",
    "message": "Tu saldo actual es $2.475.000 COP y tu cuenta está activa."
  },
  "intent": "Balance",
  "requestId": "1717330000000",
  "timestamp": 1717330001234,
  "toolData": {
    "clientId": "JEISON-001",
    "balance": 2475000,
    "currency": "COP",
    "status": "ACTIVE"
  }
}
```

**Confirmación de conexión (se envía al conectar):**

```json
{
  "type": "connected",
  "message": "Conexion establecida con el servidor .NET"
}
```

**Error:**

```json
{
  "type": "error",
  "message": "descripción del error",
  "requestId": "1717330000000"
}
```

---

## Ejemplos de conversación

| Mensaje del usuario         | Intención detectada | Acción                                         |
| --------------------------- | ------------------- | ---------------------------------------------- |
| "¿Cuál es mi saldo?"        | `Balance`           | `GET /balance/JEISON-001`                      |
| "Ver mis movimientos"       | `Movements`         | `GET /movements/JEISON-001`                    |
| "Ver mis últimos 5 retiros" | `Movements`         | `GET /movements/JEISON-001?type=DEBIT&limit=5` |
| "Quiero depositar 100000"   | `Transfer`          | `POST /transaction` (CREDIT)                   |
| "Retirar 50000 pesos"       | `Transfer`          | `POST /transaction` (DEBIT)                    |
| "Hola, ¿cómo estás?"        | `Normal`            | Solo respuesta del LLM                         |

---

## Compilar sin ejecutar

```powershell
$dotnet = "$env:USERPROFILE\dotnet\dotnet.exe"
& $dotnet build .\src\BancaConversacional.Api\BancaConversacional.Api.csproj -c Release
```

## Publicar para despliegue

```powershell
$dotnet = "$env:USERPROFILE\dotnet\dotnet.exe"
& $dotnet publish .\src\BancaConversacional.Api\BancaConversacional.Api.csproj -c Release -o .\publish
```

El binario resultante en `.\publish\BancaConversacional.Api.exe` es autocontenido y no requiere Visual Studio.

---

## Seguridad

- La API key de NVIDIA **nunca** se guarda en `appsettings.json` — se inyecta como variable de entorno en tiempo de ejecución.
- El archivo `.env` está en `.gitignore` y no se sube al repositorio.
- Rate limiting activo: **60 solicitudes por minuto por IP**. Si se supera, el servidor responde `429 Too Many Requests`.
- Los `HttpClient` tienen timeouts configurados: NVIDIA 40s, API bancaria 20s.

---

## Docker y Kubernetes

### Construir imagen Docker

```powershell
docker build -t banca-conversacional-api:latest .
```

### Ejecutar contenedor local

```powershell
docker run --rm -p 8080:8080 \
  -e ASPNETCORE_ENVIRONMENT=Development \
  -e ExternalServices__AzureApiKey=<AZURE_API_KEY> \
  -e ExternalServices__BankingApiBaseDev=https://zqp02jwv1j.execute-api.us-east-1.amazonaws.com/poc \
  -e ExternalServices__DashboardApiBaseDev=http://172.27.4.20:4429 \
  banca-conversacional-api:latest
```

### Archivos Kubernetes incluidos

- `deploy/k8s/configmap.yaml`
- `deploy/k8s/secret.example.yaml`
- `deploy/k8s/deployment.yaml`
- `deploy/k8s/service.yaml`
- `deploy/k8s/ingress.example.yaml`

### Desplegar en Kubernetes

1. Crear secret real (copiar desde `secret.example.yaml` y colocar llaves reales).
2. Ajustar imagen en `deploy/k8s/deployment.yaml` (`your-registry/banca-conversacional-api:latest`).
3. Aplicar manifiestos:

```powershell
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.example.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
```

4. (Opcional) Si usas Ingress NGINX:

```powershell
kubectl apply -f deploy/k8s/ingress.example.yaml
```

Prueba de automatización documentacion
