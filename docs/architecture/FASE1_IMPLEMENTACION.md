# Fase 1 — Implementación

Corrige los 6 issues reportados y el mismo patrón de fallos similares.

## Issues → fix

| # | Síntoma | Fix |
|---|---------|-----|
| 1 | `Mision` no detecta; frase larga sí | FAQ: keywords cortas institucionales + overlay expresiones |
| 2 | `hablame del banco` → asesor | Entrada institucional overlay + fallback RAG institucional |
| 3 | Reclamación vuelca manual | `reclamacion_guardrail` pide canal primero |
| 4 | `en qué me puedes ayudar` → eco saludo | `scope_guardrail` lista capacidades según portafolio |
| 5 | `QUE ES BANCO SANTA CRUZ` → asesor | Overlay `fase1-banco-santa-cruz` + fallback |
| 6 | `COÑO` → saludo | `moderation.py` redirección neutral |

## Archivos nuevos / tocados

```
src/genesis_cognitive/router/moderation.py
src/genesis_cognitive/router/scope_guardrail.py
src/genesis_cognitive/router/reclamacion_guardrail.py
src/genesis_cognitive/router/faq_guardrail.py          (umbrales + overlay)
src/genesis_cognitive/router/field_guardrails.py       (orden fast-path)
src/genesis_cognitive/rag/local_rag.py                 (fallback institucional)
src/genesis_cognitive/demo/contract_inspector_app.py   (pending reclamación + FAQ fallback)
data/kb_faq_overlay_fase1.json
scripts/export_docs_from_excel.py
docs/**                                               (esta documentación)
tests/unit/test_fase1_orchestration.py
```

## Variables de entorno (contenedor-friendly)

| Variable | Default | Uso |
|----------|---------|-----|
| `GENESIS_FAQ_PATH` | `data/kb_faq_vf01.json` | FAQ principal |
| `GENESIS_FAQ_OVERLAY_PATH` | junto al FAQ (`kb_faq_overlay_fase1.json`) | Expresiones / entradas Fase 1 |
| `GENESIS_FAQ_INSTITUTIONAL_MIN_SCORE` | `0.65` | Umbral FAQ corto institucional |
| `GENESIS_PROFANITY_EXTRA` | vacío | Términos extra (CSV) |
| `GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL` | `1` | No escalar institucionales |
| `GENESIS_API_EXCEL_PATH` | — | Export docs API |
| `GENESIS_KB_EXCEL_PATH` | — | Export docs KB |
| `GENESIS_DOCS_OUT_DIR` | `docs/` | Destino export |

## Cómo probar

```powershell
# Local
pytest tests/unit/test_fase1_orchestration.py -q
$env:GENESIS_VALIDATE_BASE="http://127.0.0.1:8445"
python Test_local/validate_fase1_cases.py

# QA 8447 (instancia de evolución)
.\.venv\Scripts\python.exe .\deploy\corp-8446\build_corp_package.py
$env:SSH_DEPLOY_PASS="..."
$env:SSH_HOST="20.127.25.24"
.\.venv\Scripts\python.exe .\deploy\corp-8447\deploy_ssh_password.py
$env:GENESIS_VALIDATE_BASE="http://20.127.25.24:8447"
python Test_local/validate_fase1_cases.py
```

UI QA: http://20.127.25.24:8447/pruebas
