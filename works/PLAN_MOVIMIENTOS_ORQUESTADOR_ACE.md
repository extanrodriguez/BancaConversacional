# Plan de trabajo — Movimientos vía orquestador + ACE

Documento de diseño (sin implementación). Objetivo: que la cognitiva pida movimientos, el orquestador externo llame a IBM App Connect (`172.27.4.20:4429`) y devuelva evidencia normalizada.

---

## 1. Objetivo y alcance

| Incluye | No incluye (fase 1) |
|---------|---------------------|
| Cuenta (rango fechas) | Filtros ACE que no existen (comercio, monto, tipo) |
| Préstamo | Cognitiva llamando ACE directo |
| TC (fase posterior por latencia) | Historial ilimitado en el chat |
| Caché Redis corta | Cambiar Presentation Product / WRITE PATH de portafolio |

**Servicios ACE que usamos (ya validados 23/09/2026):**

| `product_kind` | Endpoint |
|----------------|----------|
| `ACCOUNT` | `GET /account-management/v1/account-transactions/retrieve` |
| `ACCOUNT` + “últimos N” (opcional) | `GET /account-management/v1/account-recent-transactions/retrieve` |
| `LOAN` | `GET /loan-management/v1/loan-transactions/retrieve` |
| `CREDIT_CARD` | `GET /credit-card-management/v1/credit-card-transactions/retrieve` |

Base: `http://172.27.4.20:4429` (dev8). Alterno `:4430` mismo contrato.

---

## 2. Flujo end-to-end (2 hops)

```text
Hop A — Pedido
  APK → Orquestador → POST /turn { question, customer_id, conversation_id }
  Cognitiva → detecta ACCOUNT_MOVEMENTS_READ
           → resuelve producto + fechas
           → responde con core_channel (MOVEMENTS_QUERY)
           → reply puede ser null o “un momento…”

Hop B — Evidencia
  Orquestador lee core_channel
  → cache hit? usa Redis
  → si no: GET ACE → normaliza → SETEX Redis
  → POST /turn { movements_evidence, conversation_id, customer_id, question=null o eco }
  Cognitiva → narra top 3–5 → reply al APK
```

Regla: el LLM **nunca** habla con ACE; solo ayuda a interpretar. Fechas y refs las fija la cognitiva con reglas + snapshot Redis.

---

## 3. Lo que la cognitiva envía al orquestador (`core_channel`)

Extensión del contrato Genesis **1.2.0** (mismo envelope que hoy; nueva operación).

### 3.1 Envelope

```json
{
  "schema_version": "1.2.0",
  "request_id": "uuid",
  "correlation_id": "uuid",
  "timestamp": "2026-09-23T19:00:00Z",
  "operation": {
    "type": "MOVEMENTS_QUERY",
    "contract_code": "P30",
    "nature": "query",
    "requires_confirmation": false,
    "next_action": "execute_operation"
  },
  "identity": {
    "customer_id": "827340",
    "conversation_id": "conv-uuid",
    "turn_number": 4
  },
  "capability": {
    "intent_id": "ACCOUNT_MOVEMENTS_READ",
    "capability_candidate": "ACCOUNT_MOVEMENTS",
    "selected_route": "PERSONAL_READ",
    "confidence": 1.0
  },
  "contract": { "... ver 3.2 ..." },
  "telemetry": {
    "cognitive_status": "VALID_CONTRACT",
    "pipeline_version": "0.8.0"
  }
}
```

### 3.2 `contract` — pedido de movimientos

Campos **obligatorios** según producto:

```json
{
  "query_type": "movements",
  "product_kind": "ACCOUNT | LOAN | CREDIT_CARD",
  "product_ref": "11042010173807",
  "currency_code": "214",
  "start_date": "23/08/2026",
  "end_date": "23/09/2026",
  "limit": 50,
  "ace_operation": "GetAccountTransactions"
}
```

