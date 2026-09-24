# Análisis del conocimiento y plan para la entrega del lunes

Fecha: 19-09-2026. Preparación documental y técnica; sin cambios en Azure, Redis, Core, código desplegado ni índices. No se ha vuelto a ejecutar QA bancaria en este trabajo.

## Qué está fallando y qué podemos corregir

La base tiene contenido suficiente para mejorar muchas respuestas actuales. El problema combina **extracción de contenido, selección del tema, resolución del producto y conservación de tareas**. Subir más documentos, por sí solo, no corrige esos cuatro pasos.

El hallazgo más aprovechable está en el propio archivo: `Criterio de aceptación origen` conserva textos completos que otras columnas reducen a un título. De las fichas recuperadas, 72 tienen una definición notablemente más corta que el cuerpo recuperado. Esta es una observación del archivo; comprobar si el indexador actual toma la columna equivocada requiere revisar el checkout.

| Evidencia en VF01 | Consecuencia posible | Corrección preparada |
|---|---|---|
| Filas 80–81 y 82–83 repiten el contenido completo de misión y visión | Duplicados o recuperación solo del encabezado | Fichas únicas con ambas filas de procedencia |
| Fila 262: definición/esperada = título; cuerpo completo en criterio de origen | Visa Joven se responde con otro concepto o queda sin contenido | Recuperación de la descripción de Joven; separación de crédito/débito |
| Fila 320: respuesta esperada = título; criterio de origen incluye proceso de reclamación | “No encontré esa definición” pese a existir procedimiento | Ficha de procedimiento y resumen acotado para QA |
| Filas 319 y 323 presentan el mismo patrón | Cancelación y liberación tratadas como simples definiciones | Recuperar etapas/canales y diferenciar procedimiento de ejecución |
| Filas 277–278 heredan producto crédito para contenido de débito | Cruce incorrecto de familias | Metadatos corregidos desde el texto de origen |
| Filas 279, 281–284 tienen títulos de Clásica pero texto de otros productos | Comparaciones y alias contaminados | Nombres normalizados desde la columna de origen, con trazabilidad |
| Fila 310 repite cargos y penalidades bajo título de metodología | Una supuesta fórmula de intereses que no es una fórmula | Apartar el detalle; no habilitar cálculos personales |
| Datos simulados y respuestas de ejemplo comparten matriz con conocimiento | Cifras de prueba pueden convertirse en “hechos” del banco | Fuentes, reglas, pruebas y conocimiento en archivos distintos |

No se afirma que se auditó el código actual completo: los insumos nuevos de este trabajo son la base, su manifiesto y la guía. El prompt obliga a Cursor a confirmar cada ruta y contrato en su checkout.

## Inventario y límites de la evidencia

| Elemento | Resultado |
|---|---:|
| Filas útiles de la base | 344 |
| Filas de conocimiento general | 246 |
| Filas de reglas/consultas personales y conversación | 98 |
| Filas que solo son encabezados y se convierten en relaciones | 18 |
| Fichas candidatas, incluyendo resúmenes y ampliaciones | 239 |
| Fichas seleccionadas para QA | 195 |
| Fragmentos QA con procedencia | 196 |
| Fichas detalladas separadas para revisión | 44 |
| Casos de la guía asociados a fuentes y reglas | 236 |
| Conversaciones multi-turno | 36: 26 por secciones + 10 MIX en tablas |
| Capturas revisadas visualmente en este trabajo | 6 |
| Casos funcionales ejecutados por este paquete | 0 |

Todas las filas originales están marcadas `Propuesta funcional`; todas declaran cobertura `100`. Ese porcentaje no acredita aprobación de Producto, ejecución de pruebas ni cobertura funcional. Se conserva como dato original, no como métrica de calidad.

La selección QA no significa aprobación para producción. Los resúmenes acotados permiten explicar lo respaldado sin recitar cifras o plazos pendientes de validación. Se conserva íntegro el contenido candidato para revisión, separado del material que se propone recuperar.

## Qué aportó internet y qué no se debe inferir

Se agregaron **nueve fichas breves** de fuentes oficiales: contacto general BSC; escalamiento de reclamaciones; crédito, débito, tasa efectiva, amortización, garantía, liquidez y tasa de interés. Cada ficha incluye URL y fecha de consulta. El glosario público complementa conceptos; no determina campos del Core ni condiciones de un contrato individual.

