#!/usr/bin/env python3
"""Copy, relocate, sign and attest tools with their complete native library closure."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import release_manifest as release


def bundle(output, tools):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    (output/'bin').mkdir();(output/'lib').mkdir();(output/'licenses').mkdir()
    edges={};all_sources=set();roots={name:Path(path).resolve() for name,path in tools.items()}
    for executable in roots.values():
        pending=[executable]
        while pending:
            source=pending.pop();deps=release.native_dependencies(source,executable)
            if source in edges:
                if edges[source]!=deps:raise RuntimeError('Ambiguous executable-relative library: '+str(source))
                continue
            edges[source]=deps;all_sources.add(source);pending.extend(deps.values())
    destinations={source:output/'lib'/(release.sha(source)[:12]+'-'+source.name) for source in all_sources}
    for name,source in roots.items():destinations[source]=output/'bin'/name
    provenance=[]
    for source,target in destinations.items():
        shutil.copy2(source,target);target.chmod(0o755)
        changes=[]
        for raw,dependency in edges[source].items():
            relative=os.path.relpath(destinations[dependency],target.parent)
            changes+=['-change',raw,'@loader_path/'+relative]
        if target.parent.name=='lib':changes+=['-id','@loader_path/'+target.name]
        commands=subprocess.check_output(['/usr/bin/otool','-l',str(source)],text=True)
        for runpath in re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset \d+\)',commands):
            changes+=['-delete_rpath',runpath]
        if changes:subprocess.run(['/usr/bin/install_name_tool',*changes,str(target)],check=True,capture_output=True,text=True)
        subprocess.run(['/usr/bin/codesign','--force','--sign','-','--timestamp=none',str(target)],check=True,capture_output=True,text=True)
        provenance.append({'file':str(target.relative_to(output)),'original_path':str(source),'original_sha256':release.sha(source)})
    # Retain supplied licenses and the exact installed formula/receipt for all
    # copied packages. Public distribution can also use this source provenance.
    packages={}
    for source in all_sources:
        keg=next((p for p in source.parents if (p/'INSTALL_RECEIPT.json').is_file()),None)
        if keg is None:continue
        package=keg.parent.name+'-'+keg.name
        if package in packages:continue
        target=output/'licenses'/package;target.mkdir()
        for source_file in keg.rglob('*'):
            if source_file.is_file() and (source_file.name.upper().startswith(('COPYING','LICENSE','NOTICE','AUTHORS'))
                                         or source_file.name=='INSTALL_RECEIPT.json' or source_file.parent.name=='.brew'):
                dest=target/source_file.relative_to(keg);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_file,dest)
        packages[package]=str(keg)
    manifest={}
    for name,source in roots.items():
        target=destinations[source];closure=release.libraries(target)
        if not all(Path(p).is_relative_to(output) for p in closure):raise RuntimeError('Media library escaped the bundle')
        manifest[name]={'path':'MediaTools/'+str(target.relative_to(output)),'sha256':release.sha(target),
                        'libraries':{'MediaTools/'+str(Path(p).relative_to(output)):h for p,h in closure.items()}}
    (output/'manifest.json').write_text(json.dumps({'tools':manifest,'packages':packages,'provenance':provenance},indent=2,sort_keys=True)+'\n')
    print(f'Bundled {len(roots)} tools and {len(all_sources)-len(roots)} relocatable libraries.')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));import media_security
    tools={name:media_security.resolve_tool(name) for name in ('ffmpeg','ffprobe','HandBrakeCLI')}
    if not all(tools.values()):raise SystemExit('Install media tools in the build environment before packaging.')
    bundle(args.output,tools)
