# Genesis Cognitive 8448 — Docker on VM

## Target
- Port: **8448** (containers; parallel to systemd 8446/8447)
- Compose: `deploy/corp-8448/docker-compose.yml`
- Services: `genesis-api-8448` + `genesis-redis-8448`

## Architecture
```
Internet / QA
    → :8448  genesis-api (FastAPI, Redis session)
         → Azure OpenAI + Azure AI Search
         → host.docker.internal:8080 (MCP Bridge, optional)
```

## Deploy from Windows
```powershell
# 1) Build corp ZIP (incluye KB FAQ + UI)
.\.venv\Scripts\python.exe deploy\corp-8446\build_corp_package.py

# 2) Deploy containers on VM
$env:SSH_DEPLOY_PASS="..."
.\.venv\Scripts\python.exe deploy\corp-8448\deploy_ssh_password.py
```

## Local Docker
```powershell
docker compose -f deploy/corp-8448/docker-compose.yml up -d --build
curl http://127.0.0.1:8448/health
```

## URLs
- Health: http://20.127.25.24:8448/health
- Pruebas: http://20.127.25.24:8448/pruebas

## Notes
- Does **not** stop 8446/8447.
- Requires Docker on the VM and NSG allow for TCP 8448 if accessed from internet.