El sitio del banco distingue Joven de crédito, Débito Joven y Cuenta de Ahorro Débito Joven. Esa distinción respalda tratar “Joven” como un selector potencialmente ambiguo. Las páginas de detalle no entregaron contenido comercial completo en esta consulta; no se agregaron tasas, descuentos ni beneficios supuestos. [Mapa oficial del sitio](https://bsc.com.do/mapa-del-sitio).

El teléfono general publicado por BSC es 809 726 1000. VF01 incluye 809-227-1222 en el procedimiento de fallecidos. Se registra la discrepancia; no se reemplaza silenciosamente un contacto posiblemente especializado por otro. [Sitio oficial BSC](https://bsc.com.do/).

Hay un cambio regulatorio publicado el 17-09-2026 sobre el instructivo de cuentas inactivas y abandonadas. Se verificó la ficha oficial, no el contenido íntegro del PDF: **no se afirma que hayan cambiado los umbrales**. Producto/Legal debe revisar su impacto antes de publicar las cifras de VF01 como vigentes. [Circular de la SB](https://sb.gob.do/regulacion/normativas-sb/circular-csb-reg-2026000017/).

El procedimiento de ProUsuario aclara que el reclamo empieza en la entidad y puede escalarse. Se añade esa orientación, sin confundir los canales de ProUsuario con canales de BSC. La fuente describe 180 días en crédito cuando intervienen marcas internacionales; VF01 también menciona débito. Esa diferencia queda pendiente de revisión, no se generaliza. [Reclamaciones de ProUsuario](https://prousuario.gob.do/servicios/reclamaciones/).

No se incorporaron artículos comerciales de terceros, tasas personales, elegibilidad crediticia ni una navegación abierta dentro del chat. La URL del tarifario 2026 fue localizada, pero no se recuperó su documento completo con vigencias/importes. “Fuente localizada” y “contenido verificado” tienen estados diferentes en `fuentes/ampliaciones_web.json`.

## Lo que muestran las imágenes

Se revisaron `img_0001`, `img_0212`, `img_0301`, `img_0313`, `img_0409` e `img_0470` del ZIP original. No se realizó revisión visual exhaustiva de las 493 imágenes.

- TC03 pide características de Visa Joven y recibe la definición de cliente.
- GR03 pide el procedimiento de reclamación y recibe el capital pendiente del préstamo anterior.
- GR09 pide orientación tras fallecimiento y recibe la definición de cliente.
- MIX10 muestra recuperación de Multicrédito para una pregunta de cancelación de préstamos: es selección de tema incorrecta.
- CC02 conserva Infinite como segundo elemento, pero repite su descripción; la asociación ordinal correcta no basta para dar una respuesta de calidad.
- En la primera captura P01 hay aclaración y ficha de tarjeta, pero el recorte no permite acreditar las tres facetas de toda la conversación. Debe ejecutarse el recorrido completo.

TC03, GR03 y GR09 están rotulados “Cumple” en la guía aunque la captura contradice esa etiqueta. Se mantienen las etiquetas originales y se agrega la revisión; no se usan como respuestas esperadas.

## Prioridades concretas

| Prioridad | Trabajo | Condición de terminado |
|---|---|---|
| P0 | Ingestión desde el cuerpo completo y corpus QA versionado | Misión/visión, Joven, reclamaciones y fallecidos recuperan la ficha correcta, no un título ni “cliente” |
| P0 | Resolver nombre/alias dentro del portafolio autorizado | Crédito/débito, producto único/múltiple/ausente y contexto incompleto tienen conductas distintas |
| P0 | Conservar todas las tareas y corregir referencias | P01, P06 y tasa+definición responden cada faceta o justifican su ausencia; selección no borra tareas |
| P0 | Oráculos y evidencia en `/turn` | Casos prioritarios completos, sin “PASS_SAFE” como aprobación funcional |
| P1 | Comparación ordenada y cambio catálogo→personal | CC02, CC03, MIX07, MIX09 y MIX10 pasan con fixtures adecuados |
| P1 | Recuperación híbrida, filtros y trazas | Mejora medible frente al corpus/ruta previa con las mismas preguntas |
| P2 | Movimientos, campos faltantes, beneficios/tarifas detallados | Producto o proveedor de datos entrega la fuente/contrato faltante; se conecta y se prueba |

No esperar al catálogo perfecto para reparar misión/reclamaciones o multi-tarea. Tampoco declarar terminada una capacidad que el Core no proporciona. Para el lunes, el alcance de demostración debe limitarse a los recorridos con evidencia de extremo a extremo y mostrar claramente cualquier simulación.

## Qué debe entregar Producto

1. **Identidad comercial y mapeo:** código del Core ↔ familia/subtipo ↔ nombre comercial ↔ alias. Confirmar si “Crédito Joven Empleado” y Multicrédito tienen condiciones particulares.
2. **Semántica de campos:** definición de saldo de tarjeta, saldo contable/disponible, balance al corte, próxima cuota, vencimiento final, tasa y periodicidad, saldo para cancelar y su vigencia. Fechas no llevan RD$/US$.
3. **Vigencias:** tarifarios, cargos, recompensas, tasas comerciales, requisitos y manuales con versión/fecha/responsable. Confirmar gracia y plazos, no trasladarlos entre productos.
4. **Procedimientos:** canal por producto para cancelación; documentos/etapas de reclamaciones, garantías y fallecidos; confirmar contactos y alcance normativo.
5. **Casos esperados:** criterio por faceta, aclaraciones permitidas y respuestas ante ausencia. Corregir etiquetas inconsistentes de la guía.
6. **Límites de servicio:** qué puede consultar el asistente, qué solo explica y qué acciones no ejecuta; ruta real de atención humana y horario vigente cuando corresponda.

## Recomendación de arquitectura con lo existente

Mantener Azure como intérprete y redactor, Redis como estado tipificado, contexto/herramientas como fuente personal y conocimiento curado como fuente pública. Unificar la planificación antes de ejecutar atajos que podrían consumir tareas. No convertir la base de conocimiento en un prompt de 344 filas ni intentar resolver memoria aumentando el contexto indiscriminadamente.

La mejora se mide por entidad correcta, campos correctos, cobertura de todas las tareas, recuperación pertinente, continuidad y latencia. El nombre o tamaño del modelo es una variable para evaluar después de corregir esos contratos.

En Azure, la búsqueda híbrida combina recuperación textual y vectorial; conviene evaluarla para nombres exactos y formulaciones naturales. Las salidas estructuradas ayudan a cumplir el esquema, pero requieren validación semántica. Estas son capacidades útiles dentro de la arquitectura, no garantías de una respuesta correcta. [Azure AI Search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview), [Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs).
