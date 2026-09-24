# Especificación — RedisSessionStore

Documento técnico de referencia para la implementación en Fase 1.

## Interfaz (idéntica a ReactiveSessionStore)

```python
class SessionStoreProtocol(Protocol):
    def get_session(self, conversation_id: str) -> SessionState | None: ...
    def put_session(self, conversation_id: str, session: SessionState) -> None: ...
    def create_session(self, conversation_id: str, customer_id: str) -> SessionState: ...
    def delete_session(self, conversation_id: str) -> None: ...
    def get_snapshot(self, customer_id: str) -> CustomerContextSnapshot | None: ...
    def get_snapshot_age(self, customer_id: str) -> float | None: ...
    def put_snapshot(self, customer_id: str, snapshot: CustomerContextSnapshot) -> None: ...
```

## Esquema JSON — SessionState

```json
{
  "customer_id": "TEST-QA-001",
  "history": [{"role": "user", "content": "Hola"}],
  "pending_action": null,
  "last_resolved": {
    "intent_id": "balance_inquiry",
    "account_ref": "11042010152142",
    "original_question": "saldo"
  },
  "updated_at": 1710000000.0
}
```

## Esquema JSON — SnapshotEntry

```json
{
  "snapshot": { "... CustomerContextSnapshot fields ..." },
  "loaded_at": 1710000000.0,
  "version": "v1"
}
```

## Claves Redis

| Key | TTL | Contenido |
|-----|-----|-----------|
| `session:{conversation_id}` | `GENESIS_SESSION_TTL_S` | SessionState JSON |
| `customer:{customer_id}:snapshot` | `GENESIS_SNAPSHOT_TTL_S` | SnapshotEntry JSON |

## Serialización CustomerContextSnapshot

Opción A (recomendada): añadir métodos en el dataclass:

```python
def to_json_dict(self) -> dict: ...
@classmethod
def from_json_dict(cls, data: dict) -> CustomerContextSnapshot: ...
```

Opción B: wrapper en RedisSessionStore con mapeo manual de campos Decimal → string.

## Configuración cliente Redis

```python
import redis

client = redis.from_url(
    os.environ["GENESIS_REDIS_URL"],
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    retry_on_timeout=True,
    health_check_interval=30,
)
```

## Health check en /health

Extender endpoint existente:

```python
redis_ok = store.ping() if hasattr(store, "ping") else True
return {"status": "ok", "redis": redis_ok}
```

## Test de sesión compartida (manual)

```powershell
# Réplica 1
$body = '{"customer_id":"TEST-QA-001","conversation_id":"shared-1","message":"Hola"}' 
Invoke-RestMethod -Uri http://127.0.0.1:8445/turn -Method POST -Body $body -ContentType application/json

# Réplica 2 (misma conversation_id)
$body2 = '{"customer_id":"TEST-QA-001","conversation_id":"shared-1","message":"¿Cuál es mi saldo?"}'
Invoke-RestMethod -Uri http://127.0.0.1:8448/turn -Method POST -Body $body2 -ContentType application/json
# Debe reconocer historial / last_resolved
```

## fakeredis para CI

```python
import fakeredis
store = RedisSessionStore(client=fakeredis.FakeRedis(decode_responses=True))
```
