# Documentación — Banca Conversacional Genesis

Documentación canónica para operar, enseñar y evolucionar el asistente conversacional
de Banco Santa Cruz. Preparada para despliegue en contenedores.

## Índice

| Sección | Contenido |
|---------|-----------|
| [Arquitectura FAQ + RAG](architecture/ORQUESTACION_FAQ_RAG.md) | Orquestación unificada, capas, routing |
| [Fase 1 — implementación](architecture/FASE1_IMPLEMENTACION.md) | Moderación, alcance, FAQ, reclamaciones, RAG |
| [API de contexto](context-api/README.md) | Campos del servicio de productos del cliente |
| [Reglas de negocio](business-rules/README.md) | KB exportada desde Excel VF01 |
| [Requisitos](REQUISITOS.md) | Qué necesita el sistema para responder bien |
| [Enseñar y evolucionar](ENSENAR_Y_EVOLUCIONAR.md) | Cómo añadir conocimiento sin redeploy frágil |
| [Contenerización](CONTAINERIZACION.md) | Variables, volúmenes, imagen Docker |
| [Deploy VM](DEPLOY_VM.md) | Despliegue en laboratorio / VM |
| [Gaps conocidos](KNOWN_GAPS.md) | Deuda técnica previa |

Flujo mental (una frase)

**Higiene → reglas deterministas (FAQ / alcance / procesos) → LLM solo si hace falta → RAG grounded → escalación humana solo como último recurso.**

## Instancia de evolución

Trabajar y validar cambios en **QA :8447** (`http://20.127.25.24:8447/pruebas`).
El puerto local 8445 es solo desarrollo; 8446 es legacy y no se toca en deploys 8447.

## Fuentes de verdad

1. **Excel de negocio** → import / export scripts → `data/kb_faq_vf01.json` + `docs/business-rules/`
2. **API Productos** → `docs/context-api/` + mapper `core_portfolio_mapper.py`
3. **Código de routing** → `src/genesis_cognitive/router/`
4. **RAG Azure** → índice `genesis-kb` + `local_rag.py`

Regenerar MD desde Excel (local o CI):

```bash
python scripts/export_docs_from_excel.py \
  --api-excel "$GENESIS_API_EXCEL_PATH" \
  --kb-excel "$GENESIS_KB_EXCEL_PATH" \
  --out-dir docs
```
