# Resultados QA Azure real — usuario lab 726588

Fecha de corrida: **2026-09-18** (UTC). Autorización: consultas de lectura + sesiones de prueba.  
**No** se ejecutaron transacciones, despliegues ni cambios a Foundry/índices.  
**No** se modificó `BSC.genesis.conversational.backend`, frontend, WebSocket productivo, contratos externos ni datos bancarios.

## 1. Entorno y versión realmente probados

| Campo | Valor observado |
|---|---|
| Host | `http://20.127.25.24:8447` |
| `/health` | `status=ok`, `service=genesis-cognitive`, **`env=dev`**, **`version=0.8.0`**, `rag=ready` |
| `/config` | `genesis_env=dev`, `allow_cognitive_execute=true` (sin secretos) |
| Interfaz | `GET /pruebas/` → 200; JS `app.js?v=14` |
| Contexto 726588 | `POST /orch/context` → `CONTEXT_LOADED`, **`context_source=lab_fallback`** |
| Persistencia previa al chat | Confirmada: turnos posteriores en la misma `conversation_id` resolvieron portafolio (no sesión vacía) |
| Stamp de contexto | `2026-09-18T02:0x…+00:00` (frescura = momento de carga lab; Core real no aportó snapshot) |
| Error Core (esperado en lab) | `core_error` presente con claves `http`, `websocket` — **no** se usó Core productivo |
| Inventario (solo tipos) | 1 cuenta ahorros **DOP**; **2 préstamos**; **sin** tarjeta activa; **sin** cuenta USD visible; 4 productos / 3 activos |

### Ruta de la interfaz vs API

1. **UI `/pruebas/`** carga contexto con `POST /orch/context` y envía chat a **`POST /orch/chat/front`**.
2. Ese proxy reenvía al orquestador (`GENESIS_ORCH_URL`, tip. `:8080`), que a su vez debe llamar **`POST /turn`** en :8447.
3. **`GET /orch/health`** → **502** `{"orch":"down","detail":"timed out"}`.
4. Por tanto: **prueba de interfaz chat = BLOQUEADA** (orquestador caído).  
   **Prueba API autorizada = `POST /turn`** (y alias `/chat/front` en el mismo proceso cognitivo) = **ejecutada**.

Una respuesta correcta por fastpath **no** prueba Azure. En este despliegue `/turn` **no expone** `decision_trace` ni `correlation_id`; la telemetría usable es `audit` + `rag_status` + `app_channel.intent_id` + latencia/estilo de redacción.

### Local vs QA

| Aspecto | Local (workspace) | QA :8447 corrido |
|---|---|---|
| Versión reportada | App `0.8.0` en código | `0.8.0` |
| Entrega 1C local | CAS/gate, `rate_context_guardrail`, tests cierre | **No verificable** como desplegada: respuesta canal sin `decision_trace`; fallos de comprensión/continuidad coinciden con gaps previos a estabilización completa |
| Redis multiproceso | Procedimiento documentado; Docker no bloqueó esta corrida | **No evaluado** aquí (fuera de alcance de esta matriz funcional) |

## 2. Matriz de resultados

Conv. anonimizada: `conv-` + prefijo de UUID de la corrida principal (raw en `works/_qa_azure_run_726588_raw.json`).  
Valores monetarios / ids → enmascarados (`[AMT]`, `####`, `[RATE]%`).

