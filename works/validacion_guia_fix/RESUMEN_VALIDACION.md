# Resumen validación guía — columna fix (strict-v2.2 continuación)

Fecha UTC: 2026-09-21

## Fuente
- ZIP original / guía: conservados bajo `works/validacion_guia_fix/source/`
- Inventario: 236 IDs

## Ejecución canónica
- Oráculo: `strict_v2.2`
- Código: `potenciacion-strict-v2.2`
- Cliente QA: 726588 · lab_fallback · Core no vivo
- API: `20260921T004314Z_strict_v22_oracle_guide` (turnos de `20260920T203909Z_d83c1c54` + reeval oráculos guía)
- PENDING_EVALUATION: **0** (antes 78)
- UI: `20260921T004500Z_chrome_p0fix` (8 casos Chrome channel) + histórico `20260920T200903Z_ba3ee002`

## Conteos columna fix
- RESUELTO: 16
- PARCIAL: 69
- FALLA: 151

## Notas de esta iteración
- P12: oráculo exige ventana temporal; PARTIAL hasta redeploy QA con cálculo explícito
- L09/MIX10: acreditación por audit, no por nombrar `payoff_amount` en texto
- Comparaciones: valores concretos; se mantiene veto Joven bajo Platinum
- Capturas: automatización OK vía Chrome instalado; resto PENDING_UI

## Limitaciones
- Redeploy cognitivo a `:8447` pendiente (sin SSH en esta sesión)
- Core vivo no disponible
- Sin cambios PROD / backend externo
