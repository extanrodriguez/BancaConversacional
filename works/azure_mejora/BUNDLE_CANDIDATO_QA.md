# Bundle candidato QA — preparación

## Artefacto local

- Entrypoint: `scripts/run_contract_inspector.py`
- Código: `src/genesis_cognitive/**`
- Nuevo: `src/genesis_cognitive/rag/azure_search_retrieve.py`
- Flags runtime QA propuestas (sin secretos):

```
GENESIS_SEMANTIC_MODE=azure_plan
GENESIS_AZURE_BRAIN=1
GENESIS_SEARCH_RETRIEVE=1
AZURE_SEARCH_INDEX=bsc-kb-conocimiento
GENESIS_SESSION_BACKEND=redis   # en VM con Entra; en PC local: memory
```

## Deploy / rollback

Usar el mecanismo existente del repo (`deploy/corp-8447/` / scripts SSH ya empleados). **No inventar** nombres de servicio.

1. Respaldar build previo en VM.
2. Copiar solo capa cognitiva (no `BSC.genesis.conversational.backend`).
3. Reiniciar únicamente el servicio cognitivo autorizado.
4. Confirmar `/health`, hash de código, `POST /turn` smoke.
5. Rollback: restaurar tarball/directorio previo + restart.

## Exclusiones del bundle

- `.env`, API keys, snapshots con PII real
- Cambios a backend .NET / frontend / WebSocket

## Evidencia a empaquetar

- `ESTADO_ACTIVACION_HOY.md`
- `DEPENDENCIAS_REAL_VS_LOCAL.json`
- `BRECHAS_PENDIENTES.md`
- `probe_reconcile_20260921/`
- `suite_representativa_20260921/`
- `search_smoke_queries.json`
- Resultados 141/95 cuando existan JSONL completos
