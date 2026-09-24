"""Reevaluación estricta de corridas históricas (no modifica archivos originales)."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from potenciacion_eval import ORACLE_VERSION, evaluate_case  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "works" / "qa_runs"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def reevaluate_run(run_id: str) -> Path:
    src = RUNS / run_id
    if not src.is_dir():
        raise FileNotFoundError(run_id)
    out = RUNS / f"reeval_{ORACLE_VERSION}_{run_id}"
    out.mkdir(parents=True, exist_ok=True)

    by_turns: dict[str, list[dict]] = {}
    turns_path = src / "turnos.jsonl"
    if turns_path.exists():
        for line in turns_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            t = json.loads(line)
            by_turns.setdefault(str(t.get("case_id")), []).append(t)

    results_path = src / "resultados_casos.jsonl"
    counts: Counter[str] = Counter()
    rows_out = []
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        old = json.loads(line)
        cid = str(old.get("case_id"))
        turns = by_turns.get(cid) or [{
            "question": old.get("expected") and "",
            "reply": old.get("obtained") or "",
        }]
        # Prefer stored question/reply from turnos
        eval_turns = []
        for t in turns:
            eval_turns.append({
                "question": t.get("question") or "",
                "reply": t.get("reply") or t.get("text") or "",
                "turn": t.get("turn"),
                "audit": {
                    "field_accreditation": t.get("field_accreditation"),
                    "payment_window": t.get("payment_window"),
                    "provider": t.get("provider"),
                    "route": t.get("route"),
                    "context_source": t.get("context_source") or t.get("data_origin"),
                    "field_path": (t.get("field_accreditation") or {}).get("field_path")
                    if isinstance(t.get("field_accreditation"), dict) else t.get("field_path"),
                    "payoff_accredited": (
                        (t.get("field_accreditation") or {}).get("payoff_accredited")
                        if isinstance(t.get("field_accreditation"), dict)
                        else t.get("payoff_accredited")
                    ),
                    "field_origin": t.get("field_origin") or t.get("context_source"),
                    "source_fetched_at": t.get("source_fetched_at"),
                },
            })
        if not any(t.get("reply") for t in eval_turns) and old.get("obtained"):
            eval_turns = [{"question": "", "reply": old.get("obtained") or ""}]
        status, detail = evaluate_case(
            cid,
            str(eval_turns[0].get("question") or ""),
            "\n".join(t.get("reply") or "" for t in eval_turns),
            turns=eval_turns,
        )
        counts[status] += 1
        rows_out.append({
            "source_run_id": run_id,
            "case_id": cid,
            "previous_status": old.get("status"),
            "previous_oracle": old.get("oracle_version"),
            "status": status,
            "assertions": detail,
            "changed": old.get("status") != status,
        })

    (out / "reeval_resultados.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows_out) + "\n",
        encoding="utf-8",
    )
    flips = [r for r in rows_out if r["changed"]]
    summary = {
        "reeval_id": out.name,
        "source_run_id": run_id,
        "oracle_version": ORACLE_VERSION,
        "generated_utc": utc_now(),
        "counts": dict(counts),
        "flipped": len(flips),
        "note": "Histórico original intacto; esta carpeta es reevaluación separada.",
        "false_positive_examples": [
            r for r in flips
            if str(r["previous_status"]).startswith("PASS") and not str(r["status"]).startswith("PASS")
        ][:30],
    }
    (out / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# Reevaluación `{out.name}`",
        "",
        f"- Fuente: `{run_id}` (intacta)",
        f"- Oracle: `{ORACLE_VERSION}`",
        f"- Conteos: `{json.dumps(dict(counts), ensure_ascii=False)}`",
        f"- Cambios de veredicto: {len(flips)}",
        "",
        "## Flips PASS→no-PASS (muestra)",
        "",
    ]
    for r in summary["false_positive_examples"][:20]:
        md.append(f"- `{r['case_id']}`: {r['previous_status']} → {r['status']}")
    (out / "resumen.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def main() -> int:
    targets = sys.argv[1:] or [
        "20260920T024920Z_d0453ded",
        "20260920T030922Z_3dee5fcc",
        "20260920T051148Z_00716214",
        "20260920T051355Z_30349d81",
    ]
    idx = RUNS / "INDEX.md"
    for run_id in targets:
        try:
            out = reevaluate_run(run_id)
        except FileNotFoundError:
            print("SKIP missing", run_id)
            continue
        print("REEVAL", out.name)
        with idx.open("a", encoding="utf-8") as f:
            man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            f.write(
                f"| {man['generated_utc']} | `{out.name}` | reeval:{ORACLE_VERSION} | source={run_id} | "
                f"flips={man['flipped']} counts={man['counts']} | [resumen]({out.name}/resumen.md) |\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
