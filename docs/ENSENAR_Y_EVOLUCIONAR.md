# Enseñar y evolucionar la banca conversacional

## Principio

**Negocio edita Excel / MD; ingeniería publica artefactos versionados; el contenedor
solo monta datos y variables.** El modelo no “aprende solo” de chats: se enseña
con reglas explícitas + índice RAG + tests.

**No grabar todas las respuestas en el FAQ.** El FAQ son atajos de alta confianza
(frases frecuentes / institucionales). Si no hay match fuerte:

1. Se interpreta la **intención** contra el corpus KB (`kb_intent_resolver`: FAQ JSON + MD).
2. Si hay hit grounded → se responde con ese contenido.
3. Si no → Azure RAG; solo al final se escala a humano.

Así el bot puede responder “pago mínimo”, “crédito diferido”, derechos, etc. sin
duplicar cada fila del Excel como expresión FAQ.

## Ciclo de vida del conocimiento

```
1. Negocio actualiza Excel VF01 o propone expresiones nuevas
2. Export / import:
     scripts/export_docs_from_excel.py   → docs/
     scripts/import_kb_excel_vf01.py     → data/kb_faq_vf01.json + Knowledge_Base/
3. Hotfix de frases (sin reimportar Excel):
     data/kb_faq_overlay_fase1.json  (o GENESIS_FAQ_OVERLAY_PATH)
4. Reindex RAG (Azure) con los MD / chunks aprobados
5. pytest + matriz de escenarios
6. Promoción de imagen / volumen de datos al contenedor
```

## Cómo añadir una pregunta nueva (checklist)

1. **¿Es dato personal del cliente?**  
   → Guardrail de producto + campo del API contexto. No va a FAQ.

2. **¿Es definición / institucional con respuesta fija y frase frecuente?**  
   → Añadir fila Excel o entrada en overlay FAQ con `expressions` + `answer`.  
   → Regenerar JSON.  
   → Test con la frase exacta y 2 variantes coloquiales.  
   → Si la pregunta es rara o parafraseada: **no** hace falta FAQ; el resolver de
     intención + RAG deben alcanzar el mismo topic en el corpus.

3. **¿Es proceso con varios caminos (reclamación, cancelación)?**  
   → Clarification-first (como `reclamacion_guardrail`).  
   → Respuestas parciales por opción.  
   → No volcar el manual en el primer turno.

4. **¿Requiere razonar sobre muchos documentos?**  
   → Indexar en RAG; FAQ solo como atajo si hay frase frecuente.  
   → Tras FAQ miss, el pipeline usa intención KB antes de “asesor humano”.

5. **¿Es grosería / fuera de alcance?**  
   → Moderación o template out-of-scope (no inventar respuesta).

## Cómo corregir un fallo tipo “a veces sí / a veces no”

1. Reproducir con la frase exacta en `/turn` (mismo `customer_id`).  
2. Ver `decision_trace` / step del fast-path (`moderation`, `faq`, `scope`, …).  
3. Si debió ser FAQ: ampliar `expressions` / `synonyms` en overlay.  
4. Si debió entenderse por intención (parafraseo): verificar corpus MD/JSON y
   `resolve_knowledge_intent`; no añadir FAQ si el topic ya existe.  
5. Si escaló a humano: verificar política institucional, chunks RAG e intent KB.  
6. Añadir test unitario **antes** de cerrar el ticket.

## Evolución por fases

| Fase | Qué aporta |
|------|------------|
| **1 (actual)** | Moderación, alcance, FAQ + intención KB, reclamaciones, no-escalación institucional |
| **2** | Metadata de ambigüedad del Excel ejecutable; embeddings de reglas |
| **3** | RAG contextualizado (regla + snapshot); dashboards de calidad |
| **4** | Nuevas capacidades operativas (pagos, transferencias) con confirmation UI |

## Gobernanza

- Toda respuesta institucional debe poder citarse a una fila Excel / id FAQ.  
- Cambios de overlay en el mismo release que los tests.  
- No editar a mano el índice Azure sin dejar traza del corpus MD.
