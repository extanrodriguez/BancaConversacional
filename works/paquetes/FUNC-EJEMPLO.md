# Paquete funcional transformado (para cognitiva / IA)

> Generado automáticamente desde CSV del formato funcional.

## 1. Intenciones

### `LOAN_CUOTA_MONTO` (P0)
- **Familia/producto:** personal / prestamo
- **En cristiano:** El cliente quiere saber de cuánto es la cuota de su préstamo
- **Frases:** Cuanto es mi proxima cuota? | De cuanto es mi letra? | Cual es el monto de la cuota?
- **Debe:** Decir el monto de la cuota en pesos si existe; si no existe decir que no está disponible y ofrecer capital/tasa/fecha
- **No debe:** No responder con la fecha de pago; no inventar la cuota; no hablar del certificado DAP
- **Si hay varias:** Si tiene varios préstamos preguntar cuál; si solo hay uno responder directo
- **Si falta dato:** No tengo el monto de la cuota contractual en este momento. Puedo indicarte capital pendiente tasa o próxima fecha de pago. También BSC en Línea o 809.726.1000
- **Dato sistema:** cuota contractual del préstamo

### `LOAN_CUOTA_FECHA` (P0)
- **Familia/producto:** personal / prestamo
- **En cristiano:** El cliente quiere saber cuándo paga la próxima cuota
- **Frases:** Cuando es mi proxima cuota? | Cuando me toca pagar la letra? | Cual es la proxima fecha de pago del prestamo?
- **Debe:** Decir la próxima fecha de pago del préstamo
- **No debe:** No dar el monto como si fuera la fecha; no confundir con vencimiento final del préstamo
- **Si hay varias:** Si hay varios préstamos preguntar cuál
- **Si falta dato:** La fecha de pago no está disponible en este momento
- **Dato sistema:** next_due_date

### `CARD_RESUMEN_TODAS` (P0)
- **Familia/producto:** personal / tarjeta_credito
- **En cristiano:** El cliente quiere info de todas sus tarjetas (deuda y/o disponible)
- **Frases:** Cuanto debo en mis tarjetas y cual tiene mas disponible? | Cuanto debo en mis tarjetas de credito?
- **Debe:** Resumir TODAS las tarjetas de crédito: adeudado y disponible; decir cuál tiene más disponible
- **No debe:** No pedirle que elija una tarjeta; no mostrar DAP; no tratar débito como crédito si pidió débito
- **Si hay varias:** Listar todas (no aclarar)
- **Si falta dato:** N/A
- **Dato sistema:** saldo adeudado y disponible de cada TC

### `CARD_DEBITO_PERSONAL` (P0)
- **Familia/producto:** personal / tarjeta_debito
- **En cristiano:** El cliente pregunta por SUS tarjetas de débito
- **Frases:** Cuanto debo en mis tarjetas de debito? | Saldo de mi tarjeta de debito
- **Debe:** Explicar que en el portafolio consultable no figuran débito como producto (van ligadas a cuentas) y ofrecer saldo de cuentas o preguntar si quiso crédito
- **No debe:** No listar tarjetas de crédito como si fueran débito; no forzar elección de TC
- **Si hay varias:** Si el mensaje mezcla débito y crédito disponible preguntar: ¿Te refieres a tus tarjetas de crédito?
- **Si falta dato:** Según política de tono aprobada
- **Dato sistema:** producto débito / vínculo a cuenta

### `PAGO_PROXIMO_MIXTO` (P0)
- **Familia/producto:** personal / mixto
- **En cristiano:** El cliente pregunta si tiene préstamo O tarjeta con pago próximo
- **Frases:** Tengo algun prestamo o tarjeta con un pago proximo?
- **Debe:** Listar préstamos y tarjetas con su fecha de pago o corte
- **No debe:** No responder con ficha de certificado DAP; no quedarse pegado a un producto anterior de la conversación
- **Si hay varias:** Incluir ambos tipos si el cliente dijo préstamo o tarjeta
- **Si falta dato:** No encontré préstamos ni tarjetas con fecha de pago en tu portafolio
- **Dato sistema:** next_due_date y/o fecha límite/corte TC

