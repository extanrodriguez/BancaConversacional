# Entrega — Corrección auditada V3.1

Fecha UTC: 2026-09-18

## Objetivo cumplido

Reparar defectos comprobados del cierre cognitivo V3.1 (gate de evaluación, financieros, pendientes/transiciones, catálogo/fuentes, reproducibilidad del ZIP) sin tocar `BSC.genesis.conversational.backend`, sin deploy ni Azure/Redis como bloqueantes.

## Comandos ejecutados

```text
.\.venv\Scripts\python.exe -m pytest ^
  tests/unit/test_correccion_auditada_v3_1.py ^
  tests/unit/test_casos_adicionales_v3.py ^
  tests/unit/test_cierre_cognitivo_v3_1.py ^
  tests/unit/test_cognitive_improvement_v3.py -q --tb=line
```

Resultado local: **59 passed**.

Empaquetado:

```text
.\.venv\Scripts\python.exe scripts\pack_cognitive_v3_1.py
```

Verificación contra extracción limpia del ZIP (hashes + import + smoke pytest) documentada en `works/ZIP_COGNITIVO_V3_1_META.json` y manifiesto regenerado.

## Correcciones principales

| Área | Cambio |
|---|---|
| Reproducibilidad | Allowlist de `security_secrets.py` en el packer (ya no se excluye por substring `secret`) |
| Gate 24 casos | Informe se escribe siempre; `failed` hace fallar pytest (parametrizado + `test_run_all_24…`) |
| V3-05/08/12/19/13 | Assertions estrictas (AND de campos; IDs de entidad; mapeo autorizado; fecha ausente explícita) |
| CC02 / CC03 / IG01 | Recorridos de 5 turnos separados (Visa ≠ cuentas/nómina); IG01 exige misión+visión+diferencia |
| Financieros | `ledger None` ≠ available; `due_date` de tarjeta no cae a balance; DAP capital sin `or available`; totales/subtotales con ausentes |
| Pendientes | No sobrescribir `fields` por `["rate"]` al retomar; corrección limpia foco/pending; cierre por transición |
| Plan | Validación DAG/ciclos → `InvalidTurnPlanError`; except del path plan sanitizado (secretos no siguen crudos) |
| Catálogo | Platinum unmapped; Multicrédito / Crédito diferido / Cuotas BSC separados; existencia con `catalog_personal_map` |
| Fuentes | Glosario versionado `data/kb_glossary_local_v31.json`; sin inventar FAQ en Python |
| Semántica | Autoridad: `heuristic_multi`; Azure = fallthrough 1 intención (ver `DOC_PLAN_INTERPRETER_V3_1.md`) |

## Resultados 24 adicionales

Fuente: `works/RESULTADOS_CASOS_ADICIONALES_V3.json`

- **passed:** 22  
- **blocked:** 2  
- **failed:** 0  

Críticos: V3-05, V3-08, V3-12, V3-13, V3-19 → passed.

## Matriz

`works/MATRIZ_COBERTURA_CIERRE_V3_1.json` recalculada (260 = 236 + 24):

- passed: 31 (9 Word vinculados + 22 adicionales)  
- blocked: 2  
- not_executed: 227  

`not_executed` / `blocked` no cuentan como aprobados.

## Límites / pendientes remotos

- **Azure Brain QA real:** no ejecutado (`GENESIS_AZURE_BRAIN=0` en esta batería).  
- **Redis CAS / concurrencia:** documentado aparte; no bloquea estas reparaciones.  
- **Backend externo** `BSC.genesis.conversational.backend`: **sin cambios** y **no** verificado por hashes en este paquete (ausente del ZIP a propósito).  
- Paquete de auditoría `Auditoria_Codigo_Real_V3_1.md` / `Resultados_Reproduccion_V3_1.json`: no estaba en el checkout local; se aplicaron los criterios del prompt de corrección.

## Evidencia de paquete

Tras `pack_cognitive_v3_1.py`:

- ZIP: `works/BancaConversacional_Cognitivo_V3_1_20260918.zip`
- SHA-256 ZIP: `4362cf9f04501914decd4faf138d2750d7d6c6f644f9b4e883acb567983ee9c0`
- Meta: `works/ZIP_COGNITIVO_V3_1_META.json`
- Manifiesto (bytes de extracción limpia): `works/MANIFEST_SHA256_CIERRE_V3_1.json`

Hashes clave (extracción limpia):

| Archivo | SHA-256 |
|---|---|
| `plan_interpreter.py` | `0b4add8e1c2a3e1d35bf04ed05876563b529adee3a018946358684e0c01ae755` |
| `plan_executor.py` | `42e0edb54853f310f06d98455a1a81ec5151ffaf2ef0fe4284d91b77d28bb6a5` |
| `grounded_executor.py` | `cd736992672da67346cb980e7263a53603be2fdc467d2eeef1253c249be33a85` |
| `security_secrets.py` | `fae21731b7de6b3e61584be90081bfcf5410eca552eb4ec50047be0ab8fc53b8` |

Comprobaciones en extracción:

1. Existe `src/genesis_cognitive/brain/security_secrets.py`
2. Import OK: `interpret_turn_plan` / `scan_auth_secrets`
3. Smoke pytest desde extract (`test_ledger_none…`, `test_card_due_date…`, `test_plan_cycle…`) → 3 passed
