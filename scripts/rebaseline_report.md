# Agentic + RAG Architecture Rebaseline Report

## Fecha: 2026-07-26
## Versión de directrices: 1.3

## Estado de T07

**RECHAZADO**

Defectos pendientes (backlog T08):
- CapabilityCatalog acepta acciones sin entidades requeridas.
- Acepta missing_requirements ajenos a la capacidad.
- Acepta entidades ajenas durante clarificaciones.
- Constructor no rechaza required/optional superpuestas.
- Constructor no rechaza reglas min_required_entities incoherentes.
- Manifiestos no son profundamente inmutables.
- test_unknown_with_candidate_rejected vacío.
- T07 solo 14 pruebas de adaptadores.
- Ruff reporta 7 errores.
- README y evidencias desactualizados.

## Cambio arquitectónico

| Antes | Después |
|-------|---------|
| Clasificador de intención simple | Sistema agentic con coordinación |
| RAG real en "fuera de alcance" | RAG real obligatorio |
| Evaluación semántica PENDING | Evaluación ejecutada obligatoria |
| Respuesta: solo contrato tipado | Respuesta bancaria visible + contrato |
| FakeResolver cierra aceptación | Solo nivel C cierra aceptación semántica |

## Nuevas directrices (211–235)

- 211: No bot determinístico.
- 212: Aceptación comienza con lenguaje natural real.
- 213: Agent Framework = autoridad semántica.
- 214: Prohibido inferir mediante keywords/regex.
- 215: Catalog/RouteTable no interpretan lenguaje.
- 216: Validadores post-modelo, no reemplazo.
- 217: FakeResolver = test contractual.
- 218: Mock no cierra aceptación funcional.
- 219: Evaluación con modelo real obligatoria.
- 220: Prohibido cerrar con skip/PENDING.
- 221: RAG real para BUSINESS_KNOWLEDGE_QUERY.
- 222: Fuentes: Protocolo Maestro + Base FAQ.
- 223: Protocolo gobierna comportamiento y seguridad.
- 224: Base FAQ aporta conocimiento granular.
- 225: Trazabilidad RAG obligatoria.
- 226: Salida cognitiva completa.
- 227: Respuesta clara, cordial, prudente.
- 228: Contexto para evitar preguntas repetidas.
- 229: Aclaración mínima.
- 230: Multi-acción soportada.
- 231: 7 capacidades = seed, no límite.
- 232: Extensión sin router central.
- 233: Aceptación con lenguaje natural.
- 234: Evidencia con versiones completas.
- 235: Directrices no pueden ser opcionales.

## Validaciones documentales

- [x] Versión de directrices = 1.3
- [x] Directrices 211–235 presentes
- [x] "RAG real" NO en Fuera de alcance
- [x] PENDING_LIVE_MODEL_EVALUATION eliminado como cierre
- [x] Agent Framework real es obligatorio
- [x] Dos PDFs referenciados por ruta absoluta
- [x] CognitiveTurnResult definido
- [x] Respuesta bancaria visible candidata definida
- [x] Trazabilidad RAG definida
- [x] Tasks T08–T24 reformuladas
- [x] Ninguna tarea autoriza ejecución financiera
- [x] Ninguna tarea autoriza crear infraestructura