### `KB_QUE_ES_DAP` (P0)
- **Familia/producto:** conocimiento / dap
- **En cristiano:** El cliente quiere saber qué es un certificado / DAP
- **Frases:** Que es un certificado de deposito? | Que es un DAP? | Que es deposito a plazo?
- **Debe:** Definición institucional del producto de inversión a plazo
- **No debe:** No dar saldo del DAP del cliente; no confundir con préstamo con garantía de certificado
- **Si hay varias:** Si dice garantía/préstamo aclarar ambas opciones
- **Si falta dato:** Según KB
- **Dato sistema:** N/A conocimiento

## 2. Diálogos golden

### `GOLD-001`
- **Turno 1** (`usuario1`)
  - Usuario: Cuanto debo en mis tarjetas de credito y cual de ellas tiene mas credito disponible?
  - Debe: Mostrar resumen de todas las TC con adeudado y disponible; indicar cuál tiene más disponible
  - No debe: Pedir elegir una sola tarjeta; hablar de DAP
  - Notas: Plural = resumen
- **Turno 2** (`usuario1`)
  - Usuario: y el pago minimo de la 6374?
  - Debe: Responder solo pago mínimo de la tarjeta 6374
  - No debe: Cambiar a otra tarjeta; devolver ficha completa
  - Notas: Debe recordar el hilo y el dígito

### `GOLD-002`
- **Turno 1** (`usuario1`)
  - Usuario: Cuanto es mi proxima cuota?
  - Debe: Respuesta de MONTO de cuota (o no disponible) del préstamo en foco
  - No debe: Responder con la fecha de pago
  - Notas: Cuánto ≠ cuándo
- **Turno 2** (`usuario1`)
  - Usuario: y cuando es?
  - Debe: Ahora sí la próxima fecha de pago
  - No debe: Volver a hablar de monto
  - Notas: Follow-up de fecha sobre el mismo préstamo

### `GOLD-003`
- **Turno 1** (`usuario1`)
  - Usuario: Que es un certificado de deposito?
  - Debe: Definición KB de DAP/inversión
  - No debe: Mostrar capital/tasa del DAP personal 5511
  - Notas: Conocimiento ≠ personal
- **Turno 2** (`usuario1`)
  - Usuario: Tengo algun prestamo o tarjeta con un pago proximo?
  - Debe: Resumen de préstamos/tarjetas con fechas de pago
  - No debe: Seguir hablando del certificado 5511
  - Notas: Debe soltar el foco del DAP

### `GOLD-004`
- **Turno 1** (`usuario1`)
  - Usuario: Cuanto debo en mis tarjetas de debito?
  - Debe: Decir que no hay débito como producto consultable; ofrecer cuentas o preguntar si quiso crédito
  - No debe: Ofrecer Credito Joven 6374 / Multicredito 7111 para elegir
  - Notas: No confundir débito con crédito

## 3. Fallos de la semana

### `F-001` — bloqueante
- **Fecha:** 2026-09-14
- **Usuario:** Cuanto es mi proxima cuota?
- **Bot dijo:** …la próxima fecha de pago… es 2026-08-25
- **Debía:** Monto de la cuota o aviso de que el monto no está disponible
- **Comentario:** Confundió cuánto con cuándo

### `F-002` — bloqueante
- **Fecha:** 2026-09-14
- **Usuario:** Cuanto debo en mis tarjetas de debito y cual de ellas tiene mas credito disponible?
- **Bot dijo:** ¿Quieres consultar: Credito Joven 6374 o Multicredito 7111?
- **Debía:** No listar crédito como débito; explicar débito no consultable o preguntar si quiso crédito; si es crédito resumir todas
- **Comentario:** Pidió débito y además no debía forzar elección

### `F-003` — bloqueante
- **Fecha:** 2026-09-14
- **Usuario:** Tengo algun prestamo o tarjeta con un pago proximo?
- **Bot dijo:** Ficha del Certificado de Depósito 5511
- **Debía:** Listar préstamo(s) y tarjeta(s) con fecha de pago/corte
- **Comentario:** Se pegó al DAP de la sesión anterior
