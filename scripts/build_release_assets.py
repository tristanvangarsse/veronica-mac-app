#!/usr/bin/env python3
"""Package a verified application as a versioned, drag-and-drop download."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile

REPO='https://github.com/tristanvangarsse/veronica-mac-app'


def package(app, output, tag):
    app=Path(app).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True)
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?',tag):raise ValueError('Use a version tag such as v0.16.0-beta.1')
    architecture=subprocess.check_output(['/usr/bin/lipo','-archs',str(app/'Contents/MacOS'/info['CFBundleExecutable'])],text=True).strip()
    if architecture!='arm64':raise ValueError('This download package supports Apple Silicon builds only')
    version=tag.removeprefix('v');minimum=info['LSMinimumSystemVersion']
    release_label='Preview release' if '-' in version else 'Release'
    if version.split('-')[0]!=info['CFBundleShortVersionString']:raise ValueError('Tag does not match the app version')
    filename='Veronica-'+version+'-macOS-arm64.dmg';dmg=output/filename
    if dmg.exists():raise ValueError('Release download already exists; use a new output directory or version')
    release=REPO+'/releases/tag/'+tag
    with tempfile.TemporaryDirectory(prefix='veronica-dmg-') as td:
        stage=Path(td)
        subprocess.run(['/usr/bin/ditto',str(app),str(stage/'Veronica.app')],check=True)
        # Build-time umask may be private. Shipped app resources must also be
        # readable by a different standard user after a shared installation.
        stage.chmod(0o755)
        copied=stage/'Veronica.app'
        for item in [copied,*copied.rglob('*')]:
            if not item.is_symlink():item.chmod(0o755 if item.is_dir() or item.stat().st_mode&0o111 else 0o644)
        subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(copied)],check=True)
        (stage/'Applications').symlink_to('/Applications')
        (stage/'Read me first.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Welcome to Veronica</title>
<style>body{margin:0;background:#f7f5fa;color:#241d2c;font:17px/1.6 -apple-system,BlinkMacSystemFont,sans-serif}main{max-width:680px;margin:48px auto;padding:40px;background:white;border-radius:24px}h1{font-size:42px;line-height:1.15;color:#813cb0}h2{margin-top:32px;font-size:23px}a{color:#68258d}.badge{display:inline-block;padding:6px 12px;border-radius:20px;background:#e4f6e6;color:#145c25}li{margin:12px 0}small{color:#63576f}</style>
<main><span class="badge">'''+release_label+''' · Apple Silicon</span><h1>Make room for more.</h1><p>Welcome to Veronica '''+html.escape(version)+'''.</p>
<h2>Install</h2><ol><li>Drag Veronica into Applications. If you cannot install apps for all users, copy it into an Applications folder inside your own Home folder instead.</li><li>Eject this disk image, then open your installed copy.</li><li>First launch prepares the built-in tools automatically. No extra downloads or developer tools are required.</li></ol>
<h2>First opening</h2><p>This download is not signed with an Apple Developer ID or notarized by Apple. If macOS blocks it, follow <a href="https://support.apple.com/102445">Apple’s instructions</a> for approving a trusted app in System Settings → Privacy &amp; Security. Do not disable system-wide security protections.</p>
<h2>Your first cleanup</h2><p>Add copies of a small test folder first. Scan, review the planned changes, then choose Smart cleanup. Replaced originals go to the Mac Trash; keep them there until you have checked the results. You can find dated change logs under Settings → Support.</p>
<p><strong>Requirements:</strong> Apple Silicon Mac · macOS '''+html.escape(minimum)+''' or later.</p>
<p><a href="'''+release+'''">Release notes and downloads</a> · <a href="'''+REPO+'''/issues">Report a problem</a></p>
<small>Veronica is released under the MIT licence. Bundled third-party tools retain their own licences. Corresponding media-tool sources and build recipes are supplied with this release.</small></main></html>''')
        shutil.copy2(Path(__file__).resolve().parents[1]/'LICENSE',stage/'Veronica licence.txt')
        subprocess.run(['/usr/bin/hdiutil','create','-volname','Veronica '+version,'-srcfolder',str(stage),'-format','UDZO','-ov',str(dmg)],check=True,capture_output=True,text=True)
    subprocess.run(['/usr/bin/hdiutil','verify',str(dmg)],check=True,capture_output=True,text=True)
    digest=hashlib.sha256(dmg.read_bytes()).hexdigest()
    (output/'SHA256SUMS.txt').write_text(digest+'  '+filename+'\n')
    manifest={'version':version,'tag':tag,'app_build':info['CFBundleVersion'],'minimum_macos':minimum,'architecture':'arm64','dmg':filename,'sha256':digest,'apple_notarized':False,'developer_id_signed':False}
    (output/'release.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(dmg)
    return dmg


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--tag',required=True);a=p.parse_args();package(a.app,a.output,a.tag)
