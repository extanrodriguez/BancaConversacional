# Plan de merge — 8446 golden code → nuevo 8447 (conservando WRITE PATH)

**Fecha:** 2026-09-21  
**Backup:** `backups/8447_before_foundry_20260921_211159/` (checksums OK)

---

## 1. Clarificación crítica (nombres vs realidad)

| Lo que dice el prompt | Realidad en QA / repo |
|----------------------|------------------------|
| `8446 = Foundry+Redis validada` | El **puerto :8446 está DOWN**. No hay servicio golden escuchando ahí. |
| `8447 = capa cognitiva actual` | **Correcto**: `:8447` vivo, Redis Entra, WRITE PATH operativo. |
| Tomar implementación de 8446 | Significa el **código/paquete** `genesis_corp_8446.zip` = árbol local actual, **no** clonar el puerto 8446. |

```text
NO HACER:  copiar /opt/genesis-cognitive-8446 → 8447   (legacy caído / distinto)
SÍ HACER:  desplegar código golden (workspace/ZIP) EN puerto 8447
           preservando .env Redis + WRITE PATH
```

---

## 2. Arquitectura objetivo (obligatoria)

```text
                 ORQUESTADOR (INTOCABLE)
                     │
                     ▼
                POST /turn
                     │
          ┌──────────┴──────────┐
          │                     │
    context_info=true      question != null
          │                     │
          ▼                     ▼
     WRITE PATH             READ / NL PATH
          │                     │
          ▼                     ▼
 ContextPersistence        Foundry / azure_plan
    Service                    │
          │                     ▼
          ▼              get_customer_products (flag)
        Redis                   │
                                ▼
                       ProductContextService → Redis
```

### WRITE PATH (conservar — ya existe en 8447)

```text
context_info=true
→ validate context.data
→ ConversationGate (genesis:conv_lock:{id})
→ map_core_portfolio (determinista)
→ REPLACE + CAS expected_revision
→ session:{conversation_id}
→ customer:{customer_id}:snapshot
→ CONTEXT_LOADED | CONTEXT_REFRESHED
→ Foundry NO invocado
```

### READ PATH (desde código golden / flag)

```text
question
→ (flag=0) azure_plan + snapshot Redis   ← productivo actual
→ (flag=1) Foundry personal → get_customer_products → ProductContextService → Redis
→ RAG/Foundry KB solo conocimiento
```

---

## 3. Qué ya está en el código local (candidato)

| Componente | Estado |
|------------|--------|
| `ContextPersistenceService` | Sí — WRITE PATH |
| `map_core_portfolio` + CAS + Gate + Entra | Sí |
| `ProductContextService` + `get_customer_products` | Sí |
| `foundry_personal_agent` (flag OFF) | Sí |
| Fix compare TC personal (Full Car vs Joven) | Sí (unit tests OK; hotfix pendiente en QA) |
| Puerto / systemd 8447 | Conservar |

---

## 4. Procedimiento de despliegue (sin tocar :8446)

1. Backup local verificado ✅  
2. Backup remoto (automático en `deploy_8447.sh`)  
3. Rebuild ZIP desde workspace  
4. `deploy_ssh_password.py` → solo `:8447`  
5. Preservar `.env` (Redis Entra, FAQ, Foundry KB)  
6. `GENESIS_FOUNDRY_PRODUCT_TOOLS=0` hasta regresión  
7. Smoke: `/health`, `/ready`, `/ready/redis`, `context_info`, NL  
8. Opcional: flag=1 para READ Foundry tools  

---

## 5. Prohibiciones

- Reconstruir contexto desde Core/BUS/Foundry/RAG  
- Foundry en WRITE PATH  
- Patch/merge arbitrario del snapshot (usar REPLACE+CAS)  
- Fail-open a memoria si Redis cae  
- Alterar orquestador / WebSocket / frontend  
- `rm -rf` del legacy sin backup  
- Usar `instalador/genesis_corp_8447.zip` (2026-09-17) como golden  

---

## 6. Estado actual vs prompt “reemplazar por 8446”

El merge **ya está mayormente en el código** que se despliega a 8447.  
Lo que falta operacionalmente:

1. Confirmar hotfix compare TC en QA (o redeploy completo)  
2. Regresión WRITE PATH orquestador  
3. Activar `GENESIS_FOUNDRY_PRODUCT_TOOLS=1` solo cuando se quiera el READ Foundry  

**8446 puerto:** no se toca (y está caído).  
**8447:** sigue siendo el endpoint del orquestador.
