# Cursor — Implementar mejora incremental de contexto, RAG y rendimiento

Actúa sobre el checkout actual de BancaConversacional. Ejecuta implementación, pruebas y documentación; aprovecha lo que funciona. El objetivo es mejorar resolución semántica, continuidad y latencia con evidencias verificables. No declares capacidad plena por haber creado recursos o aumentado el porcentaje del evaluador.

## Instrucciones de arranque

Lee `Plan_Trabajo_Azure_Cognitivo.md`, `configuracion_objetivo_qa.json` y este prompt. La configuración adjunta es una especificación propuesta: **sus campos nuevos no son variables de entorno existentes ni API de Azure**. Crea un adaptador validado hacia la configuración real; produce una tabla de equivalencias. Conserva la integración y las dependencias actuales siempre que sean compatibles.

Usa como fuentes del proyecto: PDF RAG, corpus preparado BSC, guía conversacional original con imágenes y ZIP strict-v2.2. Resuelve rutas reales; no confíes en el sufijo de descarga. Revisa instrucciones del repositorio si existen. Registra hash de insumos y del código desplegado. No extraigas credenciales de ZIP ni registres secretos.

Alcance: solo capa cognitiva, pruebas, scripts de despliegue propios y configuración QA explícitamente autorizada. Directorio protegido:
`C:\NovusIntelligence\BancoSantaCruz\BancaConversacional\BSC.genesis.conversational.backend`.
Frontend, WebSocket, contratos externos, PROD y transacciones permanecen fuera del alcance de modificación. Probar la UI existente sí está autorizado. Cliente QA de lectura: 726588. Preserva Redis/Entra, CAS, candado, aislamiento, frescura y semántica actual de `/turn`.

## A. Descubrir y medir antes de cambiar

1. Identifica entrada real `/turn`, rutas FAQ/atajos/Azure, construcción de prompts, deployments efectivos, esquema y clientes Search, fuente del snapshot, claves Redis, versión del store y timeouts del consumidor por lectura del backend externo. No asumas que la VM y la PC ejecutan el mismo código.
2. Descubre recursos Azure exactos con sesión autorizada: suscripción, grupo, Search y sus índices, Redis, Foundry/deployments, MI runtime/ingesta, red privada y permisos. Recurso Redis reportado `bsc-cognitive-redis-qa`; VM reportada `vm-test002-genesis`; grupo reportado `RG_BSC_PRJ_GENESIS`. Confirma todo en runtime. No asumas que los otros servicios están en el mismo grupo o región.
3. Entrega `works/azure_mejora/INVENTARIO_REAL.md`: recurso/config actual, propuesta, permiso requerido, ruta real que la consume y reversión. Registra si algo es desconocido. Exporta configuración sin secretos y diff de cambios propuestos.
4. Baseline con casos de la guía, mismas precondiciones/reloj/oráculos. Medir latencia por fase, tokens, inferencias, rutas, error y cobertura. Preservar falsos positivos conocidos como pruebas negativas del evaluador; no consumir la jornada repitiendo suites que no aclaren un riesgo concreto.
5. Si no hay repositorio Git usable, crea manifest de archivos/hash y respaldo aislado; no inventes commit ni sobrescribas trabajo ajeno.

## B. Construir corpus candidato y fragmentación

Implementa pipeline reproducible con tokenizer compatible:
- Objetivo 600 tokens; banda 400–800; overlap inicial 80 dentro de misma sección/producto.
- Mantén fichas breves completas. Divide por semántica, títulos y tablas; nunca rellenes con otro producto.
- Conserva unidades regla/excepción; si necesitan más contexto, enlaza padre/hijos y recupera conjuntamente bajo presupuesto. Toda excepción de tamaño se registra; no truncar condiciones.
- Produce `chunk_id`, `parent_id`, texto, producto/familia/alcance, tipo de contenido/faceta, fuente/sección, aprobación/vigencia, hashes, versión del corpus y embedding.
- Conserva clasificación de publicación original. Material sin aprobación no se convierte en vigente. Las ampliaciones web requieren fuente y revisión de contenido; no uses internet en vivo para completar tasas, requisitos o importes.
- Ingestión incremental por hash; quitar chunks obsoletos solo del candidato; no borrar índice activo.
- Excluye preguntas de evaluación, etiquetas históricas, capturas, prompts y snapshots personales del índice.
- Evalúa perfiles 400/50, 600/80 y 800/100 sobre el mismo subconjunto de recuperación y publica tabla de calidad/latencia/tokens. Usa 600/80 si hay empate o faltan datos, marcándolo provisional.

