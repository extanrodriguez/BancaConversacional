# ENTREGA_DESPLIEGUE_QA

Fecha UTC cierre: 2026-09-21T13:10Z Â· Estado final: **QA_DESPLEGADO_PARCIAL**

## Destino verificado

| Elemento | Valor |
|---|---|
| VM | `vm-test002-genesis` |
| IP pÃºblica | `20.127.25.24:8447` |
| Servicio | `genesis-cognitive-8447` (User=genesis) |
| App | `/opt/genesis-cognitive-8447/Genesis_v2` |
| Redis | `bsc-cognitive-redis-qa.eastus.redis.azure.net` Â· Entra MI Â· session+lock ping OK |
| Search | `AZURE_SEARCH_INDEX=bsc-kb-conocimiento` (conservado; Ã­ndice candidato no creado) |
| Backend .NET / frontend / WS | **intactos** |
| Cliente lectura | **726588** Â· lab_fallback Â· sin PROD/tx |

## Candidato utilizado

- PartiÃ³ de `CANDIDATO_LOCAL_PARCIAL` + continuaciÃ³n strict-v2.2.
- Artefacto ZIP: `deploy/corp-8446/dist/genesis_corp_8446.zip`
- SHA256 artefacto: `3356ef95a7a36c393a8a478185b32953e5e3f4b75638bc092e4288eea2580904` (901 files, 60.67 MB)
- Respaldo remoto: `/opt/genesis-cognitive-8447/backups/genesis_v2_20260921_102720.tar.gz`
- Hotfixes post-activaciÃ³n (mismo release):
  1. `plan_executor.py` â€” cancelaciÃ³n prÃ©stamos sin Search genÃ©rico
  2. `app_channel.py` â€” `allow_single` (TypeError que rompÃ­a `/turn`)

## Baseline â†’ post

- Pre: health OK, ready/redis OK (Entra), sin ventana P12
- Post (verificado 2026-09-21): health `ok` Â· ready/redis `ok` (session+lock ping) Â· **HAS_P12_WINDOW**
- Redis ops probe `--cas --lock`: **ok** (session_ping, lock_nx, cas_conflict)
- Token Entra renewal ciclo largo: **pendiente operativo**

## ValidaciÃ³n post-deploy

| Pieza | Resultado |
|---|---|
| Smoke /health /ready/redis /turn | OK |
| P0 live `20260921T103028Z_08481d4c` | 21 PASS + 6 clar Â· 4 PARTIAL Â· fails L09/MIX10/CC03/L06 |
| UI post-deploy `20260921T103100Z_postdeploy_ui` | capturas reales `/pruebas/` (Chrome) |
| Matriz 236 `20260921T105853Z_4f3d3488` | **236/236 ejecutados** |

### Conteos API (orÃ¡culo strict_v2.2)

