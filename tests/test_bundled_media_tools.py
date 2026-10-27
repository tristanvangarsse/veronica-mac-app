#!/usr/bin/env python3
"""A relocated native tool keeps working after its original libraries disappear."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from bundle_media_tools import bundle
import release_manifest
with tempfile.TemporaryDirectory(prefix='veronica-relocatable-') as td:
    base=Path(td).resolve();original=base/'Original build';original.mkdir()
    (original/'library.c').write_text('int answer(void) { return 7; }')
    (original/'main.c').write_text('int answer(void); int main(void) { return answer()==7 ? 0 : 1; }')
    library=original/'libanswer.dylib';binary=original/'example'
    subprocess.run(['/usr/bin/clang','-dynamiclib',str(original/'library.c'),'-o',str(library),'-Wl,-install_name,'+str(library),'-Wl,-headerpad_max_install_names'],check=True,capture_output=True)
    subprocess.run(['/usr/bin/clang',str(original/'main.c'),'-L'+str(original),'-lanswer','-o',str(binary),'-Wl,-headerpad_max_install_names'],check=True,capture_output=True)
    output=base/'MediaTools';manifest=bundle(output,{'example':binary})
    shutil.rmtree(original)
    relocated=base/'Different location with spaces'/'MediaTools';relocated.parent.mkdir();output.rename(relocated)
    subprocess.run([str(relocated/'bin/example')],check=True,env={'PATH':'/usr/bin:/bin'})
    expected=manifest['example'];assert expected['path']=='MediaTools/bin/example'
    assert all(not Path(p).is_absolute() for p in expected['libraries'])
    assert all(Path(p).is_relative_to(relocated) for p in release_manifest.libraries(relocated/'bin/example'))
    subprocess.run(['/usr/bin/codesign','--verify','--strict',str(relocated/'bin/example')],check=True,capture_output=True)
print('Relocated and signed tool uses only bundled libraries after deleting original build: PASS')
