# Genesis Cognitiva — Despliegue integral VM laboratorio y réplica corporativa

**Versión:** 1.0  
**Fecha:** 2026-07-30  
**Alcance:** Capa cognitiva (Contract Inspector + Disparo Determinista + sesión reactiva).  
**No incluye:** VPN S2S (en lab opera transparente), ejecución Core, autenticación de canal (orquestador).

---

## 1. Inventario de infraestructura objetivo

| Parámetro | Valor laboratorio / plantilla corporativa |
|-----------|-------------------------------------------|
| VM | `vm-test002-genesis` |
| Grupo de recursos | `RG_BSC_PRJ_GENESIS` |
| Suscripción | EA (corporativa: mapear suscripción real) |
| Región | East US |
| SO | Linux Ubuntu 24.04 |
| Tamaño | Standard **B2s** (2 vCPU / 4 GiB) — mínimo viable; recomendar B4ms si carga E2E + clasificadores paralelos satura |
| Usuario admin | `genesis` |
| IP privada (ideal) | `192.168.150.5` |
| VNet | `VNET_S2S_AZ_TO_BSC_GEN` |
| Subred | `SNET_S2S_GEN_APP` |
| DNS | No configurado (acceso por IP) |
| Puerto **prohibido** | **8443** (ocupado) |
| Puerto **autorizado** | Uno libre en **8440–8449** (ej. **8445**) |
| SSL en esta fase | **Sin SSL** (HTTP plano para pruebas de red del equipo) |

### Azure OpenAI (valores de despliegue)

```bash
AZURE_OPENAI_ENDPOINT=https://testbsc0001.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
# API Key: usar la key actual del recurso (NO versionar en git)
AZURE_OPENAI_API_KEY=<secret>
AZURE_OPENAI_API_VERSION=2024-08-01-preview   # ajustar a la versión habilitada en el recurso
```

### Knowledge Base (RAG) — rutas de origen en estación de desarrollo

```text
C:\Users\boris\Documents\Genesis\Genesis_v2\Knowledge_Base\KB_GENESIS_Protocolo_Maestro_Asistente_Bancario_Conversacional_v1.01.pdf
C:\Users\boris\Documents\Genesis\Genesis_v2\Knowledge_Base\KB_GENESIS_Base_Conocimiento_RAG_Asistente_Bancario_v1.01.pdf
```

En la VM se copian a, por ejemplo:

```text
/opt/genesis/Knowledge_Base/
```

---

## 2. Principios de portabilidad

1. **Toda** IP, puerto, endpoint OpenAI, path de KB y `GENESIS_ENV` van en **variables de entorno** o `.env` fuera del código.
2. El proceso escucha en `0.0.0.0` solo si la NSG/firewall de la VNet lo permite; preferible bind a IP privada de la NIC.
3. Mismo procedimiento en lab y corporativo: solo cambian valores de `.env` y nombres de RG/VM/IP.
4. Cognitiva **no** ejecuta Core; mutantes emiten VALIDATE (EXECUTE solo si `GENESIS_ENV=dev|test`).

---

## 3. Mapa de endpoints a validar remotamente

| Uso | Método | Ruta (actual / objetivo) | Notas |
|-----|--------|--------------------------|-------|
| Salud | GET | `/health` | **Debe existir** (añadir si falta; respuesta `{"status":"ok"}`) |
| UI Lab | GET | `/` | Contract Inspector estático |
| Turno conversacional | POST | `/inspect` (alias opcional `/turn`) | Body: `question`, `customer_id`, `conversation_id` |
| Disparo determinista | POST | `/contract-lab/dispatch` | Comandos canónicos 1.2 |
| Config entorno | GET | `/config` | `genesis_env`, `allow_cognitive_execute` |
| Clientes dummy | GET | `/customers` | Lista sandbox |

**Contrato de body multiturno (orquestador / PCo):**

```json
{
  "question": "saldo de mi cuenta de ahorros?",
  "customer_id": "CUST001",
  "conversation_id": "<uuid-estable-sesion>",
  "turn_number": 1
}
```

El **orquestador** asigna `conversation_id` y `customer_id`; la cognitiva asocia sesión y responde.

---

## 4. Procedimiento de despliegue en la VM (lab)

### 4.1 Acceso

```bash
# Desde jump host / estación con ruta a 192.168.150.5 (lab transparente)
ssh genesis@192.168.150.5
```

### 4.2 Paquetes base

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip git build-essential curl
```

### 4.3 Código de la aplicación

```bash
sudo mkdir -p /opt/genesis
sudo chown genesis:genesis /opt/genesis
cd /opt/genesis

# Opción A: git clone del repo corporativo
# git clone <url-repo-genesis> Genesis_v2
# cd Genesis_v2