| Estado | N | IDs |
|---|---|---|
| PASS_RESOLVED | 73 | P03,P04,P08,P09,P12,C01â€“C05,C07,C08,D01â€“D06,D09,D10,R03,X02,X07â€“X10,IG02,IG03,IG05,IG07,IG15,IG18,CD01â€“CD03,CD10,CD12,CD14,CD15,CD18,TC01â€“TC03,TC06,TC07,TC10â€“TC14,TD04,TD07,PR01,PR03,PR10,CE01,CE02,CE07,GR03â€“GR05,GR09,GR11,CTX03,CTX07,DA05,MIX03,MIX07,MIX09,CC02,CA03,CA05,CA06 |
| PASS_CLARIFICATION_EXPECTED | 8 | P01,P02,P05,P10,P11,P15,X01,MIX01 |
| PARTIAL_CAPABILITY | 56 | P13,P14,R01,X05,X06,IG01,IG06,IG08,IG12,IG13,IG16,IG17,IG19,IG20,CD04â€“CD07,CD11,CD13,CD16,CD17,CD20,TC04,TC08,TC09,TC15,TC16,TD01,TD03,TD05,TD06,PR04,PR05,PR08,PR09,PR11,PR12,CE03â€“CE06,GR01,GR07,GR08,DA01,DA06,DA08â€“DA10,MIX04â€“MIX06,MIX08,CMP12,CMP40 |
| FAIL_GROUNDING | 51 | CMP01â€“CMP11,CMP13â€“CMP39,CMP41â€“CMP48,CC01,CC03â€“CC05,CA01 |
| FAIL_INTERPRETATION | 30 | C06,D07,R04,X03,X04,IG04,IG14,CD08,CD09,CD19,TC05,TD02,TD08,PR02,PR06,PR07,PR13,GR06,CTX01,CTX02,CTX06,CTX08,DA02,DA04,DA07,MIX02,CA02,CA04,CA07,CA08 |
| FAIL_RETRIEVAL | 7 | PR15,CE08,GR02,GR10,GR12,CTX09,DA03 |
| FAIL_STATE | 4 | D08,CTX04,CTX05,MIX10 |
| BLOCKED_DEPENDENCY | 6 | P06,P07,IG09,IG10,IG11,PR14 |
| PENDING_EVALUATION | 1 | R02 |

Destacados: **P12 PASS** (ventana temporal), **CC02 PASS**. MIX10 sigue FAIL_STATE (payoff). CMP*/CC* dominan FAIL_GROUNDING (KB/evidencia Search).

### Columna `fix` (evidencia post-deploy Ãºnicamente)

| fix | N | Criterio |
|---|---|---|
| RESUELTO | 17 | PASS API + captura `/pruebas/` del run UI post-deploy |
| PARCIAL | 121 | parcial funcional, o PASS API sin captura nueva (`API_VERIFIED_UI_PENDING` = 65) |
| FALLA | 92 | orÃ¡culo FAIL_* |
| BLOQUEADO | 6 | BLOCKED_DEPENDENCY |

RESUELTO con captura post-deploy: P01â€“P05, P08â€“P12, P15, TC03, GR03, GR09, MIX07, MIX09, CC02.

No se reutilizan capturas de builds anteriores para acreditar este candidato.

## Search / Ã­ndice

- No se borrÃ³ ni sobrescribiÃ³ `bsc-kb-conocimiento`.
- `GENESIS_SEARCH_RETRIEVE=1`; filtro de contaminaciÃ³n de matriz en cÃ³digo.
- Ãndice candidato nuevo: **no creado** (permisos/tiempo); validaciÃ³n con Ã­ndice existente + fuentes locales.

## Rollback

Procedimiento: restaurar `genesis_v2_20260921_102720.tar.gz` + restart solo `genesis-cognitive-8447`. **No ejecutado** (servicio estable).

## Paquete de evidencias

- GuÃ­a FIX MD/HTML: `works/validacion_guia_fix/Guia_Pruebas_Conversacionales_IA_BSC_Resultados_FIX.*`
- ZIP: `works/validacion_guia_fix/VALIDACION_GUIA_BSC_FIX_20260921.zip`
- SHA256 ZIP: `12673B633C0153F4FB1BC3E6865774491012B14D7D23C394FB5D841F453D1132`
- Copia: `C:\Users\zeusa\Downloads\VALIDACION_GUIA_BSC_FIX_20260921.zip`
- Deploy logs: `works/azure_mejora/deploy_vpn_20260921/`
- API run: `works/qa_runs/20260921T105853Z_4f3d3488/`
- UI run: `works/validacion_guia_fix/qa_runs_ui/20260921T103100Z_postdeploy_ui/`

## Estado final

**QA_DESPLEGADO_PARCIAL** â€” capa cognitiva desplegada y validada en alcance declarado; 236 ejecutados; no se declara aceptaciÃ³n completa mientras existan parciales, fallas, bloqueados o PASS sin captura UI del candidato.
