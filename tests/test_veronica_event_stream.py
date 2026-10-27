#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    script = project / "media_maintenance.py"
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        root = base / "Media"
        state = base / "state"
        events = base / "events.jsonl"
        root.mkdir()
        state.mkdir()
        proc = subprocess.run(
            [sys.executable, str(script), "annual", "--root", str(root), "--state-dir", str(state),
             "--run-date", "2027-01-03", "--events-jsonl", str(events), "--yes"],
            cwd=str(project), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines() if line.strip()]
        names = [row["event"] for row in rows]
        assert names[0] == "annual_started"
        assert "annual_cutoff" in names
        assert "plan_complete" in names
        assert names[-1] == "annual_complete"
        cutoff = next(row for row in rows if row["event"] == "annual_cutoff")
        assert cutoff["cutoff"] == "2025-01-03"
        complete = rows[-1]
        assert Path(complete["report"]).exists()

    print("Veronica JSON event stream: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
