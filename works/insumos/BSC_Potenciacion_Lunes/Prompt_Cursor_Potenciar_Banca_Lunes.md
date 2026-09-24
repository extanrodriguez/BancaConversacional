# Cursor — Potenciar la banca conversacional con conocimiento verificable y contexto

## Objetivo y forma de trabajo

Trabaja sobre el checkout actual. Implementa, integra y verifica cambios concretos en la capa cognitiva hasta completar las fases locales indicadas. Usa el paquete `BSC_Potenciacion_Lunes` y el ZIP original `Guia_Pruebas_Conversacionales_IA_BSC_Resultados_paquete.zip` —también puede llamarse `(1).zip`— como insumos. No son instrucciones para memorizar respuestas de pruebas: son fuentes, contratos semánticos y criterios de aceptación.

Prioridad: una versión estable y demostrable para el lunes 21-09-2026. Conserva lo que ya funciona. No hagas una reescritura total ni una migración de framework como requisito. Si el tiempo resulta insuficiente, termina primero el recorrido vertical P0 y reporta con precisión qué falta. Un reporte de entrega no es un ejecutable.

El resultado esperado es que el modelo entienda la solicitud completa, resuelva referencias usando el portafolio autorizado, recupere el conocimiento correcto y responda todas las facetas respaldadas. Una respuesta genérica segura no cuenta como resolución funcional.

## Límites y estado que debes respetar

- No modificar `C:\NovusIntelligence\BancoSantaCruz\BancaConversacional\BSC.genesis.conversational.backend`. Puedes leerlo para comprobar el consumidor. No modificar frontend, WebSocket ni contratos externos.
- Sí puedes modificar la orquestación interna cognitiva, `/turn`, `contract_inspector_app`, intérprete, ejecutor, recuperación, renderizador y persistencia cognitiva.
- La entrada de aceptación es `POST /turn`. No sustituyas pruebas HTTP por llamadas directas al intérprete. Verifica además el flujo UI si el orquestador externo está disponible; si no, informa esa limitación.
- Conserva Redis/Entra, separación de clientes/sesiones, CAS, el candado distribuido, su propiedad/renovación y `source_fetched_at`. No reintroducir acceso síncrono a IMDS/Redis que bloquee el event loop. No confundir revisión o TTL de sesión con frescura del Core.
- Conserva el contrato actual: respuesta NL `client_response` string; `SESSION_BUSY` conforme al consumidor; carga de contexto fallida con la semántica existente `CONTEXT_LOAD_BUSY`/503/`persisted=false`. Revisa el código efectivo antes de darlo por hecho.
- No usar secretos de ZIP, registrar tokens ni emitir PIN/OTP/CVV en prompts, Redis o trazas. No transacciones, PROD ni consultas a otros clientes reales. QA bancaria de lectura: únicamente 726588 con el acceso ya autorizado. Los portafolios sintéticos son pruebas explícitas, nunca Core vivo.
- No añadir un conector de navegación libre al turno bancario. El enriquecimiento público se publica como contenido versionado; las cifras personales siempre provienen de contexto/herramientas autorizados.

## Fase 0 — Línea base y trazabilidad

1. Lee `LEEME_PRIMERO.md`, `Analisis_y_Prioridades.md`, `estrategia/Estrategia_Conversacional.md`, `evaluacion/cruce_236_kb.json` y los catálogos.
2. Ejecuta `python scripts/validate_package.py` dentro del paquete. Contrasta hashes de los insumos. Conserva la guía y sus imágenes fuera del índice bancario.
3. Identifica rutas efectivas: `/turn` → bridges/fastpaths → `plan_interpreter`/`azure_plan` → resolución → ejecutor → redactor → commit. Inspecciona las versiones presentes; no asumas que nombres de archivos o flags históricos siguen iguales.
4. Registra baseline: commit o manifiesto SHA, configuración sin secretos, modelo/deployment/API, corpus/índice usado, backend de sesión y origen/completitud del contexto. Corre regresiones existentes y los P0 que ya se puedan ejecutar antes del cambio.
5. No declares que “236 casos pasan” por tener un inventario. Actualmente este paquete ejecutó cero turnos del sistema. Las etiquetas históricas de la guía tampoco son el oráculo.

