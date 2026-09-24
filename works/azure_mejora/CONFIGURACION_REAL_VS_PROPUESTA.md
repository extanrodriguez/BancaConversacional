# Configuración real vs propuesta

Fuente propuesta: `config/configuracion_objetivo_qa.json` (PROPOSED_NOT_APPLIED).

| Clave propuesta | Equivalente real actual | Estado |
|---|---|---|
| redis.host_reported | Env/MI del servicio en VM (no leído desde PC) | Desconocido en PC; preservar |
| redis.snapshot_volatile_staleness_qa_trial_s=60 | Clasificación en código de frescura existente | No aplicado como refresh Core |
| redis.portfolio_staleness_qa_trial_s=600 | Idem | No aplicado |
| document_cache.enabled_initially=false | Sin caché documental global personal | Cumple (sigue false) |
| chunking 600/80 | Corpus paquete ya fragmentado; eval local pendiente tabla 400/600/800 | Provisional 600 |
| search.candidate_index_pattern | No creado | Pendiente autorización |
| search.k=50 top=5 | `local_retrieve` léxico local; Azure híbrido si índice activo | Parcial |
| context.recent_exchanges_initial=6 | Sesión Redis / history en /turn | Verificar en runtime |
| model.structured_outputs TurnPlan | `azure_plan_adapter` + schema | En uso |
| inference max 2 | Atajos deterministas + azure_plan | Parcialmente cumplido |
| temperature 0 / 0.2 | Depende cliente Foundry | No verificado |

**Conclusión:** la propuesta guía parámetros QA; no se aplicó CONFIG SET Redis, ni se borró índice, ni se tocó PROD.
