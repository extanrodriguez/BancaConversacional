# Estrategia de conversación fluida — FAQ ↔ RAG ↔ Portafolio

## Objetivo

El cliente debe poder **cambiar de tema en cualquier orden** (banco →
préstamos → reclamaciones → mis productos → banco otra vez) y recibir
siempre una respuesta real, grounded y coherente. La moderación de
lenguaje es la primera capa.

## Capas (orden fijo)

```
1. Moderación (groserías)          → template / NON_OPERATIONAL
2. Reclamaciones (clarificación)   → overview KB + canal opcional
3. Portafolio / saldo / préstamos  → snapshot de la SESIÓN
4. Alcance / saludo
5. FAQ (atajos de alta confianza)  → kb_faq + overlay
6. Intent KB (si FAQ miss)         → kb_intent_resolver (FAQ+MD)
7. Azure RAG                       → chunks indexados
8. Fallback institucional / humano → último recurso
```

**Principio:** no grabar todas las frases en FAQ. FAQ = atajos frecuentes.
Si no hay match fuerte → interpretar intención sobre el corpus → RAG.

## Cambio de tema (pendings)

- Un pending (canal de reclamación, desambiguación de préstamo, etc.)
  **no debe atrapar** la conversación.
- Si el usuario pregunta otra cosa (productos, banco, saldo, catálogo),
  se libera el pending y responde el guardrail correcto.
- Tras overview de reclamaciones puede quedar un pending *suave* solo
  para detalle de canal; cualquier cambio de tema lo cancela.

## Contexto de usuario (snapshot)

| Evento | Qué pasa |
|--------|----------|
| Login / `context_info=true` | Se carga snapshot y se guarda **en la sesión** |
| Cada turno de la misma `conversation_id` | Se renueva la vida de la sesión (+contexto) |
| Logout / expiración por inactividad de sesión | Snapshot **inválido** |
| Nueva sesión | Hay que volver a cargar contexto |

**El contexto no caduca por un TTL corto independiente.** Vive lo que
viva la sesión (`GENESIS_SESSION_TTL_S`, por defecto ~30 min de
inactividad). Variable `GENESIS_SNAPSHOT_TTL_S=session` (default).

> Futuro: recarga de productos desde Core on-demand. Hoy el snapshot
> de la sesión es la fuente de verdad personal.

## FAQ ↔ RAG (sincronía)

| Origen | Uso |
|--------|-----|
| Excel VF01 → `kb_faq_vf01.json` | Corpus canónico + expresiones |
| `kb_faq_overlay_fase1.json` | Frases coloquiales / catálogos sin reimportar Excel |
| `Knowledge_Base/excel_vf01/*.md` | Intent resolver + índice RAG |
| Azure RAG | Parafraseos / documentos largos |

Regla: misma respuesta de negocio debe poder citarse a un `id` FAQ o
sección MD. Si RAG inventa o escala a humano en un tema que está en
FAQ, se considera bug de orquestación (falta intent/FAQ antes de humano).

## Moderación

Capa 0 (`moderation.py`): insultos → respuesta de contención profesional,
sin eco de saludo vacío y sin inventar datos de portafolio.

## Foco de producto (préstamo) y reanudación

| Campo | Rol |
|-------|-----|
| `last_resolved` | Deíxis inmediata (último producto personal con ref) |
| `product_focus` | Memoria del **préstamo** consultado; **no** se pisa con FAQ/RAG/misión/saldo |

### Escenarios

| Flujo | Resultado esperado |
|-------|-------------------|
| Préstamo 27615 → "qué tasa tiene" | Tasa del snapshot (12.5%), no glosario FAQ |
| Préstamo → misión del banco → "qué tasa tiene" | Reanuda el préstamo en foco (intent gate) |
| Préstamo → saldo cuenta → "qué tasa tiene" | Sigue el préstamo en `product_focus` |
| "qué es tasa de interés" (con o sin foco) | Definición FAQ/RAG (conocimiento) |
| LLM clasifica BUSINESS_KNOWLEDGE + hay foco + campo | Gate → snapshot **antes** de Azure RAG |

**Principio:** el RAG/intent solo **clasifica** personal vs definición. La tasa/cuota/mora
salen del snapshot de sesión, nunca se inventan.

## Checklist al añadir conocimiento

1. ¿Dato personal del cliente? → guardrail + snapshot (no FAQ).
2. ¿Frase frecuente institucional? → overlay FAQ + test.
3. ¿Parafraseo raro? → corpus MD + intent/RAG (no duplicar FAQ).
4. ¿Proceso multi-camino? → clarification-first (como reclamaciones).
5. ¿Grosería? → moderación.
6. ¿Campo deíctico de producto? → `product_focus` + intent gate, no FAQ.

## Pruebas recomendadas

```powershell
# Multi-tema tras KB
.\.venv\Scripts\python.exe Test_local\validate_multiturn_portfolio_after_kb.py

# Follow-up tasa + reanudación tras otro tema
.\.venv\Scripts\python.exe Test_local\validate_loan_tasa_followup.py

# Control aleatorio x20
.\.venv\Scripts\python.exe Test_local\validate_issues_random_20.py --rounds 20
```
