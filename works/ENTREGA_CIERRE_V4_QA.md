# Entrega — Cierre V4 QA

Fecha: 2026-09-18. Cliente lectura autorizado: **726588**. Servicio: `genesis-cognitive-8447` (`http://127.0.0.1:8447` / `20.127.25.24:8447`).  
Orquestador externo / Foundry / PROD: **sin cambios**.

## Fuentes de verdad (no mezclar)

| Carril | Estado en esta entrega |
|---|---|
| Azure real (`resolve_full` / gpt-4o-mini) | Acreditado en turnos con `inference_count≥1` y `route_source` azure_plan o repair |
| Redis real + Entra MI | `ready/redis` ok; `auth_mode=entra_managed_identity` |
| `context_source=lab_fallback` | Persistente; `has_core_error=true` |
| Core vivo | **No validado** (bloqueado por fallback) |

Éxito **no** se declara por HTTP 200 ni por pytest solo.

## Causas confirmadas (D / E / F)

1. **AttributeError isolate:** `ResolverResult.interpretation is None` en `CLARIFICATION_REQUIRED` / `NON_OPERATIONAL` → `interpretation_to_turn_plan` hacía `.actions` sobre `None`. Corregido con reparación estructural + guardia.
2. **D/F opciones perdidas:** plan parcial devolvía `VALID_CONTRACT`+`app_channel_options`, pero `assemble_app_channel` solo armaba options si status=`CLARIFICATION_REQUIRED`. Ahora reenvía `app_channel_options`.
3. **D2/F2 selección:** `selected_option_ref` tipo `PRESTAMO_#####` no coincidía con `display_order` (product_id). Mapeo de ref APK → product_id + atajo `shortcut:pending_resume`.
4. **F1 plan incompleto:** «tasa + saldo» sin «significa» no creaba tarea de préstamo. Añadido en `plan_interpreter`.
5. **E2 corriente:** Azure devolvía ahorro + misión; suplemento de corrección fuerza `account_subtype=CHECKING` → `absent` + misión FAQ.

## Redis/Entra

Parche async (warm gate + `to_thread` / lifespan) integrado en checkout y desplegado. Ready Redis OK en corrida final.

| Ítem | Resultado |
|---|---|
| R2 arranque/lifespan | PASS (ready sin hang) |
| R1 concurrencia HTTP | Dos `/turn` solapados misma conv: ambos `VALID_CONTRACT` (A ~18s, B ~9s) — serialización efectiva; **no** `NON_OPERATIONAL` como ocupado |
| R3 renovación token Entra | **PENDING** (procedimiento; TTL largo no atravesado en esta sesión) |
| Política cluster | No verificada por API de control |

## Latencia (muestra n=13 turnos QA, servicio caliente)

Dominante: `resolve_full_attempt1_ms` ≈ 5–11 s. Atajos de selección ≈ 0.2–0.4 s.  
Timeout consumidor externo: **no leído** en esta corrida (incertidumbre documentada; no se inventa SLA).  
No se declara p95.

## Pruebas ejecutadas

```text
pytest tests/unit/test_cierre_v4_qa.py  → 15 passed
works/_qa_v4_azure_run_726588.py        → 13 turnos HTTP 200; ver JSON raw
```

Artefacto raw: `works/_qa_cierre_v4_726588_raw.json`.

## Matriz focalizada

Leyenda: PASS / FAIL / BLOCKED / NOT_EXECUTED / NOT_APPLICABLE.

| ID | Local fixtures | QA 726588 Azure+Redis | Notas |
|---|---|---|---|
| D1 | PASS | **PASS** | Definición FAQ + aclaración préstamo; 2 options |
| D2 | PASS | **PASS** | `shortcut:pending_resume`; tasa + definición |
| F1 | PASS | **PASS** | Saldo cuenta + aclaración préstamo |
| F2 | PASS | **PASS** | Selección → tasa; pending reanudado vía Redis |
| E1 | PASS (fixture con corriente) | NOT_APPLICABLE | 726588 lab sin corriente única garantizada en E1 |
| E2 | PASS | **PASS** | Ausencia corriente + misión KB |
| E3 | PASS fixtures | NOT_APPLICABLE | No hay dos corrientes en lab 726588 |
| B1 | PASS | PASS parcial | Distingue disponible vs contable en B journey |
| B2 | PASS (null) | BLOCKED Core | Contable null no forzado en lab; fixture local PASS |
| B3 | PASS (cero) | NOT_EXECUTED en lab | Fixture local |
| C1 | PASS | **PASS** | Visión + «volvamos a esa cuenta» |
| A1 | PASS fixtures | PASS parcial | Disponible DOP; USD en A2 |
| A1 USD | — | **PASS** (A2) | «No tienes cuentas activas en USD» |
| P1/P2/K1/S1 | PASS suite local | NOT_EXECUTED remoto focal | Cubiertos en pytest |
| R1 | — | **PASS** explicado | Ver arriba |
| R2 | — | **PASS** | |
| R3 | — | **PENDING** | |
| L1 | Instrumentado | PASS acotado | Cuello = resolve_full |

## Paquete

Generar con `python scripts/pack_cierre_v4_qa.py`.  
SHA256 completo en `works/ZIP_CIERRE_V4_QA_META.json` y `works/MANIFEST_SHA256_CIERRE_V4_QA.json`.

Incluye arreglo Redis/Entra async del despliegue (factory/gate/lifespan + `contract_inspector_app`).

## Pendientes concretos

1. Core vivo (quitar `lab_fallback` / resolver `has_core_error`) — validación personal real.
2. R3 renovación sostenida Entra (atravesar TTL del token con mismo cliente).
3. Política de clúster Redis (lectura autorizada).
4. Timeout efectivo del consumidor orquestador (presupuesto L1).
5. Recorrido UI → orquestador → cognitivo (no ejecutado).
6. Alinear VM al ZIP completo (hotpatch de archivos clave ya aplicado; redeploy ZIP para igualdad SHA).

## Declaración de cierre

Corrección cognitiva D/E/F + saldo + latencia por etapa **validada sobre lab_fallback + Azure real + Redis/Entra**, cliente 726588.  
**No** se declara Core vivo, continuidad Entra prolongada, ni PROD listo.
