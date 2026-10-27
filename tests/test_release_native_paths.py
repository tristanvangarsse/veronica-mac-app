#!/usr/bin/env python3
"""Attest an actual native dependency with one loader-relative run path."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_manifest',ROOT/'scripts/release_manifest.py')
manifest=importlib.util.module_from_spec(spec);spec.loader.exec_module(manifest)
with tempfile.TemporaryDirectory(prefix='veronica-native-path-') as td:
    base=Path(td);common=base/'common.c';middle=base/'middle.c';main=base/'main.c'
    common.write_text('int common(void) { return 7; }\n')
    middle.write_text('int common(void); int middle(void) { return common(); }\n')
    main.write_text('int middle(void); int main(void) { return middle() == 7 ? 0 : 1; }\n')
    def cc(*args):subprocess.run(['/usr/bin/clang',*map(str,args)],check=True,capture_output=True,text=True,timeout=30)
    lib=base/'libcommon.dylib';mid=base/'libmiddle.dylib';binary=base/'check'
    cc('-dynamiclib',common,'-o',lib,'-Wl,-install_name,@rpath/libcommon.dylib')
    cc('-dynamiclib',middle,'-o',mid,'-L'+str(base),'-lcommon','-Wl,-rpath,@loader_path','-Wl,-install_name,'+str(mid))
    cc(main,'-o',binary,'-L'+str(base),'-lmiddle')
    subprocess.run([str(binary)],check=True,timeout=10)
    pinned=manifest.libraries(binary)
    assert pinned[str(lib.resolve())]==manifest.sha(lib)
    lib.write_bytes(lib.read_bytes()+b'changed')
    assert manifest.sha(lib)!=pinned[str(lib.resolve())]
    cc('-dynamiclib',middle,'-o',mid,'-L'+str(base),'-lcommon','-Wl,-install_name,'+str(mid))
    try:manifest.libraries(mid)
    except RuntimeError as error:assert 'Unresolved runtime library' in str(error)
    else:raise AssertionError('Missing run path must fail closed')
print('Native loader-relative dependency attestation and unresolved-path refusal: PASS')
