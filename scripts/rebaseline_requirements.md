# Requisitos — Cognitive Turn Routing MVP (Rebaseline Agentic + RAG)

## Objetivo

```
orchestrator_turn_request
→ validación estructural
→ ensamblaje de contexto
→ Microsoft Agent Framework
→ agentes de intención y entidades
→ selección de capacidad
→ agente especialista o RAG
→ respuesta bancaria visible candidata
→ validación determinística
→ IntentResolution fuertemente tipado
→ CognitiveTurnResult
```

Este incremento interpreta semánticamente el turno del usuario mediante Agent
Framework real, identifica acciones, ejecuta recuperación documental cuando
corresponda, produce una respuesta bancaria visible grounded y un contrato
tipado para el orquestador.

## Directriz normativa

Versión: 1.3
Ruta: `C:\Users\boris\Documents\Genesis\Genesis_v2\.kiro\steering\mandatory-project-directives.md`

---

## Niveles de prueba

| Nivel | Descripción | Cierra aceptación semántica |
|-------|-------------|-----------------------------|
| A — Contractual | Schemas, Pydantic, DAG, seguridad | No |
| B — Integración | Pipeline con dobles controlados | No |
| C — Cognitiva | Agent Framework real + modelo real + lenguaje natural + RAG real | **Sí** |

Solo el nivel C demuestra comprensión cognitiva.

---

## Fuentes documentales obligatorias

| Fuente | Tipo | Precedencia |
|--------|------|-------------|
| `C:\Users\boris\Documents\Genesis\Genesis_v2\Knowledge_Base\KB_GENESIS_Protocolo_Maestro_Asistente_Bancario_Conversacional_v1.01.pdf` | Protocolo Maestro | Crítica (máxima) |
| `C:\Users\boris\Documents\Genesis\Genesis_v2\Knowledge_Base\KB_GENESIS_Base_Conocimiento_RAG_Asistente_Bancario_v1.01.pdf` | Base FAQ RAG | Alta (subordinada al Protocolo) |

Política: Protocolo Maestro > Base FAQ > fuentes institucionales adicionales > aclaración o handoff.

---

## Resultado cognitivo completo — CognitiveTurnResult

| Campo | Descripción |
|-------|-------------|
| `contract_version` | Versión del contrato |
| `request_id` | ID de la solicitud |
| `correlation_id` | ID de correlación |
| `conversation_id` | ID de conversación |
| `intent_resolution` | IntentResolution tipado |
| `assistant_response_candidate` | Respuesta bancaria visible |
| `rag_trace` | Trazabilidad de recuperación |
| `prompt_id` | ID del prompt utilizado |
| `prompt_version` | Versión del prompt |
| `model_id` | Identificador del modelo |
| `model_version` | Versión del deployment |
| `capability_catalog_version` | Versión del catálogo |

### AssistantResponseCandidate

| Campo | Descripción |
|-------|-------------|
| `message` | Texto visible para el cliente |
| `response_type` | Tipo: answer, clarification, unsupported, handoff |
| `next_step` | Siguiente paso anticipado |
| `requires_confirmation` | Requiere confirmación del orquestador |
| `handoff_required` | Requiere atención humana |

### RagTrace

| Campo | Descripción |
|-------|-------------|
| `used` | Si se utilizó recuperación |
| `evidence_sufficient` | Si la evidencia fue suficiente |
| `protocol_sources` | Fuentes del Protocolo Maestro |
| `knowledge_sources` | Fuentes de la Base FAQ |
| `source_conflict` | Si hubo conflicto entre fuentes |

---

## Caso vertical obligatorio

Entrada: "¿Cuáles son los requisitos para solicitar un préstamo hipotecario?"

Debe demostrar:
1. Entrada real en lenguaje natural.
2. Agent Framework real invocado.
3. Intención BUSINESS_KNOWLEDGE_QUERY identificada.
4. Ruta BUSINESS_RAG.
5. Recuperación de FAQ correspondiente.
6. Aplicación del Protocolo Maestro.
7. Respuesta visible grounded.
8. Siguiente paso anticipado.
9. IntentResolution válido.
10. CognitiveTurnResult válido.
11. Fuentes registradas.

---

## Criterios de aceptación

### Nivel A — Contractuales (cierran con FakeResolver)

CA-01 a CA-03: Validación de entrada y autenticación.
CA-08 a CA-10: Correspondencias y catálogo.
CA-12 a CA-17: Aislamiento, adaptadores, schemas.
CA-22: DAG acíclico.
CA-24 a CA-32: Prompts, telemetría, extensibilidad.

### Nivel C — Cognitivos (requieren Agent Framework + modelo real)

| ID | Criterio |
|----|----------|
| CA-04 | Casos canónicos con modelo real |
| CA-05 | Invarianza de paráfrasis con modelo real |
| CA-06 | Ambigüedad → CLARIFICATION con modelo real |
| CA-07 | No soportado → UNSUPPORTED con modelo real |
| CA-11 | Sin keyword routing (paráfrasis adversarial) |
| CA-18 | Multi-acción independiente con modelo real |
| CA-19 | Multi-acción dependiente con modelo real |
| CA-21 | Aclaración contextual con modelo real |
| CA-33 | Respuesta bancaria visible grounded |
| CA-34 | Recuperación de fuentes documentales |
| CA-35 | Groundedness verificable |
| CA-36 | Siguiente paso anticipado |
| CA-37 | Modelo real obligatorio |
| CA-38 | Extensibilidad sin router central |
| CA-39 | Trazabilidad documental completa |

### Métricas semánticas obligatorias

- 100% salidas válidas contra schema.
- 100% seguridad sin violaciones.
- ≥ 90% exactitud intención y ruta.
- ≥ 90% exactitud entidades.
- ≥ 90% consistencia paráfrasis.
- Fuente esperada presente en recuperación canónica.
- Cero afirmaciones de ejecución no confirmada.

---

## Fuera de alcance

- Ejecución de transferencias contra Core.
- Confirmación al usuario.
- Idempotencia.
- SLA definitivo de latencia.
- Persistencia durable (Cosmos/Redis reales).
- Service Bus.
- Event Grid.
- Container Apps.
- Despliegues Azure.
- Pruebas AWS.
- CRM.
- Contratos financieros finales.
