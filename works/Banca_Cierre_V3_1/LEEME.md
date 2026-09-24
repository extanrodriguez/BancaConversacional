# Cierre cognitivo V3.1 — instrucciones de uso

Este paquete continúa la entrega local V3 reportada el 18 de septiembre de 2026. Incluye el prompt de cierre y los archivos que Cursor indicó no haber encontrado.

1. Extrae la carpeta `Banca_Cierre_V3_1` dentro de `works/` del repositorio actual de la capa cognitiva.
2. Comprueba que `works/Banca_Cierre_V3_1/Prompt_Cursor_Cierre_V3_1.md` y la carpeta `insumos/` estén presentes.
3. Abre esa carpeta en Cursor o adjunta el prompt al chat del repositorio. Envía este mensaje:

> Lee `works/Banca_Cierre_V3_1/Prompt_Cursor_Cierre_V3_1.md` y sus insumos. Continúa desde la implementación V3 actual y completa el alcance local del cierre. Primero verifica las rutas y los conteos de 236 casos extraídos y 24 propuestos; después implementa y prueba los cinco recorridos por `/turn`. No modifiques `BSC.genesis.conversational.backend`.

Si extraes el ZIP en otra ubicación, sustituye esa ruta por la real. Cursor debe localizar los insumos con relación al prompt y no asumir que están en Downloads.

## Contenido

- `Prompt_Cursor_Cierre_V3_1.md`: instrucciones de continuación, riesgos por comprobar y criterios de cierre.
- `insumos/Modelo_Mejora_Cognitiva_QA_V3.md`: análisis y modelo original.
- `insumos/Prompt_Cursor_Banca_V3_Pruebas_QA.md`: alcance original como referencia; el prompt de cierre precisa la siguiente ejecución.
- `insumos/Casos_QA_236_Extraidos.jsonl`: inventario del Word con resultados reportados, no reejecutados durante nuestro análisis.
- `insumos/Casos_QA_Adicionales_V3.jsonl`: 24 casos propuestos con precondiciones; no ejecutados.
- `insumos/Resumen_QA.json`: conteos y límites del análisis original.
- `MANIFIESTO_ARCHIVOS.json`: tamaños y SHA-256 de los archivos del paquete; no corresponde a la versión del código del banco.

El Word original no se duplica en este ZIP. Sus escenarios extraídos permiten preparar la evaluación; las discrepancias que requieran capturas deben contrastarse con el documento original. No subir estos casos ni los fixtures a Foundry como hechos bancarios.

El reporte recibido confirma avances declarados en hotfixes y pruebas locales, pero no acredita la ejecución multi-tarea completa, Azure real ni Redis distribuido. El nuevo prompt se basa en ese reporte; no se recibió ni auditó el diff nuevo de Cursor. Los riesgos de regresión enumerados son hipótesis a comprobar, no fallos ya reproducidos del nuevo código.
