# Prompt para Cursor — mejora cognitiva basada en pruebas reales de QA

## Objetivo y resultado esperado

Trabaja sobre el checkout **actual** de la banca conversacional. Implementa las mejoras locales necesarias para que la capa cognitiva comprenda solicitudes compuestas, cambie de tema, resuelva referencias y responda con evidencia. Entrega código, pruebas de comportamiento y un informe reproducible. Completa el trabajo local necesario; no te detengas tras otro diagnóstico ni después de un único parche de palabras clave.

Lee primero `Modelo_Mejora_Cognitiva_QA_V3.md`, los casos extraídos del Word y los casos adicionales incluidos en este paquete. Las rutas de este paquete deben resolverse desde donde lo coloque el usuario. Busca las rutas reales del proyecto antes de editar.

## Alcance y límites ya acordados

- Se puede modificar toda la **capa cognitiva**, incluida su orquestación interna, `brain/turn_orchestrator.py`, `demo/contract_inspector_app.py`, adaptador de `/turn`, routers, ejecutores, estado, herramientas internas, recuperación y redacción.
- El directorio externo `C:\NovusIntelligence\BancoSantaCruz\BancaConversacional\BSC.genesis.conversational.backend` es **solo lectura**. No modificar frontend, WebSocket productivo, servicio externo de contexto ni contratos consumidos por ese backend.
- La ruta productiva identificada es `POST /turn`. Las pruebas de `/inspect` por sí solas no acreditan integración productiva.
- Conserva la compatibilidad ya acordada: para contención NL, HTTP 200 con `SESSION_BUSY` y `client_response` string; para carga de contexto que no pudo persistirse, el comportamiento documentado HTTP 503 / `CONTEXT_LOAD_BUSY` / `persisted=false`. Verifica estos comportamientos en el checkout actual antes de reutilizarlos. No agregues campos ni estados incompatibles al contrato externo para exponer telemetría.
- Conserva las mejoras existentes de copias, CAS, frescura, candados y aislamiento. No las rehagas por defecto ni vuelvas a introducir referencias mutables o un retry de escritura con revisión nueva.
- No ejecutar transacciones bancarias, cambiar índices/agentes/configuración remota, desplegar ni usar secretos de un ZIP. Este encargo autoriza implementación y validación local. Existe autorización previa de consultas funcionales de lectura en QA con usuario 726588 mediante el acceso ya aprobado; el identificador no es una credencial ni autoriza otros clientes. Usa QA solo si ese acceso está disponible sin alterar servicios compartidos; registra bloqueos reales sin fabricar éxito.
- Redis local o Azure pendiente no debe bloquear las correcciones semánticas. Separa explícitamente las pruebas locales de las distribuidas y de Azure real.

## Evidencia de partida: no asumir que la copia histórica es el servicio actual

El Word registra 236 escenarios: 95 Cumple, 72 Cumple parcialmente y 69 No cumple. Son etiquetas del documento, no resultados de esta implementación. Se extrajo el texto de todos los casos y se revisaron visualmente 34 capturas de 24 casos, más una captura independiente.

Hallazgos que debes reproducir y corregir:

1. Tras consultar un préstamo, `mision del banco` y después `vision` producen una aclaración genérica repetida. La FAQ histórica sí tiene misión (`vf01-r80`) y visión (`vf01-r82`). En esa versión, el detector `_is_explicit_knowledge_request` no reconoce estas expresiones cortas. Comprueba qué componente produce actualmente la salida; no atribuyas el fallo al modelo sin traza.
2. P01–P15: faltan subpreguntas, se pierden pendientes tras seleccionar producto y se muestran campos excluidos. En P15 se pidió omitir balance/capital.
3. CD13 y GR02: preguntas generales de pago mínimo o proceso de cancelación terminan en datos personales. Una palabra no determina el ámbito ni autoriza una operación.
4. MIX07: tras explicar Multicrédito, `¿Tengo yo ese producto?` termina en saldo de una cuenta.
5. CC02/CC03: añadir un producto del catálogo a una comparación se confunde con seleccionarlo en el portafolio del usuario. Se pierde el conjunto ordenado.
6. X05/X06: PIN/OTP del mensaje se interpretan como terminaciones de producto. X07: pregunta sobre el esposo recibe un saldo presentado como propio. Esto no prueba acceso a datos del esposo; exige corregir interpretación de titularidad y salida.
7. API QA previa: disponible se enruta a préstamos y saldo actual se confunde con disponible. Modelo Azure estructurado no acreditado mediante traza; contexto reportado `lab_fallback`.

