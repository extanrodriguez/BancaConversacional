# Arquitectura objetivo

## Diagrama lógico (estado final — Fase 3)

```text
                    ┌─────────────────────────────┐
                    │   Orquestador / Canales     │
                    │   (Banca Santa Cruz)        │
                    └──────────────┬──────────────┘
                                   │ HTTPS
                    ┌──────────────▼──────────────┐
                    │  Application Gateway + WAF  │
                    │  TLS, rate limit, IP allow  │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────▼────────────────────────┐
          │           Azure Container Apps Environment         │
          │  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
          │  │ api-rev │  │ api-rev │  │ api-rev │  (N≥2)    │
          │  │   #1    │  │   #2    │  │   #3    │           │
          │  └────┬────┘  └────┬────┘  └────┬────┘           │
          │       └─────────────┼─────────────┘                │
          │                     │                              │
          │              autoescala HTTP/CPU                   │
          └─────────────────────┼──────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
 Azure Cache              Azure Key Vault         Azure OpenAI
 for Redis                 (secrets, MI)           (gpt-4o-mini)
 session:*                  AZURE_OPENAI_*         eastus
 customer:*snapshot
        │
        ▼
 Azure AI Search (RAG)
 genesis-search-lab
```

## Principios de diseño

1. **Modelo fuera del contenedor** — Azure OpenAI es servicio gestionado; el contenedor solo orquesta prompts y guardrails.
2. **Estado en Redis** — Obligatorio antes de N réplicas; hoy `ReactiveSessionStore` es in-memory.
3. **Imagen inmutable** — Tag por commit SHA; no pip install en producción.
4. **Fast-path primero** — Guardrails deterministas evitan LLM (~10 ms vs ~6 s).
5. **Health/readiness** — `/health` para liveness; readiness opcional con ping OpenAI.
6. **Secrets en Key Vault** — Nunca en git ni en la imagen.

## Componentes del contenedor API

| Capa | Responsabilidad |
|------|-----------------|
| `uvicorn` + FastAPI | HTTP, `/turn`, `/inspect`, `/health`, `/pruebas` |
| `field_guardrails` | Fast-path sin LLM (saldo, préstamo, TC, transferencias) |
| Capa 0/1 | Clasificadores dominio/producto (solo si fast-path no aplica) |
| Proposer/Verifier | Interpretación LLM |
| `ReactiveSessionStore` → Redis | Sesión, pending, last_resolved, snapshot TTL |

## Límites de escala

| Recurso | Límite práctico |
|---------|-----------------|
| Réplicas API | Limitado por TPM/RPM de Azure OpenAI |
| Redis | ~10k sesiones concurrentes (Basic C1 suficiente para MVP) |
| Latencia fast-path | < 100 ms p95 |
| Latencia LLM | 2–8 s (5–7 llamadas en peor caso; reducir ampliando fast-path) |

## Entornos

| Entorno | Compute | URL ejemplo |
|---------|---------|-------------|
| local | Docker Compose | http://127.0.0.1:8445 |
| corp-lab | VM + Docker / ACA dev | http://20.127.25.24:8446 |
| qa | Container Apps | https://genesis-qa.{domain} |
| prod | Container Apps + App Gateway | https://genesis.{domain} |

## Dependencias Azure existentes (no recrear)

- Subscription: `871a5b90-0204-450e-b968-3190e9143faf`
- RG: `rg-genesis-cognitive-mvp-eus`
- OpenAI: `aoai-genesis-871a5b`
- AI Search: `genesis-search-lab`
