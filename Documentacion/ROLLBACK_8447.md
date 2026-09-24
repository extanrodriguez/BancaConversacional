# ROLLBACK 8447 — Volver a la versión pre-migración Foundry tools

Procedimiento ejecutable. Objetivo: restaurar el comportamiento validado **antes** de cambios de arquitectura Foundry + Product Context tools.

**Backup de referencia local:**  
`backups/8447_pre_foundry_redis_20260921_194845/`

**Backup de referencia en VM (si existe deploy previo):**  
`/opt/genesis-cognitive-8447/backups/genesis_v2_<timestamp>.tar.gz`

---

## 0. Premisas

1. El orquestador **no** se toca; el contrato `POST /turn` debe permanecer.
2. No restaurar secretos desde git: el `.env` remoto se **preserva** o se recupera desde backup del host (modo `600`).
3. Preferir rollback del **código desplegado** en la VM; el backup local sirve si el árbol remoto se corrompió o no hay tarball.

---

## 1. Stop nueva versión

```bash
sudo systemctl stop genesis-cognitive-8447.service
sudo systemctl status genesis-cognitive-8447.service --no-pager
# debe quedar inactive
```

Verificar que el puerto liberó:

```bash
ss -ltnp | grep 8447 || echo "8447 libre"
```

---

## 2. Preserve configuración sensible

```bash
sudo cp -a /opt/genesis-cognitive-8447/Genesis_v2/.env \
  /tmp/genesis8447.env.rollback.$(date -u +%Y%m%d_%H%M%S)
sudo chmod 600 /tmp/genesis8447.env.rollback.*
```

Si hay `EnvironmentFile` o unit modificados:

```bash
sudo cp -a /etc/systemd/system/genesis-cognitive-8447.service \
  /tmp/genesis-cognitive-8447.service.rollback.$(date -u +%Y%m%d_%H%M%S)
```

---

## 3A. Restore desde tarball de la VM (preferido)

```bash
BACKUP_ROOT=/opt/genesis-cognitive-8447/backups
# listar y elegir el tarball PRE-migración
ls -lt "$BACKUP_ROOT"/genesis_v2_*.tar.gz | head

TIMESTAMP=<elegir>
sudo systemctl stop genesis-cognitive-8447.service

# mover árbol actual a cuarentena
sudo mv /opt/genesis-cognitive-8447/Genesis_v2 \
  /opt/genesis-cognitive-8447/Genesis_v2.failed_$(date -u +%Y%m%d_%H%M%S)

sudo mkdir -p /opt/genesis-cognitive-8447
sudo tar -xzf "$BACKUP_ROOT/genesis_v2_${TIMESTAMP}.tar.gz" \
  -C /opt/genesis-cognitive-8447

# restaurar .env preservado
sudo cp -a /tmp/genesis8447.env.rollback.* /opt/genesis-cognitive-8447/Genesis_v2/.env
sudo chmod 600 /opt/genesis-cognitive-8447/Genesis_v2/.env
sudo chown -R genesis:genesis /opt/genesis-cognitive-8447/Genesis_v2
```

Si el tarball **excluyó** `.venv` (como hace `deploy_8447.sh`):

```bash
cd /opt/genesis-cognitive-8447/Genesis_v2
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
grep -v '^-e' requirements.runtime.txt > /tmp/_req_runtime_clean.txt
.venv/bin/pip install -r /tmp/_req_runtime_clean.txt
.venv/bin/pip install -e .
```

---

## 3B. Restore desde backup local (Windows → VM)

Usar cuando no hay tarball usable en la VM.

1. Empaquetar desde el backup:

```powershell
$bak = "c:\NovusIntelligence\BancoSantaCruz\BancaConversacional\backups\8447_pre_foundry_redis_20260921_194845"
# Reconstruir árbol deployable: source → src/genesis_cognitive, scripts, requirements, systemd, data
```

2. Transferir zip a la VM (`/tmp/genesis_corp_8447.zip`) y ejecutar el flujo de `deploy/corp-8447/deploy_8447.sh` **solo después** de confirmar que el zip corresponde al backup pre-migración.

3. Restaurar unit:

```bash
sudo cp deploy/corp-8447/genesis-cognitive-8447.service /etc/systemd/system/
sudo systemctl daemon-reload
```

---

## 4. Restore service definition si cambió

```bash
# Si se guardó copia en /tmp:
sudo cp /tmp/genesis-cognitive-8447.service.rollback.<ts> \
  /etc/systemd/system/genesis-cognitive-8447.service
sudo systemctl daemon-reload
```

Unit esperada (esencia):

- `User=genesis`
- `WorkingDirectory=/opt/genesis-cognitive-8447/Genesis_v2`
- `Environment=GENESIS_PORT=8447`
- `EnvironmentFile=.../Genesis_v2/.env`
- `ExecStart=.../.venv/bin/python scripts/run_contract_inspector.py`
- `Restart=always`

---

## 5. Start versión anterior

```bash
sudo systemctl start genesis-cognitive-8447.service
sudo systemctl status genesis-cognitive-8447.service --no-pager
journalctl -u genesis-cognitive-8447.service -n 80 --no-pager
```

---

## 6. Health / ready / smoke

```bash
curl -sf http://127.0.0.1:8447/health
curl -sf http://127.0.0.1:8447/ready/redis
# /ready genérico puede ser 404 — no bloquear rollback por eso
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8447/pruebas/

# Smoke /turn (institucional; no requiere snapshot)
curl -sf http://127.0.0.1:8447/turn \
  -H 'Content-Type: application/json' \
  -d '{"question":"cual es la mision del banco","conversation_id":"rollback-smoke-1","customer_id":"726588","context_info":false}'
```

Criterios de éxito:

| Check | Esperado |
|-------|----------|
| `/health` | `status=ok`, `rag=ready` |
| `/ready/redis` | `ok=true`, pings true |
| `/turn` smoke | HTTP 200, `status` coherente (p.ej. `VALID_CONTRACT`) |
| systemd | `active (running)` |

Comparar contra: `Documentacion/BASELINE_8447_PRE_MIGRACION.md`

---

## 4. Feature-flag rollback (si la migración se desplegó con flags)

Si la nueva ruta Foundry tools se activó solo con variables, **primero** intentar:

```bash
# en .env remoto — valores conceptuales; no pegar secretos
GENESIS_FOUNDRY_PRODUCT_TOOLS=0   # o el flag que se introduzca
# reiniciar
sudo systemctl restart genesis-cognitive-8447.service
```

Solo si el flag no restaura el baseline, ejecutar restore de código (§3).

---

## 8. Checklist post-rollback

- [ ] Servicio `active`
- [ ] `/health` OK
- [ ] `/ready/redis` OK
- [ ] `/pruebas/` 200
- [ ] Smoke `/turn` OK
- [ ] Orquestador puede cargar `context_info` (si hay acceso de prueba)
- [ ] No quedó proceso huérfano en 8447

---

## 9. Contactos / artefactos

| Artefacto | Ubicación |
|-----------|-----------|
| Estado pre | `Documentacion/ESTADO_PRE_MIGRACION_8447.md` |
| Baseline | `Documentacion/BASELINE_8447_PRE_MIGRACION.md` |
| Backup local | `backups/8447_pre_foundry_redis_20260921_194845/` |
| Checksums | `.../BACKUP_CHECKSUMS.txt` |
| Deploy script | `deploy/corp-8447/deploy_8447.sh` |