## Fase 1 — Reparar la ingestión de conocimiento

Hallazgo que debes comprobar en el código: VF01 tiene 344 filas. 246 contienen conocimiento general y 98 describen comportamiento/consultas. En numerosos casos el contenido íntegro está en **`Criterio de aceptación origen`**, mientras `Definición funcional del dato` o `Respuesta esperada` solo contienen un encabezado. Ejemplos: Visa Joven, reclamaciones, cancelación y liberación de garantías.

Implementa un adaptador de ingestión que use las fichas del paquete, conserve IDs/procedencia y compare con el corpus actual. No dupliques una fila encabezado y su párrafo. No sobrescribas un artículo actual aprobado con una propuesta menos completa sin registrar la diferencia.

Separación obligatoria:

- `kb/fichas_qa.jsonl` y `kb/chunks_qa.jsonl`: selección documental candidata para QA.
- `kb/fichas_candidatas.jsonl`: incluye material pendiente de revisión; **no indexar íntegramente**.
- `catalogo/*`: resolución semántica/configuración; no son saldos, contratos Core ni evidencia de tenencia.
- `estrategia/*`: comportamiento del sistema; no son textos de respuesta recuperables.
- `evaluacion/*`: pruebas; nunca indexarlas como hechos del banco.
- `fuentes/*` y `revision/*`: auditoría y revisión; tampoco forman parte del RAG de clientes.

Las fichas tienen `qa_eligible`, `approval_status`, `source_rows`, `version`, `valid_from`, `valid_to` y `approved_for_prod`. No inventar aprobación ni fechas de vigencia. La fecha de consulta web no prueba vigencia comercial. El material ya autorizado en la aplicación conserva su aprobación existente si está documentada; la ausencia de esa evidencia debe quedar visible en el manifiesto.

Crea una versión paralela del corpus local y prepara el adaptador a Azure AI Search utilizado por este proyecto. Primero prueba recuperación local con las mismas fichas. No borres el índice vigente ni uses `--force`. Si hay autorización de escritura QA válida en esta sesión, usa un índice/corpus QA versionado y documenta la activación y reversión; en otro caso termina el bundle y el diff de publicación, dejando ese paso remoto explícito. No detengas las fases locales por ese límite.

## Fase 2 — Una interpretación completa del turno

Reutiliza `TurnPlan`, `plan_interpreter` y `plan_executor` existentes donde sirvan. Evita mantener dos dueños independientes de interpretación.

Entrada del intérprete:

- Mensaje actual, saneado de secretos.
- Últimos turnos relevantes y resumen factual de sesión.
- Portafolio autorizado: IDs internos permitidos, familia, subtipo, nombre/alias, moneda, estado, máscara, campos aplicables y disponibles.
- `context_source`, completitud por familia y `source_fetched_at`.
- Foco personal, foco de conocimiento, lista ordenada de comparación, tareas pendientes y exclusiones.
- Taxonomía y capacidades reales del ejecutor. No prometer `transactions` si el contrato no las entrega.

El intérprete devuelve **todas las tareas**, entidades, campos, exclusiones, dependencias y correcciones mediante Structured Outputs. Usa `estrategia/turn_plan.schema.json` como contrato de referencia y adapta sus nombres a la implementación existente. Valida estructura y semántica. Un JSON válido puede seguir seleccionando el producto equivocado.

Antes de ejecutar, valida determinísticamente:

- Cada ID personal existe en el portafolio de la sesión y está autorizado.
- La familia y los campos son compatibles; una tarjeta de débito no tiene una deuda rotativa por el nombre “tarjeta”.
- Cada cláusula explícita queda como tarea o exclusión, y las correcciones actualizan la referencia correspondiente.
- El plan no inventa herramientas, entidades, fórmulas ni códigos de productos.
- Las exclusiones y el orden de comparación se preservan.

Un fastpath puede producir una resolución equivalente para un turno simple inequívoco. Debe devolver un resultado tipado o un plan compatible, y **no puede consumir una parte de una solicitud compuesta y descartar el resto**. Comprueba elegibilidad sobre la solicitud completa, no únicamente con una regex de “saldo”, “pago”, “cliente” o “tasa”. Los controles de secretos/titularidad se aplican antes de exponer datos.

