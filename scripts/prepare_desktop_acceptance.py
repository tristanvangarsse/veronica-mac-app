#!/usr/bin/env python3
"""Prepare an unchanged downloaded app for native QA on the current desktop.

This only prepares files. Launch the returned installed app through the native
app interface, then operate Veronica normally. No account switching or tool
uninstallation is needed. Keep the session until its results are reviewed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile


def run(*arguments):
    return subprocess.run(list(map(str,arguments)),check=True,capture_output=True,text=True).stdout


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def settings_snapshot(directory):
    return {str(p.relative_to(directory)):digest(p) for p in directory.rglob('*.json')
            if p.is_file() and 'Sessions.noindex' not in p.parts and 'Change Logs' not in p.parts}


def copy_dmg_app(dmg,destination):
    image=plistlib.loads(subprocess.check_output(['/usr/bin/hdiutil','attach','-readonly','-nobrowse','-plist',str(dmg)]))
    mount=next(Path(e['mount-point']) for e in image['system-entities'] if e.get('mount-point'))
    try:
        source=mount/'Veronica.app'
        run('/usr/bin/codesign','--verify','--deep','--strict',source)
        run('/usr/bin/ditto',source,destination)
        run('/usr/bin/codesign','--verify','--deep','--strict',destination)
        assert digest(source/'Contents/MacOS/Veronica')==digest(destination/'Contents/MacOS/Veronica')
        return plistlib.loads((destination/'Contents/Info.plist').read_bytes())
    finally:run('/usr/bin/hdiutil','detach',mount)


def write_record(record, data):
    temporary=record.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n')
    temporary.chmod(0o600)
    temporary.replace(record)


def active_marker():
    return Path.home()/'Library/Caches/Veronica Release Tests/active-session.json'


def prepare(args):
    require_app_quit()
    marker=active_marker()
    if marker.exists():
        raise RuntimeError(f'Restore the active QA session before starting another: {marker.read_text().strip()}')
    parent=Path.home()/'Library/Caches/Veronica Release Tests'
    parent.mkdir(parents=True,exist_ok=True)
    session=Path(tempfile.mkdtemp(prefix='desktop-',suffix='.noindex',dir=parent))
    installed=session/'Installed/Veronica.app';installed.parent.mkdir()
    info=copy_dmg_app(args.previous_dmg or args.dmg,installed)
    fixtures=session/'Generated test folders'
    run('/usr/bin/ditto',args.fixtures,fixtures)
    stress=session/'Cancellation samples';stress.mkdir()
    for i in range(1600):(stress/f'unchanged-{i:04}.txt').write_text('Generated cancellation sample.\n')
    personal=Path.home()/'Library/Application Support/Veronica'
    preferences=session/'Original user defaults.plist'
    exported=subprocess.run(['/usr/bin/defaults','export','com.tristan.veronica',str(preferences)],capture_output=True)
    if exported.returncode and b'does not exist' not in exported.stderr:
        raise RuntimeError(exported.stderr.decode())
    data={'session':str(session),'installed_app':str(installed),'state_dir':str(personal),
          'fixtures':str(fixtures),'cancellation_samples':str(stress),'target_dmg':str(args.dmg.resolve()),
          'target_dmg_sha256':digest(args.dmg),'starting_version':info['CFBundleShortVersionString'],
          'personal_state':str(personal),'personal_settings_before':settings_snapshot(personal),
          'personal_profile_existed':personal.exists(),'personal_profile_backup':str(session/'Saved normal profile'),
          'original_defaults_existed':exported.returncode==0,'profile_active':False,
          'fixture_hashes_before':{str(p.relative_to(fixtures)):digest(p) for p in fixtures.rglob('*') if p.is_file()}}
    record=session/'session.json';write_record(record,data)
    with marker.open('x') as stream:stream.write(str(record)+'\n')
    marker.chmod(0o600)
    # Move the whole profile atomically rather than relying on a home override:
    # Swift and the frozen Python coordinator must see the same empty profile.
    data['profile_active']=True;write_record(record,data)
    try:
        if personal.exists():personal.rename(data['personal_profile_backup'])
        personal.mkdir(mode=0o700,parents=True)
        empty=session/'Empty user defaults.plist';empty.write_bytes(plistlib.dumps({}))
        run('/usr/bin/defaults','import','com.tristan.veronica',empty)
    except Exception:
        restore(argparse.Namespace(session=record));raise
    print(record);print('Open this unchanged app through the native app interface:',installed)


def require_app_quit():
    for line in run('/bin/ps','-axo','uid=,comm=').splitlines():
        uid,_,command=line.strip().partition(' ')
        if uid==str(os.getuid()) and command.strip().endswith('/Veronica.app/Contents/MacOS/Veronica'):
            raise RuntimeError('Quit Veronica through its app menu before changing the QA profile')


def upgrade(args):
    require_app_quit()
    record=args.session.resolve();data=json.loads(record.read_text());session=Path(data['session']).resolve()
    assert record==session/'session.json' and session.name.endswith('.noindex')
    assert data['profile_active'],'This QA profile has already been restored'
    installed=Path(data['installed_app']);assert installed==session/'Installed/Veronica.app'
    assert digest(data['target_dmg'])==data['target_dmg_sha256']
    assert not (session/'Previous Veronica.app').exists(),'This test session was already upgraded'
    # The caller quits the test app through its UI before replacing this copy.
    installed.rename(session/'Previous Veronica.app')
    try:info=copy_dmg_app(Path(data['target_dmg']),installed)
    except Exception:
        if installed.exists():installed.rename(session/'Failed app copy - preserved')
        (session/'Previous Veronica.app').rename(installed)
        raise
    data['installed_version']=info['CFBundleShortVersionString'];data['installed_build']=info['CFBundleVersion']
    write_record(record,data);print('QA copy upgraded:',data['installed_version'],data['installed_build'])


def verify(args):
    data=json.loads(args.session.read_text())
    location=Path(data['personal_profile_backup']) if data.get('profile_active') else Path(data['personal_state'])
    assert settings_snapshot(location)==data['personal_settings_before'],'Saved normal Veronica settings changed during QA'
    if not data.get('profile_active'):
        current=subprocess.run(['/usr/bin/defaults','export','com.tristan.veronica','-'],capture_output=True)
        if data['original_defaults_existed']:
            original=Path(data['session'])/'Original user defaults.plist'
            assert current.returncode==0 and plistlib.loads(current.stdout)==plistlib.loads(original.read_bytes()),'Normal macOS app preferences differ from the backup'
        else:
            assert current.returncode!=0,'Temporary macOS app preferences are still present'
    print('Normal Veronica settings are preserved byte for byte: PASS')


def restore(args):
    require_app_quit()
    record=args.session.resolve();data=json.loads(record.read_text());session=Path(data['session']).resolve()
    assert record==session/'session.json' and session.name.endswith('.noindex')
    marker=active_marker()
    if marker.exists() and Path(marker.read_text().strip())!=record:
        raise RuntimeError('Another QA session is active; restore that session first')
    if not data['profile_active']:
        verify(args)
        if marker.exists():marker.unlink()
        return
    personal=Path(data['personal_state']);backup=Path(data['personal_profile_backup'])
    completed=session/'Completed test profile'
    assert personal==Path.home()/'Library/Application Support/Veronica'
    assert backup==session/'Saved normal profile'
    if backup.exists():
        assert settings_snapshot(backup)==data['personal_settings_before']
        if personal.exists():personal.rename(completed)
        backup.rename(personal)
    elif data['personal_profile_existed']:
        # Recovery if preparation stopped before the move, or restoration stopped
        # just after it: never mistake the normal profile for disposable QA data.
        assert settings_snapshot(personal)==data['personal_settings_before']
    elif personal.exists():
        personal.rename(completed)
    if data['original_defaults_existed']:
        run('/usr/bin/defaults','import','com.tristan.veronica',session/'Original user defaults.plist')
    else:
        subprocess.run(['/usr/bin/defaults','delete','com.tristan.veronica'],capture_output=True,check=False)
    data['profile_active']=False;data['test_state_dir']=str(session/'Completed test profile')
    write_record(record,data);verify(args)
    if marker.exists():marker.unlink()
    print('Normal profile and app preferences restored; generated QA evidence retained:',session)


if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--dmg',type=Path,required=True);prep.add_argument('--previous-dmg',type=Path)
    prep.add_argument('--fixtures',type=Path,required=True);prep.set_defaults(action=prepare)
    for command,action in [('upgrade',upgrade),('verify-personal-settings',verify),('restore',restore)]:
        parser=sub.add_parser(command);parser.add_argument('--session',type=Path,required=True);parser.set_defaults(action=action)
    args=p.parse_args();args.action(args)