| ID | Pregunta (resumen) | Esperado | Observado (sanitizado) | Ruta | Evidencia modelo/recuperación | Latencia | Veredicto |
|---|---|---|---|---|---|---|---|
| A1 | ¿Qué productos tengo? | Listado activo | Lista cuenta DOP + 2 préstamos | fastpath | `intent=PORTFOLIO_LIST`, `audit.step_count=1`, `total_ms≈1` — **no Azure** | ~200 ms | **PASS** |
| A2 | ¿Cuánto tengo disponible? | Disponible de **cuenta** | Aclaración entre **préstamos** | fastpath | `PORTFOLIO_QUERY`, step_count=1 — **no Azure** | ~250 ms | **FAIL** (comprensión / campo) |
| A3 | ¿Y cuál es el saldo actual? | Campo **saldo actual** | Responde **saldo disponible** de la cuenta | fastpath | `ACCOUNT_BALANCE_READ`, step_count=1 — **no Azure** | ~230 ms | **FAIL** (campo disponible≠actual) |
| B1 | ¿Cuánto debo de mi préstamo? | Aclaración multi-préstamo | Options de 2 préstamos | fastpath | `LOAN_DETAIL_READ` | ~240 ms | **PASS** |
| B2 | Selección estructurada 1.er préstamo | Resuelve candidato | Detalle del préstamo (deuda/tasa) | fastpath | `selected_option_ref` OK | ~200 ms | **PASS** |
| B3 | ¿y esa cuenta? | No arrastrar préstamo como cuenta; aclarar producto | Clarificación genérica dominio (productos vs banco) | fastpath | Pierde foco de producto | ~430 ms | **FAIL** (continuidad) |
| B4–B6 | Continuidad DOP/USD | Multi-moneda | — | — | Sin cuenta USD en portafolio | — | **NO APLICA** |
| C1 | Ahora el otro préstamo | Cambia foco | Detalle del otro préstamo | fastpath | Continuidad préstamo | ~300 ms | **PASS** |
| C2 | No, me refería a la cuenta de ahorros | Corrige a cuenta sin atributos préstamo | Clarificación genérica dominio | fastpath | No corrige foco | ~690 ms | **FAIL** (continuidad/corrección) |
| D1 | ¿Cuál es el saldo de mi cuenta? | Saldo cuenta | Disponible cuenta (NLG) | NLG probable | `total_ms≈1052`, redacción “Hola, Félix…” — **señal de modelo de respuesta**, sin contador completions | ~1.4 s | **PASS** parcial (consulta ok; campo=disponible) |
| D2 | ¿qué significa saldo disponible? | Definición sustentada | Definición operativa de disponible | **FOUNDRY_KB** | `intent=BUSINESS_KNOWLEDGE_QUERY`, `rag_status=FOUNDRY_KB` — **recuperación Foundry**, no prueba por sí sola el brain estructurado | ~2.4 s | **PASS** (recuperación) |
| D3 | ¿y cuánto tengo en esa cuenta? | Conserva foco cuenta | Disponible de la misma cuenta | NLG probable | `ACCOUNT_BALANCE_READ`, ~1.3 s | ~1.5 s | **PASS** (foco) |
| E1 | ¿Cuál es mi tasa? | Aclarar o usar contexto | Tasa anual de un préstamo (foco previo) | NLG probable | Sin aclaración multi-préstamo en este turno; usó continuidad | ~1.9 s | **PASS** (contexto suficiente tras C1) |
| E2 | ¿Qué significa tasa? | Conocimiento | Definición tarifario/contrato | **FAQ** | `rag_status=FAQ` | ~3.7 s | **PASS** |
| E3 | Tasa de mi préstamo y qué significa | Ambas partes con evidencia | Tasa personal + explicación en la misma respuesta | NLG probable | `rag_status=NOT_REQUIRED` — la parte “significa” **no** vino marcada FAQ/Foundry (posible parafraseo de modelo) | ~1.8 s | **PASS** funcional / **riesgo** de no-grounding en definición |
| F1 | dime el dispoonible… (typo) | Entiende reformulación | Clarificación genérica | fastpath | No mapea a disponible | ~420 ms | **FAIL** (comprensión lenguaje) |
| F2 | y el actual? | Corto dependiente del turno | Clarificación genérica | fastpath | No usa foco previo | ~410 ms | **FAIL** (continuidad corta) |
| F3 | cuanto debo del prestamo | Deuda préstamo | Total adeudado (NLG) | NLG probable | Tras foco préstamo | ~2.4 s | **PASS** |
| G1 | Fecha de corte de mi tarjeta | No inventar / no cero | Declara ausencia de TC activas + enlace contratación | fastpath | Correcto ante ausencia | ~1.2 s | **PASS** |
| UI-CHAT | Flujo completo `/pruebas` chat | Orch→`/turn` | Orquestador down | — | `/orch/health` 502 | — | **BLOQUEADO** |

### Azure / Foundry / FAQ — qué sí se demostró

| Capacidad | ¿Demostrada en esta corrida? | Cómo |
|---|---|---|
| Fastpath / plantillas | Sí | A1–A3, B1–B2, C1, G1 (`audit.total_ms` ~0–1, `step_count=1`) |
| FAQ corpus | Sí | E2 `rag_status=FAQ` |
| Foundry KB (recuperación) | Sí | D2 `rag_status=FOUNDRY_KB` |
| Inferencia Azure (brain estructurado / completions) | **No demostrada de forma telemetrada** | No hay `decision_trace` ni contador de completions en la respuesta canal. Hay **inducción** por latencia>1s + NLG en D1/D3/E1/E3/F3, insuficiente para afirmar `azure_structured` |
| UI end-to-end | No | Orquestador caído |