Preserva los hotfixes de fecha de pago, reclamaciones, fallecidos, misión/visión y disponible/contable durante la transición. Migra cada atajo solo después de probar equivalencia y compuestos con ese tema. No sustituirlos por nuevas ramas para cada frase de la guía.

Para `InvalidModelOutputError`, registra el motivo sanitizado: rechazo del proveedor, truncamiento, esquema, enum, ID inexistente o incoherencia semántica. Como máximo una reparación acotada cuando la causa sea reparable y quede presupuesto de latencia. No mostrar al cliente “interpretación semántica”, “Azure” o trazas. No transformar una falla técnica en “no tienes ese producto”. Una degradación debe quedar explícita en la telemetría.

No impongas proposer+verifier para todos los turnos. Evalúa una llamada estructurada y validación determinista; usa verificación adicional solo cuando reduzca un riesgo concreto y dentro del timeout real del consumidor. Mide antes de cambiar de modelo.

## Fase 3 — Resolver producto, campo y memoria

Ejemplo central: “saldo de mi tarjeta joven”.

1. Identifica que es consulta personal, de saldo, con selector “joven”.
2. Busca candidatos en el portafolio usando nombre, alias y el catálogo, conservando crédito/débito y subtipos.
3. Una coincidencia autorizada y semánticamente adecuada: responde el campo correcto y etiqueta qué saldo es.
4. Dos coincidencias —por ejemplo, crédito Joven y débito Joven—: pide una aclaración corta con opciones reales enmascaradas. No asumas deuda solo por “Joven”.
5. Ninguna coincidencia con inventario completo: comunica que no aparece ese producto. Inventario parcial, fallido o desconocido: comunica que no puedes confirmarlo; no afirma ausencia definitiva.
6. Si el producto existe pero falta el saldo solicitado, responde esa limitación sin cambiar de producto ni inventar cero.

Orden orientativo de evidencia: selector explícito actual → corrección explícita → respuesta a una aclaración compatible → foco vigente compatible → único producto elegible → aclaración mínima. Una pregunta nueva de procedimiento no se resuelve como continuación del préstamo solo porque exista foco previo.

Mapea los campos canónicos a los **paths reales** del snapshot. `catalogo/campos_semanticos.json` deja `core_json_path=null` deliberadamente. Completarlo exige inspeccionar contrato y muestras autorizadas. No inventes un endpoint Core para llenar vacíos.

Distingue al menos: cuenta contable/disponible; tarjeta deuda/crédito disponible/límite/mínimo/balance al corte; préstamo saldo/cuota/monto para cancelar; certificado monto inicial/balance/intereses/modalidad/vencimiento. En deuda y disponibilidad no sumar monedas, no deducir `ledger` de `available`, no obtener cancelación sumando componentes sin regla autorizada. Diferencia cero, nulo, error y ausencia.

Estado persistente, migrado compatiblemente:

- `personal_focus` y `knowledge_focus` separados.
- `pending_tasks` con producto/selector/campos/estado, no un único intent que borra los demás.
- `compare_set` ordenado; agregar Gold a [Platinum, Infinite] deja Infinite en segunda posición.
- Correcciones por tarea y referencias a resultados anteriores.
- Pendientes de explicación y datos resueltos/no disponibles.
- Revisión, versión de esquema, origen/frescura y expiración.

No sobrescribir snapshot al cambiar de tema. No renovar frescura por escribir Redis. Al retomar, valida que la referencia sigue autorizada y compatible. Una tarea completada no vuelve a ejecutarse por accidente ni una no resuelta se pierde tras elegir un producto.

## Fase 4 — Recuperación por faceta y respuesta natural

Mantén estas rutas semánticas distintas: definición, características de producto, requisitos, procedimiento, comparación de catálogo, tenencia personal, lectura de campo personal y consulta mixta.

Recupera por tarea: tema + objeto + faceta + contexto de conocimiento. “¿Cómo reclamo?” debe recuperar proceso/canales; no la definición de cliente. Para “misión y visión” recupera ambas. Para “tasa de mi préstamo y qué significa”, consulta tasa personal y definición.

