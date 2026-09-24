# APK Interfaz — Banca Conversacional

Directorio para instalar y probar la banca conversacional **desde el APK** (build passkey-test).

## Qué hay aquí

| Archivo | Uso |
|---------|-----|
| `app-release-passkey-test.apk` | Build Android listo para instalar |
| `config.apk.json` | Endpoints embebidos en el APK (extraídos del bundle) |
| `scripts/verificar_conectividad.ps1` | Comprueba `:8000` (chat APK) y `:8447` (cognitiva) |
| `scripts/abrir_nsg_8000.ps1` | Abre el puerto 8000 en el NSG de Azure para tu IP |
| `scripts/probar_chat_front.ps1` | Smoke test del contrato que usa el APK |
| `scripts/instalar_apk.ps1` | Instala el APK con `adb` |

## Configuración embebida en este APK

El chat conversacional **no** apunta a `:8447`. Está hardcodeado así:

```
CHAT_API_URL = http://20.127.25.24:8000/chat/front?x-api-key=genesis-rag-temp-c04f313048e160f088601c96
```

Resto relevante:

| Campo | Valor |
|-------|-------|
| Package | `com.appconversacionalbsc` |
| API banco (login/passkey) | `https://apigateway-gen.dev.bsc.com.do/api` |
| WebSocket Genesis | `https://api-genesis.dev.bsc.com.do/ws` |
| Cognitiva QA (referencia UI) | `http://20.127.25.24:8447/pruebas` |

Flujo real:

```
APK  --POST /chat/front-->  genesis-rag :8000  --proxy-->  cognitiva :8447 (/turn)
```

## Checklist rápido (orden correcto)

### 1) Abrir red hacia `:8000`

Hoy `:8447` suele estar abierto (UI `/pruebas` funciona) pero **`:8000` está cerrado en el NSG**. Sin eso el APK se queda “pensando”.

```powershell
az login
cd C:\NovusIntelligence\BancoSantaCruz\BancaConversacional\APK_Interfaz
.\scripts\abrir_nsg_8000.ps1
.\scripts\verificar_conectividad.ps1
```

Esperado:

- Puerto **8000** → `TcpTestSucceeded = True` y `/health` OK  
- Puerto **8447** → OK (ya debería)

Si el teléfono usa otra red (datos móviles), vuelve a ejecutar `abrir_nsg_8000.ps1` desde esa misma red o añade la IP pública del dispositivo.

### 2) Confirmar el contrato del chat

```powershell
.\scripts\probar_chat_front.ps1
```

Debe devolver JSON con `reply` (no timeout ni 401/403).

### 3) Instalar el APK

Requisitos: USB debugging o emulador + `adb` (Android SDK platform-tools).

```powershell
.\scripts\instalar_apk.ps1
```

O manual:

```powershell
adb install -r .\app-release-passkey-test.apk
adb shell monkey -p com.appconversacionalbsc -c android.intent.category.LAUNCHER 1
```

### 4) Probar en el dispositivo

1. Abre la app **Banco Santa Cruz** (`com.appconversacionalbsc`).
2. Completa login / passkey contra el API gateway DEV (`apigateway-gen.dev.bsc.com.do`).
3. Entra al asistente conversacional.
4. Pregunta algo corto: `hola`, `dame el balance de mis cuentas`.

Si el login falla pero el chat smoke test de `:8000` pasa, el problema es autenticación DEV (VPN/credenciales/passkey), no la capa cognitiva.

## Fallos frecuentes

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| Chat infinito / “pensando” | NSG sin puerto 8000 | `abrir_nsg_8000.ps1` + verificar |
| `/pruebas` OK, APK no | APK usa `:8000`, UI usa `:8447` | Abrir 8000 y validar proxy RAG |
| HTTP 401/403 en smoke | API key distinta en VM | Alinear clave en `genesis-rag` o aceptar la del APK |
| Login / passkey falla | API gateway DEV o red corporativa | Revisar acceso a `apigateway-gen.dev.bsc.com.do` |
| `adb` no encontrado | SDK incompleto | Instalar platform-tools o añadir al PATH |

## Relación con el repo

- Proxy APK: `deploy/rag-proxy/cognitive_front_proxy.py`
- NSG: `deploy/azure/open_nsg_apk_8000.ps1`
- UI web equivalente: `http://20.127.25.24:8447/pruebas`

## Nota sobre el binario

El `.apk` (~84 MB) está en este directorio para pruebas locales. Evita commitearlo al git si no es necesario.
