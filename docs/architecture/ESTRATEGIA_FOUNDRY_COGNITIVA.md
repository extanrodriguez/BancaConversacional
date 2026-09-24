# Estrategia: Cognitiva + Foundry KB (aprendizaje continuo)

## Principio
- **Personal (saldo, corte, mis tarjetas):** siempre Cognitiva + snapshot. Foundry no interviene.
- **Conocimiento (qué es, responsabilidades, catálogo banco):** FAQ/overlay primero → Foundry (índice `bsc-kb-conocimiento`) → Search local → fallback.

## Cómo “aprende” Foundry
1. Corregir/ampliar MD o FAQ overlay en el repo.
2. Reindexar: `python scripts/index_kb_azure.py --sources faq,md` (sin `--force` para merge).
3. Actualizar **Instrucciones** del agente (`docs/architecture/FOUNDRY_KB_AGENT_INSTRUCTIONS.md`).
4. Probar en **Área de juegos**; si falla, añadir expresión al overlay y repetir.

## Cómo aprende Cognitiva
1. Guardrails deterministas (campo tras clarificación, match por alias, ambigüedad).
2. Overlay FAQ (`data/kb_faq_overlay_fase1.json`) para frases reales del APK.
3. Tests unitarios con la frase exacta del reporte.
4. Deploy 8447.

## Si no entiende
Preguntar (clarificación) en vez de inventar:
- Varias tarjetas / productos → options APK.
- Certificado vs garantía → aclarar.
- Responsabilidad banco vs cliente → respuestas distintas; follow-up “y la del banco” usa `last_knowledge_topic`.
- “cómo se usa” tras una definición → ampliar con el tema KB previo y FAQ/Foundry (no saludo).
- Fecha límite de pago TC sin dato en Core → decirlo y dar corte + estado de cuenta.
- Fecha de pago de préstamo tras selección → conservar `original_question` (PAYMENT_DATE_READ).

## Contexto conversacional (Cognitiva)
1. `last_knowledge_topic` en sesión Redis tras cada FAQ/RAG.
2. `knowledge_followup.py` reescribe follow-ups cortos (“como se usa”, “y la del banco”).
3. Bloqueo de follow-up personal (préstamo/TC) cuando el hilo es de conocimiento.
4. Foundry recibe la pregunta **ampliada** si Cognitiva escala a RAG.
