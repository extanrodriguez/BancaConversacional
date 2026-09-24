# Diagnóstico: contexto en `/pruebas` QA — Presentation Product vs lab

Fecha: 2026-09-19. Host cognitivo: `20.127.25.24:8447` (`vm-test002-genesis`).

## Estado del código (desplegado en :8447)

`POST /orch/context` prioriza **Presentation Product** (mismo template que el orch .NET):

`GENESIS_PRESENTATION_PRODUCT_URL_TEMPLATE=https://apigateway-gen.qa.bsc.com.do/api/presentation/product/{customerId}`

Orden: Presentation Product → Core WS legacy → lab (si `allow_lab_fallback`).

| Badge | Significado |
|---|---|
| **QA · Presentation Product real → Redis** | Portafolio vivo del API gateway QA. |
| **QA · Core WS/HTTP real → Redis** | Fallback legacy. |
| **QA · datos LAB** | Presentation y Core fallaron. |

UI `/pruebas` usa `/turn` local tras cargar sesión (no depende de mcp-bridge `:8080`).

## Bloqueo actual en la VM (verificado 2026-09-19)

Desde `20.127.25.24`:

- `resolvectl query apigateway-gen.qa.bsc.com.do` → **not found** (NXDOMAIN también vía 8.8.8.8)
- Core WS `api-genesis.dev.bsc.com.do` → **not found**
- `172.27.4.20:4430/4428/4429` (banking on‑prem del variable group) → **timeout**
- Por tanto `allow_lab_fallback=false` → **502** `context_bootstrap_failed` / `presentation_product_unreachable`

El orquestador .NET on‑prem (otra red/DNS privado) sí puede resolver Presentation Product; esta VM Azure **no** tiene el Private DNS / peering hacia ese gateway.

## Qué falta de infra

1. Enlazar Private DNS Zone de `bsc.com.do` (o el FQDN del gateway) a la VNet de `vm-test002-genesis`, **o**
2. Exponer Presentation Product en un host/IP alcanzable desde la VM y apuntar `GENESIS_PRESENTATION_PRODUCT_URL_TEMPLATE`, **o**
3. Entrada `/etc/hosts` solo si hay IP fija autorizada.

Luego: login en `/pruebas` con `726588` + «Exigir Presentation Product» → badge **Presentation Product real → Redis**.

## Puertos en la misma VM (no son el orch .NET)

| Puerto | Proceso |
|---|---|
| 8447 | cognitiva QA (este servicio) |
| 8080 | `mcp-bridge` (no `BancaConversacional.Api`) |
| 8000 | `genesis-rag-api` |

`PrivateRagEndpoint` del variable group (`:8000/chat/front`) apunta al RAG, no al orquestador .NET.
