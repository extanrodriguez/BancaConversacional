# BASELINE_Y_DIFERENCIAS

Generado: 2026-09-21T20:45:53.409572+00:00

Snapshot: `20260921T204551Z`

## Config QA efectiva

- `AZURE_SEARCH_INDEX` = `bsc-kb-qa-vnext-20260921`
- `AZURE_OPENAI_CHAT_DEPLOYMENT` = `gpt-6-astra`
- `GENESIS_AZURE_DEPLOYMENT` = `gpt-6-astra`
- `AZURE_OPENAI_DEPLOYMENT` = `gpt-6-astra`
- `GENESIS_SEMANTIC_MODE` = `azure_plan`
- `GENESIS_AZURE_BRAIN` = `1`
- `GENESIS_SEARCH_RETRIEVE` = `1`
- `GENESIS_SEARCH_RERANK_LOCAL` = ``

## Local vs QA (archivos cognitivos críticos)

| Archivo | Estado |
|---|---|
| `src/genesis_cognitive/brain/azure_plan_turn.py` | **DIVERGED** |
| `src/genesis_cognitive/brain/plan_executor.py` | **MATCH** |
| `src/genesis_cognitive/brain/plan_interpreter.py` | **MATCH** |
| `src/genesis_cognitive/brain/semantic_mode.py` | **MATCH** |
| `src/genesis_cognitive/brain/azure_plan_adapter.py` | **MATCH** |
| `src/genesis_cognitive/agents/agent_framework_turn_resolver.py` | **MATCH** |
| `src/genesis_cognitive/agents/semantic_verifier.py` | **MATCH** |
| `src/genesis_cognitive/rag/azure_search_retrieve.py` | **MATCH** |
| `src/genesis_cognitive/rag/grounding_verifier.py` | **MATCH** |
| `src/genesis_cognitive/router/field_guardrails.py` | **DIVERGED** |
| `src/genesis_cognitive/router/domain_classifier.py` | **MATCH** |
| `src/genesis_cognitive/demo/contract_inspector_app.py` | **DIVERGED** |

- MATCH: 9
- DIVERGED: 3

## Nota

Sin repositorio Git: versionado por snapshot SHA256 + copia en `works/recuperacion_integral/snapshots/`.
Promociones de ejemplos / ranking experimental: **pospuestas** durante P0.

## Post-fix institucional (misma sesión)

- Hotfix QA: `azure_plan_adapter` / `azure_plan_turn` / `azure_search_retrieve`
- Corpus: +3 docs `inst-vf01-*` (candidato → 222)
- Smoke: misión/visión recuperadas; ver `ENTREGA_RECUPERACION_INTEGRAL.md`
