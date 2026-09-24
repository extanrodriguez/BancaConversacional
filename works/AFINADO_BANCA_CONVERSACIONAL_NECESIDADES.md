# Qué necesitamos para afinar la banca conversacional (AS-IS → “IA del banco”)

| Campo | Valor |
|-------|-------|
| **Fecha** | 2026-09-15 |
| **Objetivo** | Respuestas más acertadas, contexto de sesión continuo, interpretación fina de intención, sensación de IA bancaria real |
| **Prioridad** | Acierto > costo de tokens (por ahora) |
| **Audiencia** | Funcional / negocio + producto + Core/API + Azure AI + equipo cognitiva |
| **Instancia** | QA :8447 |

---

## 1. Visión de “IA del banco” (criterio de éxito)

Queremos que el usuario sienta:

1. **Me entiende** — interpreta intención aunque hable mal, mezcle temas o diga “débito” cuando quiere “crédito”.
2. **Me recuerda** — durante toda la sesión sabe de qué producto habla, qué preguntó antes y qué ya le respondimos.
3. **No inventa** — si no tiene el dato, lo dice y ofrece alternativa útil (canal, otro campo, aclaración).
4. **Sabe del banco** — respuestas institucionales grounded en KB oficial (FAQ + Foundry + Search).
5. **Parece conversación** — no un menú rígido; aclara solo cuando hace falta; resume varias tarjetas/préstamos cuando pide “todas”.

Esto **sí** puede apoyarse más en Azure AI (clasificadores, Foundry Agent, memoria de hilo, embeddings). Lo que **no** puede improvisar Azure es: saldos, cuotas, fechas personales y reglas de compliance sin fuente.

---

## 2. Resumen ejecutivo: ¿qué pedirle a funcional?

| # | Pedido a funcional | Por qué |
|---|--------------------|---------|
| 1 | **Matriz de intenciones canónicas** (personal vs conocimiento vs proceso vs fuera de alcance) con frases reales del APK | Hoy fallamos por frases ambiguas / coloquiales no cubiertas |
| 2 | **Golden set de conversaciones** (diálogos de 5–15 turnos) con respuesta esperada | Para medir “IA real” y regresión |
| 3 | **Reglas de desambiguación** (cuándo preguntar vs cuándo asumir vs cuándo listar todas) | Evita clarificaciones molestas y sticky de producto incorrecto |
| 4 | **Contrato de datos personales por pregunta** (qué campo Core debe venir) | Sin cuota / fecha TC / movimientos no hay respuesta “acertada” |
| 5 | **Glosario de sinónimos RD** (cuota=letra, DAP=certificado, etc.) | Mejora intención sin alucinar |
| 6 | **Política de tono y límites** (qué puede / no puede decir, escalación humana) | Consistencia de marca y riesgo |
| 7 | **Prioridad de productos y escenarios MVP+** (qué afinar primero) | Enfocar el effort donde duele más |
| 8 | **Validación semanal de fallos** (excel de bugs con frase exacta + esperado) | Circuito de aprendizaje continuo |

Abajo está el detalle accionable.

---

## 3. Pedidos concretos al equipo funcional / negocio

### 3.1 Matriz de intenciones (entregable #1)

Tabla Excel/Sheets con columnas:

| Columna | Ejemplo |
|---------|---------|
| `intent_id` | `LOAN_NEXT_PAYMENT`, `CARD_AVAILABLE`, `KB_WHAT_IS_DAP` |
| `familia` | personal / conocimiento / proceso / ood |
| `pregunta_canonica` | ¿Cuándo es mi próxima cuota? |
| `variantes_cliente` | 10–30 frases reales (“cuanto pago el 25”, “cuando me toca la letra”) |
| `producto_esperado` | préstamo / TC / DAP / cuenta / ninguno |
| `campo_dato` | `next_due_date`, `ledger_balance`, … |
| `si_ambiguo` | aclarar / listar todas / usar foco de sesión |
| `si_dato_faltante` | mensaje + CTA canal |
| `no_debe_hacer` | no devolver ficha completa; no ir a Foundry; no usar DAP |
| `prioridad` | P0 / P1 / P2 |

**Mínimo P0 a cubrir (ya vimos fallos reales):**

