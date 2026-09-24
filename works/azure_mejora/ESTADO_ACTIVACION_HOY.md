# ESTADO_ACTIVACION_HOY

Fecha: 2026-09-21. Checkout local sin git (manifiesto SHA). Backend externo intacto.

## Suites

| Corrida | Resultado |
|---|---|
| Grupo representativo | **8/8 PASS** (`suite_representativa_20260921/`) |
| Subset 141 (20 casos, local `:8445`) | run `20260921T092444Z_59eeca0f`: 13 PASS / 5 PARTIAL / 2 FAIL — **no cierra** los 141 |
| 141 completos + 95 regresión | **Pendiente** |

## Estado de entrega

**`CANDIDATO_LOCAL_PARCIAL`** con evidencia `LOCAL_AZURE_REAL_VERIFICADO` en probe + Search cableado + grupo representativo. No es QA completa ni aceptación de la guía 236.


## Qué funciona desde esta PC

| Capacidad | Evidencia |
|---|---|
| Azure OpenAI `testbsc0001` / deployment `gpt-4o-mini` | `/turn` con `inference_count≥1`, calls proposer/verifier |
| Azure AI Search índice `bsc-kb-conocimiento` (980 docs) | Consultas híbridas reales; evidencia `source=azure_search` en misión/Joven |
| Capa cognitiva local `POST /turn` | TestClient + servidor `:8445` (memoria) |
| Probe reconciliado (2 preguntas) | `works/azure_mejora/probe_reconcile_20260921/` — reply completo (T1 len=1074; el [:500] era del runner) |
| Grupo representativo guía | **8/8 PASS** en `suite_representativa_20260921/` |

## Límites efectivos (declarados)

| Pieza | Etiqueta |
|---|---|
| Sesión | **MEMORIA_SIMULADA** — Redis QA TCP inalcanzable |
| Portafolio | **CONTEXTO_SINTETICO** `qa_726588_contract_demo.json` / customer `726588` |
| Search en definición «saldo disponible» | Hits del índice son filas de matriz → filtrados; cae a **glosario local** |
| structural_repair en vencimientos | Transporte OK; verifier a veces CLARIFICATION vacía; reparación determinista P12 etiquetada (no éxito semántico LLM puro) |
| Suites 141/95 completas | En curso / pendiente sobre el mismo build local; no cerradas |
| Redis/Entra, UI orquestada, VM QA | **Pendiente** acceso autorizado VM |

## Correcciones aplicadas hoy (candidato local)

1. Glosario «qué significa el saldo disponible» (artículo opcional); no leer saldo personal.
2. Mixta definición+saldo → no atajo glosario único (`open_mixed_glossary_personal`).
3. Pending personal no consume definiciones/glosario.
4. P12 / `is_upcoming_payment_scan_question`: «se me vence», «estos días».
5. Adaptador `azure_search_retrieve` + cableado en ejecutor institucional/catálogo (`GENESIS_SEARCH_RETRIEVE=1`).
6. Filtro de contaminación matriz en Search/KB intent (sin borrar índice).
7. Recuperación de proposal inicial solo si cubre vencimientos; si no → structural_repair.

## Build

- `cognitive_py_sha256_prefix`: ver `probe_reconcile_full.json` / manifiesto
- Flags: `GENESIS_SEMANTIC_MODE=azure_plan`, `GENESIS_AZURE_BRAIN=1`, `GENESIS_SESSION_BACKEND=memory`, `GENESIS_SEARCH_RETRIEVE=1`
- Puerto local preparado: `8445` vía `scripts/run_contract_inspector.py`

## Siguiente

Ver `BRECHAS_PENDIENTES.md`. Despliegue QA solo del mismo artefacto tras autorización VM.
