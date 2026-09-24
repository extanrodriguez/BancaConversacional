# CAS / revisión de sesión — Etapa 1C (documentación, sin aplicar en callers HTTP)

## Bloqueo HTTP end-to-end (explícito)

La API de store (`ReactiveSessionStore.put_session` / `RedisSessionStore.put_session`)
soporta CAS con `expected_revision`. **El endpoint `POST /inspect` sigue escribiendo
sin `expected_revision`**: la concurrencia de `/inspect` **no** se declara protegida.

No se modifica `contract_inspector_app.py` en esta etapa (restricción vigente).

## Callers concretos que necesitan `expected_revision`

Todos los `store.put_session(conv_id, session_state)` (o equivalente) en el flujo
HTTP de inspect / turnos, hoy sin CAS. Ubicaciones en
`src/genesis_cognitive/demo/contract_inspector_app.py` (no editar ahora):

| Zona aproximada | Contexto |
|---|---|
| ~365, ~375 | Semilla / bind de sesión al entrar |
| ~483 | Persistencia tras turno |
| ~710, ~833, ~946 | Ramas de respuesta / knowledge |
| ~1257, ~1284, ~1481 | Continuidad / pending / focus |
| ~1686, ~1732, ~1819, ~1857, ~1965 | Más ramas de turno |
| ~3254, ~3353 | Cierre / utilidades de sesión |

Cambio mínimo del caller (cuando se autorice tocar el inspector):

```python
# Al leer:
session = store.get_session(conv_id)
base_rev = int(getattr(session, "revision", 0) or 0)
# ... mutar copia / aplicar resultado del turno ...
try:
    store.put_session(conv_id, session, expected_revision=base_rev)
except SessionConflictError:
    # Tratamiento de conflicto (mínimo):
    # 1) Relanzar 409 Conflict al cliente, o
    # 2) Releer sesión fresca, reaplicar el turno de forma idempotente, un reintento.
    raise
```

Escrituras legacy (`expected_revision=None`) deben quedar solo para herramientas
admin / migración, no para el path de turno concurrente.

## Conflicto: tratamiento documentado (sin aplicar)

1. Detectar `SessionConflictError(conversation_id, expected, actual)`.
2. No silenciar: el segundo escritor no debe “ganar” en silencio.
3. Respuesta HTTP preferida: **409** con `expected`/`actual` sanitizados.
4. Opcional: un reintento read-modify-write si el turno es idempotente
   (mismo `conversation_id` + misma pregunta ya aplicada → no duplicar history).

## Referencias mutables compartidas (riesgo pendiente)

`ReactiveSessionStore.get_session` devuelve **la misma instancia** guardada en
`self._sessions[conversation_id]` (ver prueba
`test_cas_mutable_shared_reference_before_revision_check`).

Consecuencias:

- Mutar `session.history`, `pending_action`, etc. **altera el store en memoria
  antes** de `put_session(..., expected_revision=...)`.
- Dos hilos que hacen `get_session` comparten el objeto: el CAS por revisión
  no basta si ambos mutan in-place el mismo `SessionState`.
- `_sync_freshness_locked` también escribe campos en el objeto al leer.

Mitigación mínima futura (no aplicada):

- Devolver `copy.deepcopy(session)` (o copia de campos mutables) en `get_session`,
  **o**
- Exigir que callers clonen antes de mutar y pasen el clon a `put_session`.

Redis WATCH protege réplicas al persistir JSON, pero el bug de ref compartida
es del store in-memory usado por `/inspect` local.

## Qué sí está validado en pruebas locales

- `put_session(..., expected_revision=N)` lanza `SessionConflictError` si no coincide.
- Dos escritores concurrentes con la misma revisión esperada → uno gana, uno falla.
- Escritura legacy sin `expected_revision` sigue sobrescribiendo (compat inspector).

## Qué no se declara

- **No** se declara protegida la concurrencia de `/inspect`.
- **No** se declara CAS end-to-end HTTP hasta cablear `expected_revision` en el caller.
