# DIAGNOSTICO_CHECKOUT.md — Incremento A

Fecha UTC: 20260921T191806Z (baseline) · Actualizado post-fix.

## Estado verificado

| Elemento | Evidencia |
|---|---|
| `bsc-kb-conocimiento` | 980 docs — **intacto** |
| `bsc-kb-qa-vnext-20260921` | 196 docs — **activo en VM** |
| `AZURE_SEARCH_INDEX` VM | `bsc-kb-qa-vnext-20260921` |
| Redis Entra | ready ok session+lock ping |
| `/turn` deployment | `AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o-mini` en `testbsc0001` |
| `gpt-6-astra` en endpoint `/turn` | **NotFound** → `PENDIENTE_DEPLOYMENT_GPT6` |
| Foundry playground | Modelo gpt-6-astra ≠ servicio `:8447` |
| Foundry Search tool | Reportado en UI como `bsc-kb-conocimiento` → `PENDIENTE_FOUNDRY_INDEX` |

Fuente: `works/mejora_supervisada/evidencia_baseline/baseline.json`

## Hallazgos a–j

| ID | Hallazgo | Estado checkout | Acción |
|---|---|---|---|
| a | Promote por votos sin aprobación | **Confirmado** en `scripts/promote_learning_expressions.py` (antes: `--apply` sin approval) | **Corregido**: exige `--approved-json` |
| b | Re-run infla votos | **Confirmado** en `feedback_store.record_feedback` ON CONFLICT votes+1 sin dedup | **Corregido**: `feedback_dedup` + idempotencia |
| c | Retry Search quita filtros | **Confirmado** en `azure_search_retrieve.py` (`body.pop("filter")`) | **Corregido**: error tipado `http_*_filter_required`; `filter_stripped=false` |
| d | Filtro producto solo content | Parcialmente mitigado (title/product/content + document_types) | **Mejorado**; docs generales vía tipos sin producto |
| e | Grounding solo mención producto | **Confirmado** en verifier v1 | **Corregido**: `attribute` + `ATTRIBUTE_MARKERS` |
| f | Compare parcial como completo | **Confirmado** (`status=available` con 1 producto) | **Corregido**: `status=partial` + `compare_completeness` |
| g | Truncado 1200 / 320 en compare | **Confirmado** | **Corregido**: content budget 3200; compare clip 2800 |
| h | Rerank léxico vs Semantic Ranker | **Confirmado** (bonos locales) | **Corregido**: flag `GENESIS_SEARCH_RERANK_LOCAL`; label `local_lexical_bonus` |
| i | Fastpath omite tareas compuestas | No reescrito en esta sesión | **Pendiente B3 ampliado** (solo registro) |
| j | Modelo declarado ≠ efectivo | Foundry gpt-6-astra vs `/turn` gpt-4o-mini | **Documentado**; `semantic_mode` lee también `AZURE_OPENAI_CHAT_DEPLOYMENT` |

## Archivos tocados

- `src/genesis_cognitive/rag/azure_search_retrieve.py`
- `src/genesis_cognitive/rag/grounding_verifier.py`
- `src/genesis_cognitive/brain/plan_executor.py`
- `src/genesis_cognitive/brain/semantic_mode.py`
- `src/genesis_cognitive/learning/feedback_store.py`
- `scripts/promote_learning_expressions.py`
- `tests/unit/test_incremento_a_filters_grounding_promote.py` (4 passed)