Antes de convertir las etiquetas en assertions, revisa D04 e IG01. D04 muestra contexto previo de préstamo: responder su tasa puede ser correcto si el referente es inequívoco. IG01 contiene misión, visión y diferencia pese a etiqueta parcial. Conserva la discrepancia y reejecuta con precondiciones definidas; no fuerces un fallo o éxito por la etiqueta.

## 0. Baseline y procedencia

Identifica commit local, cambios sin commit, punto de entrada, orden efectivo de handlers, versión desplegada conocida, modelo/deployment configurado, flags, ruta de conocimiento y origen del contexto. No imprimas credenciales, cadenas de conexión, tokens ni datos financieros personales en la entrega.

Añade una traza interna estructurada y depurada con identificador de correlación, versión, ruta, origen del contexto, estado inicial/final resumido, plan, ejecutor, IDs de evidencia y resultado. Para Azure registra intento, resultado, validación de esquema, error y si hubo bypass. La latencia o la redacción natural no prueban que el intérprete Azure se ejecutó. No solicites ni almacenes razonamientos internos del modelo; basta información operativa de decisiones.

Reproduce los fallos seleccionados con fixtures locales y por `/turn`. Conserva una pequeña regresión de lo que ya funciona. No cambies el deployment del modelo ni el SDK sin una incompatibilidad concreta demostrada.

## 1. Entrada, titularidad y reparación institucional inmediata

Aplica detección contextual y redacción de PIN, OTP, CVV y contraseñas **antes** de extracción de números de producto, historial, logs de aplicación y llamadas al modelo. Reutiliza guardrails existentes y comprueba su ejecución en todas las rutas de lenguaje natural. No suprimas toda cifra: un sufijo de producto explícito es diferente de un PIN declarado. Prueba la colisión donde el PIN coincide con el sufijo de un producto del fixture.

La identidad y los productos autorizados provienen del contexto autenticado del servidor. Nunca de `customer_id`, un número de cuenta o una afirmación del mensaje/LLM. Una consulta de datos de terceros no puede transformarse silenciosamente en una consulta propia. Mantén consultas generales sobre terceros sin revelar datos personales y continúa únicamente con subconsultas propias autorizadas y claramente separables.

Repara el camino institucional para misión, visión y otras entidades reconocidas de la taxonomía, incluyendo texto corto y errores ortográficos habituales. Debe funcionar sin snapshot personal, tras una consulta personal y durante un pendiente personal. Verifica recuperación real de las entradas existentes; si no hay evidencia, devuelve una limitación específica sobre ese conocimiento, no otra pregunta genérica de categoría. Esta reparación debe integrarse con el plan semántico del siguiente paso.

## 2. Un plan semántico interno con múltiples tareas

Evoluciona el `IntentPacket` actual hacia un `TurnPlan`, conservando un adaptador temporal para casos simples. Define un contrato interno validado que incluya:

- `tasks[]`, cada una con ID, dominio, acción, objeto, campos, ámbito y cardinalidad.
- Ámbitos independientes: `personal`, `catalog`, `institutional`; cardinalidad independiente: `single`, `all`, `compare`.
- Referencias de entidad, filtros, exclusiones de campos, dependencias, operadores y slots no resueltos.
- Transición conversacional propuesta: selección, corrección, cambio de tema, ampliación de comparación o continuación.
- Estado por tarea: lista para ejecutar, requiere aclaración, no soportada o error. El ejecutor determina disponibilidad real del dato.

Usa Structured Outputs si el deployment configurado lo soporta. En modo estricto, todas las propiedades declaradas deben estar en `required`, las opcionales representarse con `null` conforme al esquema y los objetos cerrarse con `additionalProperties: false`, también en tipos anidados. Valida semántica adicional: campos permitidos por objeto, acciones soportadas, IDs únicos, dependencias existentes y sin ciclos, referencias compatibles y exclusiones respetadas.

