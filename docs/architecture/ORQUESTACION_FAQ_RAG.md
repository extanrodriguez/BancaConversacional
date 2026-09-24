# Orquestación FAQ + RAG

## Objetivo

Minimizar ambigüedad y alucinaciones: responder rápido con reglas cuando existan,
usar RAG solo para enriquecer o cubrir huecos, y **no escalar a humano** preguntas
institucionales o de proceso que ya están en la base de conocimiento.

## Pipeline de un turno

```
Usuario
  │
  ├─ Capa 0  Moderación (profanity)
  │     └─ solo grosería → redirección neutral
  │     └─ grosería + intención → limpia texto y continúa
  │
  ├─ Capa 1  Fast-path determinista (sin LLM)
  │     orden: reclamación → portafolio → alcance → saludo →
  │            préstamos/tarjetas/saldos → FAQ
  │
  ├─ Capa 2  Clasificadores LLM + turn-decision
  │     own_product | business_knowledge | ood | non_operational
  │
  ├─ Capa 3  RAG Azure (si BUSINESS_KNOWLEDGE_QUERY)
  │     HITS → respuesta grounded
  │     NO_HITS → FAQ fallback → institucional fallback → humano
  │
  └─ Capa 4  Templates / respuesta final al canal (APK)
```

## Cuándo FAQ vs RAG

| Condición | Ruta | Ejemplo |
|-----------|------|---------|
| Match FAQ / overlay ≥ umbral | FAQ directo | `CUAL ES LA MISION`, `Mision` |
| Proceso multi-paso | Clarificación primero | reclamaciones → pedir canal |
| Alcance del asistente | Guardrail scope | `¿en qué me puedes ayudar?` |
| Knowledge sin FAQ fuerte | RAG | requisitos detallados de un producto |
| Institucional sin chunks | Fallback institucional | `hablame del banco` |
| Dato no autorizado / fuera de catálogo | Humano / no disponible | comisión no publicada |

## Política anti-alucinación

1. **Datos personales** solo del `CustomerContextSnapshot` (API Productos).
2. **Datos institucionales** solo de KB / chunks RAG; nunca inventar tasas.
3. **Procesos largos**: aclarar antes de volcar el manual completo.
4. **Escalación humana**: último recurso; desactivable para institucionales vía
   `GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL=1`.

## Componentes de código

| Pieza | Ruta |
|-------|------|
| Fast-path | `router/field_guardrails.py` → `run_field_fastpath` |
| Moderación | `router/moderation.py` |
| Alcance | `router/scope_guardrail.py` |
| Reclamaciones | `router/reclamacion_guardrail.py` |
| FAQ | `router/faq_guardrail.py` + `data/kb_faq_vf01.json` + overlay |
| RAG | `rag/local_rag.py` |
| Entrada HTTP | `demo/contract_inspector_app.py` (`POST /turn`) |
