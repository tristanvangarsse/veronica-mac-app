#!/usr/bin/env python3
"""Execute script-style regressions, including ones pytest cannot collect."""
from pathlib import Path
import os
import argparse
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
os.environ.pop('PYTHONOPTIMIZE',None)
parser=argparse.ArgumentParser()
parser.add_argument("--source-only",action="store_true",help="Leave frozen-engine checks to the release build")
args=parser.parse_args()
failed = []
for test in sorted((root / 'tests').glob('test_*.py')):
    if args.source_only and test.name in {"test_frozen_engine_security.py", "test_packaged_folder_recipes.py", "test_clean_install.py"}:
        print(test.name+": deferred to release validation",flush=True)
        continue
    result = subprocess.run([sys.executable, str(test)], cwd=root,
                            env=dict(os.environ, PYTHONPATH=str(root), PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin")), timeout=240)
    print(f'{test.name}: {"PASS" if result.returncode == 0 else "FAIL"}', flush=True)
    if result.returncode:
        failed.append(test.name)
if failed:
    raise SystemExit('Failed: ' + ', '.join(failed))
print('All source regression scripts passed; frozen engine deferred' if args.source_only else 'All regression scripts passed')
