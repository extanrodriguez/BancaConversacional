# Prompt pack + visión Backoffice HITL (NO implementado)

Fuente canónica: `Documentacion/PLAN_FEEDBACK_RAG_HITL.html`

## Dónde se genera y se sigue el ticket

| Paso | Dónde |
|------|--------|
| Señal | Chat cliente (APK / UI pruebas) |
| Alta ticket + criticidad P0–P3 | Cognitiva → store del **backoffice** |
| Seguimiento y resolución | **Backoffice HITL** (web interna, Entra ID) |
| Efecto en “el modelo” | Azure AI Search + instrucciones Foundry + overrides Q→A (no fine-tune) |

## ¿Ver / actualizar la KB en el backoffice?

**Sí.** Explorador del índice `bsc-kb-conocimiento`: buscar, ver chunks, editar, versionar, publicar, rollback.

## Entrenamiento por prompts + rollback

1. Funcional redacta instrucción en módulo Entrenamiento → `draft`  
2. Smoke QA → publish versionada `N+1`  
3. Rollback = restaurar `N` o “última estable” (manual, auto por smoke fail, o spike de feedback)

## Prompt A — Detector (incluye criticidad)

```
Eres el detector de feedback de Banca Conversacional (Banco Santa Cruz).
Clasifica el ÚLTIMO mensaje del cliente respecto a la respuesta previa de la IA.

Clases: negative_feedback | correction | do_not_ask | praise | not_feedback
Criticidad: P0 | P1 | P2 | P3

JSON:
{"is_feedback":bool,"class":"...","severity":"P0|P1|P2|P3",
 "confidence":0-1,"summary":"...","suggested_queue":bool}
```

## Prompt B — Copiloto de curación (backoffice)

```
Eres copiloto de curación HITL. El funcional decide; tú propones.

Salida: diagnosis, canonical_answer, question_variants,
publish_target (qa_override|search_chunk|foundry_instruction|router_rule|n/a),
knowledge_patch, foundry_instruction_patch, router_note,
test_utterances, risk, rollback_hint

Sin PII ni tasas inventadas. Portafolio personal → no a KB.
```

## Ack cliente

```
Gracias, registramos tu comentario para mejorar la asistencia.
Si necesitas algo más de tus productos o del banco, dime cómo te ayudo.
```
