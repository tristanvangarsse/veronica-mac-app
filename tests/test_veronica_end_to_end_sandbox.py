#!/usr/bin/env python3

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd, cwd):
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise AssertionError(
            f"command failed with exit code {result.returncode}: {' '.join(map(str, cmd))}"
        )
    return result


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    engine = project / "media_maintenance.py"

    ffmpeg = shutil.which("ffmpeg")
    handbrake = shutil.which("HandBrakeCLI")
    ffprobe = shutil.which("ffprobe")

    if not ffmpeg or not handbrake or not ffprobe:
        print("Veronica end-to-end sandbox: SKIP (ffmpeg, ffprobe, and HandBrakeCLI required)")
        return 0

    with tempfile.TemporaryDirectory(prefix="veronica-e2e-") as td:
        base = Path(td)
        media = base / "media"
        state = base / "state"

        image_dir = media / "Streams" / "Image" / "2023"
        video_dir = media / "Streams" / "Video" / "2023"
        image_dir.mkdir(parents=True)
        video_dir.mkdir(parents=True)
        state.mkdir()

        (state / 'settings.json').write_text(json.dumps({"process_images":False, "filename_date_format":"YYYY-MM-DD_"}))
        image = image_dir / "2023-01-01_test-image.jpg"
        video = video_dir / "2023-01-01_test-video.mov"

        run([
            ffmpeg,
            "-y",
            "-f", "lavfi",
            "-i", "testsrc2=size=2200x1400:rate=1",
            "-frames:v", "1",
            "-q:v", "1",
            str(image),
        ], project)

        run([
            ffmpeg,
            "-y",
            "-f", "lavfi",
            "-i", "testsrc2=size=640x360:rate=30",
            "-t", "2",
            "-c:v", "prores_ks",
            "-profile:v", "3",
            "-metadata", "creation_time=2023-01-01T12:00:00Z",
            str(video),
        ], project)

        run(["touch", "-t", "202301010101", str(image), str(video)], project)

        original_hash = sha256(video)

        plan = run([
            sys.executable,
            str(engine),
            "plan",
            "--root", str(media),
            "--state-dir", str(state),
            "--run-date", "2026-09-22",
        ], project)

        assert "Executable planned: 1" in plan.stdout
        assert "CONVERT_VIDEO" in plan.stdout
        assert "Veronica" in plan.stdout

        plans = sorted(state.glob("plan-*.json"))
        assert len(plans) == 1
        plan_path = plans[0]

        stage = run([
            sys.executable,
            str(engine),
            "stage",
            "--plan", str(plan_path),
            "--state-dir", str(state),
            "--max-images", "0",
            "--max-videos", "1",
            "--max-audio", "0",
        ], project)

        assert "STAGED_VERIFIED" in stage.stdout
        assert sha256(video) == original_hash

        staging_dirs = list((state / "staging").iterdir())
        assert len(staging_dirs) == 1
        staging_id = staging_dirs[0].name

        commit = run([
            sys.executable,
            str(engine),
            "commit-video",
            "--staging-id", staging_id,
            "--state-dir", str(state),
            "--relpath", "Streams/Video/2023/2023-01-01_test-video.mov",
            "--yes",
        ], project)

        assert "COMMITTED:" in commit.stdout

        live_mp4 = video.with_suffix(".mp4")
        assert live_mp4.exists()
        assert not video.exists()

        quarantined = list((state / "quarantine").rglob("2023-01-01_test-video.mov"))
        assert len(quarantined) == 1
        assert sha256(quarantined[0]) == original_hash

        commit_id = quarantined[0].parts[quarantined[0].parts.index("quarantine") + 1]

        rollback = run([
            sys.executable,
            str(engine),
            "rollback",
            "--commit-id", commit_id,
            "--state-dir", str(state),
            "--yes",
        ], project)

        assert "ROLLED_BACK:" in rollback.stdout
        assert video.exists()
        assert sha256(video) == original_hash
        assert not live_mp4.exists()

        displaced = list((state / "rollback-displaced").rglob("2023-01-01_test-video.mp4"))
        assert len(displaced) == 1

        print("Veronica end-to-end sandbox: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
