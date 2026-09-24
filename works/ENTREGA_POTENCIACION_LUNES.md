# Entrega — Potenciación Lunes strict-v2.2

Fecha: 2026-09-20.

## Versión final

- Código: **`potenciacion-strict-v2.2`**
- Oráculo: **`strict_v2.2`**
- KB: `bsc-kb-2026-09-19-candidate-1`
- Entorno: QA `:8447` · lab_fallback · cliente **726588** · Core no vivo
- Backend externo / frontend / WebSocket: **intactos**
- ZIP: `works/qa_runs/EVIDENCIAS_POTENCIACION_LUNES_STRICT_V22.zip`
- SHA256: `4EC31D314A66723A34EE02632233581B130FB51D3487C90DE4A0328D1DCA962A`

## Correcciones de esta iteración

1. **Producto–evidencia (CC02/L10)**  
   Validación de aplicabilidad del documento al producto pedido; rechazo Platinum←Joven.  
   Comparación por atributos equivalentes o «no documentado».  
   Test negativo: `test_rejects_cc02_platinum_with_joven_evidence`.

2. **Oráculos**  
   Aserciones tipadas ampliadas (L02–L07, L11–L12, MIX07, CC03, …).  
   Sin oráculo tipado → **`PENDING_EVALUATION`** (no FAIL funcional ni PASS).  
   Reevaluación canónica all: `reeval_strict_v2.2_20260920T203909Z_d83c1c54` (78 PENDING).

3. **Cancelación L09/MIX10**  
   Respuesta acredita `LoanSnapshot.payoff_amount`, significado, origen y frescura.  
   Si solo hay `outstanding_principal` → limitación explícita (PARTIAL).

4. **Ruta real**  
   Telemetría leída desde `audit.decision_trace`.  
   Distingue `STRUCTURED_SHORTCUT` / `AZURE_OPENAI`+`model_invoked` / `DETERMINISTIC_FASTPATH` / `UNDECLARED`.  
   VM Azure ≠ inferencia de modelo.

5. **Evidencia visual**  
   Prompt `Prompt_Cursor_Validacion_Guia_Columna_Fix.md` ejecutado.  
   UI HTTP 200; capturas **PENDING_UI** (timeout descarga Chromium Playwright).  
   Guía: `works/qa_runs/guia_columna_fix.md`.

6. **Checksums primera corrida**  
   `manifest.json` y `resumen.md` de `5c7a2597` / `d0453ded` / `3dee5fcc` **coinciden** con sus `checksums.sha256`.  
   Ver `works/qa_runs/CHECKSUM_DISCREPANCIA_PRIMERA_CORRIDA.md`.

## P0 final

Run: `works/qa_runs/20260920T201855Z_c6702543`  
Reevaluación (mismo oráculo, 0 flips): `reeval_strict_v2.2_20260920T201855Z_c6702543`

| Métrica | Valor |
|---|---|
| Ejecutados | 40/40 |
| PASS_RESOLVED | **34** |
| PARTIAL_CAPABILITY | **6** |
| FAIL_* | **0** |
| PENDING_EVALUATION | **0** |

Prioritarios: CC02/L10/L09/MIX10/MIX09/L08/P12 PASS; P02 PARTIAL (movimientos ausentes).

Rutas (muestra de turnos): STRUCTURED_SHORTCUT 64 · AZURE_OPENAI/`model_invoked` 9 · DETERMINISTIC_FASTPATH 3 · UNDECLARED 5.

## Matriz 236

Ejecución: `works/qa_runs/20260920T203909Z_d83c1c54` (histórico intacto; clasificó mal `no_oracle` como FAIL).  
**Clasificación canónica** (reeval same oracle): `works/qa_runs/reeval_strict_v2.2_20260920T203909Z_d83c1c54`

| Estado | Ejecución cruda | Reevaluación canónica |
|---|---|---|
| PASS_RESOLVED | 42 | 42 |
| PASS_CLARIFICATION_EXPECTED | 7 | 7 |
| PARTIAL_CAPABILITY | 10 | 10 |
| FAIL_INTERPRETATION | 140 | **62** |
| FAIL_RETRIEVAL | 5 | 5 |
| FAIL_GROUNDING | 32 | 32 |
| FAIL_STATE | 0 | 0 |
| PENDING_EVALUATION | 0 | **78** |

Comparado con all v2.1 (`…3e71ec52`): PASS 30→42; FAIL_STATE 14→0; aparece FAIL_GROUNDING (producto–evidencia).  
Los 78 PENDING no cuentan como fallo funcional del sistema.

## Limitaciones

- Core vivo no disponible.
- Capturas UI pendientes (Playwright browser download timeout).
- 78 casos sin oráculo tipado → PENDING_EVALUATION.
- Sin cambios PROD.

