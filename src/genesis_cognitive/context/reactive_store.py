"""ReactiveSessionStore — in-memory Redis-simulated store with TTL.

Replaces scattered global dicts (_sessions, _pending_actions, _last_resolved,
CustomerContextStore) with a unified, thread-safe, TTL-aware store.

Keys simulate Redis patterns:
  session:{conversation_id}  → SessionState (history, pending, last_resolved)
  customer:{customer_id}:snapshot → CustomerContextSnapshot + metadata

Thread-safe via threading.Lock per logical partition.
Stateless per request: worker reads/writes store, responds, exits.
"""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from genesis_cognitive.context.customer_context_snapshot import CustomerContextSnapshot


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PendingAction:
    """Stored pending action from a CLARIFICATION turn."""

    intent_id: str
    capability_candidate: str | None
    selected_route: str
    detected_entities: dict[str, str | None]
    missing_requirements: list[str]
    suggested_question: str
    # Pregunta de campo del turno previo (ej. "fecha de corte") para T2
    original_question: str = ""
    # Semántica estructurada que no depende del texto visible de la card.
    query_spec: dict[str, str] = field(default_factory=dict)


@dataclass
class LastResolved:
    """Tracks the last successfully resolved product for follow-up turns."""

    intent_id: str
    account_ref: str
    original_question: str


@dataclass
class ProductFocus:
    """Último producto personal consultado; sobrevive turnos de FAQ/RAG."""

    kind: str
    product_id: str
    intent_id: str
    original_question: str = ""
    updated_at: float = field(default_factory=time.time)


@dataclass
class SessionState:
    """Full session state for a conversation_id.

    El snapshot de contexto vive CON la sesión: al expirar/cerrar la sesión
    el contexto deja de ser válido. No depende de un TTL corto independiente.
    """

    customer_id: str
    history: list[dict[str, Any]] = field(default_factory=list)
    pending_action: PendingAction | None = None
    last_resolved: LastResolved | None = None
    product_focus: ProductFocus | None = None
    last_knowledge_topic: str | None = None
    snapshot: CustomerContextSnapshot | None = None
    updated_at: float = field(default_factory=time.time)
    # Compat: estados antiguos sin estos campos → defaults al deserializar
    # schema_version 2: pending_tasks + compare_set (V3.1)
    schema_version: int = 2
    revision: int = 0
    snapshot_source_fetched_at: float | None = None
    # V3.1 — pendientes multi-tarea y comparación de catálogo ordenada
    pending_tasks: list[dict[str, Any]] = field(default_factory=list)
    compare_set: list[str] = field(default_factory=list)
    process_focus: str | None = None
    # Mapeo autorizado de prueba catálogo→producto personal (V3-13)
    catalog_personal_map: dict[str, str] = field(default_factory=dict)

    @property
    def turn_number(self) -> int:
        return len(self.history) + 1


def copy_session(session: SessionState) -> SessionState:
    """Copia profunda: mutar el resultado no altera el estado almacenado."""
    return copy.deepcopy(session)


class SessionConflictError(Exception):
    """Conflicto CAS al persistir sesión (revisión esperada no coincide)."""

    def __init__(self, conversation_id: str, expected: int, actual: int) -> None:
        self.conversation_id = conversation_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"session conflict {conversation_id}: expected_revision={expected} actual={actual}"
        )


