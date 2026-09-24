# Redis QA wire — ruta Entra (Access Keys deshabilitadas)

Actualización 2026-09-18: el recurso tiene **Access Keys Authentication = Deshabilitado**.
La integración vigente es Microsoft Entra + identidad administrada.

Re-verificación plan «Cablear Redis Azure en QA :8447» (**2026-09-19**):
backup `.env.bak.redis.plan.20260919_085524`, restart servicio, `/health` ok,
`/ready/redis` ok (session+lock ping), probe CAS+lock ok, 2 turnos misma conversación ok.
Detalle: [`REDIS_QA_AZURE_8447.md`](REDIS_QA_AZURE_8447.md).

Ver **[`CONEXION_REDIS_QA_ENTRA.md`](CONEXION_REDIS_QA_ENTRA.md)** y `deploy/corp-8447/redis_qa.env.example`.

## Estado

| Capa | Estado |
|---|---|
| Código (fábrica común sesiones+candados) | Listo en checkout |
| Pruebas unitarias Entra/fail-closed | Passed |
| Cableado remoto VM + data-plane | **Hecho 2026-09-18**; **re-verificado 2026-09-19** — ver `RESULTADOS_REDIS_QA_VM.md` |
| `/ready/redis` ambos backends Redis + Entra | **OK** (2026-09-19) |
| `redis_entra_ops_probe.py --cas --lock` | **OK** (2026-09-19) |
| Concurrencia HTTP 2 procesos | **OK** (A VALID_CONTRACT / B NON_OPERATIONAL) |
| Docker local en esta PC | Engine inactivo — no valida Redis real aquí |

## Ya listo (histórico de red)

- SSH / host QA `vm-test002-genesis`
- TCP al Redis por Private Endpoint: OK (corridas previas)
- Script legado de keys: `deploy/corp-8447/configure_redis_qa_8447.py` — **no usar** mientras keys estén off

## Desbloqueo remoto

1. Identidad system-assigned de la VM → usuario Entra en `bsc-cognitive-redis-qa`
2. Merge de `redis_qa.env.example` en `.env` del servicio
3. `systemctl restart genesis-cognitive-8447`
4. `curl -sS http://127.0.0.1:8447/ready/redis` y `scripts/redis_entra_ops_probe.py --cas --lock`
