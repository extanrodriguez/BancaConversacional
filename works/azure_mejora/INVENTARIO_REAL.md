# Inventario real — azure_mejora (descubrimiento)

Fecha UTC: 2026-09-21. Especificación propuesta ≠ configuración aplicada.

## Alcance
- Checkout: `C:\NovusIntelligence\BancoSantaCruz\BancaConversacional`
- Backend protegido: `BSC.genesis.conversational.backend` (sin modificar)
- QA lectura: cliente `726588` · lab_fallback · sin PROD
- Entrada productiva: `POST /turn` en servicio cognitivo QA `:8447`

## Insumos locales
| Recurso | Ruta | Notas |
|---|---|---|
| fuentes/ | `works/azure_mejora/fuentes` (+ `works/insumos/BSC_Potenciacion_Lunes/fuentes`) | Guía textual, filas 344, base MD |
| insumos_derivados/ | `works/azure_mejora/insumos_derivados` | chunks/fichas QA, catálogo, Bindings verificados |
| guia/ | `works/azure_mejora/guia` | original.MD + evidencias_fix/; imágenes históricas en Downloads/paquete |
| Plan / config propuesta | `works/azure_mejora/config/configuracion_objetivo_qa.json` | PROPOSED_NOT_APPLIED |
| Prioridad 141 / regresión 95 | `works/azure_mejora/prioridades_141.json` | 69 No cumple + 72 parciales; 95 Cumple |

**Ausente en Downloads:** paquete separado `insumos_derivados/` con Matriz_KB_344_Normalizada / tools/actualizar_guia_fix del análisis. Se reconstruyó desde BSC_Potenciacion_Lunes + mapeo verificado en checkout.

## Azure / runtime (reportado vs confirmado)
| Recurso | Propuesta / reportado | Confirmado esta sesión | Permiso / acción |
|---|---|---|---|
| Cognitive QA UI | `http://20.127.25.24:8447/` | HTTP 200 `/` y `/pruebas` | Lectura OK |
| Redis | `bsc-cognitive-redis-qa.eastus.redis.azure.net:10000` | No inspeccionado (red privada) | Requiere VM/VPN autorizada |
| Search índice activo | discover | Desconocido sin CLI | Read Index |
| Índice candidato | `bsc-kb-qa-vnext-<fecha>-<hash>` | No creado | Contributor + apply autorizado |
| Foundry gpt-4o-mini | reutilizar | Desconocido sin sesión Azure | No cambiar hasta medir |
| MI / Entra | preservar | No ciclo de renovación medido | — |

## Código cognitivo relevante
| Capacidad | Ruta |
|---|---|
| /turn | `src/genesis_cognitive/demo/contract_inspector_app.py` |
| Mapper Core→snapshot | `src/genesis_cognitive/context/core_portfolio_mapper.py` |
| TurnPlan / ejecutor | `brain/plan_interpreter.py`, `plan_executor.py`, `grounded_executor.py` |
| FAQ / KB local | `router/faq_guardrail.py`, `rag/kb_package_ingest.py` |
| Ventana P12 | `context/upcoming_payment_window.py` |
| Oráculo | `scripts/potenciacion_eval.py` (`strict_v2.2`) |

## Cambios aplicados en esta sesión (locales)
1. Payoff: no sustituir capital por cancelación cuando `domestic == principal`.
2. Retrieval local: filtro de aplicabilidad producto (anti Platinum←Joven).
3. Bindings semánticos documentados y verificados contra mapper.
4. Estructura `fuentes/` / `insumos_derivados/` / `guia/` bajo `works/azure_mejora`.

## Reversión
- Revertir commits/archivos de `src/genesis_cognitive/**` y `scripts/**` afectados.
- No hay apply remoto de índice/Redis en esta sesión → nada que rollbackear en Azure.
- Guías/evidencias son aditivas bajo `works/`.
