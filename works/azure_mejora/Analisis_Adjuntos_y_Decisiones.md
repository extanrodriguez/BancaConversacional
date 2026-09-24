# Complemento basado en los adjuntos BSC

Preparado: 21 de septiembre de 2026. Análisis de archivos y preparación de implementación; no ejecución remota del LLM. Este documento complementa el plan y precisa los mapeos a partir del contrato recibido. Ante un conflicto con una hipótesis anterior, prevalece el campo documentado y su aplicabilidad validada; no un nombre genérico del snapshot.

## 1. Inventario verificado

| Insumo | Hallazgo | Uso correcto |
|---|---|---|
| Excel API | 6 hojas; 27 campos de producto; categorías CA, CC, CD, TC y PR; monedas 214/DOP y 840/USD | Adaptador tipado, catálogo de capacidades y pruebas de campos |
| Matriz de conocimiento | 344 filas: 246 de información general y 98 reglas funcionales/transversales | Documentación candidata separada de reglas del asistente |
| Estado de la matriz | Las 344 filas dicen «Propuesta funcional» | No equivale a aprobación comercial o publicación PROD |
| Cobertura funcional % | Fórmula de conteo de celdas no vacías; manifest advierte valores almacenados no recalculados | No es porcentaje de pruebas aprobadas ni exactitud del modelo |
| Guía original | 236 IDs únicos: 200 casos de un turno y 36 recorridos | Regresión por escenario, manteniendo turnos y precondiciones |
| Estructura de los recorridos | 26 bajo encabezados y 10 MIX dentro de tablas, unidos por flechas | El parser debe reconocer ambas formas; son 330 mensajes base antes de aclaraciones |
| Historial original | 95 Cumple, 72 parciales, 69 No cumple | Priorizar los 141 con problemas; conservar los 95 como regresión |
| Imágenes originales | 493 archivos; algunas referencias repetidas | Conservarlas como evidencia histórica; no reutilizarlas como un fix nuevo |

La clasificación histórica anterior pertenece a esta guía. No es la clasificación strict-v2.2 de otra corrida. Cada evaluación tiene su run_id, criterio, datos y versión; no combinar porcentajes de distintas versiones.

`FUENTES_LOCALES.json` contiene hashes de los cuatro adjuntos. El `source_hash` del manifest de conversión corresponde al Excel original de conocimiento, que no está en este lote; no valida por sí solo el MD entregado. Los adjuntos originales no fueron modificados.

## 2. Hallazgo principal de ingestión: recuperar el texto completo

En 55 de las 246 filas generales, «Definición funcional del dato» es solo el título. En 50 filas, consultar además «Criterio de aceptación origen» permite recuperar texto más extenso. No todas esas 50 son una ficha completa: algunas siguen siendo encabezados que necesitan revisión. Por eso el extractor conserva las 246 filas y marca calidad, sin publicar automáticamente.

Ejemplos comprobados:

| Filas Matriz_Cuentas | Contenido encontrado | Corrección de ingestión |
|---|---|---|
| 80–83 | Misión y visión aparecen como título y como texto en filas relacionadas | Conservar texto institucional y procedencia, evitando duplicación de respuesta |
| 260–262 | Platinum, Infinite y Joven: definición corta, descripción extensa en criterio de origen | Recuperar la columna correcta y filtrar por producto; no responder únicamente «tema disponible» |
| 323 | Liberación de garantías: título en definición, procedimiento en origen | Recuperar etapas, requisitos y restricciones del procedimiento |
| 324 | Procedimiento de fallecidos documentado | Buscar procedimiento; «cliente» dentro de la pregunta no debe activar una definición de cliente |
| 279 | Etiqueta Clásica, pero encabezado/contenido hablan de Gold | Marcar conflicto; no adjudicar atributos de Gold a Clásica |
| 277–278 | Etiqueta de producto Crédito y texto de Débito | Corregir metadatos mediante revisión, con trazabilidad |
| 280 | Platinum en contenido y referencia de sección Clásica en observaciones | Resolver la referencia antes de activar esa ficha |
| 90 | Cuotas con límite de 48 meses en una entrada rotulada general | Conservar ámbito contractual; no extender ese plazo a todo préstamo |
| 104 y 123 | Pago mínimo de Multicrédito y tarjeta tradicional con reglas diferentes | Modelar dos conceptos por producto; no unir por similitud de palabras |

