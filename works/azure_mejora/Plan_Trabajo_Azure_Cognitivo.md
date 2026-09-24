# Plan de trabajo — Mejorar comprensión, contexto y rendimiento de Banca Conversacional

Preparado el 21 de septiembre de 2026. Propuesta para implementar sobre el checkout actual; no representa una configuración ya desplegada. La presentación de la próxima jornada debe distinguir resultados medidos, capacidades parciales y trabajo pendiente.

## 1. Decisión recomendada

Conservar el servicio cognitivo y mejorar su flujo de extremo a extremo: un plan completo por turno, resolución de productos contra el contexto autorizado, recuperación documental por tarea y respuesta natural comprobada. Introducir un índice candidato y activar cambios mediante configuración reversible. Reutilizar Redis/Entra y los deployments actuales mientras se miden alternativas.

El objetivo demostrable es que el asistente entienda paráfrasis, complete preguntas compuestas, retome referencias y responda con datos pertinentes. Tener Foundry, aumentar memoria o llamar más veces al modelo no acredita esas capacidades. Los avances se aceptan mediante casos funcionales y métricas de la misma versión.

Insumos: guía técnica RAG adjunta; guía conversacional con 236 casos; corpus BSC preparado; última evidencia strict-v2.2. Esta última declara 42 resueltos, 7 aclaraciones, 10 parciales, 99 fallos y 78 pendientes de evaluación en la clasificación canónica. Son etiquetas del evaluador: siguen pendientes la revisión de P12, la suficiencia de comparaciones y la columna fix con capturas. El contexto QA reportado es lab_fallback, no Core vivo.

## 2. Alcance que se conserva

- Entrada productiva: POST /turn. Conservar nombres, tipos, códigos y semántica del contrato consumidor.
- Directorio protegido: `C:\NovusIntelligence\BancoSantaCruz\BancaConversacional\BSC.genesis.conversational.backend`.
- Frontend y WebSocket existentes se utilizan para pruebas; no se modifican.
- Redis con identidad administrada, conexión privada/TLS, CAS, aislamiento y candado por conversación.
- NL ocupado: SESSION_BUSY con HTTP 200 y texto; fallo de persistencia en carga de contexto: CONTEXT_LOAD_BUSY según contrato vigente (503 reportado). Confirmar en checkout antes de editar.
- Consultas QA autorizadas de lectura para 726588. Otros portafolios se cubren con fixtures locales identificados como sintéticos. Sin transacciones ni cambios en PROD.
- El orquestador externo sigue cargando el contexto por el mecanismo existente. Verificar qué servicio escribe Redis realmente; no asumir acceso directo del backend externo ni cambiar su esquema de claves.

La autorización para leer QA no equivale a autorizar cambios de permisos, índices, SKU o red. Cursor debe preparar el cambio concreto, aprovechar autorizaciones ya existentes y solicitar una única aprobación del lote remoto restante si no está autorizado. Este paquete no ejecuta cambios Azure.

## 3. Flujo cognitivo propuesto

1. **Admisión y estado.** Validar sesión/identidad, cargar una copia consistente y aplicar la coordinación existente. Obtener snapshot con origen/frescura y estado conversacional mínimo.
2. **Interpretación.** Construir un TurnPlan con todas las tareas: objeto, selector de producto, campos/facetas, dependencias, corrección y referencias. El LLM interpreta lenguaje; validadores comprueban estructura y significado permitido.
3. **Resolución.** Selección explícita actual, corrección, aclaración pendiente compatible, foco compatible y único producto elegible. Con varios candidatos preguntar; con inventario incompleto no afirmar ausencia definitiva.
4. **Ejecución.** Leer campos personales mediante adaptador tipado del contexto existente. Recuperar conocimiento por producto/familia y faceta. Ejecutar tareas independientes con concurrencia acotada, sin compartir mutaciones del estado.
5. **Cobertura.** Una tarea tiene resultado con evidencia, necesita aclaración o queda limitada con una razón concreta. No perder tareas al elegir un producto o cambiar de tema.
6. **Respuesta.** Redacción breve y natural a partir de resultados. Exactitud numérica y correspondencia producto–evidencia comprobadas por código. Mantener detalles internos en auditoría.
7. **Persistencia.** Un commit coherente sujeto a revisión/propiedad del candado antes de confirmar la respuesta definitiva. No reintentar solamente una escritura fallida con revisión nueva. Conservar tareas pendientes y foco, sin rejuvenecer el snapshot.

