# -*- coding: utf-8 -*-
"""Evalúa perfiles de fragmentación 400/50, 600/80, 800/100 sobre chunks QA (aprox. por palabras*1.3)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "insumos_derivados" / "chunks_qa.jsonl"


def approx_tokens(text: str) -> int:
    words = len((text or "").split())
    return max(1, int(words * 1.3))


def stats_for(chunks: list[dict], target: int, overlap: int) -> dict:
    sizes = [approx_tokens(c.get("content") or "") for c in chunks]
    in_band = sum(1 for s in sizes if (target - 200) <= s <= (target + 200))
    short = sum(1 for s in sizes if s < 400)
    over = sum(1 for s in sizes if s > 800)
    return {
        "profile": f"{target}/{overlap}",
        "n": len(sizes),
        "avg_tokens_approx": round(sum(sizes) / max(len(sizes), 1), 1),
        "pct_near_target_pm200": round(100 * in_band / max(len(sizes), 1), 1),
        "pct_short_lt400": round(100 * short / max(len(sizes), 1), 1),
        "pct_over_gt800": round(100 * over / max(len(sizes), 1), 1),
        "note": "Chunks ya curados; perfiles son referencia de medición, no re-chunk en caliente",
    }


def main() -> None:
    chunks = [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]
    chunks = [c for c in chunks if c.get("qa_eligible") is True]
    rows = [
        stats_for(chunks, 400, 50),
        stats_for(chunks, 600, 80),
        stats_for(chunks, 800, 100),
    ]
    out = ROOT / "eval_chunking_profiles.json"
    out.write_text(json.dumps({"provisional_choice": "600/80", "rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(rows, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
