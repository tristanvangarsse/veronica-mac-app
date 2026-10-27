#!/usr/bin/env python3
"""Sign nested Mach-O code from the inside out, then seal the final app."""
import argparse
from pathlib import Path
import subprocess
p=argparse.ArgumentParser();p.add_argument('app');p.add_argument('--identity',default='-');a=p.parse_args()
app=Path(a.app).resolve()
if not app.is_dir() or app.suffix!='.app':raise SystemExit('An existing app bundle is required')
flags=['--force','--sign',a.identity]
flags+=['--timestamp=none'] if a.identity=='-' else ['--options','runtime','--timestamp']
magic={b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'}
for f in sorted((x for x in app.rglob('*') if x.is_file() and not x.is_symlink()),key=lambda x:len(x.parts),reverse=True):
    with f.open('rb') as stream:header=stream.read(4)
    if header in magic:subprocess.run(['/usr/bin/codesign',*flags,str(f)],check=True)
for f in sorted(app.rglob('*.framework'),key=lambda x:len(x.parts),reverse=True):
    if not f.is_symlink():subprocess.run(['/usr/bin/codesign',*flags,str(f)],check=True)
subprocess.run(['/usr/bin/codesign',*flags,str(app)],check=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict','--verbose=2',str(app)],check=True)
print('App and nested code signatures verified')
