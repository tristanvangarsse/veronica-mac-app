#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import media_maintenance as mm


def main() -> int:
    project = PROJECT
    script = project / "veronica.py"
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        root = base / "Media"
        state = base / "state"
        root.mkdir()
        state.mkdir()
        con = mm.init_db(state / "media-maintenance.sqlite", root)
        con.close()
        proc = subprocess.run(
            [sys.executable, str(script), "ui-snapshot", "--state-dir", str(state)],
            cwd=str(project), capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        data = json.loads(proc.stdout)
        assert data["version"] == mm.VERSION
        assert data["state_dir"] == str(state.resolve())
        assert data["active_assets"] == 0
        assert data["unresolved_reviews"] == []
        assert data["recent_changes"] == []
        assert data["annual"]["cutoff_exclusive"] == mm.audit.calendar_years_before(mm.dt.date.today(), 2).isoformat()
    print("Veronica UI snapshot: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
