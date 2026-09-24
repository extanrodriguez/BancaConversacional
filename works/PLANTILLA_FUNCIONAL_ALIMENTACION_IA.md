# Plantilla funcional — Alimentación de la Banca Conversacional (Genesis)

> **Uso:** el equipo **funcional** completa este archivo (o una copia por release).  
> **Consumo:** el equipo **cognitiva** lo usa para implementar routing, Azure AI, FAQ/Foundry, memoria de sesión y tests.  
> **Regla:** cada fila debe ser accionable. Si un campo no aplica, escribe `N/A` (no lo dejes vacío sin explicación).

---

## Metadatos del paquete

| Campo | Valor (completar) |
|-------|-------------------|
| `paquete_id` | ej. `FUNC-2026-W38` |
| `fecha` | YYYY-MM-DD |
| `autor_funcional` | nombre |
| `revisado_por` | nombre / área |
| `version_kb_referencia` | ej. VF01 / fecha Excel |
| `instancia_destino` | `8447` (QA) |
| `prioridad_global` | P0 / P1 / P2 |
| `verticales_en_foco` | préstamos, TC, DAP, KB, reclamaciones, … |
| `notas` | contexto del ciclo |

---

## 0. Instrucciones para funcional (leer antes de llenar)

1. Completar primero la **sección 1 (intenciones P0)** y la **sección 2 (diálogos golden)**.
2. Usar **frases reales** del APK / usuarios (con errores ortográficos si así hablan).
3. En “respuesta esperada” ser explícitos: qué **debe** decir y qué **no debe** decir.
4. Si el bot debe **aclarar**, escribir la pregunta de aclaración sugerida.
5. Si el dato depende de Core y no existe, marcar `dato_core: FALTA` y proponer mensaje al cliente.
6. Un paquete semanal ideal: **intents P0 + ≥5 diálogos nuevos + fallos de la semana**.

---

## 1. Matriz de intenciones

> Cada intención es un “contrato” que la IA debe cumplir.

### 1.1 Intent

Copiar el bloque por cada intención.

```yaml
intent_id: # ej. LOAN_INSTALLMENT_AMOUNT
familia: # personal | conocimiento | proceso | ood | saludo | aclaracion
prioridad: # P0 | P1 | P2
producto: # prestamo | tarjeta_credito | tarjeta_debito | cuenta | dap | ninguno | mixto
campo_dato: # ej. installment_amount | next_due_date | available_balance | kb_definicion
pregunta_canonica: |
  ¿Cuánto es la cuota de mi préstamo?
variantes_cliente:
  - Cuanto es mi proxima cuota?
  - De cuanto es mi letra?
  - Cual es el monto de la cuota?
sinónimos_clave:
  - cuota
  - letra
  - mensualidad
debe_incluir:
  - monto de cuota en DOP si existe en snapshot
  - máscara del préstamo (últimos dígitos)
no_debe:
  - responder con la fecha de pago como si fuera el monto
  - inventar la cuota
  - ir a Foundry/KB
si_ambiguo: # aclarar | listar_todas | usar_foco_sesion | asumir_unico_producto
pregunta_aclaracion: |
  ¿De cuál préstamo deseas consultar la cuota?
si_dato_faltante: |
  No tengo el monto de la cuota contractual en este momento. Puedo indicarte capital pendiente, tasa o próxima fecha de pago. También BSC en Línea / 809.726.1000.
dato_core: # OK | PARCIAL | FALTA | N/A
campo_core_oficial: # nombre del campo/API si se conoce
criterio_pass: |
  PASS si responde monto de cuota o mensaje de no disponible aprobado; FAIL si responde fecha u otro producto.
```

### 1.2 Inventario rápido (tabla resumen)

| intent_id | familia | producto | prioridad | dato_core | estado_funcional |
|-----------|---------|----------|-----------|-----------|------------------|
| | | | P0 | OK/FALTA | nuevo/actualizado |

---

## 2. Diálogos golden (multi-turno)

> Estos diálogos alimentan tests de regresión y el “comportamiento de IA con memoria”.

### 2.1 Diálogo

Copiar por cada conversación.

```yaml
dialogo_id: # ej. GOLD-TC-001
titulo: # Resumen de dos tarjetas + follow-up
customer_id: # id de prueba
prioridad: P0
tags: [tarjeta, multi_producto, followup]
precondicion: |
  Cliente con 2 TC activas (····6374 y ····7111). Sesión limpia.
turnos:
  - n: 1
    usuario: |
      Cuanto debo en mis tarjetas de credito y cual tiene mas disponible?
    esperado:
      debe:
        - mencionar ambas tarjetas
        - indicar adeudado de cada una
        - indicar cuál tiene más disponible
      no_debe:
        - pedir elegir una sola tarjeta
        - hablar de DAP
      tipo_respuesta: # resumen | campo_unico | aclaracion | kb | no_disponible
  - n: 2
    usuario: |
      y el pago minimo de la 6374?
    esperado:
      debe:
        - pago mínimo de 6374
      no_debe:
        - cambiar a 7111 sin motivo
        - devolver ficha completa innecesaria
cambio_tema_en_turno: # número o N/A
notas_funcional: |
```

