# Cursor — cierre funcional local de V3.1

## Encargo

Continúa desde la entrega «Mejora cognitiva V3» del 18 de septiembre de 2026. Conserva las correcciones ya implementadas y completa la ejecución del plan por tareas, el estado conversacional y la separación entre catálogo y productos personales. La entrega anterior es una estabilización local parcial: declara expresamente pendientes las capacidades centrales de V3.

El resultado solicitado es código funcional integrado por `POST /turn`, pruebas reproducibles y un informe de cobertura. No basta con declarar clases nuevas o convertir un `IntentPacket` de una tarea en un contenedor con una tarea. Completa el trabajo local; los bloqueos de Azure, Redis o fuentes externas deben quedar separados y no detener las partes implementables con fixtures.

## 1. Insumos y procedencia

Este paquete incluye, bajo `insumos/`:

- `Modelo_Mejora_Cognitiva_QA_V3.md`.
- `Prompt_Cursor_Banca_V3_Pruebas_QA.md`.
- `Casos_QA_236_Extraidos.jsonl`: exactamente 236 registros únicos.
- `Casos_QA_Adicionales_V3.jsonl`: exactamente 24 registros únicos, propuestos y no ejecutados.
- `Resumen_QA.json`.

Resuelve las rutas desde la ubicación de **este archivo**, no desde Downloads. Enumera los archivos encontrados y valida los conteos JSONL antes de afirmar cobertura. Lee el modelo y los casos pertinentes. Este prompt precisa el cierre a partir de la entrega más reciente; el modelo anterior aporta el diseño completo.

Si falta un archivo, informa su ruta exacta y continúa con los criterios autocontenidos de este prompt. No sustituyas los casos por una lista inventada ni declares revisada la matriz ausente. La ausencia del Word original no impide usar los escenarios extraídos; las dudas sobre capturas se registran como adjudicación pendiente.

El informe anterior dice que no hay git usable. Identifica el mecanismo real de versionado disponible. Si sigue ausente, registra un manifiesto SHA-256 de los archivos relevantes antes/después, dependencias y configuración no secreta, y conserva una copia local de las versiones que vayas a editar. No inicialices un repositorio padre ni alteres el backend externo. La versión `0.8.0` sola no identifica el código validado.

## 2. Límites que se mantienen

Puedes modificar toda la capa cognitiva, su router y su orquestación interna, incluyendo `contract_inspector_app.py` y `brain/turn_orchestrator.py`.

Es de solo lectura:

`C:\NovusIntelligence\BancoSantaCruz\BancaConversacional\BSC.genesis.conversational.backend`

Mantén frontend, WebSocket productivo, servicio externo de contexto y contrato consumidor. Conserva copias, CAS, frescura y candados existentes. No rehagas esa infraestructura salvo un defecto concreto demostrado.

Respeta el comportamiento previamente acordado: NL ocupado retorna HTTP 200, `SESSION_BUSY` y texto string; carga de contexto no persistida retorna el error existente HTTP 503 / `CONTEXT_LOAD_BUSY` / `persisted=false`. Verifica el contrato completo, no únicamente el código HTTP.

Este trabajo es local: sin despliegue, transacciones ni cambios a índices, agentes o corpus remotos. No imprimir ni pedir que el usuario pegue claves en el chat. Las consultas de lectura QA previamente autorizadas con usuario 726588, si se ejecutan por el acceso aprobado, deben documentarse aparte; ese ID no es autenticación ni permite probar otros clientes. Redis/Access Key no es requisito para completar semántica y pruebas locales.

## 3. Verifica que los hotfixes no introduzcan regresiones

Los siguientes son **riesgos por comprobar**, no fallos ya demostrados del nuevo código:

### Disponible no implica siempre cuenta

Verifica la heurística `liquidez → account` y `resolve_option_pool`. Primero resuelve producto explícito, corrección, pendiente compatible y foco; después decide el campo y los candidatos por capacidad. No cambies a cuenta por una palabra si el usuario está consultando una tarjeta.

