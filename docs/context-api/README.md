# API de Contexto — Productos por Cliente

Fuente: `Documentacion_API_Productos`. Documentación canónica del servicio
que alimenta el `CustomerContextSnapshot` de la banca conversacional.

> En contenedores, montar o regenerar este directorio con
> `GENESIS_API_EXCEL_PATH` + `scripts/export_docs_from_excel.py`.

## Endpoint

| Propiedad | Valor |
|-----------|-------|
| Método / Endpoint | GET `/products/v1/get-products-by-customer-id` |
| Base URL | `http://172.27.4.20:4429` |
| Stored Procedure / Package | `KI.PKG_INTERFAZ_CLIENTE.obtener_productos_por_cliente` |

## Descripción

Retorna todos los productos financieros asociados a un cliente. Incluye
cuentas de ahorro, certificados de depósito, tarjetas de crédito y préstamos.

## Campos raíz de la respuesta

| Campo | Tipo | Descripción | Uso en conversación |
|-------|------|-------------|---------------------|
| `resultCode` | number | Código de resultado de la operación. 0 = éxito. | Validar éxito (0) antes de mapear productos |
| `resultMessage` | string | Mensaje descriptivo del resultado. | Log / diagnóstico; no mostrar al cliente |
| `products` | array | Lista de productos financieros del cliente. | Fuente del snapshot de portafolio del turno |

## Índice

- [Diccionario de campos](diccionario-campos.md)
- [Tablas de referencia](tablas-referencia.md)
- [Casos de uso por producto](casos-de-uso.md)
- [Ejemplo de respuesta](ejemplo-productos.md)
- [Notas operativas](notas.md)
