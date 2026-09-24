# BRECHAS_PENDIENTES

Fecha: 2026-09-21.

| ID | Causa | Impacto | Siguiente acción |
|---|---|---|---|
| B1 | Redis QA inalcanzable desde PC | Sin CAS/lock multi-réplica real; sesión solo memoria | Probar desde VM con Entra; no abrir red ad-hoc |
| B2 | Índice Search mezcla conocimiento + filas matriz VF01 | Definiciones sensibles (saldo disponible) sin hit limpio → glosario local | Índice candidato separado o exclusión por `document_type`/`source_scope`; **no** borrar activo |
| B3 | Verifier → CLARIFICATION vacía en vencimientos abiertos | Plan LLM no acreditable; depende de structural_repair P12 | Medir tasa reparación; ajustar schema/prompt sin quitar verifier aún |
| B4 | Suites 141+95 completas no cerradas | Subset 20/141: 13 PASS / 5 PARTIAL / 2 FAIL (`20260921T092444Z_59eeca0f`) | Completar 141+95 sobre mismo build `:8445`/VM |
| B5 | Payoff/cancelación: bindings sin fuente Core explícita | Riesgo de semántica incorrecta si se infiere domestic≠principal | Mantener BLOCKED_DATA hasta contrato documentado |
| B6 | Capturas UI QA | Sin `CAPTURED` del chat integrado | Tras deploy VM + orch |
| B7 | `GENESIS_KB_DIR=Knowledge_Base` incluye MD de matriz | Contaminación local si Search off | Preferir FAQ overlay + Search; no usar MD matriz como definición |
| B8 | Acceptance QA / 236 | Fuera de alcance local | Solo tras smoke VM + Redis ready |

## No confundir

- `SEARCH_REAL_PASS` en misión/Joven ≠ limpieza de los 980 docs.
- `structural_repair` ≠ interpretación semántica del modelo.
- Grupo representativo 8/8 ≠ suites 141/95.
