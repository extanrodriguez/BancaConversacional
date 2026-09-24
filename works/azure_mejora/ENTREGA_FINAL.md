# ENTREGA FINAL — Mejora cognitiva Azure (en curso)

Fecha UTC: 2026-09-21

## Estado
Implementación local iniciada según `Prompt_Cursor_Mejora_Azure_Cognitiva.md`.  
**No** se aplicaron cambios remotos Redis/Search/Foundry/PROD.  
Backend externo **intacto**. Cliente QA `726588` lectura.

## Insumos
| Carpeta | Uso |
|---|---|
| `works/azure_mejora/fuentes/` | Fuentes del paquete Potenciación |
| `works/azure_mejora/insumos_derivados/` | KB chunks/fichas + Bindings verificados |
| `works/azure_mejora/guia/` | Original + semilla fix 236 + evidencias_fix/ |

Paquete `insumos_derivados/` del análisis (Matriz_KB_344 completa / tools actualizar_guia) **no estaba en Downloads**; se reconstruyó lo esencial desde BSC_Potenciacion_Lunes + mapper del checkout.

## Correcciones de código (capa cognitiva)
1. **Payoff ≠ principal** cuando `domesticCurrencyBalance == currentBalance` → `payoff_amount=None` (PARTIAL honesto).
2. **Retrieval local** con filtro producto (evita Platinum←Joven en `local_retrieve`).
3. **Bindings_Semanticos_API.json** verificados contra `core_portfolio_mapper.py`.
4. Conservados: ventana P12, contraste de atributos, audit vs texto cliente (strict-v2.2 previa).

## Priorización guía
- 141 históricos fallidos/parciales → `prioridades_141.json`
- 95 Cumple → regresión obligatoria
- Semilla fix: `guia/Guia_con_fix_SEED.MD` (NOT_EXECUTED / PENDING_UI)

## Medición remota (QA `:8447`, código desplegado — no el diff local)

| Corrida | Alcance | Resultado |
|---|---|---|
| `20260921T020704Z_90a62b16` | 141 históricos parcial/no cumple | 47 PASS · 1 aclaración · 16 PARTIAL · 77 FAIL |
| `20260921T032230Z_ba269a3b` | 95 históricos Cumple (regresión) | **17 PASS · 5 PARTIAL · 73 FAIL** |

La regresión de los 95 **no se conserva** bajo el oráculo `strict_v2.2` actual: muchos «Cumple» históricos fallan por grounding/retrieval (comparaciones CMP y evidencia de producto). No se marcan completados.

## Capturas UI
Run `20260921T023000Z_azure_mejora_fix`: 12/12 capturas reales (Chrome channel) en  
`works/validacion_guia_fix/images/fix/20260921T023000Z_azure_mejora_fix/`.  
Resto de la guía: **PENDING_UI**. HTTP 200 no acredita chat.

## Guía fix
`works/azure_mejora/guia/Guia_Pruebas_FIX.md` — 236 filas.  
Conteos visuales: RESUELTO 18 · PARCIAL 68 · FALLA 150.  
**Ningún caso se marca completado** si falta captura revisada o si el criterio completo no está verificado en el código desplegado.

## Bloqueos visibles
1. Redeploy del diff local (payoff ≠ principal, filtro retrieval) a `:8447` no ejecutado (sin apply remoto autorizado).
2. Índice Search candidato no creado (permiso/apply pendiente).
3. FAIL_GROUNDING masivo en CMP/CC (evidencia cruzada de catálogo en QA).
4. FAIL_RETRIEVAL en CD/PR/DA: corpus/KB o wording no cubre el esperado.
5. Datos BLOCKED_DATA: movimientos, cuota exacta, fecha límite TC, cotización de cancelación cuando Core no la distingue del capital.
6. Regresión 95 no verde — no declarar conservación de los históricos Cumple.

## Chunking
`eval_chunking_profiles.json`: fichas actuales ~71 tokens (cortas, completas). Elección provisional **600/80** sin re-chunk agresivo.

## Hash ZIP (fuera del archivo)
- `works/qa_runs/EVIDENCIAS_AZURE_MEJORA_20260921T041632Z.zip`
- SHA256: `C16FF45AB67BBEDD0EF65F56F14BC05C6324F94A2D90DC1EE13B4249DE2C36D5`
- Sidecar: `works/qa_runs/EVIDENCIAS_AZURE_MEJORA_20260921T041632Z.sha256`

## Rollback
Diff local en `core_portfolio_mapper.py`, `kb_package_ingest.py`, `plan_executor.py`. Sin cambios Azure/PROD/backend externo.


## Chunking
Perfiles medidos en chunks actuales (~71 tokens promedio; fichas cortas conservadas). Elección provisional **600/80** marcada en `eval_chunking_profiles.json`. Re-chunk semántico 400–800 pendiente de pipeline dedicado.

## Pendiente para cierre “completado”
- Redeploy cognitivo QA con diff local
- Terminar 141 + regresión 95 con misma versión desplegada
- Capturas reales por escenario corregido → embeber en guía fix
- Índice Search candidato (solo con apply autorizado)
- Ciclo Entra / Redis desde VM

## Rollback
Solo archivos locales en `src/genesis_cognitive` y `works/azure_mejora`. Sin apply Azure.