# Opción B: rsync/scp desde estación Windows
# (ejecutar en Windows, ajustando IP)
# scp -r C:\Users\boris\Documents\Genesis\Genesis_v2 genesis@192.168.150.5:/opt/genesis/
```

Estructura mínima esperada:

```text
/opt/genesis/Genesis_v2/
  src/genesis_cognitive/
  scripts/run_contract_inspector.py
  data/demo/modelo_bancario_genesis_v2.sqlite
  Knowledge_Base/          # PDFs RAG
  prompts/
  requirements.txt | pyproject.toml
```

### 4.4 Entorno virtual e instalación

```bash
cd /opt/genesis/Genesis_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# Si el entrypoint usa Microsoft Agent Framework / Azure Identity:
# pip install azure-identity openai httpx fastapi uvicorn ...
```

### 4.5 Knowledge Base

```bash
mkdir -p /opt/genesis/Genesis_v2/Knowledge_Base
# Copiar los dos PDF desde la estación de desarrollo
```

### 4.6 Archivo de configuración (no commitear secretos)

Crear `/opt/genesis/Genesis_v2/.env` (permisos `600`):

```bash
# --- Red / proceso ---
GENESIS_ENV=dev
GENESIS_HOST=0.0.0.0
GENESIS_PORT=8445
# Rango autorizado 8440-8449; 8443 PROHIBIDO

# --- Azure OpenAI ---
AZURE_OPENAI_ENDPOINT=https://testbsc0001.openai.azure.com/
AZURE_OPENAI_API_KEY=<API_KEY_ACTUAL>
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Auth alternativa (si usan Azure CLI / Managed Identity en corporativo):
# AZURE_OPENAI_AUTH=api_key|azure_cli|managed_identity

# --- Datos demo ---
GENESIS_SQLITE_PATH=/opt/genesis/Genesis_v2/data/demo/modelo_bancario_genesis_v2.sqlite
GENESIS_KB_DIR=/opt/genesis/Genesis_v2/Knowledge_Base

# --- Sesión reactiva (simulación Redis) ---
GENESIS_SESSION_TTL_SECONDS=1800
GENESIS_SNAPSHOT_TTL_SECONDS=60
```

Cargar en shell de prueba:

```bash
set -a; source /opt/genesis/Genesis_v2/.env; set +a
```

### 4.7 Elegir puerto libre (8440–8449)

```bash
for p in 8440 8441 8442 8444 8445 8446 8447 8448 8449; do
  ss -tlnp | grep -q ":$p " || { echo "Libre: $p"; break; }
done
# NO usar 8443
```

Documentar el puerto elegido (ej. **8445**) en el runbook del equipo.

### 4.8 Endpoint `/health` (obligatorio)

Si no existe, añadir en `contract_inspector_app.py` (o router):

```python
@app.get("/health")
def health():
    return {"status": "ok", "service": "genesis-cognitive", "env": os.getenv("GENESIS_ENV", "dev")}
```

Alias opcional orquestador:

```python
# POST /turn -> mismo handler que /inspect
app.add_api_route("/turn", inspect_handler, methods=["POST"])
```

### 4.9 Arranque manual de prueba

```bash
cd /opt/genesis/Genesis_v2
source .venv/bin/activate
set -a; source .env; set +a
export PYTHONPATH=src:$PYTHONPATH

# Ajustar run_contract_inspector.py para leer GENESIS_HOST/PORT
python scripts/run_contract_inspector.py
# Debe escuchar http://0.0.0.0:8445
```

### 4.10 Servicio systemd (persistente)

`/etc/systemd/system/genesis-cognitive.service`:

```ini
[Unit]
Description=Genesis Cognitive Layer (Contract Inspector)
After=network.target

[Service]
Type=simple
User=genesis
Group=genesis
WorkingDirectory=/opt/genesis/Genesis_v2
EnvironmentFile=/opt/genesis/Genesis_v2/.env
Environment=PYTHONPATH=/opt/genesis/Genesis_v2/src
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/genesis/Genesis_v2/.venv/bin/python scripts/run_contract_inspector.py
Restart=always
RestartSec=5
# Límites razonables en B2s
MemoryMax=3G

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable genesis-cognitive
sudo systemctl start genesis-cognitive
sudo systemctl status genesis-cognitive
journalctl -u genesis-cognitive -f
```

### 4.11 NSG / firewall (lab y corporativo)

En el NSG de `SNET_S2S_GEN_APP` / NIC de la VM:

- Permitir **TCP inbound** al puerto elegido (**8445**) desde:
  - Subred del equipo de pruebas
  - Subred del orquestador / PCo
- Denegar acceso público a Internet si la política corporativa lo exige
- **No** abrir 8443 para este servicio

---

## 5. Validación remota (otra máquina en la red del equipo)

Sustituir `<IP>` y `<PUERTO>` (ej. `192.168.150.5` y `8445`).

### 5.1 Salud

```bash
curl -sS "http://<IP>:<PUERTO>/health"
# Esperado: {"status":"ok", ...}
```

### 5.2 Config

```bash
curl -sS "http://<IP>:<PUERTO>/config"
```

### 5.3 Multiturno (aislamiento de sesión)

**Sesión A — CUST001**

```bash
CONV_A=$(uuidgen)
curl -sS -X POST "http://<IP>:<PUERTO>/inspect" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Hola\",\"customer_id\":\"CUST001\",\"conversation_id\":\"$CONV_A\",\"turn_number\":1}"