El LLM no puede producir identificadores personales autoritativos ni ejecutar consultas fuera del contexto permitido. El resolutor servidor valida candidatos contra el portafolio autorizado. No inventes capacidades de movimientos, cancelación, transferencias u otras operaciones ausentes.

Haz que las familias migradas produzcan un plan antes de responder. Los fastpaths útiles pasan a ser resolutores o ejecutores compatibles con ese plan. Una selección inequívoca puede evitar una llamada adicional al modelo, pero debe preservar todas las tareas pendientes. Retira gradualmente los bypass que responden por una palabra aislada. Saludos/emoción no pueden absorber una pregunta bancaria contenida en el mismo mensaje.

No uses únicamente un score de confianza del LLM para resolver ambigüedad: cuenta candidatos compatibles, referencias y slots necesarios. Distingue ambigüedad de referente, dato ausente, conocimiento no recuperado, herramienta no disponible y error técnico.

## 3. Estado de conversación y referencias

Amplía el esquema de sesión con migración compatible para estados anteriores:

- Focos separados personal, conocimiento y proceso.
- Conjunto de comparación con entidades, ámbito y orden **realmente mostrado**.
- Lista de tareas pendientes completas, opciones ofrecidas y campos ya respondidos.
- Referencias recientes tipadas, último producto resuelto, historial depurado y resumen.
- Revisión, versión del esquema y frescura de origen existentes.

Una mención o corrección explícita actual tiene prioridad. Después considera pendiente compatible y foco compatible. No ejecutes un pending antiguo antes de interpretar una corrección o cambio explícito de tema. Conserva lo pendiente que siga vigente y marca lo sustituido/cancelado para que no reaparezca.

Resuelve `esa`, `la otra`, `la segunda`, `ambas`, `este último` contra conjuntos concretos. Una excursión institucional puede dejar disponible el foco personal anterior; eso no autoriza a usarlo en una referencia ambigua al catálogo. Reanuda con aclaración focalizada cuando haya varios referentes plausibles.

Para peticiones mixtas, responde la parte independiente sustentada y conserva la parte que requiere selección. Detecta repetición de aclaraciones sin progreso; reinterpreta con el pendiente y formula una pregunta específica. No adivines tras un número de intentos.

Ejecuta cambios sobre copias y confirma estado con el mecanismo de concurrencia ya implementado antes de devolver una respuesta definitiva compatible. Comprueba por `/turn` tanto texto como carga de contexto. No declares Redis multiproceso validado si solo se usó in-memory.

## 4. Taxonomía, capacidades y recuperación

Reutiliza el Excel y el paquete de conocimiento existente. Separa cuatro artefactos versionados: taxonomía, capacidades técnicas, hechos/procedimientos y evaluación. Dominio/acción/objeto/campo son dimensiones semánticas relacionadas: no obligues cada objeto a tener una única acción mediante un árbol rígido.

Mantén identificadores de catálogo y alias aprobados. No declares equivalentes Multicrédito, Crédito Diferido, tarjeta, préstamo o sus variantes solo porque una captura los mezcla. Registra relaciones y mapeos a familias del portafolio que estén sustentados por fuentes y contratos.

Cada campo personal necesita definición, ruta del contrato real, tipo, moneda/unidad, fuente, frescura y comportamiento ante ausencia. Separa `available_balance`, `current_balance`, capital pendiente, deuda y cotización de cancelación. Un `null` no es cero. Una coincidencia numérica entre dos campos no demuestra equivalencia.

Unifica FAQ y Foundry/Search tras una interfaz de conocimiento. Audita la versión activa antes de cambiar corpus. Recupera por entidad y faceta; en comparaciones busca evidencia de cada producto y marca las celdas no sustentadas. Evalúa búsqueda híbrida cuando esté disponible en la integración actual. No agregues otra base paralela ni migres a una API nueva sin necesidad.

Prepara un informe de brechas de conocimiento: entrada existente que no se recupera, entrada desactualizada, faceta ausente, conflicto entre fuentes o producto mal mapeado. Cada propuesta conserva Excel/hoja/filas, versión, vigencia y revisión bancaria. No subas el Word de QA, capturas, respuestas fallidas o datos personales a Foundry como conocimiento.