| Campo | Tipo | Quién lo llena | Notas |
|-------|------|----------------|-------|
| `product_kind` | enum | Cognitiva | Decide qué ACE llamar |
| `product_ref` | string | Cognitiva (snapshot) | Cuenta / loanCode / creditCardNumber (18 dígitos TC). **Nunca** del texto libre sin validar contra portafolio |
| `currency_code` | string | Cognitiva | ISO 4217 numérico: `214` DOP, `840` USD. Obligatorio en préstamo y TC |
| `start_date` / `end_date` | string | Cognitiva | Siempre `dd/MM/yyyy`. En cuenta y TC **siempre** ambos |
| `limit` | int | Cognitiva | Máx. ítems a devolver tras normalizar (ej. 50). ACE no pagina |
| `customer_code` | string | Cognitiva | Solo si `ace_operation=GetAccountRecentTransactions` (= `customer_id` de sesión) |
| `number_of_movements` | int | Cognitiva | Solo Recent |
| `ace_operation` | string | Cognitiva (hint) | Orquestador puede validar/override por `product_kind` |
| `display_hint` | string opcional | Cognitiva | Ej. `"last_month"` para logs/UX, no para ACE |

### 3.3 Ejemplos Hop A

**“Movimientos de mi ahorro del último mes”**

```json
"contract": {
  "query_type": "movements",
  "product_kind": "ACCOUNT",
  "product_ref": "11042010173807",
  "currency_code": "214",
  "start_date": "23/08/2026",
  "end_date": "23/09/2026",
  "limit": 50,
  "ace_operation": "GetAccountTransactions",
  "display_hint": "last_month"
}
```

**“Últimos 5 movimientos de la cuenta”** (recomendado: Transactions + recorte; Recent es opcional)

```json
"contract": {
  "query_type": "movements",
  "product_kind": "ACCOUNT",
  "product_ref": "11042010173807",
  "currency_code": "214",
  "start_date": "01/09/2026",
  "end_date": "23/09/2026",
  "limit": 5,
  "ace_operation": "GetAccountTransactions",
  "display_hint": "last_n"
}
```

**Préstamo**

```json
"contract": {
  "query_type": "movements",
  "product_kind": "LOAN",
  "product_ref": "23582",
  "currency_code": "214",
  "start_date": "01/01/2026",
  "end_date": "23/09/2026",
  "limit": 20,
  "ace_operation": "GetLoanTransactions"
}
```

**Tarjeta**

```json
"contract": {
  "query_type": "movements",
  "product_kind": "CREDIT_CARD",
  "product_ref": "220709211440550668",
  "currency_code": "214",
  "start_date": "01/08/2026",
  "end_date": "23/09/2026",
  "limit": 20,
  "ace_operation": "GetCreditCardTransactions"
}
```

### 3.4 Traducción NL → fechas (regla cognitiva, no ACE)

| Frase | Regla sugerida |
|-------|----------------|
| “último mes” | Hoy − 1 mes → hoy (o mes calendario anterior; **fijar una** y documentarla) |
| “este mes” | Día 1 del mes → hoy |
| “últimos 7 días” | Hoy − 7 → hoy |
| “enero” / “enero 2026” | `01/01/yyyy`–`31/01/yyyy` |
| sin periodo | Default: últimos 30 días |
| “últimos N” | Default rango 30 días + `limit=N`; orquestador ordena y toma los N más recientes |

Fechas inválidas / ISO (`yyyy-MM-dd`) **prohibidas** hacia ACE.

### 3.5 Clarificación (sin `core_channel` aún)

Si hay 2+ cuentas y no hay `account_ref`:

- `status=CLARIFICATION_REQUIRED`
- `core_channel=null`
- `app_channel.options` con productos

El orquestador **no** llama ACE hasta el siguiente turno con producto elegido.

---

## 4. Lo que el orquestador debe devolver (Hop B)

### 4.1 Body hacia `POST /turn`

