# Deploy Cognitiva QA — puerto 8447

**Instancia de evolución** de la banca conversacional. No modifica 8446.

El servicio escucha en `GENESIS_HOST=0.0.0.0` → **misma instancia** en IP pública y privada.

| URL | Uso |
|-----|-----|
| http://20.127.25.24:8447/pruebas | UI de pruebas (IP **pública**) |
| http://192.168.150.5:8447/pruebas | UI de pruebas (IP **privada** / VNet) |
| http://20.127.25.24:8447/health | Health (pública) |
| http://192.168.150.5:8447/health | Health (privada) |
| `…:8447/turn` | API turn (ambas IPs) |
| `…:8447/orch/webhook/chat` | Webhook: header `ClientId` → sesión + chat (vía orquestador) |
| `…:8447/orch/webhook/session` | Solo crea sesión con `ClientId` |

Detalle y ejemplos curl: [`WEBHOOK_ORCH.md`](./WEBHOOK_ORCH.md)

## Requisitos de red

- **Pública:** NSG permitiendo tu IP en **22** y **8447**.
- **Privada:** acceso desde la VNet / VPN / jump host (no requiere Internet).
- Variable `SSH_DEPLOY_PASS` (no se guarda en el repo).

Comprobar IP pública:

```powershell
(Invoke-RestMethod https://api.ipify.org).Trim()
```

## Deploy Fase 1

```powershell
cd C:\NovusIntelligence\BancoSantaCruz\BancaConversacional

# Empaqueta src + data (FAQ overlay) + docs + deploy scripts
.\.venv\Scripts\python.exe .\deploy\corp-8446\build_corp_package.py

$env:SSH_DEPLOY_PASS = "<password>"
$env:SSH_HOST = "20.127.25.24"
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_ssh_password.py
```

El script remoto (`deploy_8447.sh`) deja en `.env` / systemd:

- `GENESIS_FAQ_PATH=.../data/kb_faq_vf01.json`
- `GENESIS_FAQ_OVERLAY_PATH=.../data/kb_faq_overlay_fase1.json`
- `GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL=1`

## Validar los 6 casos en 8447

```powershell
$env:GENESIS_VALIDATE_BASE = "http://20.127.25.24:8447"
.\.venv\Scripts\python.exe .\Test_local\validate_fase1_cases.py
```

## Notas

- **8445** = solo local.
- **8446** = legacy; el deploy 8447 no lo reinicia ni lo sobrescribe.
- **8448** = contenedores opcionales en paralelo.
