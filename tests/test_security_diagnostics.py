#!/usr/bin/env python3
"""Compile the real Swift diagnostics and verify free-form secrets stay private."""
import subprocess
from pathlib import Path
import tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='veronica-diagnostics-security-') as td:
    base=Path(td);main=base/'main.swift';binary=base/'check'
    main.write_text(r'''
import Foundation
let secret = "private-medical-record.jpg"
let data = try JSONSerialization.data(withJSONObject: ["event": secret, "error": secret, "relpath": secret, "status": secret])
let event = try JSONDecoder().decode(EngineEvent.self, from: data)
let report = DiagnosticsCenter.shared.privacySafeReport(snapshot: nil, errorMessage: "/Volumes/Private/" + secret, events: [event])
assert(!report.contains(secret))
assert(!report.contains("/Volumes/Private"))
let logs = DiagnosticsCenter.shared.sanitizedRecentLog(snapshot: nil)
assert(!logs.contains(secret))
print("Diagnostic export filename and free-form redaction: PASS")
''')
    subprocess.run(['/usr/bin/swiftc',str(ROOT/'macos/Veronica/Sources/Models.swift'),str(ROOT/'macos/Veronica/Sources/Diagnostics.swift'),str(main),'-o',str(binary)],check=True,timeout=90)
    subprocess.run([str(binary)],check=True,timeout=10)
