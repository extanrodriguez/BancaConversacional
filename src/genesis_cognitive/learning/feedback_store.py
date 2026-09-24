"""Aprendizaje continuo de intención FAQ (sin reentrenar un LLM completo).

Enfoque elegido para Banca Conversacional:
- Recuperación densa (embeddings Azure) + ranking FAQ/overlay
- Bucle de feedback (pregunta, match, OK/KO, corrección)
- Actualización de expresiones en overlay a partir de fallos

Un fine-tune neuronal grande no encaja bien: datos personales no deben
salir del perímetro, latencia/costo altos, y la KB ya está en Search/Foundry.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    raw = os.getenv("GENESIS_LEARNING_DB", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "data" / "learning" / "intent_feedback.sqlite3"


@dataclass
class FeedbackEvent:
    question: str
    matched_id: str | None
    matched_topic: str | None
    score: float
    ok: bool
    corrected_id: str | None = None
    source: str = "regression"
    meta: dict[str, Any] | None = None


def init_db(path: Path | None = None) -> Path:
    p = path or _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,
              question TEXT NOT NULL,
              matched_id TEXT,
              matched_topic TEXT,
              score REAL,
              ok INTEGER NOT NULL,
              corrected_id TEXT,
              source TEXT,
              meta_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expression_candidates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              faq_id TEXT NOT NULL,
              expression TEXT NOT NULL,
              votes INTEGER NOT NULL DEFAULT 1,
              approval_status TEXT NOT NULL DEFAULT 'none',
              approved_by TEXT,
              approved_at REAL,
              content_hash TEXT,
              last_source TEXT,
              UNIQUE(faq_id, expression)
            )
            """
        )
        # Migración suave de columnas nuevas
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(expression_candidates)").fetchall()
        }
        if "approval_status" not in cols:
            conn.execute(
                "ALTER TABLE expression_candidates ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'none'"
            )
        if "approved_by" not in cols:
            conn.execute("ALTER TABLE expression_candidates ADD COLUMN approved_by TEXT")
        if "approved_at" not in cols:
            conn.execute("ALTER TABLE expression_candidates ADD COLUMN approved_at REAL")
        if "content_hash" not in cols:
            conn.execute("ALTER TABLE expression_candidates ADD COLUMN content_hash TEXT")
        if "last_source" not in cols:
            conn.execute("ALTER TABLE expression_candidates ADD COLUMN last_source TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback_dedup (
              event_key TEXT PRIMARY KEY,
              first_ts REAL NOT NULL,
              last_ts REAL NOT NULL,
              hits INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.commit()
    return p


def _event_key(event: FeedbackEvent) -> str:
    import hashlib

    raw = "|".join(
        [
            (event.source or "").strip(),
            (event.question or "").strip().lower()[:200],
            (event.matched_id or ""),
            (event.corrected_id or ""),
            "1" if event.ok else "0",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_feedback(event: FeedbackEvent, path: Path | None = None) -> dict[str, Any]:
    """Registra feedback con idempotencia débil por event_key.

    Re-ejecutar la misma prueba NO infla votos de expression_candidates.
    Returns: {recorded: bool, duplicate: bool}
    """
    p = init_db(path)
    key = _event_key(event)
    now = time.time()
    with sqlite3.connect(p) as conn:
        row = conn.execute(
            "SELECT hits FROM feedback_dedup WHERE event_key = ?", (key,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE feedback_dedup SET last_ts = ?, hits = hits + 1 WHERE event_key = ?",
                (now, key),
            )
            conn.commit()
            return {"recorded": False, "duplicate": True, "hits": int(row[0]) + 1}

        conn.execute(
            "INSERT INTO feedback_dedup (event_key, first_ts, last_ts, hits) VALUES (?, ?, ?, 1)",
            (key, now, now),
        )
        conn.execute(
            """
            INSERT INTO feedback
              (ts, question, matched_id, matched_topic, score, ok, corrected_id, source, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                event.question,
                event.matched_id,
                event.matched_topic,
                float(event.score),
                1 if event.ok else 0,
                event.corrected_id,
                event.source,
                json.dumps(event.meta or {}, ensure_ascii=False),
            ),
        )
        if event.corrected_id and event.question.strip():
            expr = event.question.strip()[:200]
            import hashlib

            ch = hashlib.sha256(f"{event.corrected_id}|{expr}".encode("utf-8")).hexdigest()[:24]
            # Inserta candidato; ON CONFLICT solo prioriza (votes++), NUNCA aprueba
            conn.execute(
                """
                INSERT INTO expression_candidates
                  (faq_id, expression, votes, approval_status, content_hash, last_source)
                VALUES (?, ?, 1, 'none', ?, ?)
                ON CONFLICT(faq_id, expression) DO UPDATE SET
                  votes = votes + 1,
                  last_source = excluded.last_source,
                  content_hash = excluded.content_hash
                """,
                (event.corrected_id, expr, ch, event.source),
            )
        conn.commit()
    return {"recorded": True, "duplicate": False, "hits": 1}


def approve_expression(
    faq_id: str,
    expression: str,
    *,
    approved_by: str,
    path: Path | None = None,
) -> bool:
    """Marca aprobación explícita de una expresión (versión exacta)."""
    p = init_db(path)
    expr = (expression or "").strip()
    if not (faq_id and expr and approved_by.strip()):
        return False
    with sqlite3.connect(p) as conn:
        cur = conn.execute(
            """
            UPDATE expression_candidates
            SET approval_status = 'approved', approved_by = ?, approved_at = ?
            WHERE faq_id = ? AND expression = ?
            """,
            (approved_by.strip(), time.time(), faq_id, expr),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_expressions_published(rows: list[dict[str, Any]], path: Path | None = None) -> int:
    p = init_db(path)
    n = 0
    with sqlite3.connect(p) as conn:
        for row in rows:
            cur = conn.execute(
                """
                UPDATE expression_candidates
                SET approval_status = 'published'
                WHERE faq_id = ? AND expression = ? AND approval_status = 'approved'
                """,
                (row.get("faq_id"), row.get("expression")),
            )
            n += cur.rowcount
        conn.commit()
    return n


def top_expression_candidates(min_votes: int = 2, limit: int = 50, path: Path | None = None) -> list[dict[str, Any]]:
    """Lista prioritaria por votos. approval_status separado (votes ≠ aprobación)."""
    p = init_db(path)
    with sqlite3.connect(p) as conn:
        rows = conn.execute(
            """
            SELECT faq_id, expression, votes, approval_status, approved_by, approved_at
            FROM expression_candidates
            WHERE votes >= ?
            ORDER BY votes DESC
            LIMIT ?
            """,
            (min_votes, limit),
        ).fetchall()
    return [
        {
            "faq_id": a,
            "expression": b,
            "votes": c,
            "approval_status": d or "none",
            "approved_by": e,
            "approved_at": f,
        }
        for a, b, c, d, e, f in rows
    ]


def failure_rate(path: Path | None = None) -> dict[str, Any]:
    p = init_db(path)
    with sqlite3.connect(p) as conn:
        total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        fails = conn.execute("SELECT COUNT(*) FROM feedback WHERE ok = 0").fetchone()[0]
    return {"total": total, "failed": fails, "fail_rate": (fails / total) if total else 0.0}
