# Modelo de aprendizaje para Banca Conversacional

## Recomendación (qué NO hacer primero)
Entrenar una red neuronal “desde cero” o un LLM propio **no** es el mejor siguiente paso:
- Los datos personales del cliente no deben usarse para entrenar modelos externos.
- Ya tienen **Azure OpenAI + embeddings + Azure AI Search + Foundry**.
- El cuello de botella actual es **enrutamiento/intención y cobertura de expresiones**, no falta de un modelo generativo.

## Arquitectura de aprendizaje adaptada a esta app

```
Pregunta → Cognitiva (guardrails)
         → FAQ lexical + scoring
         → (opcional) rerank por embeddings
         → Foundry / Search
         → Feedback (OK/KO + corrección)
         → Overlay FAQ / reindex
```

### Capa 1 — Feedback loop (implementada base)
Módulo: `src/genesis_cognitive/learning/feedback_store.py`
- Guarda pregunta, match FAQ, score, ok/ko, corrección.
- Acumula **expression_candidates** para promover al overlay.
- DB local: `data/learning/intent_feedback.sqlite3` (o `GENESIS_LEARNING_DB`).

### Capa 2 — Recuperación densa (mejor ROI)
Usar el mismo `text-embedding-3-small` ya configurado:
1. Embeddings de cada `answer`/`topic`/`expressions` del FAQ.
2. Ante miss lexical, buscar top-k por similitud coseno.
3. Si score > umbral → responder; si no → Foundry.

Esto es un “modelo de aprendizaje” práctico: mejora con más texto indexado sin fine-tune.

### Capa 3 — Clasificador ligero (opcional, después)
Si tienen ≥2–5k ejemplos etiquetados (pregunta → id FAQ / PERSONAL / FOUNDRY):
- Entrenar un clasificador **sklearn** (LogReg / LinearSVM) o **LightGBM** sobre embeddings.
- Inferencia <10 ms; fácil de versionar y auditar (banca).
- Reentrenar semanal con feedback OK/KO.

### Capa 4 — Foundry / Search
Sigue siendo el generador grounded. El “aprendizaje” aquí es:
- Mejorar instrucciones del agente.
- Reindexar `bsc-kb-conocimiento` cuando cambie la KB Excel/MD.

## Flujo operativo semanal
1. Correr `scripts/kb_regression_suite.py` (+ `--remote http://20.127.25.24:8447`).
2. Revisar `Test_local/reports/kb_regression_*.json`.
3. Promover expresiones fallidas al `kb_faq_overlay_fase1.json`.
4. `python scripts/index_kb_azure.py --sources faq,md`.
5. Redeploy 8447.

## Métricas
- Pass rate FAQ local ≥ 95% en variantes.
- Pass rate remoto ≥ 90% en muestra.
- Tasa de `cognitive_turn_failed` ≈ 0.
- % Foundry vs FAQ (observabilidad).

## Conclusión
El modelo que mejor se adapta a esta app es un **sistema híbrido de aprendizaje continuo**:
embeddings + ranking FAQ + feedback store + Foundry grounded,
no una red neuronal aislada.
