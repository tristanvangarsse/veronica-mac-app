#!/usr/bin/env python3
"""Collect supplied license notices and SBOMs for redistributed runtime code."""
import importlib.metadata
from pathlib import Path
import shutil
import sys
import sysconfig
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
for package in ('pillow','pyinstaller','Python'):
    previous=out/package
    if previous.is_symlink():previous.unlink()
    elif previous.exists():shutil.rmtree(previous)
for package in ('pillow','pyinstaller'):
    distribution=importlib.metadata.distribution(package)
    for item in distribution.files or []:
        if 'licenses' in item.parts or 'sboms' in item.parts:
            index=next(i for i,v in enumerate(item.parts) if v in ('licenses','sboms'))
            target=out/package/Path(*item.parts[index:]);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(distribution.locate_file(item),target)
license_roots=(Path(sysconfig.get_path('stdlib')),Path(sys.base_prefix),*Path(sys.base_prefix).parents)
licenses=[p/name for p in license_roots for name in ('LICENSE','LICENSE.txt') if (p/name).is_file()]
if not licenses:raise SystemExit('Python runtime license was not found')
(out/'Python').mkdir(exist_ok=True);shutil.copy2(licenses[0],out/'Python/LICENSE')
(out/'README.txt').write_text('Notices supplied with Python, Pillow native image libraries, and the PyInstaller bootloader. Bundled media tools carry their supplied licenses, build receipts and source formulae in MediaTools/licenses, with exact binary provenance in MediaTools/manifest.json.\n')
