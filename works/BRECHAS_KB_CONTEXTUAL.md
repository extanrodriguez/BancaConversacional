# Brechas KB / contexto — interpretación contextual

Fecha: 2026-09-19.

## KB / recuperación

| Entidad / faceta | Evidencia | Tipo de brecha |
|---|---|---|
| TC03 / GR09 «cliente» vs producto comercial | Capturas históricas responden definición de cliente | Clasificación errónea / query insuficiente (mitigado FAQ: no lockear responsabilidad-cliente ante «mi tarjeta»/«tarjeta joven») |
| GR03 reclamación | Histórico muestra capital de préstamo | Recuperación irrelevante histórica; bridge actual usa `reclamacion_guardrail` |
| Movimientos de cuenta (P02/P06/P14) | Capacidad `movements` marked unsupported en plan | **Capacidad no soportada** en snapshot cognitivo |
| Saldo al corte (tarjeta) | No hay campo `statement_balance` expuesto como faceta semántica unificada en plan | Brecha de contrato/campo |
| Intereses generados DAP con cálculo | Solo `interest_amount` si Core lo trae; no se calcula | Ausencia / no inventar |

## Contexto / portafolio

| Tema | Nota |
|---|---|
| Core vivo 726588 | Puede ser flaco (sin TC/DAP); lab `qa_726588_contract_demo` sí tiene Tarjeta Joven |
| Completitud | Proyección marca `portfolio_completeness=lab_fallback\|unknown`; no declarar inventario completo |
| Casos_Guia 236 multi-turno | 26 `NOT_EXECUTED` en runner local (requieren sesión multi-turno) |

## Fuera de capa cognitiva

- Orquestador externo / UI APK / WebSocket productivo.
- Publicar corpus Foundry para cerrar brechas de contenido.
- Otros clientes reales ≠ 726588.