- Cuánto vs cuándo (cuota / pago).
- Débito vs crédito (portafolio personal).
- Resumen de **todas** las tarjetas vs elegir una.
- Préstamo **o** tarjeta con pago próximo (multi-producto).
- Follow-up corto (“y la tasa?”, “y la del banco?”, “cómo se usa?”).
- Fecha límite vs fecha de corte vs vencimiento del préstamo.
- Certificado de depósito vs préstamo con garantía de certificado.
- Reclamaciones (proceso completo, no cortado).

### 3.2 Golden conversations (entregable #2)

Al menos **30 diálogos** (ideal 80–100) con:

- Cliente de prueba (`customer_id`) y portafolio conocido.
- Turnos 1…N (no solo 1 pregunta).
- Cambio de tema a mitad (KB → personal → otra familia).
- Respuesta esperada por turno (texto o checklist: “debe incluir X”, “no debe mencionar Y”).
- Marca de severidad si falla (bloqueante / molesto / cosmético).

Sin esto no se puede afirmar “parece una IA”; solo se prueban frases sueltas.

### 3.3 Política de contexto de sesión (entregable #3)

Funcional debe decidir (por escrito):

| Situación | ¿Qué debe hacer el bot? |
|-----------|-------------------------|
| Usuario dijo “mi Visa 6374” y luego “¿y el disponible?” | Seguir en 6374 |
| Usuario hablaba de DAP y pregunta “¿tengo préstamo o tarjeta con pago próximo?” | **Romper** foco DAP; responder multi-producto |
| Usuario pide “mis tarjetas” con 2 TC | Listar / resumir **todas**, no forzar elección |
| Usuario pide un campo puntual tras clarificación | Solo el campo, no ficha completa |
| Usuario mezcla “débito” + “crédito disponible” | ¿Corregir suave? ¿preguntar? ¿asumir crédito? |
| Tras 10 turnos de KB, “¿cuánto debo?” | Volver a personal con snapshot, sin perder cliente |

Esto alimenta `product_focus`, `last_resolved`, `pending_action`, `last_knowledge_topic`.

### 3.4 Contrato de datos con Core / API Productos (entregable #4 — con TI Core)

Lista de campos **obligatorios** para respuestas “acertadas”:

| Pregunta del cliente | Campo necesario | Estado hoy (aprox.) |
|----------------------|-----------------|---------------------|
| Monto de la cuota del préstamo | cuota contractual / next installment | **Falta** en portafolio (hoy 0) |
| Próxima fecha de pago préstamo | `next_due_date` | Disponible |
| Fecha límite de pago TC | `payment_due_date` | **Débil / ausente** en snapshot |
| Fecha de corte TC | `cutoff_day` | Parcial |
| Disponible / adeudado TC | available / ledger | Disponible |
| Movimientos / últimos pagos | historial | **No disponible** |
| Tarjetas de débito como producto | tipo débito o vínculo cuenta | **No en portafolio** (solo TC) |
| Intereses / payoff préstamo | payoff, mora | Parcial |

**Pedido a funcional + Core:**

1. Confirmar endpoint / operación (`LOAN_QUERY`, `include_next_installment`, estado de cuenta TC, etc.).
2. Definir semántica exacta de cada campo (evitar usar mora como cuota).
3. SLA de frescura del snapshot (TTL Redis) aceptable para el negocio.
4. Qué decir al cliente cuando el dato no exista en Core (texto aprobado).

### 3.5 Base de conocimiento “viva” (entregable #5)

| Artefacto | Qué necesitamos de funcional |
|-----------|------------------------------|
| FAQ / overlay | Frases reales del APK + respuesta aprobada + score mínimo |
| Business rules MD | Actualización cuando cambie tarifario / proceso |
| Desambiguaciones | Lista oficial (DAP vs garantía; corte vs límite; derechos banco vs cliente) |
| Reclamaciones | Texto completo por canal, sin truncar contenido crítico |
| Catálogo productos | Nombres comerciales oficiales (Visa Joven, Multicrédito, …) |

**Ritual propuesto:** 1 vez/semana, funcional entrega “top 20 fallos de la semana” con frase exacta + esperado → se mete a overlay / test / reindex.

### 3.6 Tono, marca y límites (entregable #6)