Los atajos existentes siguen siendo útiles si cubren inequívocamente el turno completo o devuelven resultados parciales al mismo ejecutor. Un atajo no puede terminar el turno y descartar otra intención. La equivalencia se prueba también con paráfrasis no usadas para construirlo.

## 4. Qué configurar en Redis

| Configuración | Acción inmediata QA | Criterio |
|---|---|---|
| Recurso | Reutilizar `bsc-cognitive-redis-qa`; endpoint reportado `bsc-cognitive-redis-qa.eastus.redis.azure.net:10000` | Confirmar recurso y conexión efectiva, no recrear |
| Autenticación | Mantener Entra MI y fábrica común para store/candado | Renovar tokens/conexiones con el cliente compatible; probar un ciclo real de renovación |
| Transporte/red | `rediss`, validación de certificados, PE y DNS privados | No abrir acceso público para facilitar pruebas desde PC |
| Clúster | Inspeccionar política actual y compatibilidad de WATCH/MULTI/Lua | Mantener topología que funciona; no cambiar a OSS sin adaptar y probar cliente y operaciones multiclave |
| Memoria/evicción | Proponer noeviction para estado/candados si el recurso lo soporta; validar impacto y tratamiento de OOM antes de aplicar | Una expulsión de candado por presión de memoria puede romper exclusión; noeviction requiere margen y alarmas |
| Conexiones | Reutilizar pools por proceso y fábrica común; presupuesto inicial orientativo 16 conexiones por pool | Medir conexiones totales = pools × workers × réplicas; no abrir por mensaje |
| Estado | Persistir estructura compacta, pendientes, focos separados y compare_set | Evitar enviar toda la conversación o documentos enteros al modelo |
| Caché | Primera fase: solo resultados de recuperación documental, opcional y acotada | No cachear globalmente respuestas personales ni usar caché semántica de saldos |
| Capacidad | Conservar B0 en QA hasta medir memoria, CPU, conexiones y latencia | 0,5 GB no constituye dimensionamiento PROD |