El candidato entregado usa `Criterio de aceptación origen` como texto fuente para información general y conserva definición, hoja, fila y observaciones. No contiene «Respuesta esperada» como hecho financiero. La totalidad de las columnas se conserva aparte en `Matriz_KB_344_Normalizada.jsonl` para auditoría.

En la muestra visual revisada, P01 solicita deuda, disponible y fecha; CC02 devuelve dos textos de Infinite ante una comparación Platinum/Infinite; GR09 contesta la definición de cliente ante fallecimiento. Se inspeccionaron esas tres capturas representativas; no se declara revisión visual exhaustiva de las 493.

## 3. Semántica del API: el nombre del campo no basta

| Consulta | Campo/documentación aplicable | Sustitución que debe impedirse |
|---|---|---|
| Disponible de cuenta CA/CC | availableBalance | No usar el significado de TC/PR |
| Saldo actual de cuenta | currentBalance | El Excel dice que coincide con disponible; no acredita ledger contable independiente |
| Límite total de TC | availableBalance | No presentarlo como disponible para compras |
| Disponible de TC | availablePurchasesDomestic / Foreign según moneda | No sumar DOP y USD ni reconstruir con límite menos deuda |
| Deuda TC por moneda | domesticCurrencyBalance / foreignCurrencyBalance | No duplicar saldo de moneda única ni convertir sin tipo de cambio autorizado |
| Pago mínimo TC | minimumPaymentTcRd / Us | Cero puede ser no aplica: comprobar categoría, moneda y calidad de dato |
| Balance al corte | statementBalanceTcRd / Us | No sustituir deuda actual ni inventar período del estado |
| Día de corte | statementCutoffDay | No convertirlo en fecha de pago |
| Caducidad de tarjeta | cardExpiryDate (YYYYMM) | No confundir con fecha límite de pago |
| Capital original PR | availableBalance | No tratarlo como dinero disponible |
| Capital pendiente PR | currentBalance | No llamarlo monto de cancelación |
| Mora PR | pendingBalancePr | No usar como próxima cuota |
| Próximas fechas PR | nextInstallmentDatePr / nextPaymentDatePr | Conservar distinción; si difieren, no elegir por conveniencia |
| Certificado CD | currentBalance/availableBalance = capital; interestRateCd = tasa; interestAmountCd = intereses; maturityDate = vencimiento | No calcular liquidación personal no documentada |

`Bindings_Semanticos_API.json` contiene 26 mapeos propuestos y 8 brechas explícitas. Son mapeos del documento, pendientes de verificar contra el adaptador desplegado. Un campo puede existir en otro servicio ya autorizado: Cursor debe descubrirlo antes de declarar capacidad imposible.

Reglas adicionales:

- Diferenciar PRESENT, MISSING, NOT_APPLICABLE, UNKNOWN_APPLICABILITY, STALE y SOURCE_ERROR. Nunca convertir todos los ceros a ausencia ni toda ausencia a cero.
- `productStatus=3` aparece como variante activa de ahorro; no descartarlo por una regla genérica «activo solo 1». El código 2 no distingue por sí solo inactividad de bloqueo.
- `partyType` no es prueba de autorización de terceros. La sesión autenticada y el alcance del servicio determinan acceso.
- El ejemplo del Excel contiene campos duplicados por moneda en productos monomoneda y un `maturityDate` en TC aunque el diccionario lo limita a CD/PR. Aplicabilidad documentada antes de usar un valor solo porque está presente.
- Usar decimal para dinero, moneda explícita y formato de fecha validado. `interestRatePr=10` documentado como porcentaje significa 10 %, no 1.000 %.
- «Joven Empleado» puede resolverse como selector del producto personal si el contexto lo identifica. No heredar automáticamente las condiciones comerciales de «Visa Joven» sin equivalencia de catálogo confirmada.

## 4. Brechas que un prompt no puede completar

