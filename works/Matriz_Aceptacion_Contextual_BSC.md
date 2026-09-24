# Matriz de aceptación contextual BSC

Fecha: 2026-09-19. Criterios del prompt de interpretación contextual.
Ejecución vía `POST /turn` (no solo `/inspect`).

## Escenarios obligatorios

| ID | Pregunta / recorrido | Expectativa |
|---|---|---|
| AX-TJ-01 | ¿Cuál es el saldo de mi tarjeta joven? | Resuelve alias; campo deuda (convención); sin preguntar qué tarjeta si es inequívoca |
| AX-TJ-02 | ¿Cuál es la tasa de mi tarjeta joven? | Tasa del producto resuelto o ausencia justificada |
| AX-PAY-01 | ¿Cuál es mi fecha límite de pago? | Aclara solo entre productos con fecha de pago (puente fastpath) |
| AX-REC-01 | ¿Cómo realizo una reclamación? | Proceso/canales; no «definición» genérica |
| AX-FAL-01 | ¿Cuál es el proceso de clientes fallecidos? | Procedimiento KB; no definición de «cliente» |
| AX-P01 | Deuda + disponible + fecha de tarjeta | Multi-campo; una selección conserva los tres |
| AX-RATE-DEF | Tasa de mi préstamo y qué significa | Dato personal + definición; no pierde ninguna |
| AX-CORR-MIS | No, la corriente; además dime la misión | Corrección cuenta + institucional |
| AX-MIX07 | Tras Multicrédito: ¿tengo yo ese producto? | Existencia catálogo→personal; no saldo de cuenta |
| AX-SEC | Mensaje con PIN/OTP | Sanea; no usa secreto como sufijo |

## No usar como oráculo

Etiquetas históricas de la guía (Cumple / parcial / No cumple). Contradicciones visuales: TC03, GR03, GR09.

## Fixture local

Portafolio sintético `qa_726588_contract_demo.json` (incluye Tarjeta Joven). Cliente QA real 726588: si Core no trae Tarjeta Joven → `NOT_APPLICABLE` en remoto.