Entra necesita renovación antes del vencimiento del token; un PING inicial no acredita sesiones largas. La documentación recomienda renovar con anticipación. Mantener la integración existente y observar una renovación real sin imprimir tokens. [Redis Entra](https://learn.microsoft.com/en-us/azure/redis/entra-for-authentication).

La política de clúster afecta compatibilidad y operaciones multiclave. Las recomendaciones de tamaño y topología deben basarse en la configuración descubierta y las pruebas del store. [Arquitectura Redis](https://learn.microsoft.com/en-us/azure/redis/architecture).

### Retención no es frescura

| Dato | Punto de partida QA propuesto | Comportamiento |
|---|---|---|
| Sesión conversacional | Conservar TTL actual; si no existe política, ensayar 30 min de inactividad con límite absoluto ligado a autenticación | Nunca extender autorización por actividad de chat |
| Saldos y datos volátiles | Ensayo de umbral de antigüedad de 60 s, configurable | Es un umbral de clasificación, no una orden de borrar datos ni una consulta nueva a Core |
| Inventario de productos | Ensayo de antigüedad de 10 min | Fallido/parcial/desconocido no equivale a inventario completo |
| Recuperación documental | Caché opcional de 5 min, con límite de entradas/bytes | Invalidar antes por publicación, cambio de permisos o vigencia |
| Candado | Preservar lease, renovación y máximo de turno existentes tras medir | La renovación no prolonga indefinidamente una solicitud colgada |

Todos esos tiempos son hipótesis técnicas de QA, no políticas bancarias aprobadas. Si la fuente o autenticación exige menos tiempo, prevalece ese límite. Sin refresh autorizado disponible: informar fecha/limitación y conservar procedencia; no inventar actualidad. `source_fetched_at` se modifica solo al recibir datos de la fuente; escribir sesión no lo cambia.

Para contexto: mantener últimos 6 intercambios como presupuesto inicial, resumen lingüístico de hasta 600 tokens y estado estructurado íntegro de las tareas activas. No truncar silenciosamente una selección pendiente. Separar preferencias expresadas de hechos verificados. No reconstruir importes ni productos a partir de un resumen del LLM.

Clave de caché documental: hash de consulta normalizada + productos/facetas + idioma + ámbito de permisos validado + índice/corpus/retrieval versionados. Un hit conserva sus restricciones de vigencia. Mantener sesiones y candados fuera de cualquier política de limpieza de caché. Cambiar claves o esquema requiere migración compatible; inicialmente reutilizar almacenamiento actual.

Los valores pequeños y operaciones por lotes pueden reducir transferencia; evitar consultas KEYS globales. No dividir estado atómico en muchas claves si eso rompe CAS. [Desarrollo Redis](https://learn.microsoft.com/en-us/azure/redis/best-practices-development).

## 5. Qué configurar en Azure AI Search

### Corpus y fragmentación: 400–800 tokens

**Punto inicial: objetivo 600 tokens, banda 400–800, solapamiento 80 tokens** entre fragmentos contiguos del mismo producto/sección cuando se necesite continuidad. Medir con tokenizer compatible; tokens no equivalen a palabras ni caracteres.

- Cada fragmento representa una unidad de conocimiento: producto + faceta. Conservar título, fuente, sección, vigencia y aplicabilidad.
- Fichas de menos de 400 tokens se conservan completas; no rellenar ni mezclar productos para llegar al tamaño objetivo.
- Una regla y sus excepciones deben poder recuperarse juntas. Ante tablas o procedimientos largos, segmentar semánticamente, repetir encabezados y enlazar padre/hijos. Recuperar el padre o fragmentos relacionados bajo presupuesto; registrar excepciones de tamaño justificadas, nunca truncar contenido normativo.
- El solapamiento no cruza de Joven a Platinum ni mezcla vigencias. El conteo incluye títulos/metadatos textuales enviados al embedding.
- Crear IDs estables y hash por contenido. Revectorizar solo texto cambiado, retirar hijos obsoletos y actualizar metadatos/ACL sin inferir nuevas condiciones.
- Probar perfiles 400/50, 600/80 y 800/100 sobre el mismo conjunto. Seleccionar por evidencia correcta recuperada, completitud y latencia; 600 no es un resultado ya óptimo.

La documentación contempla varios métodos de división; nuestra banda es una propuesta adaptada al corpus bancario, no un requisito del servicio. [Fragmentación](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents).

### Índice candidato y metadatos

Nombre orientativo `bsc-kb-qa-vnext-<fecha>-<hashcorto>`, en el servicio existente si capacidad y permisos lo permiten. Mantener índice activo y configuración anterior. El candidato empieza en shadow para comparar; su existencia no habilita automáticamente todas sus fichas para atender clientes.

| Campo | Tipo orientativo | Uso |
|---|---|---|
| chunk_id, parent_id | Edm.String | ID único y relación con documento |
| title, content, aliases | Texto; aliases colección si conviene | Searchable; title/content recuperables |
| product_ids | Collection(Edm.String), filterable | Productos canónicos a los que aplica |
| product_family, applicability_scope | Edm.String, filterable | product, family o bank; alcance explícito |
| content_type, topic, facets | Strings/colecciones, filterable según uso | Definición, procedimiento, comparación, etc. |
| status, corpus_version | Edm.String, filterable | Solo versión y estado permitido |
| valid_from, valid_to | Edm.DateTimeOffset | Aplicabilidad temporal explícita |
| source_id, source_uri, section, content_hash | Edm.String | Evidencia y trazabilidad |
| allowed_principals / audience | Colección/string según política real | Filtros de acceso construidos por servidor |
| contentVector | Collection(Edm.Single) | Dimensión exacta del embedding; perfil HNSW/cosine compatible |

No inferir aprobación comercial a partir de que el contenido esté en un Excel. Separar material candidato QA de contenido aprobado. No indexar evaluaciones, screenshots de pruebas, estados históricos «Cumple», prompts ni snapshots de clientes como conocimiento. La guía evalúa; no contiene respuestas para memorizar.

Al resolver Platinum, filtrar por su ID o por un alcance general que aplique explícitamente a tarjetas. No hacer un OR indiscriminado por familia que admita documentos específicos de Joven. Para comparaciones, recuperar evidencia para cada producto y atributo. Rechazar resultados mal etiquetados comparando metadatos con el contenido. Con identidad incierta: aclarar o recuperar candidatos sin atribuirlos aún como hechos.

### Consulta propuesta

Búsqueda híbrida texto + vector; HNSW/cosine inicial si es compatible con embedding actual. Filtro por aplicabilidad, permisos, publicación y vigencia. Comenzar con preFilter y verificar resultados. Semantic ranker en consultas documentales libres cuando esté habilitado y aporte calidad; omitirlo solo en lecturas inequívocas de una ficha ya identificada y versionada.

`k=50`, `top=5` por tarea son puntos iniciales; no significa enviar 50 fragmentos al redactor. Seleccionar 5–8 fragmentos en total por turno típico y hasta 4.000 tokens de evidencia, reservando cobertura por faceta. Si el turno requiere más evidencia, ampliar el presupuesto dentro del límite del modelo o explicar el alcance; no descartar tareas silenciosamente. Dos búsquedas documentales independientes pueden ejecutarse en paralelo con límite inicial 2 por turno.

La búsqueda híbrida combina resultados léxicos y vectoriales mediante RRF. Los filtros y la recuperación por faceta deben aplicarse desde la aplicación, y el score no es probabilidad de verdad. [Híbrida](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview), [filtros vectoriales](https://learn.microsoft.com/en-us/azure/search/vector-search-filters).

Crear configuración semántica con título `title`, contenido `content` y palabras clave pertinentes. Confirmar tier, disponibilidad regional, plan de facturación y permiso; habilitarla en el servicio no hace que las consultas existentes la utilicen. [Habilitar semantic ranker](https://learn.microsoft.com/en-us/azure/search/semantic-how-to-enable-disable).

## 6. Qué configurar en Foundry y en el cliente del modelo

| Elemento | Propuesta inicial | Lugar real |
|---|---|---|
| Deployment de conversación | Mantener el actual, reportado como gpt-4o-mini; verificar nombre/versiones efectivas | Foundry/Azure |
| Embeddings | Reutilizar el deployment actual compatible; si falta, proponer text-embedding-3-small con 1536 dimensiones y verificar disponibilidad | Foundry + esquema Search |
| Interpretación | Una llamada Structured Outputs para TurnPlan, con schema estricto compatible | Código cognitivo/API; no basta un ajuste en Playground |
| Temperatura | 0 para interpretación y 0–0,2 para redacción, solo si modelo/API lo admite | Cliente de inferencia |
| Salida máxima | Ensayo 1.200 tokens para plan; 600 para respuesta simple y 1.200 compuesta | Cliente; detectar truncamiento y no aceptar JSON incompleto |
| Contexto de entrada | Objetivo aproximado 8.000 tokens para turno típico, ajustable por cobertura | Constructor de contexto de la aplicación |
| Segundo modelo | Evaluar alternativa disponible solo para casos difíciles si hay evidencia de ganancia | Deployment independiente + política de enrutamiento |
| Quota y límites | Medir TPM/RPM, 429, concurrencia y tokens antes de ampliar | Foundry/Azure Monitor |

No cambiar de modelo por el nombre «más potente» antes de corregir fuentes, mapeos y pruebas. Comparar el mismo conjunto ciego de paráfrasis con dos deployments disponibles y autorizados; publicar exactitud, latencia y coste. Si cambiar modelo no mejora el conjunto, conservar el actual.

Structured Outputs valida forma, no verdad. Todas las properties deben ajustarse al subconjunto de JSON Schema soportado; detectar rechazo, truncamiento y error del proveedor. El modelo no puede inventar product_id ni decidir permisos. [Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs).

### Menos llamadas innecesarias

- Ruta personal inequívoca validada: lectura determinista y respuesta breve; cero inferencias si cubre todo.
- Lenguaje libre/ambiguo: una inferencia para interpretar. Resolver tareas determinísticamente; redactor solo cuando la complejidad lo justifique. Objetivo normal máximo 2 inferencias, no prohibición absoluta.
- Sustituir el verificador LLM obligatorio por comprobaciones deterministas donde pueda demostrarse equivalencia. Mantener la ruta anterior con flag y comparar antes de activarlo.
- Un único intento adicional de reparación por salida inválida o una escalación medida, dentro de deadline; no ciclos de proposer/verifier/reparación sin límite.
- Reutilizar clientes HTTP, inferencia asíncrona y pools. Evitar trabajo síncrono de autenticación/red en el event loop, preservando el arreglo Entra existente.
- Mantener prefijo estable de instrucciones/esquema y datos dinámicos al final; aprovechar prompt caching si el deployment lo admite, midiendo cached_tokens. No rellenar el prompt para alcanzar un umbral ni tratar esa caché como memoria de usuario. [Prompt caching](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/prompt-caching).

Una salida innecesariamente larga aumenta latencia. Medir tokens de entrada/salida y tiempos por llamada antes de comprar capacidad. Streaming no debe prometerse al usuario si el contrato externo espera una respuesta final; no se modifica el WebSocket para incorporarlo en esta fase. [Latencia](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/latency).

## 7. Permisos, red y automatización desde Cursor

**Sí, Cursor puede preparar y ejecutar esta configuración mediante terminal, Azure CLI, SDKs y REST; no requiere un conector especial.** Necesita identidad autorizada, acceso a recursos y conectividad. Un inicio de sesión CLI no otorga nuevos permisos. La MI de la VM no se exporta a la PC: ejecutar desde la VM autorizada para probar servicios privados o usar una identidad local autorizada por separado.

| Trabajo | Automatizable desde Cursor | Requisito |
|---|---|---|
| Inventario de recursos/configuración | Sí, lectura CLI/ARM | Permiso de lectura y suscripción correcta |
| Código de contexto/retrieval/chunking | Sí, local | Checkout y dependencias reales |
| Esquema, configuración semántica e ingesta | Sí, REST/SDK | Permiso de esquema y escritura de documentos |
| Lecturas Search desde servicio | Sí | MI con Search Index Data Reader |
| Publicación documentos | Sí | Identidad de ingesta con Search Index Data Contributor |
| Gestión de esquema | Sí | Search Service Contributor o permiso equivalente acotado |
| Cambio Redis, modelos, cuotas, red | Preparación sí; aplicación según permisos/operación disponible | Autorización administrativa; algunas cuotas requieren solicitud al proveedor |
| Prueba privada Redis/Search/modelo | Sí desde entorno con ruta | VM/VPN/ejecutor autorizado; DNS y PE existentes |
| Capturas | Sí con navegador autorizado existente; alternativa manual | Chat operativo y sesión QA |

Verificar los permisos precisos, separar runtime de ingesta y no otorgar Owner al servicio. Los roles de servicio no sustituyen filtros documentales. [Roles Search](https://learn.microsoft.com/en-us/azure/search/search-security-rbac).

En QA reutilizar red existente. Para Search/modelo confirmar desde la VM conectividad privada y resolución DNS antes de cambiar acceso público. Una conexión privada entrante a Search no configura la salida de un indexer hacia Storage o embeddings. Para el piloto se recomienda reutilizar el pipeline Python de ingesta desde la VM: reduce cambios de red; vectorización integrada puede evaluarse después. No duplicar ambos pipelines.

## 8. Plan por entregas y dependencias

Estimación orientativa de 12–20 horas de trabajo técnico más validación, según estado del repo, permisos, datos y tiempo de inferencia. No es garantía de disponibilidad mañana. Se puede obtener primero una demostración acotada de 6–8 recorridos; la guía completa sigue siendo compromiso de validación y no se reemplaza por ese subconjunto.

| Orden | Trabajo y responsable | Tiempo orientativo | Evidencia de salida |
|---|---|---|---|
| 0 | Desarrollo: inventario, baseline y respaldo | 1–2 h | Recursos exactos, ruta /turn, versión de código/oráculo, muestras de latencia |
| 1 | Desarrollo + producto: catálogo/aplicabilidad y chunking | 2–3 h | Corpus candidato, perfiles 400/600/800, trazabilidad y brechas |
| 2 | Desarrollo/infra: índice candidato e ingesta QA | 1–3 h tras permisos | Búsquedas reales y prueba negativa Platinum/Joven |
| 3 | Desarrollo: contexto compacto y plan unificado | 3–5 h | Mixtas y continuidad completas, sin regresión CAS |
| 4 | Desarrollo: presupuesto de inferencias/pools/caché | 1–2 h | Tiempos por fase; ganancia medida sin pérdida de cobertura |
| 5 | QA + desarrollo: casos P0, guía completa y fix | 3–5 h o más por bloqueos | Aserciones, capturas reales, 236 estados honestos |
| 6 | Responsable técnico: selección de versión demostrable | 30–60 min | Demo repetible, informe, rollback probado y límites |

Preparar código y pruebas locales mientras la configuración remota está pendiente. No ejecutar varias versiones a la vez sobre la misma sesión QA. No gastar la jornada en migrar VM a AKS, instalar otro framework o habilitar internet libre para el LLM.

### Escenarios de demostración

1. Saldo/disponible de cuenta → definición → retomar cuenta.
2. Tarjeta Joven + reclamación, con aclaración real si hay varias.
3. Préstamo: tasa + significado → selección → ambas tareas.
4. Corrección de producto + misión en el mismo turno.
5. Platinum/Infinite → diferencias → agregar Gold → segunda.
6. Pagos próximos con reloj/intervalo verificable, incluidos vencidos separados.
7. Producto no disponible/contexto incompleto, sin inventar.
8. Secreto en mensaje y consulta de tercero frente a procedimiento general.

Usar solo datos autorizados; si el portafolio vivo no permite un caso, presentarlo con fixture local explícito y evidencias separadas. Una respuesta completa sobre lab no acredita integración Core viva.

## 9. Medición y criterios de aceptación

Targets de ingeniería para ensayar, no SLA: p95 lectura determinista ≤2 s; p95 consulta documental simple ≤5 s; p95 mixta ≤8 s bajo carga QA acotada. Si baseline o dependencia impide esos targets, reportar valor real y causa. Primero preservar exactitud. Cada deadline debe ser inferior al timeout efectivo del consumidor con margen; descubrirlo antes de fijar valores.

Medir: resolución de intención y producto/campo, cobertura de tareas, evidencia aplicable, exactitud de cifras, conservación del contexto, latencia p50/p95 total y por fase, tokens, inferencias/turno, 429/timeout, edad snapshot, espera de candado y memoria/evicciones Redis.

Comparación reproducible: misma versión del oráculo, fixtures/reloj, preguntas y condiciones; incluir cache fría/caliente. En muestra de rendimiento usar al menos 30 turnos por categoría y publicar n; no llamar estable a un p95 de 3 consultas. Ensayar concurrencia controlada de 1, 3 y 5 conversaciones de prueba dentro de capacidad QA; detener si afecta a otros usuarios. No confundir esto con certificación de carga PROD.

Para aceptación, ningún caso prioritario aprobado puede mezclar productos, inventar valores, ocultar facetas omitidas ni reutilizar capturas antiguas. Una ausencia esperada puede aprobar manejo de ausencia; no consulta completa. Los 78 sin oráculo siguen pendientes hasta implementar y revisar criterios. No atribuirlos al modelo. Pruebas negativas del evaluador deben rechazar los falsos positivos ya observados.

La columna `fix` se incorpora a cada escenario de la guía derivada, preservando resultado/imágenes históricos. Cada corrección necesita run_id, versión y captura real del chat; API verificada y UI pendiente son estados diferentes. Una página que responde 200 no acredita chat funcional. Preferir navegador ya disponible en el entorno autorizado para evitar repetir descargas fallidas; nunca construir imágenes desde logs como prueba UI.

## 10. Reversión y siguiente etapa

Snapshot de configuración no secreta, commit/hash del código, versión del esquema de sesión y referencia del índice anterior. Flags por separado para contexto/retrieval/verificador/caché. Cambio de índice por configuración existente o referencia versionada; conservar original. Invalidar caché mediante versión. No realizar migración irreversible de Redis antes de la presentación. Detener activación si rompe contrato, exactitud o persistencia.

Después de la presentación: resolver Core vivo y permisos de publicación restantes, cerrar guía y capturas, probar renovación Entra sostenida y concurrencia multiproceso, dimensionar PROD con carga real y revisar contenido con producto. QA y PROD deben tener recursos/identidades/datos independientes según política del banco. Alta disponibilidad y persistencia Redis se deciden según recuperación requerida; no convierten Redis en libro contable ni garantizan cero pérdida. Evitar geo-replicación activa como sustituto de una exclusión de sesión demostrada.

## 11. Mensaje para presentar

«Conservamos las integraciones existentes. Mejoramos la comprensión del turno, la memoria estructurada y la selección de evidencia. Los datos personales se obtienen del contexto autorizado; el conocimiento del banco se recupera de documentos versionados. Mostramos por escenario qué responde el asistente, su evidencia y su tiempo real. La activación es gradual y reversible».