Implementa índices candidatos en el servicio Search existente si capacidad/permisos lo permiten. Reutiliza embedding actual; si falta, prepara deployment y dimensionamiento compatibles sin cambiar vectores del índice activo. No codifiques dimensión sin comprobar la salida real.

Preferencia de implementación: pipeline Python existente que genera embeddings y sube documentos desde el entorno autorizado. Si ya existe vectorización integrada funcional, reutilízala en vez de duplicarla. Verifica conectividad de ingesta y de consultas por separado.

## C. Recuperación por producto y tarea

Crea/adapta un único contrato interno de retrieval consumible por todas las rutas documentales, incluido FAQ. Evita un FAQ local antiguo que anule el índice nuevo; puede quedar como caché versionada/fallback acreditado, con las mismas reglas de aplicabilidad y vigencia.

Consulta inicial: híbrida, k=50, top=5 por tarea, filtros de servidor y semantic ranker cuando esté configurado. Empieza con preFilter, pero comprueba recall y compatibilidad de API. Los filtros de identidad/permisos no los decide el LLM.

Aplicabilidad: producto específico exacto o ámbito general declarado que corresponda. Un documento de Joven no es general de tarjetas solo por compartir familia. Validar metadatos y contenido. No aceptar fuente por el rótulo con que la presenta el redactor. Comparaciones recuperan evidencia por producto y atributo, mostrando valores concretos o ausencia de documentación por atributo.

Deduplicar y seleccionar evidencia preservando cobertura. Presupuesto típico 5–8 fragmentos y 4.000 tokens totales; el adaptador puede ampliar según número de tareas y límite del modelo. La presión de tokens no autoriza omitir subintenciones.

Devuelve evidencia estructurada: documento/chunk/version, producto y alcance, faceta, contenido, procedencia y estado. El score ayuda a ordenar, no demuestra verdad. No devuelvas una definición de cliente para «mi tarjeta Joven».

## D. Memoria y ejecución de tareas

Trabaja con el esquema actual de sesión, migración aditiva y reversión compatible. Mantén snapshot autenticado y estado lingüístico diferenciados. Estado mínimo: revisión, schema_version, personal_focus, knowledge_focus, pending_tasks, compare_set ordenado, correcciones, hechos resueltos con procedencia y resumen breve.

Construye al intérprete una proyección compacta de productos autorizados: IDs internos opacos, nombres/alias, familia/subtipo, moneda, estado, campos aplicables y completitud. Importes quedan en el ejecutor; para filtros/comparaciones numéricas el modelo produce operaciones permitidas que el ejecutor evalúa sobre datos autorizados, sin código arbitrario. Nunca selecciones un producto por un ID inventado.

Usa últimos 6 intercambios y resumen de hasta 600 tokens como inicio; preserva el estado estructurado de pendientes aunque cambie la ventana de mensajes. Si la conversación excede presupuesto, comprime texto histórico sin alterar hechos ni autorización. El resumen no es una fuente bancaria.

TurnPlan debe representar todas las tareas, dependencias y cambios explícitos. Un prompt de referencia:
«Identifica cada solicitud del mensaje usando el estado autorizado. Distingue lectura personal, conocimiento y consulta mixta. Mantén los pendientes compatibles y aplica correcciones explícitas. Selecciona solo entidades candidatas autorizadas; con ambigüedad real devuelve aclaración mínima. No inventes productos, campos, valores ni acciones ejecutadas».

Prioridad: selector/corrección actual → aclaración pendiente compatible → foco compatible → único elegible → aclarar. Un cambio institucional no debe convertirse en continuación de préstamo. Una consulta general de fallecidos no equivale a pedir acceso a saldos de terceros.

