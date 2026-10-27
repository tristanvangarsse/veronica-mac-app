#!/usr/bin/env python3
"""Validate the downloadable disk image, its contents and its checksum."""
from pathlib import Path
import hashlib
import json
import plistlib
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from build_release_assets import package
with tempfile.TemporaryDirectory(prefix='veronica-dmg-test-') as td:
    base=Path(td).resolve();app=base/'Veronica.app';macos=app/'Contents/MacOS';macos.mkdir(parents=True)
    source=base/'main.c';source.write_text('int main(void) { return 0; }')
    subprocess.run(['/usr/bin/clang','-arch','arm64',str(source),'-o',str(macos/'Veronica')],check=True,capture_output=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.tristan.veronica.packagingcheck','CFBundleExecutable':'Veronica','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.16.0','CFBundleVersion':'7','LSMinimumSystemVersion':'26.0'}))
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
    assets=base/'Downloads';dmg=package(app,assets,'v0.16.0-beta.1')
    data=json.loads((assets/'release.json').read_text())
    assert data['sha256']==hashlib.sha256(dmg.read_bytes()).hexdigest()
    assert data['architecture']=='arm64' and not data['apple_notarized']
    attach=subprocess.check_output(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-plist',str(dmg)])
    mount=next(Path(e['mount-point']) for e in plistlib.loads(attach)['system-entities'] if e.get('mount-point'))
    try:
        assert (mount/'Applications').is_symlink() and (mount/'Applications').readlink()==Path('/Applications')
        text=(mount/'Read me first.html').read_text();assert 'Privacy &amp; Security' in text and '0.16.0-beta.1' in text
        assert (mount/'Veronica licence.txt').is_file()
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(mount/'Veronica.app')],check=True,capture_output=True)
    finally:subprocess.run(['/usr/bin/hdiutil','detach',str(mount)],check=True,capture_output=True)
    try:package(app,assets,'v0.16.0-beta.1')
    except ValueError:pass
    else:raise AssertionError('An existing versioned release was overwritten')
    try:package(app,base/'Mismatch','v0.17.0-beta.1')
    except ValueError:pass
    else:raise AssertionError('An app was packaged under a mismatched version')
print('Verified DMG, mounted signed app, install instructions, Applications shortcut, checksum and immutable versioned output: PASS')
