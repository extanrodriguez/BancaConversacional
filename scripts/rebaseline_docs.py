"""Rebaseline: generate requirements.md, design.md, tasks.md, and report."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SPECS = ROOT / ".kiro" / "specs" / "cognitive-turn-routing-mvp"
EVIDENCE = ROOT / "evidence"


def write_requirements() -> None:
    path = SPECS / "requirements.md"
    path.write_text(
        (ROOT / "scripts" / "rebaseline_requirements.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"OK: {path}")


def write_design() -> None:
    path = SPECS / "design.md"
    path.write_text(
        (ROOT / "scripts" / "rebaseline_design.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"OK: {path}")


def write_tasks() -> None:
    path = SPECS / "tasks.md"
    path.write_text(
        (ROOT / "scripts" / "rebaseline_tasks.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"OK: {path}")


def write_report() -> None:
    path = EVIDENCE / "agentic-rag-architecture-rebaseline-report.md"
    path.write_text(
        (ROOT / "scripts" / "rebaseline_report.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"OK: {path}")


if __name__ == "__main__":
    write_requirements()
    write_design()
    write_tasks()
    write_report()