| Precondición / pregunta | Comportamiento esperado |
|---|---|
| Foco tarjeta inequívoco → «¿cuánto tengo disponible?» | Disponible de esa tarjeta, si existe ese campo |
| Sin foco → «disponible de mi tarjeta» | Selección de tarjeta si hace falta; nunca cuenta |
| Foco tarjeta → «disponible de mi cuenta» | La mención explícita cambia a cuenta |
| Una cuenta y préstamos sin capacidad de disponible; sin otro foco | Cuenta, manteniendo el caso QA A2 corregido |
| Cuenta y tarjeta elegibles, sin foco → «¿cuánto tengo disponible?» | Aclaración concreta, según capacidades reales |
| «¿Qué significa saldo disponible?» | Definición general con evidencia |
| «¿Cuánto disponible tiene mi préstamo?» | Usar campo real si está soportado; si no, explicar esa limitación, sin convertirlo a cuenta |

Comprueba el mapeo de `ledger_balance` contra el contrato/documentación real del contexto y su adaptador. El nombre del atributo no acredita que signifique «saldo actual». Prueba fuente → normalización → evidencia → etiqueta final con valores distintos, `null` y cero. No uses disponible como sustituto silencioso.

### FAQ institucional sin omitir otras tareas

Revisa `institutional_faq_pre_brain`: el atajo debe cubrir la solicitud completa o aportar solo la evidencia de la tarea institucional al plan. No retornar antes de atender las otras subpreguntas.

Prueba al menos:

- «misión y visión» → ambas, incluso si la FAQ devuelve una sola coincidencia de score 1.0.
- «Dime la misión y cuánto tengo disponible en mi cuenta» → dos tareas; responde/aclara cada una.
- «No pregunté por la misión; quiero la tasa de mi préstamo» → atender la corrección.
- Pendiente de selección de préstamo → misión → «retomando el préstamo, el segundo» → reanudar la tasa pendiente.
- Consulta institucional sin snapshot personal → puede responder con conocimiento disponible.

### Secretos y titularidad

Demuestra que el secreto queda depurado antes de logs de aplicación, historial, extracción de sufijos y payload enviado al modelo. Bloquear la ficha del producto no demuestra por sí solo que no se guardó o transmitió el secreto.

Centraliza la depuración en la entrada cognitiva y conserva defensas en resolutores. Usa únicamente PIN/OTP/CVV sintéticos en tests. Captura las superficies anteriores para verificar que el valor no aparece. Un número declarado como PIN no puede seleccionar producto aunque coincida con su sufijo. Un sufijo declarado como tal puede seguir usándose en el contexto autenticado.

La autorización procede del contexto del servidor. Los parentescos no son una política de autorización: «¿cómo abro una cuenta para mi hijo?» es una pregunta general; «saldo de mi esposo» solicita información ajena. Prueba ambas. No sustituir una consulta ajena por el saldo propio. Se puede conservar una subconsulta propia independiente y autorizada después de depurar el mensaje, sin usar el secreto.

## 4. Cablea TurnPlan a la ruta completa

Extiende el intérprete para producir varias tareas desde **el mensaje original completo y el estado**, antes de que un clasificador de intención única descarte información. Mantén un adaptador para flujos legados simples durante la migración.

El plan debe contener:

- Lista de tareas con ID, dominio, acción, objeto, campos, ámbito y cardinalidad.
- Ámbito `personal`, `catalog` o `institutional`, independiente de `single`, `all` o `compare`.
- Referencias, filtros, exclusiones, dependencias, criterios de comparación y slots pendientes.
- Transición de contexto propuesta y estado de resolución de cada tarea.

