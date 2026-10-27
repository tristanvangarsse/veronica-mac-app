#!/usr/bin/env python3
"""A dependency update must not ship an older runtime's licence metadata."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='veronica-runtime-notices-') as td:
    output=Path(td)/'notices'
    stale=output/'pillow/sboms/previous-release.cdx.json'
    stale.parent.mkdir(parents=True)
    stale.write_text('{"components": [{"name": "FriBiDi", "version": "0.0.0"}]}')
    for _ in range(2):
        subprocess.run([sys.executable,str(ROOT/'scripts/collect_runtime_notices.py'),str(output)],check=True)
        assert not stale.exists(), 'An earlier runtime SBOM survived the update'
        sboms=list((output/'pillow').rglob('*.cdx.json'))
        assert len(sboms)==1
        metadata=json.loads(sboms[0].read_text())['metadata']['component']
        assert metadata['version']==importlib.metadata.version('pillow')
        assert (output/'Python/LICENSE').stat().st_size>100
        assert any((output/'pyinstaller').rglob('COPYING*')) or any((output/'pyinstaller').rglob('LICENSE*'))
print('Runtime licence collection removes stale SBOMs and preserves current notices on repeated builds: PASS')
