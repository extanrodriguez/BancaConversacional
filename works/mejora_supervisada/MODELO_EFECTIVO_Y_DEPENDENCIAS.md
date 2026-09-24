# MODELO_EFECTIVO_Y_DEPENDENCIAS.md

Fecha: 2026-09-21

## Capas distintas (no mezclar)

| Capa | Provider / recurso | Deployment / modelo | Search index | Estado |
|---|---|---|---|---|
| POST `/turn` QA `:8447` | Azure OpenAI `testbsc0001` | **`gpt-6-astra`** (audit `deployment`) | `bsc-kb-qa-vnext-20260921` (**219** docs post-C) | **VALIDADO_QA** (inestable en algunas queries) |
| Foundry Agent playground `genesis-kb-agent-poc` | Foundry project `genesis-rag-poc` | **`gpt-6-astra`** (UI) | candidato (UI) | Playground ≠ orquestador |
| Cursor IDE | n/a | n/a | n/a | No atiende `/turn` |

## Probe endpoint `/turn` (testbsc0001)

| Deployment | Resultado |
|---|---|
| gpt-6-astra | OK en audit; a veces `ModelInvocationError` / `model_resolve_full_exhausted` |
| gpt-4o-mini | Disponible como fallback potencial |

Conclusión: GPT-6 **sí** atiende `/turn`; monitorear errores de invocación en smoke beneficio/tasa.

## Env efectivo VM (sanitizado)

```
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-6-astra   # (o GENESIS_AZURE_DEPLOYMENT equivalente)
AZURE_SEARCH_INDEX=bsc-kb-qa-vnext-20260921
GENESIS_SEMANTIC_MODE=azure_plan
GENESIS_AZURE_BRAIN=1
GENESIS_SEARCH_RETRIEVE=1
```

`azure_deployment_name()` ahora resuelve también `AZURE_OPENAI_CHAT_DEPLOYMENT`.

## Dependencias

| Dependencia | Estado |
|---|---|
| Redis Entra MI | OK (session+lock) |
| Search candidato | OK 196 docs |
| Índice viejo | Conservado 980 (rollback) |
| Entra token renewal ciclo largo | Pendiente operativo (no bloquea A) |

## Pendientes

- `PENDIENTE_DEPLOYMENT_GPT6`: ~~crear/enganchar `gpt-6-astra`~~ → **HECHO 2026-09-21** (`AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-6-astra` en `:8447`)
- `PENDIENTE_FOUNDRY_INDEX`: apuntar tool Search del agente a `bsc-kb-qa-vnext-20260921`