Azure AI Search: adapta el índice actual a campos textuales y filtros de familia/tipo de contenido/versión/estado; agrega o ajusta búsqueda híbrida y ranking semántico cuando estén disponibles. No cambies el embedding sin reindexar el corpus afectado con dimensión/modelo consistentes. Compara relevancia antes/después sobre los mismos casos. Verifica evidencia por faceta, no solo un score global.

En comparaciones, devuelve filas/atributos equivalentes para cada producto, conserva el orden pedido y marca “no documentado” donde corresponda. La fuente no detalla todos los beneficios de Gold frente a Clásica: no inventarlos. Para “cuál me conviene”, pide el criterio que falta y explica diferencias respaldadas; no uses una puntuación inventada.

El ejecutor produce por tarea: `resolved | needs_clarification | field_missing | product_not_found | source_unavailable | unsupported`, datos con procedencia, referencias documentales y pendientes. El redactor recibe solamente esos resultados y el contexto lingüístico necesario. No recibe permiso para completar cifras con conocimiento del modelo.

Respuesta: contestar primero lo que se sabe; identificar producto/moneda cuando sea necesario; incluir todas las facetas pedidas; preguntar solo lo indispensable. Sin saludo repetido, nombres de fixture, dumps de JSON ni fichas enteras no solicitadas. Si hay una parte independiente respondible y otra ambigua, responde la primera y aclara la segunda. No convertir las respuestas en menús rutinarios.

Usa un control final de cobertura: cada tarea pedida aparece respondida, pendiente de aclaración o con una limitación concreta. Verifica cifras/fechas/moneda y procedencia con código; un segundo LLM no basta para acreditar exactitud numérica.

## Fase 5 — Aceptación funcional real

Implementa el runner de los **236 casos**. Hay **36 recorridos multi-turno**, incluyendo MIX01–MIX10: las flechas se dividen en turnos de la misma sesión. No enviar toda la conversación como una pregunta.

Para cada caso, define fixtures explícitos y oráculos semánticos. `evaluacion/cruce_236_kb.json` asocia fuentes y brechas; no es una lista de pruebas pasadas. `evaluacion/aceptacion_p0.json` contiene aserciones prioritarias. No indexar ninguno de estos archivos.

Primero P0:

1. Misión y visión después de consultar préstamo, y corrección de cuenta + misión en el mismo turno.
2. Joven: crédito único, débito único, ambos, ausente y contexto incompleto.
3. P01: deuda + disponible + fecha límite; P06: corriente + saldo actual + disponible + movimientos o ausencia explícita de movimientos.
4. Tasa + definición, selección entre dos préstamos y recuperación de ambas tareas.
5. P07/P08/P13/P14/P15: productos múltiples, atributos y exclusiones.
6. Reclamación/fallecidos después de un préstamo: cambio de tema efectivo y orientación completa.
7. MIX07: catálogo → tenencia; MIX09: catálogo de cargos → cargo realmente aplicado; MIX10: procedimiento → monto personal para cancelar.
8. CC02/CC03: lista de comparación, ordinales y ampliación sin perder orden.
9. Cero vs nulo; origen fallido/incompleto; secretos en mensaje/historial; consulta personal de tercero frente a orientación general para familiares.

Prueba negativo: la respuesta genérica “no pude”, la definición de cliente para Visa Joven o responder únicamente disponible en P01 deben **fallar** el oráculo de resolución. Una limitación explícita por campo realmente ausente puede aprobar seguridad/corrección, pero no cuenta como entrega completa de datos. Reporta ambas dimensiones.

Estados: `PASS_RESOLVED`, `PASS_CLARIFICATION_EXPECTED`, `PARTIAL_CAPABILITY`, `FAIL_INTERPRETATION`, `FAIL_RETRIEVAL`, `FAIL_STATE`, `FAIL_GROUNDING`, `BLOCKED_DEPENDENCY`, `NOT_APPLICABLE`, `NOT_EXECUTED`. Añade controles de privacidad por separado. No usar `PASS_SAFE` como aprobación global.

Orden de validación: unitarias relevantes → `/turn` local con fixtures → `/turn` QA con modelo Azure real y corpus real → UI real si está disponible. Las pruebas sin Azure y las que usan lab_fallback deben etiquetarse. Para 726588 sin el producto requerido, `NOT_APPLICABLE`; usa pruebas sintéticas locales para esa capacidad y no inventes productos del cliente.