El Excel no documenta fecha límite de pago de tarjeta, importe de próxima cuota, cotización vigente de cancelación, lista de movimientos, ledger independiente, disponible específico para avances, ni vínculos completos de débito y modalidades de crédito diferido.

Para cada brecha: 1) buscar capacidad ya disponible en el código/servicios autorizados; 2) registrar mapeo real si existe; 3) si falta, responder la parte sustentada y anotar BLOCKED_DATA para el criterio imposible. Preparar solicitud de contrato al responsable, sin modificar el backend protegido ni hacer nuevas llamadas Core no autorizadas.

Por ejemplo, P03 puede reconocer préstamo, saldo, cuota y fecha correctamente; sin importe de próxima cuota no alcanza el cumplimiento funcional total. Una explicación honesta de ausencia acredita manejo de limitaciones, pero no cierra la necesidad de consultar esa cuota. Solo un caso cuyo esperado sea explícitamente ausencia puede aprobarse por esa respuesta.

## 5. Repartir los insumos entre ejecución, conocimiento y evaluación

1. **Contrato y reglas:** JSON de campos/taxonomía/capacidades en el código cognitivo y contexto seleccionado del intérprete. No enviar detalles internos ni direcciones del servicio al cliente.
2. **Conocimiento:** corpus documental versionado, aprobado para el alcance de uso y con producto/faceta. Fragmentación inicial 600/80, banda 400–800; conservar procedimientos y excepciones.
3. **Evaluación:** guía, conversaciones, resultados y fotos fuera del índice del cliente. Los casos no enseñan al modelo a repetir montos de una captura.
4. **Variantes lingüísticas:** ejemplos de diseño para construir pruebas y, de forma selectiva, pocos ejemplos del intérprete. No enviar las 875 expresiones y las 200 nuevas en cada turno.

No asumir equivalencia entre IDs de fila KB-MC-rN y los IDs FAQ vf01-rN existentes: verificar fuentes y hashes antes de migrar referencias.

La taxonomía extraída mantiene dominio → acción → objeto → campo/faceta y la fila de origen. Los labels son fuente para canonizar enums del proyecto; no reemplazan ciegamente los enums existentes. La matriz de trazabilidad propone relaciones léxicas entre los 236 casos y filas KB: debe revisarse antes de transformarla en oráculo. Un score de similitud no acredita soporte.

## 6. Diccionario dominicano y enriquecimiento web

Se entregan 50 familias / 200 variantes redactadas para diseño: balance, disponible, pesos/RD$, dólares/US$, certificado financiero, saldar, mora, corte, próxima cuota, reclamación, fallecidos, Multicrédito, comparativas, correcciones y lenguaje coloquial. Son ejemplos sintéticos; no estadísticas de habla de clientes dominicanos ni un diccionario exhaustivo.

Las fuentes oficiales externas aportan terminología y conceptos candidatos. Conservar banco/producto/fecha/URL y estado editorial. No reemplazar condiciones de BSC por las de otra entidad. No consultar internet con snapshots o identificadores personales. Tarifas, plazos, requisitos y reglas legales necesitan fuente y vigencia aplicables; no rellenar una brecha personal con la web.

El glosario oficial consultado usa «Saldo» en el sentido de saldar una deuda. Ese sentido no debe sobreescribir la consulta personal «mi saldo». Es una prueba negativa concreta contra ingestión web sin desambiguación. Ver `Fuentes_Externas_y_Cursor.md`.

## 7. Ciclo de corrección y check por escenario

Prioridad: reproducir los 69 No cumple y 72 parciales del original; conservar los 95 Cumple; incorporar los fallos confirmados de corridas posteriores sin fusionar sus etiquetas.

Para cada familia de fallo: reproducir → identificar etapa causal → corregir la capacidad general → probar el caso y sus vecinos → ejecutar UI → guardar resultado → actualizar fix. Hasta tres intentos de corrección por causa antes de diagnosticar el bloqueo y continuar otros casos; nunca un bucle de reformulaciones hasta obtener una respuesta casualmente buena. Registrar todos los intentos. Un caso previamente inestable necesita repetición bajo las mismas precondiciones, no elegir solo la corrida favorable.

