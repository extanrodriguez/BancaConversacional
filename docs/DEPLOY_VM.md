# Deploy Genesis Cognitive — Azure VM (Ubuntu 24.04)

## Recursos requeridos

| Recurso | Valor |
|---------|-------|
| Subscription | 871a5b90-0204-450e-b968-3190e9143faf |
| Resource Group | rg-genesis-cognitive-mvp-eus |
| OpenAI | aoai-genesis-871a5b (gpt-4o-mini + text-embedding-3-small) |
| AI Search | genesis-search-lab (index: genesis-kb, 212 docs) |
| VM Region | eastus |
| Puerto | 8445 (rango 8440-8449, NUNCA 8443) |

## 1. Provisionar VM (si no existe)

```bash
# Desde Cloud Shell o local con az CLI
az vm create \
  --resource-group rg-genesis-cognitive-mvp-eus \
  --name vm-genesis-cognitive \
  --image Ubuntu2404 \
  --size Standard_B2s \
  --admin-username genesis \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --nsg-rule NONE

# NSG: abrir SOLO desde IPs autorizadas (equipo/VPN), NUNCA 0.0.0.0/0
az network nsg rule create \
  --resource-group rg-genesis-cognitive-mvp-eus \
  --nsg-name vm-genesis-cognitiveNSG \
  --name AllowGenesisCognitive \
  --priority 1000 \
  --source-address-prefixes "<TU_IP>/32" \
  --destination-port-ranges 8445 \
  --access Allow --protocol Tcp --direction Inbound
```

## 2. Conectar a la VM

```bash
ssh genesis@<IP_PUBLICA>
```

## 3. Instalar dependencias del sistema

```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip git curl
# Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

## 4. Autenticacion Azure

```bash
az login
# Verificar:
az account show --query "{name:name, id:id}" -o table
# Debe mostrar: Azure subscription 1 / 871a5b90-...
```

**Nota**: El servicio usa `AzureCliCredential`. La sesion `az login` debe estar activa.
Para produccion, considerar Managed Identity asignada a la VM.

## 5. Clonar/copiar repositorio

```bash
sudo mkdir -p /opt/genesis && sudo chown genesis:genesis /opt/genesis
cd /opt/genesis
git clone <REPO_URL> Genesis_v2
# O: scp -r desde local
cd Genesis_v2
```

## 6. Entorno virtual + dependencias

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 7. Configurar .env

```bash
cp .env.example .env
nano .env
```

Variables clave (ya preconfiguradas en .env.example):

```env
GENESIS_ENV=dev
GENESIS_HOST=0.0.0.0
GENESIS_PORT=8445
AZURE_OPENAI_ENDPOINT=https://aoai-genesis-871a5b-7e0e0.openai.azure.com/
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_API_VERSION=2024-12-01-preview
AZURE_SEARCH_ENDPOINT=https://genesis-search-lab.search.windows.net
AZURE_SEARCH_INDEX=genesis-kb
GENESIS_SQLITE_PATH=data/demo/modelo_bancario_genesis_v2.sqlite
```

**AZURE_SEARCH_API_KEY**: obtener con:
```bash
az search admin-key show --service-name genesis-search-lab \
  --resource-group rg-genesis-cognitive-mvp-eus --query primaryKey -o tsv
```
Pegar en .env como `AZURE_SEARCH_API_KEY=<key>` (evita subprocess en runtime).

## 8. Verificar puerto libre

```bash
for p in 8440 8441 8442 8444 8445 8446 8447 8448 8449; do
  ss -tlnp | grep -q ":$p " || { echo "LIBRE=$p"; break; }
done
```

## 9. Test manual (foreground)

```bash
source .venv/bin/activate
python scripts/run_contract_inspector.py
# En otra terminal:
curl http://localhost:8445/health
```

## 10. Instalar como servicio systemd

```bash
sudo cp deploy/genesis-cognitive.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now genesis-cognitive
sudo systemctl status genesis-cognitive
```

## 11. Verificar

```bash
# Health
curl -s http://localhost:8445/health | python3 -m json.tool

# Smoke completo
bash scripts/smoke_remote_health.sh http://localhost:8445

# Desde fuera de la VM (tu IP):
curl http://<IP_PUBLICA>:8445/health
```

## 12. Logs

```bash
journalctl -u genesis-cognitive -f
journalctl -u genesis-cognitive --since "5 min ago"
```

## 13. Reiniciar / actualizar

```bash
cd /opt/genesis/Genesis_v2
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart genesis-cognitive
sudo systemctl status genesis-cognitive
```

## Endpoints disponibles

| Metodo | Path | Descripcion |
|--------|------|-------------|
| GET | /health | Health check (status, env, rag) |
| GET | /config | Runtime config |
| POST | /inspect | Pipeline cognitivo NLP completo |
| POST | /turn | Alias de /inspect (orquestador) |
| POST | /rag/query | Consulta RAG directa |
| POST | /contract-lab/dispatch | Dispatch determinista (contratos 1.2) |
| POST | /contract-lab/validate | Mutant validate (loan) |
| GET | /customers | Lista clientes demo |
| GET | / | UI Contract Inspector |

## Seguridad

- Secretos SOLO en .env (EnvironmentFile en systemd). NUNCA en git.
- .env esta en .gitignore.
- NSG: abrir puerto 8445 SOLO a IPs autorizadas. NUNCA 0.0.0.0/0.
- GENESIS_ENV=prod bloquea phase=EXECUTE en dispatch.
- No exponer a internet sin reverse proxy + autenticacion.
- az login debe renovarse periodicamente (o usar Managed Identity).

## Troubleshooting

| Sintoma | Causa | Fix |
|---------|-------|-----|
| 401 en LLM | Token az expirado | `az login` en la VM |
| rag=not_indexed | AZURE_SEARCH_API_KEY falta | Agregar key en .env |
| Port in use | Otro servicio en 8445 | Cambiar GENESIS_PORT |
| pip install falla | Python version | Verificar python3.11 |