## 3. Fallos por categoría

### Comprensión
- **A2**: “disponible” enrutado a préstamos.
- **F1**: typo/reformulación natural no resuelta (cae a clarificación genérica).

### Continuidad
- **B3**: tras foco préstamo, “¿y esa cuenta?” no aclara incompatibilidad producto; pierde foco.
- **C2**: corrección explícita a cuenta de ahorros no aplicada.
- **F2**: turno corto “y el actual?” no hereda cuenta/campo.

### Contexto / campos
- **A3**: “saldo actual” servido como **disponible** (confusión de campos).
- **D1/D3**: útiles, pero el copy habla de disponible aunque la pregunta diga “saldo”.

### Recuperación de conocimiento
- **E3** (parcial): definición embebida sin `FAQ`/`FOUNDRY_KB` → riesgo de no-grounding.
- **D2**: Foundry OK en esta corrida; en un probe previo aislado el mismo tipo de pregunta devolvió `NON_OPERATIONAL` con `slowest_step=verifier` → **inestabilidad** de la vía modelo/recuperación (registrar, no “arreglar” corpus aquí).

### Redacción
- Mezcla de plantilla “Felix Prestamos, …” (fastpath) vs “Hola, Félix. …” (NLG) sin inconsistencia grave de contenido, pero sí de tono.
- Clarificación genérica (“¿dato de productos o información general?”) opaca frente a opciones de producto cuando el usuario ya está en hilo personal.

## 4. Evidencias sanitizadas (extracto)

```text
CTX: CONTEXT_LOADED source=lab_fallback products=4 active=3 core_error=[http,websocket]
A2: status=requires_selection intent=PORTFOLIO_QUERY reply="¿Sobre cuál préstamo…?"
A3: status=VALID_CONTRACT intent=ACCOUNT_BALANCE_READ reply="…saldo disponible… [AMT] DOP"
D2: intent=BUSINESS_KNOWLEDGE_QUERY rag=FOUNDRY_KB audit.total_ms≈2124
E2: intent=BUSINESS_KNOWLEDGE_QUERY rag=FAQ
E1: intent=LOAN_DETAIL_READ reply="…tasa… [RATE]% anual…" (sin FAQ)
G1: "no tienes tarjetas de crédito activas…"
ORCH: /orch/health → 502 orch down
```

Raw completo sanitizado: `works/_qa_azure_run_726588_raw.json`  
Runner usado: `works/_qa_azure_run_726588.py` (solo lectura remota).

## 5. Tres correcciones prioritarias (diagnóstico → no implementadas aquí)

1. **Desambiguar “disponible/saldo actual” hacia cuenta y campos correctos**  
   Evitar que consultas de liquidez caigan en `LOAN_*` / `PORTFOLIO_QUERY` de préstamos; mapear “saldo actual” → campo current/ledger y “disponible” → available (falla A2/A3).

2. **Reparar continuidad y correcciones de foco**  
   “¿y esa cuenta?”, “No, me refería a…”, y turnos cortos (“y el actual?”) deben conservar o corregir `product_ref`+`field` sin caer a clarificación genérica de dominio (falla B3/C2/F2).

3. **Estabilizar vía conocimiento + telemetría Azure en canal**  
   - Exponer en respuesta `/turn` (o audit enriquecido) `correlation_id`, `slowest_step` real y flag de completions Azure para no inferir.  
   - Asegurar que definiciones en preguntas mixtas (E3) citen FAQ/Foundry o declaren brecha; no dar por bueno el parafraseo sin `rag_status`.  
   - Separado: **restaurar orquestador** para desbloquear UI `/pruebas` (hoy BLOQUEADO).

## 6. Explicitamente no cerrado

- Concurrencia Redis multiproceso / CAS distribuido: **no** validada en esta corrida (no confundir con turnos secuenciales in-process).
- Éxito Azure brain estructurado: **no declarado**.
- Pruebas UI chat: **BLOQUEADO** por orch down.
- Escenarios USD: **NO APLICA** en portafolio 726588 lab.

## 7. Conclusión

Validación API en QA (`POST /turn`) sobre sesión lab 726588 **completada** con matriz mixta PASS/FAIL/NO APLICA/BLOQUEADO.  
El sistema responde portafolio y varios flujos personales/FAQ/Foundry, pero **falla** en distinción disponible vs actual, en ruteo de “disponible” hacia préstamos, y en continuidad/corrección de foco.  
**No** se introduce corrección de código en esta entrega: solo diagnóstico y evidencias.
