# Guía para funcional — cómo llenar las hojas (con ejemplos)

## Idea general

No les pedimos YAML ni arquitectura.  
Les pedimos **tablas en Excel / Google Sheets** (exportables a CSV).

Ustedes escriben en español de negocio.  
Nosotros después lo convertimos a Markdown/tests/FAQ para alimentar la IA.

---

## 1) Hoja `FUNC_intenciones` — “¿Qué quiere el cliente?”

Cada fila = un tipo de pregunta.

| Columna | Qué poner | Ejemplo |
|--------|-----------|---------|
| pregunta_en_cristiano | En una frase, qué quiere | El cliente quiere saber de cuánto es la cuota |
| frases_del_cliente | Varias formas de decirlo, separadas por ` \| ` | `Cuanto es mi proxima cuota? \| De cuanto es mi letra?` |
| que_debe_responder | Resultado correcto | Decir el monto de la cuota… |
| que_NO_debe_hacer | Errores que ya vimos o queremos evitar | No responder con la fecha |
| si_hay_varias_opciones | preguntar / listar todas / usar la de la conversación | Si hay varios préstamos preguntar cuál |
| si_falta_el_dato | Texto que debe decir el bot | No tengo el monto de la cuota… |
| familia | personal / conocimiento / proceso | personal |
| producto | prestamo / tarjeta_credito / dap / mixto… | prestamo |

### Ejemplo ya lleno (fila)

> **pregunta_en_cristiano:** El cliente quiere saber de cuánto es la cuota de su préstamo  
> **frases:** `Cuanto es mi proxima cuota? | De cuanto es mi letra?`  
> **debe:** monto de la cuota o “no disponible”  
> **no debe:** contestar con la fecha `2026-08-25`  
> **si faltan datos:** mensaje con capital/tasa/fecha + call center  

Ver archivo completo: `ejemplos/FUNC_intenciones_EJEMPLO.csv`

---

## 2) Hoja `FUNC_dialogos` — “Conversación de varios mensajes”

Aquí se prueba la **memoria** (que no se olvide del producto a mitad de chat).

| Columna | Ejemplo |
|--------|---------|
| dialogo_id | `GOLD-001` (mismo id en varios turnos) |
| turno | 1, 2, 3… |
| mensaje_usuario | lo que escribe el cliente |
| que_debe_pasar | checklist en texto |
| que_NO_debe_pasar | errores prohibidos |

### Ejemplo de diálogo corto

**Turno 1**  
Usuario: `Cuanto debo en mis tarjetas de credito y cual tiene mas disponible?`  
Debe: resumen de **todas** las tarjetas  
No debe: pedir elegir una  

**Turno 2**  
Usuario: `y el pago minimo de la 6374?`  
Debe: pago mínimo de esa tarjeta  
No debe: cambiarse a la otra tarjeta  

Archivo: `ejemplos/FUNC_dialogos_EJEMPLO.csv`

---

## 3) Hoja `FUNC_fallos_semana` — “Lo que falló en pruebas”

Muy fácil: copiar del chat.

| Columna | Ejemplo |
|--------|---------|
| frase_exacta_del_usuario | `Tengo algun prestamo o tarjeta con un pago proximo?` |
| que_respondio_el_bot | Ficha del certificado 5511 |
| que_debia_responder | Listar préstamo y tarjetas con fechas |
| gravedad | bloqueante / molesto / cosmético |

Archivo: `ejemplos/FUNC_fallos_semana_EJEMPLO.csv`

---

## 4) Hoja `FUNC_datos_core` — “¿El banco tiene el dato?”

| Columna | Ejemplo |
|--------|---------|
| pregunta_del_cliente | Monto de la cuota del préstamo |
| existe_hoy | NO |
| que_decir_si_no_esta | texto aprobado |
| responsable | Core / Funcional |
| prioridad | P0 |

Archivo: `ejemplos/FUNC_datos_core_EJEMPLO.csv`

---

## 5) Hoja `FUNC_faq_frases` — “Preguntas del banco (no de mi saldo)”

| Columna | Ejemplo |
|--------|---------|
| frases_del_cliente | `que es un DAP? \| que es certificado de deposito?` |
| respuesta_que_debe_dar_el_bot | definición oficial |
| no_debe | no dar el saldo del DAP del cliente |

Archivo: `ejemplos/FUNC_faq_frases_EJEMPLO.csv`

---

## Cómo se lo entregamos a funcional (mensaje listo para pegar)

> Hola, para mejorar la IA del banco no necesitamos documentos técnicos.  
> Por favor llenen estas 5 hojas en Excel/Sheets (hay ejemplos):  
> 1) Intenciones — qué pregunta el cliente y qué debe responder  
> 2) Diálogos — 2 o 3 mensajes seguidos  
> 3) Fallos de la semana — frase real + lo que debió decir  
> 4) Datos Core — qué dato falta en sistemas  
> 5) FAQ — preguntas de conocimiento del banco  
> Con eso nosotros lo convertimos y afinamos el bot en QA.

---

## Qué hacemos nosotros después (transformación)

1. Abrimos los CSV en Excel/Sheets que ellos compartan.  
2. Convertimos cada fila a:
   - tests golden  
   - entradas de FAQ overlay  
   - reglas de routing / intención  
   - backlog Core  
3. Generamos un Markdown interno del ciclo (`FUNC-2026-Wxx.md`) para trazabilidad.  
4. Desplegamos en :8447 y marcamos pass/fail.

### Vista previa: cómo se vería transformado (nosotros, no funcional)

```markdown
## Intent LOAN_CUOTA_MONTO
- Frases: Cuanto es mi proxima cuota? | De cuanto es mi letra?
- Debe: monto cuota
- No debe: fecha de pago
- Test: test_cuanto_proxima_cuota_is_amount_not_date
```

```markdown
## Diálogo GOLD-003
1. "Que es un certificado..." → KB definición
2. "Tengo prestamo o tarjeta con pago proximo?" → romper foco DAP; listar pagos
```
