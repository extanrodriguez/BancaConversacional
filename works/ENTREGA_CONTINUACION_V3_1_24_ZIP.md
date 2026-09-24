# Entrega — Continuación V3.1 (24 adicionales + ZIP + docs)

Fecha: 2026-09-18. Sin despliegue. Sin Foundry. Sin cambios a `BSC.genesis.conversational.backend`.

## 1. Escenarios adicionales (24)

Fuente: `works/Banca_Cierre_V3_1/insumos/Casos_QA_Adicionales_V3.jsonl`  
Resultados: `works/RESULTADOS_CASOS_ADICIONALES_V3.json`

| Estado | Cantidad | IDs |
|---|---:|---|
| **passed** | 22 | V3-01, V3-02, V3-03, V3-05…V3-20, V3-22…V3-24 |
| **blocked** | 2 | V3-04 (FAQ vacío no reproducible sin vaciar corpus), V3-21 (fallo Azure real no simulado; brain=0) |
| **failed** | 0 | — |
| **not_applicable** | 0 | — |

**Política:** blocked ≠ aprobado.

## 2. Nueve casos Word aprobados — vínculo a tests

Archivo: `works/VINCULACION_9_CASOS_APROBADOS_V3_1.json`

| case_id | Test exacto |
|---|---|
| P01 | `test_cierre_cognitivo_v3_1.py::test_journey3_card_fields_and_dap_exclusion` |
| P15 | `test_casos_adicionales_v3.py::test_p15_full_certificates_exclusion_journey` |
| CD13 | `test_cierre_cognitivo_v3_1.py::test_cd13_min_payment_not_personal_selection` |
| MIX07 | `test_cierre_cognitivo_v3_1.py::test_journey4_catalog_existence_and_compare_set` |
| CC02 | `test_casos_adicionales_v3.py::test_cc02_cc03_catalog_compare_ordered_add_and_ordinal` |
| CC03 | mismo test CC02/CC03 (agregar + ordinal «la segunda») |
| X05 | `test_journey5_secrets_scrubbed_and_ownership` (+ unit V3 PIN) |
| X07 | `test_journey5_…` (+ `test_third_party_spouse_is_security`) |
| IG01 | `test_mission_and_vision_both` (+ misión tras foco préstamo) |

Recorridos **P15 / CC02 / CC03** verificados con aserciones estrictas (tasas, vencimiento primero, sin capital; compare_set ordenado; Gold; Infinite en 2ª posición).

## 3. Documentación `plan_interpreter`

`works/DOC_PLAN_INTERPRETER_V3_1.md`

- Reglas locales → multi-tarea (`heuristic_multi`)
- Azure (si ON) → `IntentPacket` único en fallthrough; **no** genera hoy varias tareas
- Structured multi-tarea del modelo: diseño pendiente de cablear

## 4. Matriz actualizada

`works/MATRIZ_COBERTURA_CIERRE_V3_1.json`

| status | n |
|---|---:|
| passed | 31 (9 Word + 22 adicionales) |
| blocked | 2 |
| not_executed | 227 |
| **total** | **260** |

## 5. ZIP

Generado con `scripts/pack_cognitive_v3_1.py`.  
Metadatos: `works/ZIP_COGNITIVO_V3_1_META.json` (ruta, sha256, tamaño).

Excluye: `.env`, secretos, backend externo, datos reales de clientes, `.venv`.

## 6. Pruebas ejecutadas

```text
.venv\Scripts\python.exe -m pytest `
  tests/unit/test_casos_adicionales_v3.py `
  tests/unit/test_cierre_cognitivo_v3_1.py `
  tests/unit/test_cognitive_improvement_v3.py -q
# 25 passed
```