- Tratamiento: “tú” vs “usted”; uso del nombre.
- Cuándo ofrecer Centro de Contacto / BSC en Línea.
- Qué nunca decir (tasas inventadas, consejos crediticios personalizados no soportados, jerga técnica “Core”).
- Escalación humana: en qué intents está permitida / prohibida.

---

## 4. Qué necesitamos en Azure AI (tecnología, priorizando acierto)

Aceptamos más tokens si sube precisión. Capas recomendadas:

### 4.1 Intención y reescritura (alta prioridad)

| Capacidad Azure | Uso |
|-----------------|-----|
| **Azure OpenAI — clasificador de intención** (JSON estricto) | `personal` / `knowledge` / `process` / `ood` + producto + campo + multi-intent |
| **Query rewrite / expand** | “y la del banco” → pregunta completa con `last_knowledge_topic` |
| **Multi-intent splitter** | “cuánto debo y cuál tiene más disponible” → 2 subtareas resueltas juntas |
| **Slot filling** | extraer últimos 4, moneda, tipo producto, horizonte temporal |

Entregable técnico: schema JSON de intención versionado + ejemplos few-shot aprobados por funcional.

### 4.2 Memoria de sesión (alta prioridad)

| Capacidad | Uso |
|-----------|-----|
| **Resumen de sesión** (LLM, cada N turnos) | Mantener “de qué hablamos” sin perder el hilo largo |
| **Entity memory** | producto activo, campos ya respondidos, clarificaciones abiertas |
| Redis (ya existe) | Persistir `product_focus`, `last_resolved`, resumen, topic KB |

Pedido: TTL de sesión alineado a sesión APK real (no cortar contexto a mitad de atención al cliente).

### 4.3 Conocimiento bancario (alta prioridad)

| Capacidad | Uso |
|-----------|-----|
| **Foundry KB Agent** (ya en 8447) | Respuestas institucionales grounded |
| **Azure AI Search** `bsc-kb-conocimiento` | Evidencia + citas |
| **Reindex pipeline** | FAQ + MD + overlay → Search de forma rutinaria |
| Instrucciones del agente Foundry | Mantenerlas sincronizadas con negocio |

Pedido a funcional: ownership del contenido; a TI: cadence de reindex (diario/semanal).

### 4.4 Respuesta final “natural” (media-alta)

| Capacidad | Uso |
|-----------|-----|
| **LLM redacta** sobre hechos ya resueltos (template facts → prosa) | Suena a IA, sin inventar números |
| Guardrail: solo puede usar facts del snapshot/FAQ/Search | Anti-alucinación |

Patrón recomendado: **determinista obtiene datos → LLM solo narra**.

### 4.5 Evaluación continua (media)

| Capacidad | Uso |
|-----------|-----|
| Golden set automatizado contra :8447 | Score de acierto por intent |
| Judge LLM (opcional) | Marca “correcto / incompleto / alucinado / mal producto” |
| Telemetry de intents fallidos | Top frases sin hit |

---

## 5. Afinado de la capa cognitiva (ingeniería) — backlog de calidad

Orden sugerido (impacto en “parecer IA”):

1. **Intent LLM-first con fallback a guardrails** (no al revés cuando hay ambigüedad semántica).
2. **Session memory completa** (resumen + foco + pending + topic KB + última respuesta).
3. **Multi-producto / multi-campo** por defecto cuando el usuario habla en plural o compara.
4. **Topic-switch detector** robusto (ya empezado: no pegarse al DAP).
5. **Integración Core de cuota y fechas TC**.
6. **Foundry + Search siempre frescos** + confidence gate calibrado con funcional.
7. **Redacción natural** post-facts.
8. **Suite de regresión** con golden conversations en CI / script QA.

---

## 6. Checklist de “listo para afinar” (definition of ready)

No empezamos un ciclo de afinado serio sin esto:

- [ ] Matriz de intenciones P0 firmada por funcional  
- [ ] ≥ 30 golden conversations (multi-turno)  
- [ ] Política escrita de clarificar vs listar vs asumir  
- [ ] Lista de campos Core faltantes con owner y fecha  
- [ ] Overlay FAQ actualizado con frases APK de la última semana  
- [ ] Criterio de aceptación por intent (“pasa si…”)  
- [ ] Acceso estable a :8447 + clientes de prueba con portafolio rico  
- [ ] Foundry agent + índice Search operativos y reindexables  