curl -sS -X POST "http://<IP>:<PUERTO>/inspect" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"saldo de mi cuenta de ahorros?\",\"customer_id\":\"CUST001\",\"conversation_id\":\"$CONV_A\",\"turn_number\":2}"
```

**Sesión B — CUST008 (paralelo, otro conversation_id)**

```bash
CONV_B=$(uuidgen)
curl -sS -X POST "http://<IP>:<PUERTO>/inspect" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Dime la letra de mi prestamo\",\"customer_id\":\"CUST008\",\"conversation_id\":\"$CONV_B\",\"turn_number\":1}"
```

Verificar que A y B no cruzan `customer_context` ni `pending_action`.

### 5.4 Disparo determinista (cliente externo + mutante VALIDATE)

```bash
curl -sS -X POST "http://<IP>:<PUERTO>/contract-lab/dispatch" \
  -H "Content-Type: application/json" \
  -d '{"question":"Paga prestamo 45651 valor 1000 moneda DOP","customer_id":"123456","conversation_id":"lab-ext-1"}'
# Esperado: simulated=false, nature=mutant, phase=VALIDATE, LOAN_SERVICING_VALIDATE
```

### 5.5 UI desde navegador en la red

```text
http://192.168.150.5:8445/
```

Sin SSL en esta fase.

---

## 6. Checklist de réplica en suscripción corporativa

| Paso | Lab | Corporativo |
|------|-----|-------------|
| Suscripción / RG | EA / `RG_BSC_PRJ_GENESIS` | Mapear suscripción y RG reales |
| VM | `vm-test002-genesis` | VM asignada (mismo o similar size) |
| VNet / subnet | Ya dispuesta | Usar VNet S2S corporativa ya existente |
| IP privada | `192.168.150.5` (ideal) | IP que asigne la corporación |
| Puerto | Libre 8440–8449 ≠ 8443 | Mismo criterio |
| `.env` | Endpoint test OpenAI + API key | Endpoint/key o **Managed Identity** del recurso corporativo |
| Código | Mismo artefacto `/opt/genesis/Genesis_v2` | Mismo tag de release |
| NSG | Reglas lab | Reglas corporativas (solo redes autorizadas) |
| VPN | Transparente en lab | S2S activa según diseño; **no cambia** el procedimiento de app |
| Validación | curl `/health`, multiturno, dispatch | Idénticos apuntando a IP corporativa |

**Únicos valores a re-mapear:** suscripción, RG, nombre VM, IP, NSG, secretos OpenAI, puerto libre.

---

## 7. Ajustes de código recomendados antes del deploy (Kiro / equipo)

1. `run_contract_inspector.py` lee `GENESIS_HOST`, `GENESIS_PORT` desde entorno.  
2. `GET /health` obligatorio.  
3. Opcional: `POST /turn` = alias de `/inspect` (contrato orquestador).  
4. Carga de `.env` con `python-dotenv` al arrancar.  
5. Documentar API key **solo** en Key Vault / variable de entorno de la VM, nunca en repo.

---

## 8. Limitaciones del tamaño B2s

Con clasificadores paralelos + proposer/verifier, un E2E agresivo puede acercarse a límites de RAM/CPU. Mitigaciones:

- Delay entre requests en suites E2E  
- Un worker uvicorn  
- Monitor: `htop`, `journalctl`  
- Si hace falta: subir a **B4ms** en la misma plantilla de despliegue

---

## 9. Resumen operativo

```text
Estación dev  --(scp/git)-->  VM 192.168.150.5:/opt/genesis
                                  |
                                  systemd genesis-cognitive
                                  escucha :8445 (ejemplo)
                                  |
Red equipo --HTTP--> /health | /inspect | /contract-lab/dispatch
                                  |
                           Azure OpenAI testbsc0001
```

**Cognitiva en la VM:** interpreta, aclara, emite `operation_request` 1.2.  
**Orquestador (otra capa):** inicia sesión, autentica, llama a esta API, confirma mutantes y habla con Core.

---

*Documento listo para anexar al runbook del proyecto Genesis. Sustituir `<API_KEY>` y confirmar puerto libre en la VM antes de abrir NSG.*