@dataclass
class SnapshotEntry:
    """Cached customer snapshot (legacy/global). Prefer SessionState.snapshot.

    source_fetched_at: momento de obtención bancaria (Core). None = desconocido
    (estados antiguos sin fecha de origen; NO tratar como recién consultado).
    loaded_at: metadato de persistencia local; no implica frescura del dato.
    """

    snapshot: CustomerContextSnapshot
    loaded_at: float = field(default_factory=time.time)
    source_fetched_at: float | None = None
    version: str = "v1"
    # conversation_id que "posee" este snapshot (opcional)
    bound_conversation_id: str | None = None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class ReactiveSessionStore:
    """Unified in-memory store simulating Redis key patterns with TTL.

    Thread-safe. Supports concurrent access from async workers via locks.

    Política de contexto:
    - El snapshot útil vive en SessionState.snapshot (atado a conversation_id).
    - La sesión tiene TTL (actividad); al expirar, muere el contexto.
    - El caché global customer:*:snapshot es respaldo sin expiración propia
      mientras exista sesión activa; se limpia al borrar sesión si aplica.
    - Guardar mensajes NO renueva source_fetched_at (frescura bancaria).
    """

    def __init__(
        self,
        session_ttl_s: float = 1800.0,  # 30 minutes de inactividad
        snapshot_ttl_s: float | None = None,  # ignorado: contexto = vida de sesión
    ) -> None:
        self._session_ttl = session_ttl_s
        # Compat: si env fuerza TTL legacy, se respeta; por defecto None = sin TTL propio
        import os

        env_snap = os.getenv("GENESIS_SNAPSHOT_TTL_S", "").strip()
        if snapshot_ttl_s is not None:
            self._snapshot_ttl = float(snapshot_ttl_s)
        elif env_snap and env_snap not in ("0", "none", "None", "session"):
            self._snapshot_ttl = float(env_snap)
        else:
            self._snapshot_ttl = None  # atado a sesión

        self._sessions: dict[str, SessionState] = {}
        self._snapshots: dict[str, SnapshotEntry] = {}

        self._session_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()

    # ----- Session operations -----

    def get_session(self, conversation_id: str) -> SessionState | None:
        """Get session by conversation_id. Returns None if expired or missing."""
        with self._session_lock:
            entry = self._sessions.get(conversation_id)
            if entry is None:
                return None
            # Check TTL
            if (time.time() - entry.updated_at) > self._session_ttl:
                del self._sessions[conversation_id]
                return None
            self._sync_freshness_locked(entry)
            return copy_session(entry)

    def _sync_freshness_locked(self, session: SessionState) -> None:
        """Alinea snapshot_source_fetched_at desde el respaldo global (sin inventar)."""
        if not session.customer_id:
            return
        snap_entry = self._snapshots.get(session.customer_id)
        if snap_entry is None:
            return
        session.snapshot_source_fetched_at = snap_entry.source_fetched_at

    def put_session(
        self,
        conversation_id: str,
        session: SessionState,
        *,
        expected_revision: int | None = None,
    ) -> int:
        """Store/update session con CAS opcional por revisión.

        Si expected_revision es None (callers legacy), escribe y incrementa
        revisión sin fallar — compatible con contratos externos antiguos.
        Con expected_revision, exige coincidencia o lanza SessionConflictError.
        Persiste una copia: el caller no comparte referencia mutable con el store.
        Returns: nueva revisión persistida.
        """
        with self._session_lock:
            current = self._sessions.get(conversation_id)
            actual_rev = int(getattr(current, "revision", 0) or 0) if current else 0
            if expected_revision is not None and actual_rev != int(expected_revision):
                raise SessionConflictError(conversation_id, int(expected_revision), actual_rev)
            new_rev = actual_rev + 1
            stored = copy_session(session)
            stored.revision = new_rev
            stored.schema_version = max(1, int(getattr(stored, "schema_version", 1) or 1))
            stored.updated_at = time.time()
            self._sessions[conversation_id] = stored
            session.revision = new_rev
            session.schema_version = stored.schema_version
            session.updated_at = stored.updated_at
        # Mantener caché global alineado sin resetear source_fetched_at
        if session.snapshot is not None and session.customer_id:
            self.put_snapshot(
                session.customer_id,
                session.snapshot,
                bound_conversation_id=conversation_id,
                preserve_source_fetched_at=True,
            )
            with self._snapshot_lock:
                snap_entry = self._snapshots.get(session.customer_id)
                if snap_entry is not None:
                    session.snapshot_source_fetched_at = snap_entry.source_fetched_at
                    stored_sess = self._sessions.get(conversation_id)
                    if stored_sess is not None:
                        stored_sess.snapshot_source_fetched_at = snap_entry.source_fetched_at
        return new_rev

    def create_session(self, conversation_id: str, customer_id: str) -> SessionState:
        """Create a new session (CAS: solo si no existe; expected_revision=0)."""
        session = SessionState(customer_id=customer_id)
        self.put_session(conversation_id, session, expected_revision=0)
        return copy_session(self._sessions[conversation_id])

    def delete_session(self, conversation_id: str) -> None:
        """Remove session (cierre de sesión → contexto inválido)."""
        customer_id = None
        with self._session_lock:
            entry = self._sessions.pop(conversation_id, None)
            if entry is not None:
                customer_id = entry.customer_id
        if customer_id:
            with self._snapshot_lock:
                snap = self._snapshots.get(customer_id)
                if snap is not None and snap.bound_conversation_id == conversation_id:
                    del self._snapshots[customer_id]

    # ----- Snapshot operations -----

    def get_snapshot(self, customer_id: str) -> CustomerContextSnapshot | None:
        """Get customer snapshot. Sin TTL propio si está atado a sesión."""
        key = customer_id
        with self._snapshot_lock:
            entry = self._snapshots.get(key)
            if entry is None:
                return None
            age = self._age_from_entry(entry)
            if age is None and self._snapshot_ttl is not None and entry.source_fetched_at is not None:
                del self._snapshots[key]
                return None
            if self._snapshot_ttl is not None and age is not None and age > self._snapshot_ttl:
                del self._snapshots[key]
                return None
            return entry.snapshot

    def get_snapshot_age(self, customer_id: str) -> float | None:
        """Edad del dato bancario en segundos. None si ausente, desconocida o vencida.

        Limitación: sin mecanismo autorizado de refresh al Core en esta capa;
        una edad alta indica dato potencialmente vencido, no se afirma actualidad.
        """
        with self._snapshot_lock:
            entry = self._snapshots.get(customer_id)
            if entry is None:
                return None
            age = self._age_from_entry(entry)
            if age is None:
                return None
            if self._snapshot_ttl is not None and age > self._snapshot_ttl:
                return None
            return age

    def _age_from_entry(self, entry: SnapshotEntry) -> float | None:
        # Solo source_fetched_at cuenta como origen bancario.
        # Estados antiguos sin esa marca → desconocido (no "recién consultado").
        if entry.source_fetched_at is None:
            return None
        return time.time() - float(entry.source_fetched_at)

    def put_snapshot(
        self,
        customer_id: str,
        snapshot: CustomerContextSnapshot,
        *,
        bound_conversation_id: str | None = None,
        source_fetched_at: float | None = None,
        preserve_source_fetched_at: bool = False,
        mark_fetched_now: bool = False,
    ) -> None:
        """Store customer snapshot.

        - mark_fetched_now / source_fetched_at: nueva lectura bancaria autorizada.
        - preserve_source_fetched_at: re-guardar por actividad de sesión sin refresh.
        - Si no hay fecha previa y no se marca fetch → source_fetched_at queda None
          (desconocida), nunca se inventa "ahora".
        """
        with self._snapshot_lock:
            previous = self._snapshots.get(customer_id)
            fetched: float | None
            if mark_fetched_now:
                fetched = time.time()
            elif source_fetched_at is not None:
                fetched = float(source_fetched_at)
            elif preserve_source_fetched_at and previous is not None:
                fetched = previous.source_fetched_at
            else:
                # Compat: primera escritura explícita sin preserve se trata como fetch
                # solo si el caller no pidió preserve (p. ej. carga inicial de Core).
                fetched = time.time() if not preserve_source_fetched_at else (
                    previous.source_fetched_at if previous is not None else None
                )
            self._snapshots[customer_id] = SnapshotEntry(
                snapshot=snapshot,
                loaded_at=time.time(),
                source_fetched_at=fetched,
                bound_conversation_id=bound_conversation_id
                if bound_conversation_id is not None
                else (previous.bound_conversation_id if previous else None),
            )

    # ----- Diagnostics -----

    def session_count(self) -> int:
        with self._session_lock:
            return len(self._sessions)

    def snapshot_count(self) -> int:
        with self._snapshot_lock:
            return len(self._snapshots)

    def session_keys(self) -> list[str]:
        with self._session_lock:
            return list(self._sessions.keys())