Usa el mecanismo de salida estructurada ya compatible con el deployment. Valida tanto estructura como semántica: acción/campo aplicable al objeto, referencias autorizadas, dependencias existentes y sin ciclos, IDs únicos, límites de ejecución y exclusiones. No migres modelo o SDK para resolver este encargo sin necesidad demostrada.

El flujo efectivo debe ser: entrada depurada → interpretación/selección compatible → plan validado → resolución → ejecución → evidencia por tarea → respuesta completa → commit compatible de estado → respuesta al consumidor. Una respuesta definitiva solo se publica con el estado confirmado conforme al mecanismo existente.

Los fastpaths conservados deben producir el mismo plan o resolver sus tareas con precondiciones explícitas. Muestra qué ruta ejecutó cada caso. Evita un camino nuevo usado solo por tests mientras `/turn` sigue atendiendo por handlers antiguos que omiten partes.

No es obligatorio llamar al LLM para una selección inequívoca ni para una consulta determinista completamente cubierta. Sí es obligatorio conservar el significado completo y distinguir el bypass del uso real del intérprete Azure.

## 5. Ejecución y estado por tareas

Implementa ejecución de tareas independientes y dependientes sin perder las bloqueadas. Cada resultado tendrá entidad, campo, valor, moneda/unidad, fuente, frescura y estado: disponible, ausente, requiere aclaración, no soportado o error. Distingue el dato ausente de un referente ambiguo.

Los cálculos y el orden de fechas se realizan con código; mantén precisión decimal y monedas separadas. No calcules monto de cancelación renombrando capital pendiente.

Amplía el estado con focos personal/conocimiento/proceso, lista de pendientes completos, referencias y conjunto de comparación ordenado. Migra estados antiguos de forma compatible. Persiste y recarga ese estado entre peticiones reales al endpoint.

Prioridades de referencia: instrucción/corrección explícita actual; pendiente compatible; foco compatible. No ejecutes un pendiente antiguo antes de interpretar un cambio explícito. Al corregir, invalida las partes sustituidas para que no reaparezcan. Conserva la excursión institucional como tema diferente y permite retomar la consulta personal.

Pruebas esenciales:

- P01: deuda + disponible + fecha de pago; seleccionar tarjeta reanuda los tres campos.
- P13/P14: dos productos con proyecciones distintas, sin intercambiar atributos.
- P15: todos los certificados, tasa y vencimiento, primero en vencer, sin balance/capital en texto **ni tarjetas**.
- C/R: «la otra», «no, la corriente», cambio de campo y selección ordinal.
- Pregunta mixta con una parte inequívoca y otra ambigua: responder lo sustentado y aclarar solo lo pendiente.

El compositor consume el plan y su evidencia. Toda tarea debe tener un resultado visible o una limitación específica. Una limitación correcta cuenta como manejo correcto, no como dato recuperado. Verifica la asociación entidad/campo/valor/moneda; la mera presencia de los mismos números en el texto no detecta intercambios.

## 6. Catálogo, procesos y existencia de productos

Completa CD13/GR02: explicar pago mínimo o comparar procesos de cancelación no requiere seleccionar un producto propio ni consultar su monto de cancelación.

Completa MIX07: «¿Tengo yo ese producto?» debe resolver el referente del catálogo y consultar existencia mediante el mapeo autorizado al portafolio. Si el mapeo o el snapshot no permiten determinarlo, exprésalo; no equivale a que el producto no exista. No inferir equivalencias bancarias porque los nombres se parecen.

Completa CC02/CC03: comparar productos del catálogo no exige poseerlos. Guarda el conjunto y el orden efectivamente mostrado. Agregar/quitar una entidad actualiza ese conjunto; «la segunda» apunta a la segunda del conjunto vigente. Recupera evidencia por entidad/faceta y representa explícitamente lo que falta.

Reutiliza la interfaz de FAQ/Foundry y las fuentes existentes. Separa la ausencia de contenido del fallo de ruteo. Este trabajo no exige publicar un índice nuevo.

## 7. Telemetría y compatibilidad

