# Contrato de chat enriquecido — Front v1

El backend mantiene `client_response`, `content_format`, `options` y
`suggested_questions`. Los fronts nuevos deben preferir
`app_channel.rich_content` (o `rich_content` en el nivel raíz).

## Prioridad de renderizado

1. Si existe `rich_content.version == "1.0"`, renderizar sus bloques.
2. Si no existe, renderizar `client_response` según `content_format`.
3. Si tampoco existe, usar `reply`, `message` o `content`.

## Selección de producto

Cada opción conserva el contrato anterior y añade una selección estructurada:

```json
{
  "ref": "DEPOSITO_PLAZO_5511",
  "label": "Certificado de depósito ••••5511",
  "product_type": "term_deposit",
  "currency": "DOP",
  "subtitle": "Tasa de interés: 8.15% · Moneda: DOP",
  "context": {
    "field": "rate",
    "label": "Tasa de interés",
    "formatted_value": "8.15%",
    "currency": "DOP"
  },
  "selection": {
    "type": "product",
    "selected_option_ref": "DEPOSITO_PLAZO_5511",
    "message": "¿Cuál es la tasa de interés de mi certificado de depósito ••••5511?"
  }
}
```

Al pulsar la card, el front envía:

```json
{
  "question": "Certificado de depósito ••••5511",
  "selected_option_ref": "DEPOSITO_PLAZO_5511",
  "conversation_id": "<misma conversación>",
  "customer_id": "<cliente>"
}
```

`question` se mantiene como fallback para integradores antiguos. El backend
valida `selected_option_ref` contra el producto esperado en la sesión y conserva
el campo previo (tasa, saldo, fecha, corte, etc.).
Para pintar la burbuja del usuario, el front debe enviar y mostrar
`selection.message`; no debe usar únicamente el título de la card.

El front muestra `subtitle` debajo del nombre. `context` contiene la misma
información de forma estructurada para no tener que interpretar texto. Por
ejemplo, una consulta de vencimiento recibe `field: "maturity"` y un subtítulo
como `Vence: 19/09/2026 · Moneda: DOP`.

## Bloques

- `paragraph`: contenido inline (`text`, `strong`, `link`).
- `list`: `ordered` o `unordered`.
- `section`: título y bloques; puede ser colapsable para respuestas largas.
- `card_group`: cards de productos con acción `select_option`.
- `actions`: preguntas sugeridas u otros botones.

Ejemplo de contacto accionable:

```json
{
  "type": "link",
  "text": "809.726.1000",
  "href": "tel:+18097261000",
  "kind": "phone"
}
```

Los correos usan `mailto:` y las páginas usan `https:`. El front solo debe
permitir `http:`, `https:`, `tel:` y `mailto:`. Enlaces HTTP(S) deben abrirse
con `target=\"_blank\"` y `rel=\"noopener noreferrer\"`.

## Pseudocódigo del front

```javascript
const app = payload.app_channel ?? {};
const rich = app.rich_content ?? payload.rich_content;

if (rich?.version === "1.0") {
  renderBlocks(rich.blocks);
} else {
  renderLegacy(app.client_response ?? payload.reply, app.content_format);
}
```

El simulador de `/pruebas` implementa este contrato usando nodos DOM y
`textContent`, sin insertar HTML recibido del backend.
