#!/usr/bin/env python3
"""Both Homebrew layouts must run using only the relocated Perl libraries."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from release_manifest import bundle_date_editor
sys.path.insert(0, str(ROOT))
import media_dates


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
            with patch.object(media_dates.security, 'resolve_tool', return_value=str(tool)):
                command = media_dates.exiftool_command()
                expected_program = prefix / ('libexec/bin/exiftool' if layout == 'shell-launcher' else 'bin/exiftool')
                assert media_dates.exiftool_program(command) == expected_program
                assert command[0] == '/usr/bin/perl5.34' and '-config' in command
                source = subprocess.run(command, check=True, capture_output=True, text=True)
                assert source.stdout.strip() == 'fixture'
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
        with patch.object(media_dates.security, 'resolve_tool', return_value=str(tool)):
            try:
                media_dates.exiftool_command()
            except RuntimeError:
                pass
            else:
                raise AssertionError('Source mode accepted an unrecognized shell launcher')
    print("Old/new ExifTool package layouts, relocated libraries, removed build paths and strict refusal: PASS")


if __name__ == "__main__":
    main()
