# Dependencias REAL vs SIMULADA

Fecha de prueba: 2026-09-21 (PC local). Sin cambios a recursos Azure ni políticas de red.
Cliente/auth: deployment existente `testbsc0001` / `gpt-4o-mini` + API key de `.env`.

## Resumen

| Dependencia | Estado desde esta PC | Uso en `/turn` local de esta corrida |
|---|---|---|
| Azure OpenAI (chat) | **REAL_OK** | Inferencia real (`resolve_full` proposer+verifier) |
| Azure AI Search | **REAL_OK** (980 docs en `bsc-kb-conocimiento`) | **No usado en el turno**; retrieval = KB local |
| Redis QA remoto | **UNREACHABLE_PENDING** (TCP timeout) | Sesión **SIMULADA** en memoria |
| Core / Presentation Product | No forzado | Contexto **sintético** lab `qa_726588_contract_demo.json` |
| FAQ / chunks KB paquete | Local en disco | **REAL local** (`GENESIS_KB_PACKAGE_ROOT`) |
| Respuestas del modelo | — | **No simuladas** |

## Evidencia de conectividad

Archivo: `works/azure_mejora/DEPENDENCIAS_REAL_VS_SIMULADO.json`

- AOAI: completion real 2721 ms; JSON de comprensión de paráfrasis de vencimientos.
- Search: `GET …/docs/$count` → HTTP 200, count=980.
- Redis QA: marcado pendiente (inalcanzable); no se alteró red ni políticas.

## Evidencia POST `/turn` (capa cognitiva local)

Archivo: `works/azure_mejora/probe_turn_real/turn_real_result.json`

Configuración efectiva:

- `GENESIS_SEMANTIC_MODE=azure_plan`
- `GENESIS_AZURE_BRAIN=1`
- `GENESIS_SESSION_BACKEND=memory` (Redis pendiente)
- Contexto: sintético lab, `customer_id=726588`
- Conocimiento: paquete local `works/insumos/BSC_Potenciacion_Lunes`

### Turno 1 — interpretación con modelo REAL

Pregunta (paráfrasis abierta): *«Oye, se me vence algo pronto?…»*

- HTTP 200, ~5792 ms
- `brain_source=structural_repair` tras `resolve_full`
- `inference_count=2` (proposer 3345 ms + verifier 2285 ms, deployment `gpt-4o-mini`)
- `failed_model_attempts=0`
- Respuesta grounded con ventana America/Santo_Domingo 30d
- **No es respuesta simulada**

### Turno 2 — glosario local (sin inferencia; corregido)

Pregunta: *«Qué significa el saldo disponible…»*

- Tras fix de mapeo/ejecución: `shortcut:kb_glossary_available`, respuesta de `kb_glossary_local_v31.json`
- Antes contaminaba con fila de matriz simulada (`RD$34,569.85`) vía `GENESIS_KB_DIR=Knowledge_Base`
- Etiqueta: **LOCAL_DETERMINISTA** (no comprensión LLM)

## Etiquetas obligatorias para trabajo posterior

- Interpretación / comprensión: **MODELO_REAL** cuando `inference_count>0` y hay `calls` a Azure.
- Atajos / FAQ / repair determinista: **LOCAL_DETERMINISTA** (no acreditar como comprensión LLM).
- Snapshot portafolio en esta PC: **CONTEXTO_SINTETICO**.
- Sesión: **MEMORIA_SIMULADA** hasta que Redis QA sea alcanzable.
- Search remoto: alcanzable, pero indexación/uso en pipeline de turno = **PENDIENTE de cableado en corrida** si el turno usa solo `local_retrieve`.
- Redis remoto: **PENDIENTE**.

## Qué no se hizo

- No se cambiaron recursos Azure, NSG, DNS ni políticas.
- No se redeployó `:8447`.
- No se presentaron respuestas mock como mejoras.
