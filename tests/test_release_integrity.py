#!/usr/bin/env python3
"""Production release gates remain active even under optimized Python."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='veronica-release-integrity-') as td:
    base=Path(td);internal=base/'_internal';internal.mkdir();engine=base/'fake-engine'
    engine.write_text('#!/bin/sh\nexit 0\n');engine.chmod(0o700)
    (internal/'security-manifest.json').write_text(json.dumps({'version':'0.0.0','sources':{}}))
    result=subprocess.run([sys.executable,'-O',str(ROOT/'scripts/release_manifest.py'),'--check',str(engine)],capture_output=True,text=True,timeout=10)
    assert result.returncode!=0
    assert 'Frozen engine version is stale' in result.stderr,result.stderr
    # A preset next to the executable used to pass packaging while the frozen
    # coordinator looked for it under _internal. Require the actual runtime path.
    sys.path.insert(0,str(ROOT/'scripts'))
    import release_manifest as release
    (internal/'security-manifest.json').write_text(json.dumps({'version':release.version(),
        'sources':{name:release.sha(ROOT/name) for name in release.SOURCES}}))
    (base/'preset-720P.json').write_bytes((ROOT/'preset-720P.json').read_bytes())
    result=subprocess.run([sys.executable,str(ROOT/'scripts/release_manifest.py'),'--check',str(engine)],capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and 'Frozen video preset is missing' in result.stderr,result.stderr
    (internal/'preset-720P.json').write_bytes((ROOT/'preset-720P.json').read_bytes())
    result=subprocess.run([sys.executable,str(ROOT/'scripts/release_manifest.py'),'--check',str(engine)],capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and 'Bundled date editor is missing' in result.stderr,result.stderr
print('Release integrity gate cannot be disabled by Python optimization: PASS')
print('Release gate rejects a video preset outside the frozen runtime data directory: PASS')
