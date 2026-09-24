# Checklist global — Containerización Genesis

## Pre-requisitos

- [ ] Azure CLI + Docker Desktop instalados
- [ ] Acceso a subscription `871a5b90-...`
- [ ] Permisos en RG `rg-genesis-cognitive-mvp-eus`
- [ ] API keys OpenAI y Search en Key Vault o .env local (no en git)
- [ ] Smoke local pasa: `python Test_local/run_mvp.py --smoke`

---

## Fase 1 — Docker + Redis + VM

- [ ] `Dockerfile` en raíz del repo
- [ ] `docker-compose.yml` (api + redis)
- [ ] `RedisSessionStore` implementado y conectado vía `GENESIS_REDIS_URL`
- [ ] Fallback in-memory solo si `GENESIS_REDIS_URL` vacío (dev)
- [ ] `.dockerignore` configurado
- [ ] Imagen build local OK: `docker build -t genesis-api:local .`
- [ ] Compose up OK: `docker compose up`
- [ ] `/health` responde 200
- [ ] `/pruebas` accesible
- [ ] Smoke contra contenedor: `GENESIS_ENDPOINT=http://127.0.0.1:8445 python Test_local/run_mvp.py --smoke`
- [ ] GitHub Actions / Azure DevOps: job `build-and-test`
- [ ] Documentado en `PlanContainerizacion/FASE_1/README.md`
- [ ] Deploy en VM corporativa con compose (paralelo a systemd 8446)

---

## Fase 2 — Container Apps + ACR

- [ ] Azure Container Registry creado
- [ ] Imagen push: `{acr}.azurecr.io/genesis-api:{sha}`
- [ ] Azure Cache for Redis provisionado
- [ ] Key Vault con secretos; Managed Identity en ACA
- [ ] Container App con minReplicas=2, maxReplicas=10
- [ ] Variables de entorno / secret refs configuradas
- [ ] Ingress HTTPS externo o interno según red corporativa
- [ ] Pipeline: build → push → `az containerapp update`
- [ ] Smoke post-deploy remoto automatizado
- [ ] Rollback documentado (revision anterior)
- [ ] systemd 8446 deprecado tras validación QA

---

## Fase 3 — Producción

- [ ] Application Gateway + WAF delante de ACA
- [ ] Certificado TLS corporativo
- [ ] NSG: solo IPs/VPN autorizadas
- [ ] App Insights: métricas `total_request_ms`, `inference_count`
- [ ] Alertas: p95 > 10s, error rate > 1%, OpenAI 429
- [ ] Autoescala rules: concurrent requests > 50 → +1 replica
- [ ] Rate limit por customer_id en gateway
- [ ] Entornos dev / qa / prod con revisiones separadas
- [ ] Runbook incidentes + rollback < 5 min
- [ ] DR: backup Redis, multi-AZ si aplica

---

## Calidad conversacional (paralelo)

- [ ] Fast-path cubre > 80% consultas MVP (Excel)
- [ ] Sin respuestas "None" en saldos
- [ ] Tipo corriente sin producto → mensaje claro
- [ ] Producto inexistente → "no existe en tu portafolio"
- [ ] `Test_local/data/escenarios_routing.json` en CI