### 2.2 Inventario de diálogos

| dialogo_id | título | customer_id | #turnos | prioridad | vertical |
|------------|--------|-------------|---------|-----------|----------|
| | | | | P0 | |

---

## 3. Política de contexto de sesión

> Define cómo debe “recordar” la IA durante toda la interacción.

| Situación | Decisión funcional (`aclarar` / `listar_todas` / `usar_foco` / `romper_foco` / `asumir`) | Ejemplo de respuesta / regla |
|-----------|----------------------------------------------------------------------------------------|------------------------------|
| Usuario nombró un producto y luego pregunta un campo (“¿y el disponible?”) | | |
| Usuario cambia de familia (DAP → préstamo/tarjeta) | | |
| Usuario habla en plural (“mis tarjetas”, “cuál de ellas”) | | |
| Usuario mezcla términos contradictorios (débito + crédito disponible) | | |
| Tras KB (“qué es…”) pregunta dato personal (“¿cuánto debo?”) | | |
| Tras clarificación elige una card APK | | |
| Duración máxima de contexto a preservar | minutos / turnos: ___ | |

**TTL / sesión deseada:**

| Campo | Valor |
|-------|-------|
| Duración máxima de sesión con memoria | |
| ¿Resumen periódico del hilo? | sí/no + cada N turnos |
| ¿Qué nunca debe “pegarse” entre temas? | ej. DAP, reclamación, KB |

---

## 4. Desambiguaciones oficiales

| id | Ambigüedad | Opción A | Opción B | Preferencia / regla | Texto de aclaración |
|----|------------|----------|----------|---------------------|---------------------|
| DIS-01 | Certificado / DAP vs préstamo con garantía de certificado | | | | |
| DIS-02 | Fecha de corte vs fecha límite de pago | | | | |
| DIS-03 | Responsabilidad del banco vs del cliente | | | | |
| DIS-04 | Débito vs crédito (portafolio personal) | | | | |
| DIS-05 | Cuánto (monto) vs cuándo (fecha) en “próxima cuota” | | | | |

---

## 5. Contrato de datos personales (Core / API)

> Sin esto la IA no puede ser “acertada” en banca personal.

| Pregunta del cliente | intent_id | Campo necesario | ¿Existe hoy? | Fuente/API | Owner | Mensaje si falta (aprobado) |
|----------------------|-----------|-----------------|--------------|------------|-------|-----------------------------|
| Monto de la cuota del préstamo | | cuota contractual | sí/no | | | |
| Próxima fecha de pago préstamo | | next_due_date | | | | |
| Fecha límite de pago TC | | payment_due_date | | | | |
| Fecha de corte TC | | cutoff_day | | | | |
| Disponible TC | | available / purchases | | | | |
| Adeudado TC | | ledger_balance | | | | |
| Movimientos | | historial | | | | |
| Tarjeta de débito | | producto/vínculo | | | | |

**Decisiones de semántica (obligatorio):**

| Tema | Definición funcional |
|------|----------------------|
| ¿`pendingBalancePr` es mora o cuota? | |
| ¿Qué campo es “crédito disponible”? | |
| ¿Débito se consulta como cuenta o como plástico? | |

---

## 6. Conocimiento bancario (FAQ / Foundry / Search)

### 6.1 Entradas FAQ / overlay (frases → respuesta)

```yaml
faq_id: # ej. FAQ-MISION-001
topic: # mision_vision | dap | reclamaciones | ...
preguntas:
  - CUAL ES LA MISION DEL BANCO?
  - dime la mision y la vision
respuesta_aprobada: |
  ...
debe_combinar_con: # otros faq_id si aplica (misión+visión)
no_escalar_humano: true
fuente: # Excel VF01 / MD / legal
reindex_search: true
```

### 6.2 Inventario FAQ del paquete

| faq_id | topic | #variantes | reindex | estado |
|--------|-------|------------|---------|--------|
| | | | sí/no | nuevo/update |

### 6.3 Reglas Foundry (conocimiento)

| id | Regla | Ejemplo |
|----|-------|---------|
| | Nunca responder saldos personales | |
| | Si piden “mi” producto + definición | responder KB + indicar que el dato personal va por sesión |
| | Comparaciones | mismos criterios en ambos lados |

---

## 7. Procesos (reclamaciones, cancelaciones, etc.)

