# Cómo funciona `plan_interpreter` (V3.1)

## Rol

`interpret_turn_plan(question, session, snapshot=…)` construye un `TurnPlan` con **una o más** `PlanTask` a partir del **mensaje original completo** y del estado de sesión, **antes** de que un clasificador de intención única descarte subtareas.

Archivo: `src/genesis_cognitive/brain/plan_interpreter.py`.  
Ejecución: `src/genesis_cognitive/brain/plan_executor.py`.  
Cableado: `contract_inspector_app._inspect_unlocked` (ruta `turn_plan_multi`).

## Qué interpreta con reglas (determinista)

Reglas heurísticas locales (`source=heuristic_multi`), sin LLM:

| Familia | Señales típicas | Resultado |
|---|---|---|
| Secretos | PIN/OTP/CVV/contraseña | `refuse` (bloquea match por dígitos) |
| Titularidad | esposo/hijo + saldo/cuenta | `refuse` o proceso general («abrir cuenta») |
| Institucional | misión/visión/valores | `define` / `compare` institutional |
| Glosario | «qué significa saldo/tasa» | `glossary` |
| Personal liquidez | disponible / saldo actual | `account` o `credit_card` según mención/foco |
| Multi-campo tarjeta | deuda + disponible + fecha | una tarea con `fields[]` |
| Certificados | tasa/vencimiento/all + exclusiones | `term_deposit` all + compare earliest |
| Catálogo | compara / agrega / existencia | `compare_set`, `check_existence` |
| Proceso | cancelación tarjeta vs préstamo | `process` compare (sin payoff personal) |
| Continuidad | retomando / la segunda / corrección | ordinal + `pending_tasks` |
| Limitaciones | movimientos | `unsupported` explícito |

Si ninguna regla aplica → **adaptador** `intent_packet_to_turn_plan(heuristic_intent(…))` con `source=adapter` (una sola tarea).

## Cuándo interviene Azure

1. **Plan local primero.** Si el plan es `heuristic_multi` (o multi-tarea / refuse / catálogo / etc.), `/turn` ejecuta `execute_turn_plan` y **no** llama al modelo para interpretar ese turno.
2. **Azure Brain** (`GENESIS_AZURE_BRAIN=1`) solo en el fallthrough histórico: `run_azure_brain_turn` → `classify_intent_async` produce un **`IntentPacket` de una intención**, no un `TurnPlan` multi-tarea.
3. Con `GENESIS_AZURE_BRAIN=0` (pruebas locales) el clasificador Azure no corre; rigen reglas + FAQ + fastpaths.

## Autoridad semántica (decisión V3.1 corrección auditada)

**Autoridad local multi-tarea:** `interpret_turn_plan` (`source=heuristic_multi`) produce el `TurnPlan` ejecutable completo (campos, exclusiones, referencias, catálogo, pendientes).

**Fallthrough de una intención:** si el plan no aplica, el camino histórico puede usar Azure Brain → `IntentPacket` único (adaptado a una `PlanTask` vía `intent_packet_to_turn_plan`). Eso **no** acredita multi-tarea ni uso de modelo solo por `provider=AZURE_OPENAI` con `inference_count=0`.

**No se añadió un tercer clasificador.** `AgentFrameworkTurnResolver.resolve_full` / `ModelSemanticProposal.actions[]` permanecen disponibles, pero el cierre local no los coloca delante de `heuristic_multi` para no competir con el plan ya cableado. Extender el resolver multi-acción de Azure al esquema `TurnPlan` validado queda como mejora futura desproporcionada para esta corrección.

**Atajos deterministas** (secretos, institucional inequívoco, FAQ) se conservan; si no cubren el mensaje entero, ceden al intérprete estructurado / plan.

## Validación del plan

`validate_turn_plan` detecta ciclos de cualquier longitud (DFS). Un plan inválido lanza `InvalidTurnPlanError` y **no** continúa solo con una nota en `correlation_hint`.

## Flujo resumido

```
mensaje → scrub secretos → interpret_turn_plan
       → validate → execute_turn_plan (evidencia por tarea)
       → commit CAS sesión (pending_tasks, compare_set, focos)
       → app_channel /turn
```

Si el plan no aplica: FAQ institucional solo-si-institucional → Azure brain (opt-in) → fastpaths históricos.
