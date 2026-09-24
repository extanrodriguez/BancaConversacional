# Cutover — VM 8446 → Producción ACA + App Gateway

## Pre-cutover (T-7 días)

- [ ] Fase 2 QA estable, smoke 17/17 diario
- [ ] Escenarios `Test_local/data/escenarios_routing.json` en CI
- [ ] App Gateway + WAF desplegado apuntando a ACA prod
- [ ] Certificado TLS instalado
- [ ] IP allowlist corporativa aplicada
- [ ] `/pruebas` deshabilitado en prod
- [ ] Runbook y DR revisados con operaciones

## Pre-cutover (T-1 día)

- [ ] Congelar deploys excepto hotfix
- [ ] Backup Redis export
- [ ] Tag imagen `release-YYYY-MM-DD` en ACR
- [ ] VM 8446 documentada como fallback

## Día cutover

| Hora | Acción |
|------|--------|
| T+0 | Smoke prod vía AGW (canary interno) |
| T+15m | Cambiar DNS / routing orquestador 10% → AGW |
| T+30m | Monitoreo App Insights: 5xx, p95 |
| T+1h | 50% tráfico |
| T+2h | 100% tráfico |
| T+4h | VM 8446 en standby (no apagar) |
| T+48h | Apagar systemd 8446 si sin incidentes |

## Rollback inmediato

1. Revertir DNS / routing orquestador → VM 8446
2. O activar revisión ACA anterior (RUNBOOK)
3. Comunicar a canales

## Post-cutover

- [ ] Retrospectiva
- [ ] Actualizar documentación operativa
- [ ] Archivar deploy VM como contingencia 30 días