```yaml
proceso_id: # RECLAMACION
nombre: Reclamaciones
canales: [sucursal, app, web, call_center]
overview_aprobado: |
  Texto completo que el bot puede entregar (sin cortar ideas críticas).
pasos:
  - orden: 1
    texto: |
documentos_requeridos:
  -
pregunta_clarificacion_canal: |
  ¿Por qué canal deseas reclamar?
followups_esperados:
  - y los documentos?
  - y los plazos?
no_debe:
  - truncar la lista de documentos a mitad de frase
```

---

## 8. Tono, marca y límites

| Tema | Decisión funcional |
|------|--------------------|
| Tratamiento (tú / usted) | |
| Uso del nombre del cliente | |
| CTAs permitidos (BSC en Línea, 809.726.1000, sucursal) | |
| Palabras/jerga prohibida | ej. “Core”, “snapshot”, “RAG” |
| Temas fuera de alcance | |
| Cuándo escalar a humano | |
| Consejos crediticios personalizados | permitido / prohibido |
| Idioma / regionalismos a respetar | |

**Plantillas de mensaje aprobadas:**

```yaml
msg_dato_no_disponible: |
msg_fuera_de_alcance: |
msg_aclaracion_generica: |
msg_cambio_tema: |
```

---

## 9. Fallos de la semana (para aprendizaje continuo)

> Pegar aquí los bugs reales. Esto alimenta overlay + tests + intent.

| fail_id | fecha | frase_exacta_usuario | respuesta_bot | respuesta_esperada | severidad | intent_sugerido | notas |
|---------|-------|----------------------|---------------|--------------------|-----------|-----------------|-------|
| F-001 | | | | | bloqueante/molesto/cosmético | | |

```yaml
fail_id: F-001
frase_exacta: |
respuesta_obtenida: |
respuesta_esperada: |
severidad: bloqueante
reproduccion:
  customer_id:
  conversation_context: |
fix_sugerido:
```

---

## 10. Priorización del ciclo

| Orden | intent_id / dialogo_id / fail_id | Por qué importa | Definition of Done |
|------|----------------------------------|-----------------|--------------------|
| 1 | | | test golden en verde en :8447 |
| 2 | | | |
| 3 | | | |

**Fuera de alcance de este paquete:**

- 

---

## 11. Checklist de entrega funcional

Antes de pasar el paquete a cognitiva:

- [ ] Metadatos completos  
- [ ] ≥ 1 intent P0 nuevo/actualizado con variantes reales  
- [ ] ≥ 1 diálogo golden multi-turno  
- [ ] Política de sesión tocada si aplica  
- [ ] Desambiguaciones nuevas registradas  
- [ ] Datos Core faltantes marcados con owner  
- [ ] FAQ/overlay con respuesta **aprobada**  
- [ ] Fallos de la semana cargados (si los hay)  
- [ ] Prioridad del ciclo ordenada  
- [ ] Revisado por negocio/compliance si toca textos sensibles  

**Firma funcional**

| Rol | Nombre | Fecha |
|-----|--------|-------|
| Autor | | |
| Revisor | | |
| OK para implementar | sí/no | |

---

## 12. Bloque de consumo cognitiva (no llenar funcional)

> Lo completa ingeniería al cerrar el ciclo.

| Campo | Valor |
|-------|-------|
| `implementado_en` | commit / release / fecha |
| `tests_agregados` | rutas |
| `overlay_actualizado` | sí/no |
| `reindex_search` | sí/no |
| `foundry_instructions_update` | sí/no |
| `deploy_8447` | sí/no |
| `score_golden` | pass/total |
| `pendientes` | |

---

## Anexo A — Catálogo mínimo de `familia`

| familia | Significado |
|---------|-------------|
| `personal` | Dato del portafolio autenticado del cliente |
| `conocimiento` | Definiciones, catálogo, requisitos, glosario del banco |
| `proceso` | Reclamaciones, cancelaciones, liberaciones, guías paso a paso |
| `ood` | Fuera de dominio bancario del asistente |
| `saludo` | Saludos / small talk permitido |
| `aclaracion` | El bot debe preguntar antes de ejecutar |

## Anexo B — Catálogo mínimo de `tipo_respuesta`

| tipo_respuesta | Uso |
|----------------|-----|
| `campo_unico` | Una cifra/fecha/dato puntual |
| `resumen` | Varios productos o varios campos |
| `ficha` | Detalle completo del producto (solo si se pide) |
| `aclaracion` | Options / pregunta de desambiguación |
| `kb` | Respuesta de conocimiento (FAQ/Foundry) |
| `no_disponible` | Dato inexistente + alternativa |
| `fuera_alcance` | No soportado / escalación |

---

*Plantilla canónica para alimentar Genesis Cognitiva. Copiar como `FUNC-YYYY-WNN.md` por ciclo.*
