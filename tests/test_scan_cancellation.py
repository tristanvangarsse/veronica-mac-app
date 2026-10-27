#!/usr/bin/env python3
"""Cancel the real Swift model/engine bridge, then rescan without stale locks."""
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="veronica-cancel-scan-") as td:
        base = Path(td).resolve()
        first = base / "First folder"
        second = base / "Second folder"
        first.mkdir()
        second.mkdir()
        (first / "note.txt").write_text("This file must stay unchanged.")
        for index in range(1200):
            (second / f"note-{index:04}.txt").write_text(f"Original text {index}.")
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for folder in (first, second) for p in folder.iterdir()}
        state = base / "Preferences"
        result = subprocess.run([sys.executable, str(ROOT / "veronica.py"), "configure-folders",
                                 "--state-dir", str(state), "--add", str(first), "--add", str(second)],
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr

        app = base / "CancellationCheck.app"
        resources = app / "Contents/Resources"
        executable = app / "Contents/MacOS/CancellationCheck"
        executable.parent.mkdir(parents=True)
        resources.mkdir()
        shutil.copytree(ROOT / "macos/Veronica/Resources/Engine", resources / "Engine")
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": executable.name, "CFBundleIdentifier": "com.tristan.veronica.cancellation-check",
            "CFBundlePackageType": "APPL", "CFBundleName": "CancellationCheck"}))
        harness = base / "Harness.swift"
        harness.write_text('''import AppKit
import Foundation

@main struct CancellationCheck {
    @MainActor static func main() async throws {
        let model = AppModel()
        await model.refresh()
        precondition(model.hasLiveSnapshot && model.snapshot?.scanFolders.count == 2)

        // Cancel before the subprocess has had time to start.
        let early = Task { await model.analyzeLibrary() }
        while !model.isAnalyzing { await Task.yield() }
        model.cancelAnalysis()
        model.cancelAnalysis() // Repeated clicks are harmless.
        precondition(model.isCancellingAnalysis)
        await early.value
        precondition(!model.isAnalyzing && !model.isCancellingAnalysis)
        precondition(model.analysisCancelled && !model.analysisCompleted)
        precondition(model.errorMessage == nil && model.hasLiveSnapshot)

        // Let the first folder finish, then cancel during the second one.
        let scanning = Task { await model.analyzeLibrary() }
        let deadline = Date().addingTimeInterval(40)
        while model.analysisProgress?.folderIndex != 2 {
            precondition(Date() < deadline, "Did not reach the second folder")
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        model.cancelAnalysis()
        await scanning.value
        precondition(model.analysisCancelled && !model.analysisCompleted)
        precondition(!model.isAnalyzing && model.errorMessage == nil)

        // Cancellation must release all workers/locks and leave scanning usable.
        await model.analyzeLibrary()
        precondition(model.analysisCompleted && !model.analysisCancelled)
        precondition(model.snapshot?.latestPlan?.itemCount == 1201)
        precondition(model.errorMessage == nil && !model.isAnalyzing)
        await EngineRunner.shared.endSession()
        print("Swift scan cancellation before launch, during folder 2, and successful rescan: PASS")
    }
}
''')
        sources = ROOT / "macos/Veronica/Sources"
        subprocess.run(["/usr/bin/swiftc", "-D", "DEBUG", "-parse-as-library",
                        *[str(sources / name) for name in ("Models.swift", "Diagnostics.swift", "EngineRunner.swift", "AppModel.swift")],
                        str(harness), "-o", str(executable)], check=True, timeout=120)
        result = subprocess.run([str(executable)], env=dict(os.environ, VERONICA_STATE_DIR=str(state)),
                                text=True, capture_output=True, timeout=150)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())
        assert not list((state / "Sessions.noindex").iterdir())
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                 for folder in (first, second) for p in folder.iterdir()}
        assert before == after, "Cancellation and rescanning must not change any source file"
    print("Scan cancellation leaves all source bytes unchanged and removes temporary state on quit: PASS")


if __name__ == "__main__":
    main()