```json
{
  "customer_id": "827340",
  "conversation_id": "conv-uuid",
  "question": null,
  "context_info": false,
  "movements_evidence": {
    "schema_version": "1.0.0",
    "ok": true,
    "request_id": "uuid-del-core_channel",
    "correlation_id": "uuid",
    "source": "ACE",
    "cached": false,
    "ace_service": "GetAccountTransactions",
    "ace_http_status": 200,
    "ace_response_code": 0,
    "ace_response_message": "Ok",
    "product_kind": "ACCOUNT",
    "product_ref": "11042010173807",
    "product_mask": "****3807",
    "currency": "DOP",
    "currency_code": "214",
    "start_date": "23/08/2026",
    "end_date": "23/09/2026",
    "total_from_ace": 26,
    "total_returned": 26,
    "truncated": false,
    "limit_applied": 50,
    "items": [
      {
        "date": "2026-01-06",
        "time": null,
        "description": "Debito Por Transferencia",
        "type_code": "93",
        "type_name": "DEBITO POR TRANSFERENCIA",
        "amount": 8472.0,
        "direction": "DEBIT",
        "balance": 314045.9,
        "reference": "13512349",
        "sequence": "214718103",
        "merchant_name": null,
        "raw_operation": "Debit"
      }
    ]
  }
}
```

### 4.2 Ítem canónico (`items[]`)

| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| `date` | sí | Fecha movimiento (`yyyy-MM-dd` o ISO datetime; cognitiva formatea al usuario) |
| `description` | sí | Texto limpio (trim) |
| `amount` | sí | `decimal` (aceptar notación científica al parsear ACE) |
| `direction` | sí | `DEBIT` \| `CREDIT` \| `UNKNOWN` |
| `type_name` | no | Nombre tipo ACE |
| `type_code` | no | Código tipo |
| `balance` | no | Saldo tras movimiento si viene |
| `reference` | no | |
| `sequence` | no | No usar como ID único en TC |
| `merchant_name` | no | TC; trim; null si basura |
| `time` | no | |

### 4.3 Error / vacío

```json
{
  "movements_evidence": {
    "schema_version": "1.0.0",
    "ok": false,
    "request_id": "…",
    "product_kind": "ACCOUNT",
    "product_ref": "11042010173807",
    "ace_http_status": 200,
    "ace_response_code": 99,
    "ace_response_message": "Error: No se encontraron registros",
    "error_kind": "NO_DATA",
    "items": [],
    "total_from_ace": 0,
    "total_returned": 0,
    "truncated": false
  }
}
```

| `ace_response_code` / caso | `error_kind` sugerido | UX cognitiva |
|----------------------------|----------------------|--------------|
| `0` + lista vacía | `NO_DATA` | “No hay movimientos en ese período” |
| `99` cuenta | `NO_DATA` o `NOT_FOUND` | Idem / producto no encontrado |
| `2` préstamo | `NOT_FOUND` | Préstamo inexistente |
| `1` TC | `NOT_FOUND` | Tarjeta / fecha de corte |
| HTTP 500 / ORA-01861 | `UPSTREAM_ERROR` | “No pude consultar ahora” |
| Timeout TC | `TIMEOUT` | Reintentar / caché |

**Importante:** HTTP 200 con `responseCode ≠ 0` **no** es éxito.

### 4.4 Mapeo ACE → ítem (orquestador)

**Cuenta (`accountTransactions`)**

- `date` ← `transactionDate`
- `description` ← `description`
- `amount` ← `amount`
- `direction` ← `operation` Debit/Credit **o** `vdbCrot` D/C
- `balance` ← `balance`
- `type_name` ← `transactionTypeName`
- `sequence` ← `sequence` / `idSort`

**Recientes (`accountRecentTransactions`)**

- `date` ← `movementDate`
- `direction` ← `isDebit` TRUE/FALSE o `vdbCrot`
- Ojo: `debitAmount`/`creditAmount` suelen venir en 0 → usar `amount` + dirección

**Préstamo (`loanTransactions`)**

- `direction` ← `operation` CREDIT/DEBIT
- `type_name` ← `transactionTypeName`

**TC (`creditCardTransactions.transactions`)**

