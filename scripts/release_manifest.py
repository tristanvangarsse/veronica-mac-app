#!/usr/bin/env python3
"""Bind a release runtime to reviewed sources and bundled portable media tools."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('veronica.py','media_audit.py','media_maintenance.py','media_security.py','media_worker.py','media_dates.py','media_change_log.py','preset-720P.json')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(4*1024*1024),b''):h.update(data)
    return h.hexdigest()
def version():
    module=ast.parse((ROOT/'media_maintenance.py').read_text())
    return next(n.value.value for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets))
def native_minimum(path):
    text=subprocess.check_output(['/usr/bin/otool','-l',str(path)],text=True,stderr=subprocess.DEVNULL)
    versions=re.findall(r"\bminos\s+(\d+(?:\.\d+)+)",text)
    versions+=re.findall(r"cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version (\d+(?:\.\d+)+)",text)
    return max(versions,key=lambda v:tuple(map(int,v.split('.'))),default='13.0')

def minimum_os(engine):
    engine=Path(engine).resolve()
    manifest=json.loads((engine.parent/'_internal/security-manifest.json').read_text())
    versions=['13.0']
    paths=set()
    for tool in manifest['tools'].values():
        paths.add(engine.parent/'_internal'/tool['path'])
        paths.update(engine.parent/'_internal'/p for p in tool.get('libraries',{}))
    for path in engine.parent.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:magic=stream.read(4)
            if magic in (b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'):
                paths.add(path)
    versions.extend(native_minimum(p) for p in paths)
    return max(versions,key=lambda v:tuple(map(int,v.split('.'))))

def native_dependencies(path, executable=None):
    """Resolve a Mach-O file's non-system load commands without search guessing."""
    path=Path(path);executable=Path(executable or path)
    text=subprocess.check_output(['/usr/bin/otool','-L',str(path)],text=True)
    identities=subprocess.check_output(['/usr/bin/otool','-D',str(path)],text=True).splitlines()[1:]
    install_id=next((line.strip() for line in identities if line.strip()),None)
    result={}
    for line in text.splitlines()[1:]:
        raw=line.strip().split(' (',1)[0];dep=raw
        if dep==install_id or dep.startswith(('/System/','/usr/lib/')):continue
        if dep.startswith('@loader_path/'):
            dep=str(path.parent/dep.removeprefix('@loader_path/'))
        if dep.startswith('@executable_path/'):
            dep=str(executable.parent/dep.removeprefix('@executable_path/'))
        if dep.startswith('@rpath/'):
            commands=subprocess.check_output(['/usr/bin/otool','-l',str(path)],text=True)
            runpaths=re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset \d+\)",commands)
            if len(runpaths)!=1:raise RuntimeError('Unresolved runtime library: '+dep)
            runpath=runpaths[0]
            if runpath.startswith('@loader_path/'):
                directory=path.parent/runpath.removeprefix('@loader_path/')
            elif runpath=='@loader_path':directory=path.parent
            elif runpath.startswith('@executable_path/'):
                directory=executable.parent/runpath.removeprefix('@executable_path/')
            elif runpath.startswith('/'):directory=Path(runpath)
            else:raise RuntimeError('Unsupported runtime library search path: '+runpath)
            dep=str(directory/dep.removeprefix('@rpath/'))
        candidate=Path(dep)
        if not candidate.is_absolute() or not candidate.is_file():
            raise RuntimeError('Unresolved runtime library: '+dep)
        result[raw]=candidate.resolve()
    return result


def libraries(binary):
    found={};pending=[Path(binary)]
    while pending:
        for lib in native_dependencies(pending.pop(),binary).values():
            if str(lib) not in found:
                found[str(lib)]=sha(lib);pending.append(lib)
    return found

def bundle_date_editor(tool, vendor):
    """Copy the Perl program, never Homebrew's environment launcher."""
    import shutil
    tool = Path(tool).resolve()
    prefix = tool.parent.parent
    library = prefix/'libexec/lib/perl5'
    # Recent Homebrew bottles expose a shell launcher in bin/ and put the
    # actual program in libexec/bin/. Older bottles patched the Perl program
    # directly. Inspect only this known package layout; do not run a wrapper.
    script = tool.read_text()
    if not re.match(r'^#!\s*/usr/bin/perl[0-9.]*(?:\s|$)', script):
        program = prefix/'libexec/bin/exiftool'
        if program.is_file():
            script = program.read_text()
    require(re.match(r'^#!\s*/usr/bin/perl[0-9.]*(?:\s|$)', script),
            'ExifTool must use the macOS system Perl interpreter')
    script = re.sub(r'    use Config;\nunshift @INC, .*?;\nunshift @INC, .*?;',
                    '    unshift @INC, $incDir;', script, count=1)
    require(not any(path in script for path in ('/opt/homebrew/', '/usr/local/Cellar/', '/usr/local/opt/')),
            'ExifTool still contains an absolute library path')
    require('unshift @INC, $incDir;' in script, 'ExifTool does not load its bundled relative library')
    vendor = Path(vendor)
    if vendor.exists():
        shutil.rmtree(vendor)
    vendor.mkdir(parents=True)
    shutil.copytree(library/'Image', vendor/'lib/Image')
    shutil.copytree(library/'File', vendor/'lib/File')
    (vendor/'exiftool').write_text(script)
    shutil.copy2(prefix/'README', vendor/'README')


