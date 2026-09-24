#!/usr/bin/env python3
"""Promueve expression_candidates del feedback store al overlay FAQ.

Reglas Incremento A:
  - Los votos SOLO priorizan candidatos (no equivalen a aprobación).
  - --apply exige --approved-json con aprobación explícita de la versión exacta
    (faq_id + expression + approved_by + approved_at).
  - Sin --apply: dry-run (lista candidatos ordenados por votos).

Uso:
  .venv/Scripts/python.exe scripts/promote_learning_expressions.py
  .venv/Scripts/python.exe scripts/promote_learning_expressions.py --min-votes 2
  .venv/Scripts/python.exe scripts/promote_learning_expressions.py --apply --approved-json path.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from genesis_cognitive.learning.feedback_store import (  # noqa: E402
    failure_rate,
    mark_expressions_published,
    top_expression_candidates,
)


def _expr_key(faq_id: str, expression: str) -> str:
    raw = f"{faq_id}|{(expression or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _load_approvals(path: Path) -> dict[str, dict]:
    """Formato: {\"approvals\":[{\"faq_id\",\"expression\",\"approved_by\",\"approved_at\"}]}"""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for row in data.get("approvals") or []:
        fid = str(row.get("faq_id") or "").strip()
        expr = str(row.get("expression") or "").strip()
        by = str(row.get("approved_by") or "").strip()
        at = str(row.get("approved_at") or "").strip()
        if not (fid and expr and by and at):
            continue
        out[_expr_key(fid, expr)] = {
            "faq_id": fid,
            "expression": expr,
            "approved_by": by,
            "approved_at": at,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-votes", type=int, default=2)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Escribe en overlay SOLO expresiones con aprobación explícita",
    )
    ap.add_argument(
        "--approved-json",
        type=str,
        default="",
        help="JSON de aprobaciones (obligatorio con --apply)",
    )
    ap.add_argument(
        "--overlay",
        type=str,
        default=str(ROOT / "data" / "kb_faq_overlay_fase1.json"),
    )
    args = ap.parse_args()

    stats = failure_rate()
    print(
        f"Feedback DB: total={stats['total']} failed={stats['failed']} "
        f"fail_rate={stats['fail_rate']:.2%}"
    )
    cands = top_expression_candidates(min_votes=args.min_votes)
    print(f"Candidatos prioritarios (>= {args.min_votes} votos): {len(cands)}")
    for c in cands[:30]:
        print(
            f"  - {c['faq_id']}: {c['expression'][:80]!r} "
            f"(votes={c['votes']} approval={c.get('approval_status') or 'none'})"
        )

    if not args.apply:
        print("Dry-run: sin --apply no se escribe el overlay.")
        return 0

    if not args.approved_json:
        print(
            "ERROR: --apply requiere --approved-json. "
            "Los votos no autorizan publicación.",
            file=sys.stderr,
        )
        return 2

    approvals = _load_approvals(Path(args.approved_json))
    if not approvals:
        print("ERROR: approved-json sin aprobaciones válidas", file=sys.stderr)
        return 2

    overlay_path = Path(args.overlay)
    data = json.loads(overlay_path.read_text(encoding="utf-8"))
    by_id = {e.get("id"): e for e in data.get("entries") or []}
    added = 0
    skipped_no_approval = 0
    published_rows: list[dict] = []

    for c in cands:
        eid = c["faq_id"]
        expr = (c["expression"] or "").strip()
        if not eid or not expr or not eid.startswith(("vf01-", "fase1-")):
            continue
        key = _expr_key(eid, expr)
        appr = approvals.get(key)
        if not appr:
            skipped_no_approval += 1
            continue
        entry = by_id.get(eid)
        if entry is None:
            entry = {"id": eid, "expressions": []}
            data.setdefault("entries", []).append(entry)
            by_id[eid] = entry
        exprs = list(entry.get("expressions") or [])
        if expr not in exprs:
            exprs.append(expr)
            entry["expressions"] = exprs
            added += 1
            published_rows.append(appr)

    if added:
        overlay_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        mark_expressions_published(published_rows)

    print(
        f"Aplicadas {added} expresiones aprobadas a {overlay_path.name}; "
        f"omitidas sin aprobación: {skipped_no_approval}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
