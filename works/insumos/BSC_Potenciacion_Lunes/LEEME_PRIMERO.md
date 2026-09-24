# Paquete BSC — conocimiento y mejora conversacional para el lunes

Fecha: 19-09-2026. Meta de entrega: lunes 21-09-2026. Material preparado, sin implementación ni despliegue remoto ejecutados en este trabajo.

## Qué hacer ahora en Cursor

1. Descomprime `BSC_Potenciacion_Lunes.zip` dentro del workspace cognitivo, por ejemplo en `works/insumos/BSC_Potenciacion_Lunes/`.
2. Conserva accesible el ZIP original `Guia_Pruebas_Conversacionales_IA_BSC_Resultados_paquete(1).zip`, con sus imágenes. Este paquete incluye la guía textual y la asociación de casos; no duplica las capturas con datos personales.
3. Abre `Prompt_Cursor_Potenciar_Banca_Lunes.md` y pásale a Cursor este mensaje:

> Ejecuta el prompt adjunto sobre el checkout actual. Usa el paquete completo BSC_Potenciacion_Lunes y el ZIP original de la guía. Completa primero el recorrido P0 local por POST /turn, conserva los hotfixes y los límites externos, y reporta resultados con evidencia por faceta. El análisis y las etiquetas históricas no son pruebas ejecutadas. Continúa con las fases locales aunque algún paso remoto no esté disponible.

4. Solicita primero el diagnóstico de la ingestión: ¿qué columna utiliza hoy? Comprobar especialmente filas 262, 319, 320 y 323. Después, el diff y los recorridos P0 completos.
5. Usa los resultados para decidir la activación QA de la versión candidata. Si ya existe autorización específica de ese despliegue, Cursor debe aprovecharla; este archivo no añade autorización para PROD ni para cambiar el backend externo.

No tienes que ejecutar `ENTREGA_*.md`: los documentos de entrega son reportes. El prompt instruye a Cursor para modificar el código y ejecutar los comandos/tests que correspondan a su repositorio.

## Qué cargar como conocimiento

**Ruta preferida:** que Cursor integre `kb/chunks_qa.jsonl` en el adaptador de ingestión existente de Azure AI Search, conservando campos y filtros. `kb/fichas_qa.jsonl` contiene las fichas padre. El JSONL es un formato de intercambio del paquete, no una promesa de que cualquier pantalla de Foundry lo indexe directamente.

**Si el flujo actual acepta documentos:** `kb/Base_Conocimiento_BSC_QA.md` es una versión legible de la misma selección. Comprobar primero formatos admitidos por esa conexión; dividir por ficha o conservar IDs al fragmentar. No cargar simultáneamente Markdown y JSONL como dos corpus: duplicarías evidencia.

Preparar una versión paralela y comparar contra la actual. No eliminar ni reemplazar masivamente el índice vigente. Verificar el nombre de la conexión/corpus realmente usado por `/turn`; una carga en otro proyecto Foundry no cambia la aplicación.

**No subir al conocimiento bancario:** pruebas, imágenes, reglas de conversación, prompt de Cursor, manifiestos, filas crudas ni fichas pendientes de revisión. Esas piezas cumplen funciones diferentes.

## Archivos principales

| Archivo / carpeta | Uso |
|---|---|
| `Prompt_Cursor_Potenciar_Banca_Lunes.md` | Orden de implementación, validación y entrega |
| `Analisis_y_Prioridades.md` | Hallazgos, límites, prioridades y pendientes de Producto |
| `kb/fichas_qa.jsonl` | 195 fichas candidatas seleccionadas para QA |
| `kb/chunks_qa.jsonl` | 196 fragmentos con IDs/procedencia |
| `kb/Base_Conocimiento_BSC_QA.md` | Lectura humana y alternativa para ingestión documental |
| `kb/fichas_candidatas.jsonl` | Total de 239 fichas; incluye 44 apartadas para revisión |
| `catalogo/` | Taxonomía, alias, campos y mapeos Core pendientes de verificar |
| `estrategia/` | Estrategias, reglas funcionales y esquema interno de referencia |
| `evaluacion/` | 236 casos, cruce con fuentes y aceptación prioritaria |
| `revision/` | Trazabilidad, brechas, validación y estadísticas |
| `fuentes/` | Base original, guía textual, registros y referencias oficiales |
| `scripts/` | Reconstrucción y validación local, sin llamadas remotas |

## Validar y reconstruir

Desde la carpeta del paquete, con Python 3:

```text
python scripts/validate_package.py
python scripts/build_package.py
python scripts/validate_package.py
```

El constructor parte de las filas normalizadas y aplica una curación explícita/reproducible. No instala dependencias ni escribe en Azure. Si se edita contenido, el manifiesto deja de representar el paquete original; genera una nueva versión y hashes, no declares que conserva el mismo SHA.

## Qué significa estar listo

Corpus organizado y fuentes asociadas son avances documentales. “Listo funcional” requiere respuestas correctas desde `/turn`, memoria real de tareas y evidencias de la ruta que se va a demostrar. Modelo Azure, Core vivo, lab_fallback, fixtures y UI se acreditan por separado.

El conocimiento público ayuda a explicar productos. La respuesta personal necesita el snapshot del cliente; la memoria necesita que el ejecutor conserve tareas. Ninguna de esas tres capacidades sustituye a las otras.
