# ROLLBACK 8447 → LEGACY (pre-merge Foundry golden)

Procedimiento para volver a la versión de 8447 **antes** de aplicar el merge “golden 8446-code → puerto 8447”.

## Clarificación de nombres

| Nombre | Significado real |
|--------|------------------|
| Puerto `:8446` | Legacy; a menudo **DOWN**. **No** es la golden Foundry+Redis. |
| Artefacto `genesis_corp_8446.zip` | Paquete del código local (candidato). |
| Puerto `:8447` | Instancia QA del orquestador. Aquí vive el WRITE PATH Redis. |

**Nunca** restaurar 8447 desde el puerto 8446 caído. Usar backups de 8447.

## Backups disponibles

| Tipo | Ubicación |
|------|-----------|
| Local (este merge) | `backups/8447_before_foundry_20260921_211159/` |
| Local (pre-migración tools) | `backups/8447_pre_foundry_redis_20260921_194845/` |
| Remoto VM | `/opt/genesis-cognitive-8447/backups/genesis_v2_*.tar.gz` |

Checksums: `BACKUP_CHECKSUMS_SHA256.txt` en el backup local (verificación = 0 fallos al crear).

## Rollback rápido (flag)

Si solo se activó Foundry product tools:

```bash
# en /opt/genesis-cognitive-8447/Genesis_v2/.env
GENESIS_FOUNDRY_PRODUCT_TOOLS=0
sudo systemctl restart genesis-cognitive-8447.service
```

## Rollback de código (VM — preferido)

```bash
sudo systemctl stop genesis-cognitive-8447.service

# preservar .env
sudo cp -a /opt/genesis-cognitive-8447/Genesis_v2/.env /tmp/genesis8447.env.rollback

# listar tarballs
ls -lt /opt/genesis-cognitive-8447/backups/genesis_v2_*.tar.gz | head

# elegir tarball PRE-merge (ej. genesis_v2_20260922_012701.tar.gz)
TS=<timestamp>
sudo mv /opt/genesis-cognitive-8447/Genesis_v2 \
  /opt/genesis-cognitive-8447/Genesis_v2.failed_$(date -u +%Y%m%d_%H%M%S)

sudo tar -xzf /opt/genesis-cognitive-8447/backups/genesis_v2_${TS}.tar.gz \
  -C /opt/genesis-cognitive-8447

sudo cp -a /tmp/genesis8447.env.rollback /opt/genesis-cognitive-8447/Genesis_v2/.env
sudo chmod 600 /opt/genesis-cognitive-8447/Genesis_v2/.env
sudo chown -R genesis:genesis /opt/genesis-cognitive-8447/Genesis_v2

# si el tarball excluyó .venv:
cd /opt/genesis-cognitive-8447/Genesis_v2
python3.12 -m venv .venv
.venv/bin/pip install -r <(grep -v '^-e' requirements.runtime.txt)
.venv/bin/pip install -e .

sudo systemctl daemon-reload
sudo systemctl start genesis-cognitive-8447.service
```

## Verificación post-rollback

```bash
curl -sf http://127.0.0.1:8447/health
curl -sf http://127.0.0.1:8447/ready/redis
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8447/pruebas/

# WRITE PATH smoke (requiere context.data válido del orquestador/lab)
# Esperado: CONTEXT_LOADED / CONTEXT_REFRESHED / 422 si falta data / SESSION_BUSY bajo contención
```

## Checklist

- [ ] Servicio `active`
- [ ] `/health` OK
- [ ] `/ready/redis` `ok=true` (Entra MI)
- [ ] Orquestador puede `context_info=true`
- [ ] Turno NL responde
- [ ] **No** se tocó `/opt/genesis-cognitive-8446`

## Qué NO hacer

- `rm -rf` del árbol fallido sin backup
- Restaurar desde `instalador/genesis_corp_8447.zip` antiguo (pierde CAS/Entra)
- Sobrescribir `.env` remoto con ejemplos sin Redis Entra