def generate(output):
    sys.path.insert(0,str(ROOT))
    import media_security as sec
    if sys.version_info < (3,11):raise RuntimeError('Supported Python 3.11 or newer is required')
    tools=json.loads((Path(output).parent/'MediaTools/manifest.json').read_text())['tools']
    # Bundle the metadata editor with relative library paths, independent of
    # Homebrew on the user's Mac. Config loading is disabled by the caller.
    import shutil
    tool = Path(sec.resolve_tool('exiftool') or '')
    if not tool.is_file(): raise RuntimeError('ExifTool is required to build the date editor')
    vendor = Path(output).parent/'ExifTool'
    bundle_date_editor(tool, vendor)
    # ExifTool uses the same Artistic/GPL terms as Perl; retain its bundled
    # copyright notices and both standard license texts from the system Perl.
    for name in ('perlartistic.pod', 'perlgpl.pod'):
        candidates = list(Path('/System/Library/Perl').rglob(name))
        require(bool(candidates), 'Missing ExifTool license text: '+name)
        shutil.copyfile(candidates[0], vendor/name)
    date_editor = {str(p.relative_to(vendor.parent)):sha(p) for p in vendor.rglob('*') if p.is_file()}
    manifest={'date_editor': date_editor, 'version':version(),'sources':{n:sha(ROOT/n) for n in SOURCES},'python':sys.version.split()[0],
              'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},'tools':tools}
    Path(output).write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def check(engine):
    engine=Path(engine).resolve();manifest=json.loads((engine.parent/'_internal/security-manifest.json').read_text())
    require(manifest['version']==version(),'Frozen engine version is stale')
    require(manifest['sources']=={n:sha(ROOT/n) for n in SOURCES},'Frozen engine source manifest is stale')
    preset=engine.parent/'_internal/preset-720P.json'
    require(preset.is_file() and sha(preset)==manifest['sources']['preset-720P.json'],
            'Frozen video preset is missing or differs from the reviewed preset')
    for rel, expected in manifest.get('date_editor', {}).items():
        require(sha(engine.parent/'_internal'/rel)==expected, 'Bundled date editor changed')
    require(bool(manifest.get('date_editor')), 'Bundled date editor is missing')
    require(set(manifest['tools'])=={'ffmpeg','ffprobe','HandBrakeCLI'},'Bundled media tools are incomplete')
    for tool in manifest['tools'].values():
        binary=engine.parent/'_internal'/tool['path']
        require(not Path(tool['path']).is_absolute() and tool['path'].startswith('MediaTools/'), 'Media tool must be bundled')
        require(sha(binary)==tool['sha256'],'Bundled media tool changed')
        resolved=libraries(binary)
        expected={str((engine.parent/'_internal'/p).resolve()):h for p,h in tool['libraries'].items()}
        require(resolved==expected,'Bundled library closure changed or escapes the app')
        require(all(Path(p).is_relative_to((engine.parent/'_internal/MediaTools').resolve()) for p in resolved), 'External runtime library is not portable')
    import tempfile
    with tempfile.TemporaryDirectory(prefix='veronica-release-check-') as state:
        result=subprocess.run([str(engine),'ui-snapshot','--state-dir',state],capture_output=True,text=True,timeout=120)
        require(result.returncode==0,result.stderr)
        snapshot=json.loads(result.stdout)
    require(snapshot['version']==version(),'Frozen executable version is stale')
    require({'optimization_settings','pending_staged_outputs'}<=snapshot.keys(),'Release contract is incomplete')
    require(tuple(map(int,snapshot['preflight']['python_version'].split('.')[:2])) >= (3,11),'Unsupported frozen Python')
    require(snapshot['preflight']['pillow']['version']==manifest['packages']['pillow'],'Frozen Pillow does not match its manifest')
    require(all(snapshot['preflight']['tools'][n]['available'] for n in manifest['tools']),'Approved media tool changed or is unavailable')
    print('Release engine source, version, runtime, tool hashes and snapshot contract: PASS')

if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--generate');g.add_argument('--check');g.add_argument('--minimum-os');a=p.parse_args()
    if a.generate:generate(a.generate)
    elif a.check:check(a.check)
    else:print(minimum_os(a.minimum_os))
