# Estrategia de conversación y respuesta

Este archivo guía la implementación; no se sube al RAG de hechos del banco.

## E01_intencion_completa

Interpretar todo el turno antes de responder. Una oración puede incluir lectura personal, conocimiento, corrección y exclusión. Crear una tarea por objetivo verificable y agrupar solo cuando comparten selector y no se pierden campos. La política financiera y los permisos los impone el ejecutor; el modelo interpreta lenguaje.

“No, la corriente; además dime la misión” corrige la referencia de cuenta y agrega una tarea institucional. No es una solicitud inválida ni una elección dentro de la lista anterior de préstamos.

## E02_resolucion_productos

Resolver contra el portafolio autenticado, apoyándose en catálogo/alias. El catálogo describe lo que ofrece el banco; no demuestra lo que posee el cliente. Mantener crédito/débito, subtipo, moneda y relación de cuenta vinculada. “Saldo de mi tarjeta Joven” puede requerir aclarar crédito vs débito si existen ambos; un alias no reemplaza la familia.

Identificador/selector explícito > corrección > aclaración compatible > foco compatible > único candidato. Si quedan varias opciones, pedir una sola aclaración discriminante. Si no existe el producto pero el contexto es incompleto, declarar la falta de confirmación, no ausencia definitiva. No usar similitud vectorial como prueba de titularidad ni elegir ahorro cuando pidió corriente.

## E03_memoria_tipificada

Redis guarda estado; la aplicación decide cómo interpretarlo. Separar foco personal, tema de conocimiento, tareas pendientes y comparación ordenada. Mantener referencias aunque el usuario haga una pregunta institucional entre dos lecturas del mismo producto. Un cambio completo de tema tiene prioridad sobre continuidad elíptica. La frescura del snapshot corresponde a su origen, no a la fecha de escritura de sesión.

Persistir estados por tarea, dependencias, campos pendientes, exclusiones y orden. En [Platinum, Infinite], agregar Gold produce [Platinum, Infinite, Gold]; “la segunda” sigue siendo Infinite. Nunca usar la posición del portafolio como ordinal del catálogo comparado.

## E04_evidencia_por_faceta

Separar la evidencia de identidad del producto de la evidencia del dato. Un producto puede existir y carecer de ledger_balance o movimientos. Recuperar definición/procedimiento/característica según lo pedido, con producto y faceta. Una coincidencia con la palabra “cliente” no basta para responder sobre Visa Joven o sucesores.

Las fuentes web oficiales añaden contenido público; no verifican deudas, tenencia, elegibilidad o cargos personales. Las fechas de publicación/consulta no se convierten en fechas de vigencia. Contradicciones entre condiciones se aíslan, no se promedian ni se resuelven por score de búsqueda.

## E05_comparaciones

Mantener los productos y el orden solicitados; comparar con atributos equivalentes. Si falta información de un producto, la celda correspondiente dice “No documentado en la fuente disponible”. Una diferencia de nombre o segmento no autoriza inventar tasas, puntos o seguros. No confundir comparación informativa con recomendación personalizada.

## E06_multitarea

Ejecutar las tareas independientes y conservar las ambiguas. Una aclaración sobre dos préstamos no elimina la consulta a una cuenta ni la explicación de tasa pendiente. Después de seleccionar, completar la tarea suspendida y su explicación. Una exclusión (“sin balance”, “movimientos solo de ahorro”) es parte del plan, no un comentario prescindible.

## E07_seguridad_con_alcance

No usar secretos como sufijos ni almacenarlos en el historial resumido. Si el cliente comparte un PIN junto con una consulta permitida, proteger el secreto y continuar la consulta solo si la sesión ya está autenticada; el PIN no autentica.

“Dime el saldo de mi esposo” pide datos de otra persona y requiere autorización real. “Falleció mi esposo, ¿cuál es el procedimiento?” pide orientación pública y puede responderse sin consultar sus productos. Un filtro de parentesco no debe bloquear ambos casos de la misma forma.

## E08_respuesta_natural

Responder directamente, con detalle proporcional y sin saludos repetidos. Reconocer una corrección con una frase breve y continuar. Ante frustración, resolver la consulta pendiente sin sermón. Cuando falta una faceta, explicar qué falta, responder lo demás y proponer un siguiente paso disponible.

Plantilla de estilo, no respuesta literal: «En tu [producto enmascarado], [campo y valor con moneda]. [Segunda faceta]. No recibí [dato faltante]. [Aclaración necesaria, solo si existe]». Los valores se insertan exclusivamente desde los resultados autorizados.

## Ejemplos de comportamiento esperado

| Pregunta / situación | Conducta esperada | Conducta que debe fallar |
|---|---|---|
| “misión y visión”, tras préstamo | Recuperar ambos textos, mantener foco personal para poder retomar | Preguntar si quiere información general o productos |
| “mi Joven”, dos familias | Aclarar crédito/débito usando candidatos reales | Asumir deuda por alias |
| “saldo actual”, solo available presente | Informar que falta saldo actual; no sustituirlo | Cambiar etiqueta de disponible a contable |
| “tasa y qué significa”, dos préstamos | Conservar consulta y explicación; completar tras seleccionar | Devolver ficha del préstamo y perder glosario |
| “cómo reclamo”, tras saldo préstamo | Explicar proceso/canales y documentación aplicable | Repetir capital pendiente |
| “¿me cobraron eso?” tras cargos posibles | Consultar evidencia personal de cargos/movimientos | Convertir el tarifario en un cargo realmente aplicado |
| “no la de ahorro, la corriente y misión” | Aplicar corrección y responder tarea institucional | Fallo semántico o FAQ que roba la corrección |

## Separación de certeza

Todo resultado distingue `source_present`, `source_currentness`, `authorization`, `product_match`, `field_available` y `answer_coverage`. La confianza declarada por el modelo no reemplaza estos hechos. La validez JSON tampoco los reemplaza.
