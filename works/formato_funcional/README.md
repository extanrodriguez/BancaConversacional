# Formato simple para funcional → luego lo convertimos a Markdown/IA

El archivo técnico `PLANTILLA_FUNCIONAL_ALIMENTACION_IA.md` es para **nosotros**.  
Para **funcional**, usamos hojas tipo Excel (CSV) en lenguaje de negocio.

## Qué le pedimos que llene

| Archivo | Para qué | Quién lo llena |
|---------|----------|----------------|
| `FUNC_intenciones.csv` | Qué quiere decir el cliente y qué debe responder el bot | Funcional |
| `FUNC_dialogos.csv` | Conversaciones de varios turnos (memoria) | Funcional |
| `FUNC_fallos_semana.csv` | Bugs reales de la semana | Funcional / QA |
| `FUNC_datos_core.csv` | Qué dato del banco hace falta | Funcional + Core |
| `FUNC_faq_frases.csv` | Frases → respuesta de conocimiento | Funcional |

Plantillas vacías + ejemplos: carpeta `works/formato_funcional/`.

## Flujo

```
Funcional llena Excel/Sheets (CSV)
        ↓
Nosotros transformamos → Markdown / YAML / tests / overlay FAQ
        ↓
Deploy :8447 + regresión
```

Script de apoyo (cuando haya datos reales):

```bash
python scripts/func_csv_to_markdown.py --in works/formato_funcional --out works/paquetes/FUNC-2026-W38.md
```

*(El script se puede agregar cuando tengamos el primer paquete real.)*

## Reglas para funcional (5 líneas)

1. Escribir como habla el cliente (aunque esté mal escrito).
2. Decir qué **sí** debe responder y qué **no**.
3. Si hay duda entre dos productos, decir si el bot debe **preguntar** o **listar todos**.
4. Si falta un dato del sistema, escribir el mensaje que debe decir el bot.
5. Preferir ejemplos reales del APK / pruebas.
