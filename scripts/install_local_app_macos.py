#!/usr/bin/env python3
"""Install one current local Veronica; retain older installations as ZIP archives."""
import argparse
import datetime as dt
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

BUNDLE_ID = 'com.tristan.veronica'
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def run(*args):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True)


def is_veronica(app):
    try:
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        return info.get('CFBundleIdentifier') == BUNDLE_ID
    except (OSError, plistlib.InvalidFileException):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path, help='Exact verified .app from build_local_app_macos.sh')
    parser.add_argument('--tidy-older-copies', action='store_true', help='Archive old Applications backups and indexed development copies')
    args = parser.parse_args()
    source = args.app.expanduser().resolve()
    if not is_veronica(source):
        parser.error('Choose a Veronica application bundle')
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', source)
    applications = Path.home() / 'Applications'
    applications.mkdir(exist_ok=True)
    target = applications / 'Veronica.app'
    if source == target:
        parser.error('Choose the build output, not the installed app')
    running = run('/bin/ps', '-axo', 'command=').stdout.splitlines()

    def is_running(app):
        return any(line.startswith(str(app) + '/Contents/MacOS/') for line in running)

    if is_running(target):
        parser.error('Quit the installed Veronica before replacing it')
    archives = Path.home() / 'Library/Application Support/Veronica/Build Archives.noindex'
    archives.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')

    def archive(app):
        if is_running(app):
            print(f'Left running copy in place: {app}')
            return False
        destination = archives / f'{stamp}-{app.name}-{len(list(archives.iterdir()))}.zip'
        run('/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, destination)
        run('/usr/bin/unzip', '-tq', destination)
        run(LSREGISTER, '-u', app)
        print(f'Archived {app} -> {destination}')
        return True

    with tempfile.TemporaryDirectory(prefix='.Veronica-install-', dir=applications) as staging:
        stage = Path(staging)
        staged = stage / 'Veronica.app'
        run('/usr/bin/ditto', source, staged)
        run('/usr/bin/codesign', '--verify', '--deep', '--strict', staged)
        previous = stage / 'previous.app'
        if target.exists():
            if not is_veronica(target):
                parser.error('The existing destination is not a Veronica app')
            archive(target)
            target.rename(previous)
        try:
            staged.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise

    if args.tidy_older_copies:
        indexed = run('/usr/bin/mdfind', f'kMDItemCFBundleIdentifier == "{BUNDLE_ID}"').stdout.splitlines()
        candidates = set(Path(path) for path in indexed)
        candidates.update(applications.glob('Veronica.app.backup-*'))
        for app in sorted(candidates):
            if app in {source, target} or not app.is_dir() or not is_veronica(app):
                continue
            # Only app bundles; no source folders, documents, settings or media.
            if archive(app):
                shutil.rmtree(app)
    # Launch Services can otherwise prefer a previously opened development copy.
    run(LSREGISTER, '-u', source)
    run(LSREGISTER, '-f', target)
    print(f'Current Veronica installed at: {target}')
    print(f'Recoverable app archives: {archives}')


if __name__ == '__main__':
    main()