---

## 7. Preguntas que debemos hacerle YA al funcional

1. Si el usuario dice **“tarjetas de débito”** pero pregunta **crédito disponible**, ¿corregimos, preguntamos o asumimos TC?  
2. Cuando hay **2+ tarjetas**, ¿preferimos siempre resumen o solo si dice “todas / cuáles / cuál tiene más”?  
3. ¿Cuál es la **fuente oficial de la cuota** del préstamo (y en cuánto tiempo puede integrarse)?  
4. ¿Qué productos están **in / out** del MVP conversacional (hipotecario, USD, movimientos, transferencias)?  
5. ¿Cuál es el **tiempo máximo de sesión** que debemos recordar contexto?  
6. ¿Podemos usar **LLM para redactar** respuestas personales siempre que los números vengan del snapshot?  
7. ¿Quién aprueba textos de “dato no disponible” y CTAs a call center?  
8. ¿Con qué frecuencia nos entregan el **excel de fallos** (ideal: semanal)?  
9. ¿Hay compliance que prohíba cierto grounding o citas de documentos internos?  
10. ¿Prioridad de verticales esta quincena: préstamos, TC, DAP, KB general o reclamaciones?

---

## 8. Plan de trabajo sugerido (2–3 sprints de afinado)

### Sprint A — Entender y medir
- Recibir matriz P0 + 30 diálogos golden.
- Instrumentar scorecard en :8447 (pass/fail por intent).
- Calibrar confidence gate FAQ→Foundry con frases reales.

### Sprint B — Contexto + intención
- Intent JSON Azure OpenAI + rewrite de follow-ups.
- Session summary + topic switch.
- Multi-card / multi-loan aggregate según política funcional.

### Sprint C — Datos + naturalidad
- Integrar cuota / fechas TC desde Core (si funcional+TI lo habilitan).
- Redacción LLM sobre facts.
- Reindex KB + actualización instrucciones Foundry.
- Cerrar top fallos del excel semanal.

---

## 9. Roles y RACI (simple)

| Entregable | Funcional | Cognitiva | Core/API | Azure/Cloud |
|------------|-----------|-----------|----------|-------------|
| Matriz intenciones / golden set | **R/A** | C | I | I |
| Política clarificar vs listar | **A** | R | I | I |
| Campos cuota / fecha TC | C | C | **R/A** | I |
| FAQ overlay / business rules | **R/A** | C | I | I |
| Intent LLM + memoria sesión | C | **R/A** | I | C |
| Foundry + Search + reindex | C | R | I | **A** (infra) |
| Tono / compliance textos | **A** | R | I | I |

R = responsible, A = accountable, C = consulted, I = informed.

---

## 10. Mensaje corto para enviar a funcional

> Para que la banca conversacional se sienta como una IA real del banco (con contexto de toda la sesión y respuestas acertadas), necesitamos de ustedes: (1) matriz de intenciones con frases reales, (2) diálogos golden multi-turno con respuesta esperada, (3) reglas de cuándo aclarar / listar / asumir, (4) definición de campos Core faltantes (cuota, fecha límite TC, débito), (5) actualización semanal de fallos y FAQ, y (6) política de tono/límites. Nosotros afinamos routing, memoria de sesión y Azure AI (intent, Foundry, Search, redacción grounded). Prioridad actual: acierto; el costo de tokens es secundario.

---

## 11. Relación con lo ya detectado en QA

Estos fallos recientes demuestran exactamente los huecos de arriba:

| Fallo observado | Qué faltaba |
|-----------------|-------------|
| “Cuánto es mi próxima cuota?” → respondía fecha | Matriz intención cuánto/cuándo + tests |
| “Tarjetas de débito…” → ofrecía crédito y pedía elegir | Política débito/crédito + agregación multi-tarjeta + datos débito |
| “Préstamo o tarjeta con pago próximo?” → ficha DAP | Política de topic-switch + intent multi-producto |
| “Monto de la cuota” → no disponible | Campo Core de cuota contractual |

Afinar “muy bien” = **cerrar el circuito funcional → datos → Azure AI → regresión**, no solo parches sueltos.

---

*Documento vivo para planificación de afinado. Ubicación: `works/AFINADO_BANCA_CONVERSACIONAL_NECESIDADES.md`*
