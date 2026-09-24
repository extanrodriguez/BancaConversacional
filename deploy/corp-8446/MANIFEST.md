# Genesis Cognitive 8446 — Deploy Package

## Target
- VM: vm-test002-genesis (192.168.150.5)
- Path: /opt/genesis-cognitive-8446/Genesis_v2
- Port: 8446 (isolated from 8445)
- User: genesis

## Build (Windows / dev)
```powershell
cd C:\NovusIntelligence\BancoSantaCruz\BancaConversacional
.\.venv\Scripts\python.exe deploy\corp-8446\build_corp_package.py
# Salida: deploy\corp-8446\dist\genesis_corp_8446.zip
```

## Deploy automático (Windows, requiere VPN/red corporativa)
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\corp-8446\deploy_from_windows.ps1
# Solo empaquetar:
powershell -ExecutionPolicy Bypass -File .\deploy\corp-8446\deploy_from_windows.ps1 -BuildOnly
```

## Deploy manual (Linux / jump host)
```bash
scp deploy/corp-8446/dist/genesis_corp_8446.zip genesis@192.168.150.5:/tmp/
ssh genesis@192.168.150.5
sudo bash /opt/genesis-cognitive-8446/Genesis_v2/deploy/corp-8446/deploy_8446.sh
curl http://127.0.0.1:8446/health
curl http://127.0.0.1:8445/health  # must still be alive
```

El script `deploy_8446.sh` ahora:
1. Hace **backup** en `/opt/genesis-cognitive-8446/backups/` (tar.gz + `.env`)
2. Preserva `.env` existente
3. Instala dependencias, reinicia systemd y valida `/health` y `/pruebas`

## Rollback
```bash
# Restaurar último backup (recomendado)
sudo bash /opt/genesis-cognitive-8446/Genesis_v2/deploy/corp-8446/restore_from_backup.sh

# Solo detener servicio (legacy)
sudo bash /opt/genesis-cognitive-8446/Genesis_v2/deploy/corp-8446/rollback_8446.sh
```

## Health checks
```bash
curl http://127.0.0.1:8445/health  # existing (never modified)
curl http://127.0.0.1:8446/health  # new isolated
```

## Interfaz de prueba
Tras el deploy y `systemctl start genesis-cognitive-8446`:
- Abrir `http://20.127.25.24:8446/pruebas`
- Iniciar sesión como usuario. El login llama a `POST /lab/login`, que carga el JSON Core y el contexto (`CONTEXT_LOADED`). Sin login no hay chat.
- La UI queda fijada en `src/genesis_cognitive/demo/pruebas_ui` (no se regenera en la VM).
- `GENESIS_SERVE_UI=false` oculta el lab de `/`; `/pruebas` se sirve igual.

## Contents
- src/ — cognitive layer code (incluye `src/genesis_cognitive/demo/pruebas_ui`)
- data/lab_usuarios.json — usuarios de prueba para el login
- data/lab_portfolios/ — JSON Core de prueba
- tests/ — fixtures
- deploy/corp-8446/ — systemd unit + deploy/rollback scripts + .env.example
- requirements.runtime.txt — pinned runtime dependencies
- pyproject.toml — package metadata

## Excludes
- .env (secrets — create manually on host)
- .venv (created by deploy script)
- .git, logs, __pycache__


## Correcciones del artefacto corporativo
- ZIP reconstruido con rutas POSIX para extracción Linux sin advertencias.
- Runtime 8446 usa AZURE_OPENAI_API_KEY; no depende de az login.
- RAG usa AZURE_SEARCH_API_KEY sin fallback de Azure CLI.
- Consulta RAG alineada al índice vivo: content, source, document_name.
- Archivos __pycache__, *.pyc, SQLite SHM/WAL eliminados.
- Los indexadores son herramientas administrativas y NO se ejecutan en el deploy.