- Lista anidada bajo `creditCardTransactions`
- Trim `description`, `merchantName`, `approvalNumber`
- `direction` ← `operation`
- No usar `sequence` como unique id

Tras mapear: ordenar por fecha desc, aplicar `limit`, set `truncated = total_from_ace > total_returned`.

---

## 5. Caché (orquestador)

**Clave sugerida:**

```text
movements:{customer_id}:{product_kind}:{product_ref}:{currency_code}:{start_date}:{end_date}:{limit}
```

| Producto | TTL | Timeout HTTP |
|----------|-----|--------------|
| ACCOUNT / LOAN | 2–5 min | 10–15 s |
| CREDIT_CARD | 5–15 min | ≥ 180 s |

- Solo cachear `ok=true` (o vacío legítimo `NO_DATA` con TTL más corto, opcional).
- Invalidar tras transferencia/pago del mismo producto (si aplica).
- Preferible **mismo Redis** que sesiones cognitivas, o Redis del orquestador; si es otro, la cognitiva no lee la clave — solo consume `movements_evidence` en Hop B.

---

## 6. Qué tiene que cambiar el orquestador externo

Aplicable al orquestador .NET de banca conversacional (el que habla con cognitiva `:8447` y ya llega a `172.27.4.20`). El backend POC del repo (`GetMovementsAsync` → `GET /movements/{clientId}`) **no** es el contrato ACE; hay que apuntar a Dashboard/ACE `4429`.

### 6.1 Cliente HTTP ACE (nuevo o extensión)

- Base URL: `ExternalServices__DashboardApiBase*` ya apunta a `http://172.27.4.20:4429` en config — **reutilizar** para estos paths (no el BankingApi POC de AWS).
- Métodos nuevos, por ejemplo:
  - `GetAccountTransactionsAsync(accountNumber, start, end)`
  - `GetAccountRecentTransactionsAsync(accountNumber, customerCode, n, start, end)`
  - `GetLoanTransactionsAsync(loanCode, currencyCode, start?, end?)`
  - `GetCreditCardTransactionsAsync(cardNumber, currencyCode, start, end)`
- Query string exacta; fechas `dd/MM/yyyy`.
- Deserializar montos como `decimal` (científica).
- Validar éxito: HTTP 200 **y** `responseCode == 0`.
- HttpClient TC: timeout ≥ 180 s; no martillar en paralelo.

### 6.2 Handler de `core_channel`

Tras `/turn`, si hay `core_channel` con `next_action=execute_operation`, ejecutar y continuar.

**Cambios:**

1. Reconocer `operation.type == "MOVEMENTS_QUERY"` (y `contract_code` P30).
2. **No** descartar el flujo cognitivo ni sustituir por Banking API genérica al ver dominio ACCOUNTS (hoy a veces el orq deriva a Banking y tira el `client_response` — para movimientos debe respetar este contrato).
3. Tras ACE + normalización → Hop B a cognitiva con `movements_evidence`.
4. Propagar `request_id` / `correlation_id`.

### 6.3 Normalizador + caché

- Capa `MovementsNormalizer` (4 shapes → DTO único).
- Capa `MovementsCache` (Redis SETEX / GET).
- Recorte por `limit` + flag `truncated`.

### 6.4 Segundo POST a cognitiva

- Nuevo campo en el body de `/turn`: `movements_evidence` (acordar nombre con cognitiva).
- `question=null` en Hop B (o flag `evidence_only=true` si se prefiere).
- Misma `conversation_id` / `customer_id`.
- Manejar latencia TC: no cortar el WebSocket APK a los 30 s; o mensaje intermedio “consultando movimientos…”.

### 6.5 Seguridad / datos

- `product_ref` de TC: usar número completo solo hacia ACE; al APK/LLM solo máscara (`product_mask`).
- No loguear PAN completo.
- `customer_code` solo el de la sesión autenticada (nunca del mensaje del usuario).

### 6.6 Config / ops

