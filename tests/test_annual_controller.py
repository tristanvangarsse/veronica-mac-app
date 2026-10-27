#!/usr/bin/env python3
import subprocess
import sys
import tempfile
from pathlib import Path


def run_case(script: Path, project: Path, base: Path, run_date: str, expected_cutoff: str) -> None:
    root = base / f"root-{run_date}"
    state = base / f"state-{run_date}"
    root.mkdir()
    state.mkdir()
    proc = subprocess.run(
        [sys.executable, str(script), "annual", "--root", str(root), "--state-dir", str(state),
         "--run-date", run_date, "--yes"],
        cwd=str(project), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"Cutoff: files before {expected_cutoff}" in proc.stdout
    assert "Annual maintenance COMPLETE" in proc.stdout
    reports = list(state.glob(f"annual-{run_date}-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "Status: **COMPLETE**" in text
    assert "Review items: **0**" in text


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    script = project / "media_maintenance.py"
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # The manual age rule advances with the run date, including on leap years.
        run_case(script, project, base, "2026-09-22", "2024-09-22")
        run_case(script, project, base, "2027-01-02", "2025-01-02")
        run_case(script, project, base, "2027-02-05", "2025-02-05")
    print("annual controller two-year-cutoff integration: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
