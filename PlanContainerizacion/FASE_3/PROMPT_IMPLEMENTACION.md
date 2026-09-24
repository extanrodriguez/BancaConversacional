# Fase 3 — Prompt de implementación para Cursor

> Copia el bloque entre `--- INICIO PROMPT ---` y `--- FIN PROMPT ---`.

---

## --- INICIO PROMPT ---

Implementa la **Fase 3 de containerización**: hardening de producción para Genesis Cognitive en Azure.

### Prerrequisitos

- Fase 2 desplegada en QA con smoke verde
- `PlanContainerizacion/FASE_2/RUNBOOK.md` operativo
- Acceso a subscription `871a5b90-0204-450e-b968-3190e9143faf`

### Objetivos

1. **Application Gateway + WAF** delante de Container Apps prod
2. **Application Insights** con middleware de telemetría
3. **Alertas** latencia, errores, OpenAI 429
4. **Circuit breaker** en llamadas Azure OpenAI
5. **Rate limiting** por customer_id
6. **Entornos** dev / qa / prod aislados
7. **DR** documentado (Redis backup, rollback)

### Tareas

#### T1 — Application Gateway + WAF

Crear `PlanContainerizacion/FASE_3/appgateway.bicep` (o módulo Terraform):

- SKU WAF_v2
- Backend pool → FQDN Container App prod
- Health probe `/health`
- Listener HTTPS con certificado (Key Vault reference o upload PFX)
- WAF mode Prevention, OWASP 3.2
- Reglas custom: block paths no `/turn`, `/inspect`, `/health`, `/pruebas` (prod: deshabilitar `/pruebas`)
- IP restriction: solo rangos VPN corporativa documentados

#### T2 — Application Insights

En `contract_inspector_app.py` o middleware dedicado `src/genesis_cognitive/demo/telemetry_middleware.py`:

```python
# Instrumentar:
# - request duration ms
# - route path
# - inference_count (header o body response)
# - customer_id (hash, no PII raw)
# - fastpath hit (bool)
```

Dependencia: `opencensus-ext-fastapi` o `azure-monitor-opentelemetry`.

Variables:
- `APPLICATIONINSIGHTS_CONNECTION_STRING`

#### T3 — Dashboard y alertas

Crear `PlanContainerizacion/FASE_3/dashboard.json` (ARM export) con:
- Request rate
- p50/p95 latency
- 5xx count
- OpenAI errors
- Replica count ACA

Alertas (`PlanContainerizacion/FASE_3/alerts.bicep`):
- p95 > 10s por 5 min → warning
- 5xx rate > 1% → critical
- OpenAI 429 count > 10/min → scale down + notify

#### T4 — Circuit breaker OpenAI

En wrapper de cliente OpenAI / agent framework:

```python
# Estados: CLOSED, OPEN, HALF_OPEN
# Tras N fallos consecutivos (429/503/timeout): OPEN 30s
# Respuesta degradada: mensaje amigable sin inventar datos bancarios
```

Archivo sugerido: `src/genesis_cognitive/resilience/openai_circuit_breaker.py`

Tests unitarios con mocks.

#### T5 — Rate limiting

Opción A (preferida prod): reglas AGW / WAF rate limit por IP  
Opción B: middleware FastAPI con Redis contador `ratelimit:{customer_id}` TTL 60s, max 30 req/min

No bloquear `/health`.

#### T6 — Entornos aislados

| Env | Container App | minReplicas | GENESIS_SERVE_UI |
|-----|---------------|-------------|------------------|
| dev | genesis-api-dev | 1 | true |
| qa | genesis-api-qa | 2 | true |
| prod | genesis-api | 3 | false |

Bicep parametrizado o 3 deployments del mismo template.

#### T7 — Seguridad

- Deshabilitar `/pruebas` en prod (`GENESIS_SERVE_UI=false` + middleware 404)
- Headers seguridad: `X-Content-Type-Options`, `X-Frame-Options`
- Audit log de turns (sin PII completa): customer_id hash, intent, latency

#### T8 — DR y backup

Documentar en `PlanContainerizacion/FASE_3/DR.md`:
- Redis Premium con geo-replication (opcional)
- Export ACR images tagged
- Procedimiento failover DNS AGW
- RPO/RTO objetivos

#### T9 — Cutover VM → Prod

Script `PlanContainerizacion/FASE_3/cutover_checklist.md`:
- [ ] Smoke prod 17/17
- [ ] Escenarios routing CI
- [ ] WAF pen test básico
- [ ] Rollback VM 8446 documentado 72h
- [ ] Comunicación stakeholders

### Restricciones

- No inventar datos bancarios en modo degradado
- Cumplir fast-path existente (no regresión latencia)
- Español en mensajes al cliente
- No commitear certificados ni connection strings

### Criterios de aceptación

1. Tráfico entra solo por App Gateway en prod
2. App Insights muestra latencia e inference_count
3. Alerta de prueba dispara correctamente
4. Circuit breaker abre tras 5 fallos simulados
5. Rate limit bloquea burst > umbral
6. `/pruebas` 404 en prod
7. DR doc completo

### Entregables

- Bicep/ARM App Gateway + alerts
- Middleware telemetría + circuit breaker en código
- Dashboard + DR.md + cutover_checklist.md
- Resumen final arquitectura prod

## --- FIN PROMPT ---