| Variable / tema | Acción |
|-----------------|--------|
| `DashboardApiBase` → `:4429` | Confirmar env DEV/QA/PROD |
| Timeout HttpClient por operación | Cuenta/préstamo corto; TC largo |
| Feature flag `MovementsViaAce=true` | Rollout gradual |
| Métricas | latencia ACE, hit cache, `responseCode`, timeouts |
| Circuit breaker TC | Evitar cola de 50 s × N |

### 6.7 Pruebas orquestador

1. Cuenta rango con data → `ok=true`, ítems mapeados.
2. Cuenta sin data → `99` → `ok=false`, `NO_DATA`.
3. Fecha ISO → no enviar (cognitiva); si se envía, no tumbar el proceso.
4. Préstamo moneda mala → lista vacía `responseCode=0` → tratar como `NO_DATA`.
5. TC latencia + cache segundo call &lt; 1 s.
6. Clarificación: sin `core_channel`, no llama ACE.
7. Round-trip completo con cognitiva mock.

---

## 7. Qué cambia en la capa cognitiva (para alinear con orq)

Sin ejecutar en este documento; checklist para el mismo plan:

| Cambio | Detalle |
|--------|---------|
| `operation_request_adapter` | Mapear `ACCOUNT_MOVEMENTS_READ` → `MOVEMENTS_QUERY` / P30 |
| Resolver fechas NL | Reglas deterministas + default 30 días |
| Resolver `product_ref` | Snapshot Redis; aclaración si N>1 |
| Dejar de responder “no disponible” | Si viene `movements_evidence`, narrar; si Hop A, esperar orq |
| Aceptar `movements_evidence` en `/turn` | Nuevo path sin LLM de intent; solo grounded reply |
| Top N en respuesta | HU: últimas 3; no volcar 50 líneas |
| Intents préstamo/TC movimientos | Extender si hoy solo `ACCOUNT_MOVEMENTS_READ` |

---

## 8. Fases de entrega

| Fase | Entrega | Dueño |
|------|---------|--------|
| **0** | Acuerdo de JSON Hop A/B (este doc) + firma equipos | Ambos |
| **1** | Orq: cliente ACE cuenta + normalizer + Hop B (sin cache) | Orquestador |
| **1b** | Cognitiva: emitir `MOVEMENTS_QUERY` + consumir evidencia (cuentas) | Cognitiva |
| **2** | Cache Redis + préstamos | Orquestador + cognitiva |
| **3** | TC + timeout + cache agresiva + UX espera | Orquestador + cognitiva |
| **4** | Recent opcional, filtros locales, invalidación | Ambos |

Criterio de listo fase 1: pregunta “movimientos del último mes” de una cuenta conocida → respuesta con fechas/montos/descripciones reales de ACE, sin inventar.

---

## 9. Decisiones a cerrar (bloquean implementación)

1. Nombre exacto del campo Hop B: `movements_evidence` vs `context.movements`.
2. “Último mes” = 30 días rodantes vs mes calendario.
3. ¿Redis compartido o solo orq?
4. ¿Mensaje intermedio al APK mientras corre TC?
5. ¿`GetAccountRecentTransactions` en v1 o solo Transactions + `limit`?
6. Servidor ACE oficial: `4429` vs `4430`.

---

## 10. Resumen

**Cognitiva manda `core_channel.MOVEMENTS_QUERY` con producto + fechas `dd/MM/yyyy`; orquestador llama ACE en `:4429`, normaliza, (opcional) cachea, y devuelve `movements_evidence` en un segundo `/turn` para que la cognitiva narre.**

Los cuatro servicios ACE validados el 23/09/2026 alcanzan para este flujo; no se requiere un endpoint adicional en el bus para “último mes”.

---

## Referencia rápida Teams

- Cognitiva pide por `core_channel` (no llama al bus).
- Orquestador llama ACE + puede cachear (sobre todo TC ~50 s).
- Devuelve `movements_evidence` normalizado.
- Empezar por cuentas; después préstamo; TC al final.
