# Despliegue Genesis Cognitiva 8447

**Para:** compañero con VPN / acceso a `192.168.150.5`  
**Qué incluye:** código actual (webhook orch, FAQ overlay Fase 1, UI pruebas)  
**No toca:** puerto 8446 (legacy)

| Dato | Valor |
|------|-------|
| ZIP | `genesis_corp_8447.zip` (~1.2 MB) |
| SHA256 | `31ec429bbe2aaf4d80ce2bdbdf8cb0722b8919e5582acb27007570a97f60e453` |
| Usuario SSH | `genesis` |
| IP privada | `192.168.150.5` |
| IP pública | `20.127.25.24` |
| Destino remoto | `/tmp/genesis_corp_8447.zip` |
| Servicio | `genesis-cognitive-8447.service` |

---

## Opción A — Script automático (recomendado si tienes el repo)

Desde la raíz del repo, con VPN conectada:

```powershell
cd C:\NovusIntelligence\BancoSantaCruz\BancaConversacional

# Asegura que el ZIP del kit esté en dist (o regenera)
Copy-Item .\deploy\corp-8447\instalador\genesis_corp_8447.zip `
  .\deploy\corp-8446\dist\genesis_corp_8446.zip -Force

$env:SSH_DEPLOY_PASS = "<password genesis>"
$env:SSH_HOST = "192.168.150.5"
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_ssh_password.py
```

El script sube el ZIP, ejecuta `deploy_8447.sh`, reinicia el servicio y prueba `/health` + webhook.

---

## Opción B — Manual por SSH (solo el ZIP de esta carpeta)

### 1) Con VPN, subir el paquete

```powershell
cd <ruta>\deploy\corp-8447\instalador
scp .\genesis_corp_8447.zip genesis@192.168.150.5:/tmp/genesis_corp_8447.zip
```

### 2) Entrar a la VM y desplegar

```bash
ssh genesis@192.168.150.5
```

Dentro de la VM:

```bash
# Verificar ZIP
ls -lh /tmp/genesis_corp_8447.zip
sha256sum /tmp/genesis_corp_8447.zip
# debe coincidir: 31ec429bbe2aaf4d80ce2bdbdf8cb0722b8919e5582acb27007570a97f60e453

# Primera vez o si el script aún no está en disco:
sudo mkdir -p /opt/genesis-cognitive-8447/Genesis_v2
cd /opt/genesis-cognitive-8447/Genesis_v2
sudo unzip -oq /tmp/genesis_corp_8447.zip
sudo find . -name '*.sh' -exec sed -i 's/\r$//' {} \;
sudo chmod +x deploy/corp-8447/deploy_8447.sh
sudo bash deploy/corp-8447/deploy_8447.sh
```

Si `deploy_8447.sh` **ya existía** de un deploy anterior, basta:

```bash
sudo bash /opt/genesis-cognitive-8447/Genesis_v2/deploy/corp-8447/deploy_8447.sh
```

(el script espera el ZIP en `/tmp/genesis_corp_8447.zip`)

### 3) Validar

```bash
curl -sS http://127.0.0.1:8447/health
curl -sS -X POST "http://127.0.0.1:8447/orch/webhook/chat" \
  -H "Content-Type: application/json" \
  -H "ClientId: 726588" \
  -d '{"question":"hola"}'
```

Respuesta esperada: JSON con `reply` y `conversation_id` (no `Not Found`).

Desde tu PC (VPN):

- Health: http://192.168.150.5:8447/health  
- Pruebas: http://192.168.150.5:8447/pruebas  
- Webhook: `POST http://192.168.150.5:8447/orch/webhook/chat` + header `ClientId`

Pública (si NSG lo permite): http://20.127.25.24:8447/pruebas

### 4) Confirmar que 8446 sigue intacto

```bash
curl -sS http://127.0.0.1:8446/health
```

---

## Rollback (si algo falla)

El deploy crea backup en:

`/opt/genesis-cognitive-8447/backups/genesis_v2_YYYYMMDD_HHMMSS.tar.gz`

```bash
ls -lt /opt/genesis-cognitive-8447/backups/ | head
# restaurar el más reciente si hace falta (avisar al equipo antes)
```

---

## Notas

- El `.env` de 8447 se conserva; si es primera instalación, se copia desde 8446 y se ajusta `GENESIS_PORT=8447`.
- No hace falta Docker en 8447 (servicio systemd + venv).
- Si SSH falla por timeout: VPN desconectada o NSG bloqueando; usar solo IP privada `192.168.150.5`.
