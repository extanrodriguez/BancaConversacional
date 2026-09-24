# Tareas — Cognitive Turn Routing MVP (Rebaseline Agentic + RAG)

## T08 — Cierre de defectos T06/T07

- CapabilityCatalog: validación completa de candidates, entidades, invariantes.
- Inmutabilidad profunda de manifiestos.
- Adaptadores estrictos y pruebas faltantes.
- Ruff completamente verde.
- Backlog: test_unknown_with_candidate, required/optional superpuestas, min_required incoherentes.
- **No inicia T09 hasta Ruff=0, Mypy=0, todos los tests pasan.**

## T09 — InputValidator y ContextAssembler

- Entrada real validada.
- Contexto autorizado ensamblado.
- locale → language derivado.
- Aislamiento por customer_id y conversation_id.
- Pruebas nivel A.

## T10 — Knowledge Base ingestion assets

- Protocolo Maestro: chunking con prioridad crítica.
- Base FAQ: chunking por pregunta-respuesta con metadatos completos.
- Versiones documentales registradas.
- Formato reproducible y trazable.
- **No respuestas hardcoded.**

## T11 — Retrieval port y adaptador RAG

- Puerto asíncrono para recuperación documental.
- Adaptador local que indexa los chunks de T10.
- Recuperación real contra los activos documentales.
- Búsqueda por similaridad semántica o keyword+reranking.
- Trazabilidad: documento, versión, chunk, página, fragmento.

## T12 — ModelInputBuilder

- Proyección segura: sin IDs confiables, tokens ni credenciales.
- Incluye: texto, idioma, contexto conversacional, portafolio, catálogo efectivo, fuentes RAG relevantes.

## T13 — Microsoft Agent Framework Resolver

- Instalar agent-framework-core==1.12.1 + agent-framework-openai==1.11.0.
- Structured output → TurnInterpretation.
- Prompt cargado desde PromptRegistry.
- Tests unitarios con mock del modelo.
- **Smoke test controlado obligatorio con modelo real.**

## T14 — Supervisor, Intent/Entity y especialistas

- Supervisor Agent coordina.
- Intent and Entity Agent interpreta lenguaje natural.
- RAG Agent bajo demanda para BUSINESS_KNOWLEDGE_QUERY.
- Planning Agent bajo demanda para multi-acción.
- No cadenas innecesarias para turnos simples.

## T15 — Response Builder y CognitiveTurnResult

- Response Builder Agent construye respuesta bancaria visible.
- AssistantResponseCandidate con message, response_type, next_step.
- RagTrace con fuentes y groundedness.
- CognitiveTurnResult completo.

## T16 — ResolutionAssembler y validación final

- action_id determinista.
- depends_on_action_ids.
- domain, interaction_family, next_action deterministas.
- Schema validation.
- Guardrails de seguridad.

## T17 — Endpoint local end-to-end

- FastAPI endpoint.
- Flujo completo: request → CognitiveTurnResult.
- Error handling tipado.
- Telemetría segura.

## T18 — Dataset semántico real

- Casos canónicos con lenguaje natural real.
- ≥ 3 paráfrasis por capacidad.
- Multi-acción, ambigüedad, no soportado, mixto.
- Casos adversariales y de seguridad.
- Prompt injection.
- RAG insuficiente.
- Contradicción Protocolo/FAQ.

## T19 — Evaluación semántica ejecutada

- Agent Framework real + modelo real.
- Lenguaje natural real.
- **No skip. No PENDING. No xfail.**
- Métricas: ≥ 90% intención, ≥ 90% entidades, ≥ 90% paráfrasis.
- 100% schema válido. 100% seguridad.

## T20 — Evaluación RAG y groundedness

- Caso vertical préstamo hipotecario completo.
- Fuente FAQ recuperada.
- Protocolo Maestro aplicado.
- Respuesta grounded verificable.
- Trazabilidad documental completa.

## T21 — Pruebas adversariales y seguridad

- Prompt injection rechazado.
- Datos sensibles no expuestos.
- Ejecución financiera prohibida.
- Cero violaciones de seguridad.

## T22 — Extensibilidad de capacidades

- Incorporar capacidad nueva mediante manifest + evaluación.
- Sin modificar router central ni prompts con frases.
- Demostrar con lenguaje natural, paráfrasis y contrato tipado.

## T23 — Calidad, telemetría y evidencia

- Ruff format + check = 0.
- Mypy = 0.
- Coverage ≥ 85%.
- Telemetría con lista blanca completa.
- Scan de secretos y PII.
- Scan de prompts incrustados.
- No .env versionado.

## T24 — Informe final

- Tabla CA → archivo → comando → resultado.
- Métricas semánticas alcanzadas.
- Limitaciones documentadas.
- Versiones registradas: modelo, framework, prompt, catálogo, schemas, fuentes RAG, dataset.
- Confirmación Azure sin cambios.
- Confirmación AWS sin uso.

---

## Dependencias

```
T08 (defectos) → ninguna
T09 (Input/Context) → T08
T10 (KB ingestion) → ninguna
T11 (RAG port) → T10
T12 (ModelInputBuilder) → T09
T13 (Agent Framework) → T08, T12
T14 (Agentes) → T11, T13
T15 (Response) → T14
T16 (Assembly) → T15
T17 (Endpoint) → T16
T18 (Dataset) → T10
T19 (Evaluación) → T17, T18
T20 (RAG eval) → T19
T21 (Seguridad) → T19
T22 (Extensibilidad) → T19
T23 (Calidad) → T19, T20, T21, T22
T24 (Informe) → T23
```

## Restricciones transversales

- Ninguna tarea autoriza ejecución financiera contra Core.
- Ninguna tarea autoriza crear infraestructura Azure/AWS.
- Ninguna tarea puede cerrar evaluación semántica con mocks.
