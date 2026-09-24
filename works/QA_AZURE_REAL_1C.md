# Prueba QA — Azure real (Etapa 1C) — PREPARADA, NO EJECUTADA

Estado: **no corrida**. Requiere autorización remota explícita del propietario.
No declara éxito con modelo Azure real.

## Objetivo

Validar cerebro Azure (`GENESIS_AZURE_BRAIN=1`) con datos **sintéticos**, FAQ
corpus/overlay reales, sin llamadas al Core bancario ni modificación del
índice/agente Foundry.

## Configuración explícita del entorno autorizado

```text
GENESIS_QA_AZURE_AUTHORIZED=1
GENESIS_AZURE_BRAIN=1
AZURE_OPENAI_API_KEY=<secreto autorizado>
AZURE_OPENAI_ENDPOINT=<endpoint autorizado>
AZURE_OPENAI_DEPLOYMENT=<deployment autorizado>
AZURE_OPENAI_API_VERSION=<versión autorizada>

GENESIS_FAQ_PATH=<repo>/data/kb_faq_vf01.json
GENESIS_FAQ_OVERLAY_PATH=<repo>/data/kb_faq_overlay_fase1.json

# Explicitamente vacíos / mock local:
GENESIS_CORE_URL=
# No regenerar ni subir índice de conocimiento
```

Ejecutar solo tras checklist firmado. Comando previsto (no correr ahora):

```text
.\.venv\Scripts\python.exe -m pytest `
  tests/unit/test_cognitive_stabilization_stage1c.py::test_qa_azure_real_harness_not_run `
  -v --runxfail
```

(El test permanece `@pytest.mark.skip` hasta que se retire el skip **y** exista
`GENESIS_QA_AZURE_AUTHORIZED=1`.)

## Datos sintéticos

Mismo portafolio que etapa 1C local:

- Cuentas `CA1001DOP` / `CA2002USD`
- Préstamo `LOAN27615` (tasa 18.5%)
- TC `TC6582` (corte día 15)
- Display name: `Cliente Sintetico` — sin PII real

## Casos a registrar

### Interferencia FAQ / elegibilidad

1. ¿Cuánto tengo disponible?
2. ¿Qué significa saldo disponible?
3. ¿Y el disponible de esa cuenta?
4. ¿Cuál es mi tasa?
5. ¿Qué significa tasa de interés?
6. ¿Cuándo corta mi tarjeta?
7. ¿Qué es la fecha de corte?
8. Mixta: Dime mi saldo y qué significa disponible

### Multi-turno DOP/USD

1. ¿Cuánto tengo disponible? → clarificación
2. La de dólares. → USD 320.50
3. ¿Qué significa saldo disponible? → knowledge (FAQ o Foundry), foco USD intacto
4. ¿Y el disponible de esa cuenta? → USD
5. No, ahora la de pesos. → DOP

## Registro sanitizado (plantilla)

Por turno, loguear **sin** secretos ni PII:

| Campo | Ejemplo |
|---|---|
| turn | 1 |
| question_hash | sha256 truncado |
| route / decision_trace.step | field_fastpath_balance / faq / brain_azure |
| source | heuristic_bypass / azure_structured / faq_corpus / foundry |
| product_id | CA2002USD |
| field | available |
| status | VALID_CONTRACT |
| latency_ms | 420 |
| error | null / tipo sanitizado |
| result_ok | true/false según criterio |

No registrar: API keys, payloads crudos de Azure con PII, números de documento.

## Criterios: respuesta del modelo vs bypass heurístico

Marcar `source=heuristic_bypass` si:

- `IntentPacket.rationale` empieza por `critical:` (p.ej. `critical:generic_available`)
- o no hubo llamada HTTP a Azure (contador de completions = 0)

Marcar `source=azure_structured` solo si:

- `GENESIS_AZURE_BRAIN=1`
- hubo al menos una llamada `chat.completions.create` con `response_format.json_schema`
- el payload pasó `validate_brain_payload`
- `rationale` del packet **no** es `critical:*`

Marcar `source=faq_corpus` si `decision_trace` / intent `BUSINESS_KNOWLEDGE_QUERY`
y el texto coincide con entrada FAQ (topic/id), sin Foundry.

## Fuera de alcance de esta corrida QA

- Llamadas al Core / APIs productivas de saldo
- Migración o reindexación del índice de conocimiento
- Cambios a frontend, WebSocket, orquestador externo
- Cableado CAS en `/inspect` (sigue bloqueado a nivel HTTP E2E)

## Resultado de esta entrega

**No ejecutada. No hay éxito Azure real que reportar.**