Conserva `correlation_id`, `route_steps`, `brain_source`, `context_source` y agrega solo telemetría interna compatible que permita distinguir:

- Plan generado y validado, número de tareas y estados por tarea.
- Intérprete del plan vs redactor: cada uno puede usar modelo o bypass diferente.
- Intento Azure, resultado, error sanitizado y validación estructurada.
- Fuentes usadas, motivo de aclaración y estado antes/después resumido.

No almacenar prompts crudos, secretos ni datos financieros personales en el informe. No registrar razonamiento interno del modelo. Usa IDs internos o seudónimos donde sea suficiente.

Valida el JSON completo de `/turn` con su schema consumidor. Que HTTP sea 200 no demuestra compatibilidad. Comprueba también texto no vacío, strings requeridos, tarjetas coherentes, flujo de carga de contexto y ocupación. No ocultar `SESSION_BUSY` como éxito de negocio.

## 8. Pruebas y criterio de cierre

Conserva las 11 pruebas V3 reportadas y las regresiones pertinentes. Añade tests de los comportamientos anteriores sobre los ejecutores reales y `/turn`, con estado recargado entre turnos. No mockear el plan, la continuidad o el executor que se pretende validar. Se puede simular el transporte Azure y fuentes externas, dejando ese nivel identificado.

En paralelo lógico a la implementación, importa los 236 escenarios y los 24 adicionales. Adjudica las precondiciones de cada caso que ejecutes: sesión, portafolio, capacidades y evidencia esperada. Revisa D04/IG01 como indica el modelo. No convertir automáticamente las etiquetas del Word en verdad de los tests.

Entrega una matriz por ID con `passed`, `failed`, `blocked`, `not_applicable` o `not_executed`, motivo, precondiciones, ruta ejercitada y nivel de integración. Un caso bloqueado o no ejecutado no cuenta como aprobado. No derives una mejora porcentual de la comparación entre 11 tests unitarios y 236 escenarios del Word.

El cierre de implementación local requiere demostrar, como mínimo, los cinco recorridos completos:

1. Cuenta y tarjeta con disponible: el foco correcto decide, y la definición se atiende por conocimiento.
2. Misión + consulta personal en un mismo mensaje; interrupción institucional y retorno al pendiente.
3. Consulta de varios campos y productos, selección pendiente y exclusión de balance.
4. Catálogo → existencia personal, y comparación ordenada con adición de producto.
5. Secretos depurados antes del modelo/persistencia y titularidad correcta sin bloquear preguntas generales legítimas.

Cada recorrido debe estar cableado a `/turn` y validado en estado y respuesta. Las pruebas unitarias que solo construyen `TurnPlan` no cierran el criterio.

Para aceptación final del sistema, registra aparte la cobertura de la matriz completa, variantes reservadas, Azure real, contexto autorizado y concurrencia distribuida. El cliente QA 726588 conocido no cubre por sí solo tarjetas, USD y certificados; no inventar esos productos en su contexto real. Usa fixtures sintéticos claramente aislados para esas ramas locales.

## 9. Entrega final

Genera `works/ENTREGA_CIERRE_COGNITIVO_V3_1.md` con:

- Inventario de insumos realmente leídos y huella/versionado de código.
- Cambios implementados y rutas efectivas de `/turn`.
- Esquema del plan y migración del estado.
- Matriz de cobertura por escenario y ejemplos depurados de los cinco recorridos.
- Comandos ejecutados, resultados y prueba de contrato.
- Evidencia de que el backend externo permanece sin cambios, indicando si se verificó por git o manifiesto.
- Pendientes reales de servicios remotos separados del trabajo local.

No declares V3 completa si la ejecución multi-tarea, las referencias o los cambios catálogo/personal siguen como «base lista». Continúa hasta concretar el alcance local o documenta el impedimento técnico específico que imposibilita una parte, conservando el resto terminado.