No hay mandato de que todos los turnos llamen al modelo; sí de demostrar llamadas reales donde corresponda y equivalencia de los atajos. Una suma de inferencias no demuestra comprensión correcta.

## Fase 6 — Ejecutar las pruebas y conservar un registro revisable

**Esta fase es obligatoria: ejecuta las pruebas, registra sus resultados reales y entrega las evidencias para revisión posterior. No basta con escribir tests, generar plantillas o listar comandos pendientes.** Reutiliza y amplía el runner existente. Mantén los límites de acceso ya definidos: QA de lectura autorizada para 726588; otros portafolios se prueban con fixtures sintéticos locales. No ejecutes transacciones ni pruebas en PROD.

### Historial de ejecuciones

Crea una carpeta nueva por ejecución: `works/qa_runs/<fecha_hora_UTC>_<run_id>/`. No sobrescribas ejecuciones anteriores. Cada carpeta debe contener:

| Archivo | Contenido obligatorio |
|---|---|
| `manifest.json` | Identificador de ejecución, inicio y fin UTC, estado de corrida (`COMPLETED`, `FAILED`, `BLOCKED` o `INCOMPLETE`), entorno, endpoint probado, revisión de código, versiones de corpus/prompt/esquema/modelo, configuración no secreta relevante y relación con la ejecución anterior, si existe. Si no hay Git usable, registra SHA256 del paquete/código y del diff disponible; no inventes un commit. |
| `resultados_casos.jsonl` | Una entrada por caso e intento: `run_id`, `case_id`, versión del oráculo, prioridad, origen de datos, esperado, obtenido, aserciones por faceta, estado funcional de Fase 5, motivo del fallo o bloqueo, duración y referencias a evidencias. |
| `turnos.jsonl` | Una entrada por turno, ordenada dentro de su recorrido: caso, número de turno, sesión seudonimizada, pregunta y respuesta saneadas, HTTP/status, tareas solicitadas y cubiertas, producto/campo esperado y resuelto, aclaraciones y pendientes antes/después, ruta, llamada real al proveedor cuando corresponda, documentos recuperados, correlation_id y latencia. |
| `resumen.md` | Resultado legible: alcance, qué se ejecutó realmente, versiones, resultados P0, cobertura de los 236 casos y de los 36 recorridos multi-turno, fallos reproducibles, regresiones, bloqueos, capacidades pendientes y siguiente acción concreta. |
| `comandos.log` y `junit.xml` | Comandos reproducibles sin credenciales, salida saneada y códigos de retorno reales. Genera JUnit si el framework lo soporta; si no, conserva un reporte equivalente del runner y explica su formato. |
| `evidencias/` | Trazas mínimas y saneadas necesarias para sostener los resultados. Capturas solamente si se probó la UI; no atribuyas a la UI una prueba realizada por API. |
| `checksums.sha256` | Huellas de los archivos de la corrida, excluyendo este archivo. Permiten comprobar después que las evidencias no cambiaron. |

Mantén `works/qa_runs/INDEX.md` como historial acumulado: una fila por corrida con fecha, revisión, entorno, alcance, resumen de resultados y enlace a su `resumen.md`. Conserva cada carpeta terminada sin modificaciones; las correcciones generan otra corrida con otro ID.

### Qué debe demostrar cada prueba

- Compara **lo esperado con lo obtenido**, por tarea y campo. HTTP 200, una respuesta no vacía o `PASS_SAFE` no acreditan resolución. Evalúa también contrato, selección del producto, exactitud del campo, evidencia de conocimiento, continuidad y cobertura completa de la pregunta.
- En recorridos multi-turno, conserva la misma sesión y registra todos los turnos. Una selección posterior debe completar las tareas pendientes sin perder definiciones, comparaciones o datos de otros productos. Un recorrido solo aprueba cuando cumple sus aserciones de extremo a extremo.
- Separa explícitamente pruebas locales con mocks, modelo Azure real con fixtures, Azure real con `lab_fallback`, Azure real con Core vivo y pruebas de UI. Registra proveedor efectivamente invocado y origen real por turno; no deduzcas una llamada Azure por latencia ni por el flag configurado.
- Cuando una aserción exija dato bancario, compara con la fuente autorizada correspondiente. Sin fuente verificable, registra la limitación. No uses la propia respuesta del modelo como oráculo ni permitas que otro LLM apruebe por sí solo cifras, fechas o identidad del producto.
- Reporta numeradores y denominadores: casos inventariados, ejecutados, aprobados, fallidos, parciales, bloqueados, no aplicables y no ejecutados. Cuenta casos únicos y turnos por separado; no aumentes cobertura contando reintentos como casos nuevos. Separa las dimensiones funcional, privacidad y contrato.
- Guarda resultados de forma incremental. Si el proceso se interrumpe, conserva lo ejecutado, marca la corrida `INCOMPLETE` y el resto `NOT_EXECUTED`. Un salto de pytest, una dependencia caída o una prueba preparada no equivalen a aprobación.

