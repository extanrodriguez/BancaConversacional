# Estado: mapeos, resolución, ejecución, estado, corpus

Fecha: 2026-09-21. Tras prueba de acceso Azure desde esta PC.

## Dependencias (ver `DEPENDENCIAS_REAL_VS_SIMULADA.md`)

| Pieza | Etiqueta |
|---|---|
| Interpretación open-language | **MODELO_REAL** (`gpt-4o-mini`, proposer+verifier) |
| Contexto portafolio | **CONTEXTO_SINTETICO** lab `qa_726588_contract_demo.json` |
| Sesión | **MEMORIA_SIMULADA** (Redis QA **PENDIENTE**) |
| Azure Search remoto | Alcanzable (980 docs); **no cableado en este /turn** |
| FAQ / glosario / chunks paquete | **LOCAL** |

## Mapeos

- `Bindings_Semanticos_API.json`: verificados contra `core_portfolio_mapper.py` (sin cambios de contrato Core).
- Glosario «qué significa **el** saldo disponible…»:
  - Antes: atajo `kb_catalog_define` → lectura personal / matriz simulada `RD$34,569.85`.
  - Ahora: atajo `kb_glossary_available` → `institutional/define/glossary/available_balance`.

## Resolución

- `is_unequivocal_structured_shortcut`: glosario saldo disponible no usa catálogo por «cuenta de ahorros».
- `interpret_turn_plan`: regex con artículo opcional; no crea `available` personal si hay definición.

## Ejecución

- `_faq_text`: prioriza `kb_glossary_local_v31.json` ante definición de saldo disponible.
- `faq_guardrail._definition_hit_is_relevant`: rechaza filas de matriz / «terminada en ####» + montos.
- `kb_intent_resolver`: no indexa secciones `Fila N —` ni respuestas personales simuladas del MD en `GENESIS_KB_DIR=Knowledge_Base`.

## Estado de sesión

- Schema local: `pending_tasks`, `compare_set`, `last_knowledge_topic` (memory).
- Persistencia Redis Entra QA: **PENDIENTE** (TCP inalcanzable); sin cambios de red.

## Corpus

- Candidato local: `bsc-kb-2026-09-19-candidate-1` + paquete potenciación.
- Contaminación detectada: `Knowledge_Base/BASE_CONOCIMIENTO_IA_VF01.md` incluye respuestas esperadas de prueba como si fueran conocimiento. Filtradas en el resolver; no se presentan como mejora LLM.
- Azure Search índice `bsc-kb-conocimiento`: reachable; reindex/sync **no ejecutado**.

## Evidencia /turn (no simulada)

1. Paráfrasis vencimientos → `inference_count=2`, deployment real, ventana 30d America/Santo_Domingo.
2. Definición saldo disponible → glosario local correcto (sin montos de matriz).

No se acreditan atajos deterministas como comprensión del modelo.
