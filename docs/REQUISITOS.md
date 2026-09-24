# Requisitos para enseñar a responder

Qué necesita la banca conversacional para dar respuestas correctas, auditables y
sin alucinaciones.

## 1. Sesión autenticada + contexto de productos

| Requisito | Detalle |
|-----------|---------|
| Cliente autenticado | Sin sesión no hay datos personales |
| Snapshot de portafolio | API `GET /products/v1/get-products-by-customer-id` mapeado a `CustomerContextSnapshot` |
| Semántica de campos | Respetar `docs/context-api/casos-de-uso.md` (TC ≠ CA en `availableBalance`) |
| TTL de snapshot | Redis / store con edad controlada |

Sin esto: solo puede responder información general (FAQ/RAG), nunca saldos.

## 2. Base de conocimiento versionada

| Artefacto | Rol |
|-----------|-----|
| Excel VF01 (negocio) | Fuente editable por producto / compliance |
| `data/kb_faq_vf01.json` | Runtime FAQ |
| `data/kb_faq_overlay_fase1.json` | Expresiones coloquiales / hotfixes sin reimportar todo |
| `docs/business-rules/*.md` | Memoria humana + indexable |
| Índice Azure `genesis-kb` | RAG vectorial |

Cada regla debería poder expresar (ideal Fase 2):

- expresiones del cliente  
- respuesta esperada  
- ¿pedir aclaración?  
- ¿escalar a humano?  
- canal / producto  

## 3. Catálogo cerrado de capacidades

Solo intents del `capability_catalog` (saldos, tarjetas, préstamos, DAP, knowledge, alcance).
Todo lo demás → unsupported / out of scope / humano.

## 4. Canales y tono

- Español claro, sin jargon interno (Genesis, RAG, Knowledge_Base).  
- Enmascaramiento de cuentas/tarjetas.  
- No inventar montos ni comisiones.

## 5. Infraestructura mínima

| Componente | Obligatorio |
|------------|-------------|
| API cognitive (`/turn`) | Sí |
| Azure OpenAI (clasificadores / RAG gen) | Sí para rutas no fast-path |
| Azure AI Search | Recomendado (RAG); sin él hay FAQ + fallbacks |
| Redis (sesiones) | Recomendado en contenedores |
| Credenciales Core / lab fallback | Según entorno |

## 6. Calidad y regresión

- Suite unitaria de guardrails (Fase 1 + field).  
- Matriz de frases (`Test_local/data/escenarios*.json`).  
- Métricas objetivo: FAQ hit rate, clarification rate, escalation rate, reformulations.
