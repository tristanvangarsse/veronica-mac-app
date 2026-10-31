#!/usr/bin/env python3
"""Both Homebrew layouts must run using only the relocated Perl libraries."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from release_manifest import bundle_date_editor


PROGRAM = '''#!/usr/bin/perl5.34
use strict;
BEGIN {
    my $incDir = ($0 =~ /(.*)[\\\\\\/]/) ? "$1/lib" : './lib';
    unshift @INC, $incDir;
}
use Image::ExifTool;
use File::ExifFixture;
print "$Image::ExifTool::VERSION\\n";
'''


def main():
    with tempfile.TemporaryDirectory(prefix="veronica-exiftool-packaging-") as td:
        base = Path(td)
        for layout in ("patched-perl", "shell-launcher"):
            prefix = base / layout
            (prefix / "bin").mkdir(parents=True)
            library = prefix / "libexec/lib/perl5"
            (library / "Image").mkdir(parents=True)
            (library / "File").mkdir()
            (library / "Image/ExifTool.pm").write_text('package Image::ExifTool; our $VERSION = "fixture"; 1;\n')
            (library / "File/ExifFixture.pm").write_text('package File::ExifFixture; 1;\n')
            (prefix / "README").write_text("Fixture licence and package documentation\n")
            tool = prefix / "bin/exiftool"
            if layout == "patched-perl":
                tool.write_text(PROGRAM.replace('    unshift @INC, $incDir;',
                    '    use Config;\nunshift @INC, "/opt/homebrew/Cellar/exiftool/libexec/lib/perl5";\n'
                    'unshift @INC, "/opt/homebrew/Cellar/exiftool/libexec/lib/perl5/$Config{archname}";'))
            else:
                (prefix / "libexec/bin").mkdir()
                (prefix / "libexec/bin/exiftool").write_text(PROGRAM)
                tool.write_text('#!/bin/bash\nexport PERL5LIB="/opt/homebrew/Cellar/exiftool/libexec/lib/perl5"\n'
                                'exec "/opt/homebrew/Cellar/exiftool/libexec/bin/exiftool" "$@"\n')
            output = base / (layout + " relocated")
            bundle_date_editor(tool, output)
            assert '/opt/homebrew/' not in (output / "exiftool").read_text()
            shutil.rmtree(prefix)
            result = subprocess.run(['/usr/bin/perl', str(output / "exiftool")],
                                    check=True, capture_output=True, text=True)
            assert result.stdout.strip() == "fixture"

        # An unrecognized launcher must fail closed instead of shipping paths
        # into a developer's environment or weakening the manifest gate.
        prefix = base / "unsupported"
        (prefix / "bin").mkdir(parents=True)
        tool = prefix / "bin/exiftool"
        tool.write_text('#!/bin/bash\nexec /opt/homebrew/unknown/exiftool "$@"\n')
        try:
            bundle_date_editor(tool, base / "must-not-ship")
        except RuntimeError:
            pass
        else:
            raise AssertionError("An unrecognized external launcher was accepted")
    print("Old/new ExifTool package layouts, relocated libraries, removed build paths and strict refusal: PASS")


if __name__ == "__main__":
    main()
