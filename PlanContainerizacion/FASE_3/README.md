# Fase 3 — Producción, HA, observabilidad y seguridad

**Duración:** continuo (post go-live ACA)  
**Objetivo:** Endurecer el despliegue para producción bancaria con **Application Gateway + WAF**, autoescala fina, **Application Insights**, circuit breaker, rate limiting y entornos aislados dev/qa/prod.

## Prerrequisitos

- [ ] Fase 2 en QA estable ≥ 2 semanas
- [ ] Smoke y escenarios routing en CI
- [ ] Runbook Fase 2 probado (rollback)
- [ ] Aprobación seguridad / red corporativa

## Componentes adicionales

| Componente | Propósito |
|------------|-----------|
| Application Gateway v2 + WAF | TLS corporativo, IP allowlist, OWASP |
| Application Insights | Trazas, métricas p95, alertas |
| Azure Monitor Alerts | Latencia, 5xx, OpenAI 429 |
| Circuit breaker (httpx) | Degradar gracefully si OpenAI cae |
| Rate limit | Por customer_id / IP en gateway |
| Entornos separados | dev / qa / prod (3 CAE o 3 apps) |

## Arquitectura Fase 3

Ver diagrama completo en [00_ARQUITECTURA_OBJETIVO.md](../00_ARQUITECTURA_OBJETIVO.md).

```text
Internet / VPN corporativa
        │
        ▼
Application Gateway (WAF, TLS *.bancosantacruz.com)
        │
        ▼
Container Apps (prod) min=3 max=20
        │
   ┌────┴────┬──────────────┐
   ▼         ▼              ▼
 Redis    Key Vault    App Insights
 (Premium)              + Alerts
```

## SLOs objetivo

| Métrica | Objetivo |
|---------|----------|
| Disponibilidad | 99.5% mensual |
| Fast-path p95 | < 100 ms |
| LLM p95 | < 8 s |
| Error rate 5xx | < 0.5% |
| Rollback | < 5 min |

## Entregables

1. Bicep/Terraform módulo App Gateway
2. App Insights instrumentado en FastAPI middleware
3. Dashboard Azure Monitor
4. Alertas Pager/email
5. Circuit breaker en cliente OpenAI
6. Documentación DR y backup Redis
7. Pen test checklist (WAF rules)

## Cutover producción

1. Blue/green: nueva revisión ACA detrás de AGW backend pool B
2. Smoke canary 5% tráfico
3. Switch 100% → desactivar VM 8446
4. Monitoreo 48 h