Integrar atajos al mismo plan/ejecutor: pueden completar una tarea inequívoca, no borrar el resto. Ejecuta lecturas/retrieval independientes con límite inicial 2; agrega resultados de forma determinista y persiste una sola transición consistente. Preserva control de conflictos; nunca salvar una respuesta stale reintentando solo put con revisión nueva. Prueba lease expirado y propietario perdido antes de aceptar escrituras.

Respeta la política de frescura vigente. Los umbrales QA propuestos 60 s para dato volátil y 600 s para inventario son parámetros de clasificación, no nuevas llamadas Core ni reglas comerciales. Nunca renovar source_fetched_at por guardar sesión. Ante origen desconocido/fallido informa límite concreto, no inventes actualidad ni ausencia de producto.

## E. Cliente Redis y mejora de inferencia

Mantén fábrica Redis compartida y MI, pools reutilizables y red privada. Presupuesto inicial 16 conexiones por pool sujeto a workers/réplicas/capacidad. Expón en métricas cuál es el backend efectivo. QA/PROD no deben degradar silenciosamente a memoria.

Comprueba política de evicción, memoria/lease y compatibilidad de clúster con CAS. Propón noeviction para estado/candados solo con prueba de OOM y capacidad; no ejecutes CONFIG SET bloqueados ni cambies topología por defecto. La renovación Entra debe comprobarse durante un ciclo real cuando sea posible; registra si no se ejecutó. Conserva el arreglo que evita autenticación síncrona en el event loop.

Cachear retrieval documental es opcional: empezar deshabilitado, activar después de exactitud y medición. TTL ensayo 300 s, límite de entradas/bytes, clave incluye consulta/productos/facetas/permisos/idioma/versión; invalidar por revocación, vigencia y publicación. Nunca cachear respuestas personales globalmente. Evitar KEYS/FLUSHDB para limpiar.

Preserva deployment actual hasta medir alternativa. Structured Outputs estricto conforme al modelo/API real; required completo, additionalProperties false donde corresponda. Validar semántica con código, además de parsear JSON. Identificar error del proveedor, negativa y truncamiento.

Reduce verificador LLM obligatorio solo detrás de flag, demostrando equivalencia con verificaciones deterministas. Ruta normal: una interpretación y, si necesita redacción compuesta, una generación. Un intento adicional acotado por reparación/escalación; no bucles indefinidos. Temperatura propuesta 0 para plan y 0,2 para redacción si se admite; máximo de salida ajustable sin truncar tareas. No inventes que todos los modelos aceptan los mismos parámetros.

Configura deadline según timeout real del consumidor con margen; timeouts por dependencia, cancelación, concurrencia acotada y backoff con jitter ante 429/503 dentro del presupuesto. No multiplicar reintentos entre capas. Ninguna mejora exige modificar streaming del contrato externo.

Redactor recibe resultados y fuentes pertinentes. Debe responder primero lo solicitado, cubrir pendientes explícitos y dar una aclaración mínima. Paths internos, nombres de clase, flags y detalles del runner quedan fuera del texto al cliente. Ante monto desactualizado explica su antigüedad con lenguaje natural.

## F. Configuración remota desde Cursor

Puedes usar Azure CLI/REST/SDK desde terminal con credenciales autorizadas. No necesitas un plugin adicional. Para endpoints privados usa la VM/ejecutor ya autorizado o ruta privada existente. No abras el servicio a internet ni exportes tokens MI a la PC.

Prepara scripts idempotentes separados y documentados:
- discovery/read-only;
- export/backup de configuración saneada;
- plan/diff de infraestructura y permisos;
- creación/ingesta del candidato;
- smoke sin transacciones;
- activación QA por referencia/flag;
- rollback al índice/config/código anterior.

Usa la infraestructura como código existente si la hay. Si no existe, genera scripts con modo plan y apply explícito. Un apply que cambia configuración compartida debe comprobar recurso/entorno; nunca usar force, borrar índices o cambiar PROD. No concedas privilegios que tu sesión no tiene.

Ejecuta lo ya autorizado; si falta autorización de publicación/recursos, primero completa código, artefactos locales, diff, impacto/coste estimado verificable y reversión. Solicita solo el lote remoto concreto restante, explicando qué permisos o autorización faltan. No te detengas antes para pedir permiso sobre ediciones locales rutinarias.