Los éxitos con fixtures locales se registran aparte y no cierran el escenario QA de la guía. El generador solo admite check de cierre para environment=qa y validation_scope=QA_UI.

Un check exige todos los criterios aplicables del caso, con producto, campo, cifra/moneda/fecha, cobertura de tareas, evidencia, contexto, seguridad y contrato correctos. El oráculo debe estar revisado y vinculado a la fuente/snapshot de esa corrida. Un juez LLM puede ayudar a revisar lenguaje, pero no aprobar por sí solo números, autorización o fuentes.

No cambiar el esperado para acomodarlo a la implementación. Si el criterio original contradice el contrato o queda sin datos, abrir una incidencia de especificación y conservar el criterio original junto a la propuesta versionada. No excluir casos difíciles del denominador de la guía.

Las 36 conversaciones conservan sesión, orden, selección de producto y alcance de las tareas. Si la respuesta pide una aclaración legítima, el runner resuelve una opción según precondiciones del caso y registra el turno añadido; no elige siempre la primera. No inventar identificadores en QA; los fixtures sintéticos locales son un alcance distinto.

## 8. Capturas y edición del MD

La carpeta `guia/` incluye original, versión con `fix` por los 236 IDs, imágenes históricas y manifest de fuente. Todas las celdas nuevas comienzan NOT_EXECUTED/PENDING_UI. La cabecera aclara la diferencia entre histórico y nueva evidencia.

Para una corrección: capturar el chat existente con pregunta, respuesta completa y selecciones/turnos necesarios. Guardar en `guia/evidencias_fix/<run_id>/<case_id>/`. Si se necesita más de una captura, vincularlas todas. Registrar fecha, URL, turnos, hash y revisión visual; no fabricar capturas a partir de logs ni modificar el texto del chat para que parezca correcto.

`tools/actualizar_guia_fix.py` agrega evidencia a una copia desde el original; verifica IDs, rutas, hashes, gates, aserciones y cobertura declarada de turnos. Rechaza capturas con hash de las históricas. No juzga por sí mismo la semántica de una respuesta ni prueba que el banco respondió: esa tarea pertenece al runner y revisión de evidencia.

Cuando una prueba API pasa pero falta UI, mantener el check vacío y estado visual pendiente. Si el navegador no está disponible, usar el navegador autorizado existente o capturas manuales verificables; no repetir indefinidamente una instalación fallida.

## 9. Cursor como apoyo de ingeniería

Usar primero el agente de Cursor y terminal del proyecto para runner, pruebas, navegador y reporte. El SDK de Cursor puede automatizar ese agente desde un proceso local o CI; MCP puede exponer herramientas acotadas del runner. Ambos son opcionales y quedan fuera del camino de respuesta al cliente bancario. No son una memoria extra ni reentrenan el deployment de Foundry.

Interfaz interna opcional: listar casos, ejecutar caso autorizado, leer traza saneada, capturar chat, evaluar aserciones y publicar reporte local. Identidad QA y destinos permitidos controlados por el servidor. No conceder ejecución arbitraria o acceso a PROD a partir de texto del cliente. No condicionar la entrega funcional a instalar otro framework.

## 10. Orden de implementación actualizado

| Prioridad | Trabajo | Salida verificable |
|---|---|---|
| A | Leer adjuntos; comparar 27 campos y adaptador real | Mapeos correctos, brechas de dato y tests de contratos |
| B | Recuperar texto de origen y resolver conflictos de metadatos | Corpus candidato completo, sin mezcla de productos |
| C | Conectar plan de todas las tareas a capacidades reales | Mixtas/selecciones/correcciones sin pérdida de pendientes |
| D | Retrieval por faceta y producto; contexto compacto | Evidencia por afirmación y presupuesto medido |
| E | Reproducir, corregir, probar y capturar por caso | Checks acreditados, fallos y bloqueos explícitos |
| F | Regresión completa y rendimiento sobre misma versión | 236 estados honestos, tiempos reales y rollback |

El plan anterior de Redis/Search/Foundry se conserva. Este complemento cambia la calidad de los insumos, la exactitud del adaptador y la forma de cerrar los escenarios. La configuración remota, publicación comercial y pruebas reales siguen distinguiéndose de los artefactos preparados aquí.