## 5. Evidencia, cálculo y respuesta

Los ejecutores retornan evidencia tipada por tarea: entidad autorizada, campo, valor, moneda/unidad, fecha, procedencia y disponibilidad. Los cálculos de fechas, ordenamiento y montos se realizan en código. No sumar monedas diferentes ni comparar tasas con bases distintas sin una regla autorizada.

El compositor debe cerrar cada tarea con respuesta, aclaración o limitación específica. Debe respetar campos excluidos tanto en texto como en tarjetas. Las cifras se renderizan desde evidencia verificada. Comprueba asociaciones entidad/campo/valor/moneda/fecha; una comparación del conjunto de números del texto no detecta valores intercambiados.

Normaliza citas al formato soportado por el contrato actual; no envíes marcadores crudos del proveedor. Usa fallback determinista completo cuando falle la redacción. No inventes plazos, condiciones, aprobación de crédito ni transferencia a un humano.

## 6. Validación y aceptación

Los 236 casos extraídos son un inventario inicial; necesitan precondiciones y oráculos adjudicados para ser tests ejecutables. Revisa el origen de cada fixture. Los casos adicionales son **propuestos y no ejecutados**, con cifras sintéticas donde se indica; nunca deben entrar en el corpus bancario.

Para cada familia prueba sesión limpia y contexto previo definido. Usa clientes/fixtures con la cardinalidad necesaria. El cliente QA 726588 reportó una cuenta DOP y dos préstamos; no demuestra USD, tarjetas o certificados. Marca escenarios no aplicables y valida esas ramas con fixtures claramente sintéticos o con otro acceso autorizado posteriormente.

Prueba cuatro niveles: plan/entidades; transición de estado y ejecuciones tipadas; endpoint `/turn` conservando contrato; integración real con Azure y fuentes autorizadas cuando estén accesibles. No confundas un mock con el último nivel. Las pruebas de prosa deben evaluar significado y cobertura, no una frase exacta.

Casos mínimos obligatorios:

- Misión/visión cortas, sin acentos, juntas, tras préstamo y con pendiente previo.
- Disponible y saldo actual con valores diferentes y con campo ausente.
- Selección que reanuda varias subpreguntas; exclusión de balance en texto/tarjetas.
- Corrección de producto/campo, cambio de tema y typo sin pérdida de intención.
- Definición/proceso general que no consulta datos personales.
- Catálogo → existencia en portafolio y comparación sin requisito de poseer esos productos.
- Agregar/quitar entidades de comparación y resolver ordinales según orden mostrado.
- Ambigüedad en sesión limpia y la misma frase con foco inequívoco.
- PIN/OTP no utilizados como sufijos; titularidad ajena sin respuesta de saldo propio.
- Fallo de Azure/RAG, ausencia de datos y bucle de aclaraciones con salidas específicas.

Mide por separado tareas, entidades, aclaraciones, continuidad, recuperación, evidencia financiera, cobertura final, latencia y fallback. Conserva un conjunto reservado de variantes por conversación y familia. Propón como gates: 100 % de controles críticos, cero cifras inventadas o mal atribuidas, y al menos 95 % de continuidad/resolución y cobertura de subintenciones aplicables en la evaluación reservada. Reporta el resultado obtenido; no ajustes el denominador ocultando fallos.

## Entrega

Entrega el diff cognitivo; listado de rutas modificadas; diseño y migración de estado/plan; matriz de campos y capacidades; informe de brechas de KB; pruebas con resultados reales; ejemplos antes/después depurados; y pendientes de QA/Redis claramente separados.

Usa `works/ENTREGA_MEJORA_COGNITIVA_V3.md` para resumir versión, alcance, comandos ejecutados, resultados, límites y ruta para la siguiente validación. Comprueba por diff que el backend externo no cambió. No declares una capacidad aprobada por tener un test que omite la ruta real o por modificar exclusivamente la expectativa del test.

Empieza identificando el checkout y reproduciendo los fallos. Continúa con las correcciones locales y pruebas hasta dejar una implementación concreta y revisable.