## G. Pruebas funcionales y rendimiento

1. Ejecuta primero casos P0 y negativos del evaluador. Cubre: cuenta disponible/contable; Joven y reclamación; tasa+definición+selección; corrección+misión; comparación ordenada; pagos próximos; cero/nulo; ausencia/inventario incompleto; secretos/terceros.
2. P12 usa reloj explícito, zona horaria del negocio e intervalo documentado. Con años ocultos en evidencia no infieras vencimiento: compara antes de sanear y registra resultado. No aprobar solo porque aparece una fecha.
3. Cancela la sustitución payoff por principal: prueba origen/mapeo real y ausencia del dato. Escribir payoff_amount en la respuesta no es validación.
4. Completa criterios de los casos sin oráculo y ejecuta los 236; mantiene 36 recorridos multi-turno identificados, reconciliando fuente real. No inventes PASS ni uses respuestas del modelo como único esperado.
5. Añade paráfrasis y variaciones de portafolio no empleadas para ajustar los atajos. Todas las variantes reciben ID derivado; no sustituyen casos originales ni consultan otros clientes remotos.
6. Compara actual vs candidato con corpus/fixtures/reloj/oráculo constantes. Evalúa recuperación aparte de respuesta final. Para chunking usa los tres perfiles con mismas consultas; no mezcles a la vez cambio de modelo para atribuir mejoras.
7. Mide por categoría p50/p95, n, tokens, llamadas, 429 y errores. Targets propuestos: 2 s personal determinista, 5 s documental, 8 s mixta (p95 QA). Muestra cifras reales aunque excedan el objetivo. Carga pequeña controlada y cache fría/caliente; no ejecutes carga bancaria amplia.
8. Revalida CAS/aislamiento si cambias memoria o ejecución. Redis real disponible reemplaza necesidad de Docker local; no bloquear las pruebas por no tener Docker.

## H. Registro y columna fix obligatoria

Aplica `Prompt_Cursor_Validacion_Guia_Columna_Fix.md` si está disponible y conserva sus requisitos. Cada corrida usa carpeta inmutable `works/qa_runs/<run_id>/`, manifest de código desplegado/oráculo/prompt/corpus/config, logs saneados, resultados por caso/turno, aserciones, proveedor efectivamente invocado, tareas/campos/fuentes, latencia y hashes.

Genera la guía derivada completa con columna `fix` en minúscula para cada ID, respetando tablas/secciones e imágenes originales. Registra resultado histórico y nuevo; embebe capturas reales del chat de las correcciones. Cada recorrido multi-turno conserva sesión y evidencia de todos los mensajes. HTTP 200 no acredita chat funcional. Si descarga de navegador falla, prueba un navegador instalado mediante herramientas autorizadas o prepara captura manual; no falsees imágenes desde logs.

Distingue estado funcional, origen de datos y estado visual. Un caso puede estar API_VERIFIED_UI_PENDING, pero no RESUELTO visual sin captura. Mantén PARTIAL, FAIL, BLOCKED, NOT_APPLICABLE, NOT_EXECUTED y PENDING_EVALUATION separados. No agrupar IDs para aparentar cobertura.

## I. Entrega y activación

Entrega `works/azure_mejora/ENTREGA_FINAL.md`, código/diff, esquema e ingesta candidata, `CONFIGURACION_REAL_VS_PROPUESTA.md`, scripts plan/apply/rollback, evaluación chunking, tabla actual/candidato, manifest de versiones y ZIP de pruebas/guía fix. Hash del ZIP final se publica fuera del ZIP. No corrijas hashes históricos para ocultar discrepancias; documenta causa comprobada o desconocida.

Criterio de activación: recorrido completo mejora o conserva exactitud/cobertura, no mezcla producto/evidencia, contratos/persistencia pasan, latencia/coste se reportan, y existe reversión. No sumar éxitos de versiones diferentes para declarar cierre. Si quedan dependencias, entrega demostración honesta de los recorridos completos disponibles y la lista de pendientes; continúa el resto del trabajo autorizado.