### Corrección y repetición

Ejecuta primero los P0 y la regresión relevante; después, los demás casos de la guía. Ante un fallo, conserva pregunta, contexto mínimo saneado, esperado/obtenido, ruta y causa; corrige dentro de la capa cognitiva y repite el caso junto con la regresión afectada. Vincula la nueva corrida a la anterior y documenta el cambio que explica el resultado. No alteres el oráculo para convertir un fallo en éxito, no codifiques respuestas por `case_id` y no elimines evidencias de intentos fallidos.

Para comparar antes/después, usa el mismo caso, oráculo y fixture versionados. Si cambió el contexto Core entre corridas, indícalo y no atribuyas automáticamente el cambio de respuesta a una mejora del código. Si la línea base no pudo ejecutarse, declárala ausente; no reconstruyas un resultado histórico como si fuera una prueba real.

Sanea **antes de guardar**: nunca registres tokens, Access Keys, PIN, OTP, CVV, credenciales ni snapshots completos de clientes. Usa seudónimos estables para cliente, sesión y producto; conserva paths de campos, moneda, procedencia y resultados de comparación sin exponer números de cuenta ni valores financieros reales. Los valores ficticios pueden quedar visibles si están identificados como sintéticos. Las capturas deben estar saneadas; si no es posible, omítelas y deja evidencia textual saneada.

Al terminar, enlaza el historial y el reporte de la última corrida desde `works/ENTREGA_POTENCIACION_LUNES.md`, incluye la lista de fallos pendientes y entrega un ZIP con los registros saneados. Indica qué puede revisarse localmente y los comandos para repetir la validación. **No declares completada una validación remota que no ejecutaste ni cierres la entrega sin el registro de las pruebas efectivamente realizadas.**

## Telemetría y entregables finales

Registra sin PII sensible: correlation_id, ruta y motivo, versión de esquema/prompt/corpus/modelo, proveedor efectivamente invocado, número de tareas/facetas, resultados por tarea, IDs de evidencia, latencia por etapa, origen/completitud/edad de contexto y causa de degradación. Métricas separadas: interpretación, resolución de entidad/campo, retrieval, memoria, cobertura final y latencia p50/p95.

Entrega:

- Diff implementado y límites externos preservados.
- Ingestión reproducible, catálogo y mapeos Core confirmados; pendientes explícitos.
- Bundle QA/índice versionado, comparación con corpus anterior y reversión.
- Matriz 236 con oráculo, fuente, fixture/origen, ruta, evidencia y estado real.
- Recorridos P0 completos antes/después, incluyendo turnos de aclaración.
- Evidencia Azure real cuando se haya ejecutado; no declarar éxito remoto por mocks.
- Historial `works/qa_runs/INDEX.md`, carpetas de ejecución con esperado/obtenido por caso y turno, y ZIP de registros saneados según Fase 6.
- `works/ENTREGA_POTENCIACION_LUNES.md` con capacidades listas, brechas, métricas y pasos remotos preparados que no se hayan ejecutado.

No cierres con “listo” si únicamente redactaste documentos o pasaron tests permisivos. Implementa el recorrido completo hasta la respuesta de `/turn` y muestra los límites que permanezcan. Si un dato falta en Core o en la fuente, resuelve el resto y registra la dependencia concreta.

Referencias técnicas: [salidas estructuradas](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs), [búsqueda híbrida](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview). Usa las versiones compatibles con el deployment existente; no copies ciegamente un ejemplo de otra API.
