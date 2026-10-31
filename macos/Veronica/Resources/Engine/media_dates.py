"""Restricted, metadata-only date editing. The coordinator owns installation."""
from pathlib import Path
import datetime as dt
import json
import re
import sys
import media_audit as audit
import media_security as security

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
QUICKTIME_EXTENSIONS = {'.mov', '.mp4', '.m4v', '.m4a'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.aif', '.aiff', '.flac'}
SUPPORTED = IMAGE_EXTENSIONS | QUICKTIME_EXTENSIONS | AUDIO_EXTENSIONS


def exiftool_command():
    interpreter_options = []
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
        manifest = json.loads((base / 'security-manifest.json').read_text())
        files = manifest.get('date_editor', {})
        if not files:
            raise RuntimeError('The date editor is missing. Reinstall Veronica.')
        for rel, expected in files.items():
            path = security.inside(base, rel)
            if security.digest(path) != expected:
                raise RuntimeError('The date editor changed. Reinstall Veronica.')
        tool = base / 'ExifTool/exiftool'
    else:
        tool = security.resolve_tool('exiftool')
        if not tool:
            raise RuntimeError('The date editor is unavailable. Install ExifTool or rebuild Veronica.')
        tool = Path(tool)
        prefix = tool.parent.parent
        # Homebrew may expose a shell launcher. Run its known Perl program
        # directly; the restricted worker must never need a shell or PERL5LIB.
        program = tool
        if not re.match(r'^#!\s*/usr/bin/perl[0-9.]*(?:\s|$)', program.read_text()):
            program = prefix / 'libexec/bin/exiftool'
        if (not program.is_file() or not program.resolve().is_relative_to(prefix.resolve())
                or not re.match(r'^#!\s*/usr/bin/perl[0-9.]*(?:\s|$)', program.read_text())):
            raise RuntimeError('The date editor must provide a supported system Perl program.')
        library = prefix / 'libexec/lib/perl5'
        if library.is_dir():
            interpreter_options.append('-I' + str(library))
        tool = program
    # Use the system interpreter explicitly: no shell, config or user Perl paths.
    perl = Path('/usr/bin/perl5.34')
    if not perl.is_file():
        raise RuntimeError('The system date editor runtime is unavailable.')
    return [str(perl), *interpreter_options, str(tool), '-config', '']


def exiftool_program(command):
    """Locate the program after any attached interpreter options such as -I."""
    return Path(next(argument for argument in command[1:] if not argument.startswith('-')))


def exiftool(path, arguments, *, write=False):
    command = exiftool_command()
    result = security.bounded_run([*command, *arguments, str(path)], timeout=180,
        reads=[exiftool_program(command), path],
        writes=[path, path.with_name(path.name + '_exiftool_tmp')] if write else [])
    if result.returncode or (write and '1 image files updated' not in result.stdout):
        raise RuntimeError('The date could not be saved safely: ' + (result.stderr or result.stdout)[-1000:])
    return result.stdout


def embedded(path):
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return audit.probe_image(path).get('embedded_creation_time')
    return audit.probe_ffprobe(path).get('embedded_creation_time')


def content_identity(path):
    """Hash encoded content separately from editable metadata."""
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        data = json.loads(exiftool(path, ['-ImageDataHash', '-json']))[0]
        fingerprint = data.get('ImageDataHash')
        if not fingerprint:
            raise ValueError('This image format cannot yet be verified for date editing. It has been left unchanged.')
        # Include display-critical attributes in addition to encoded image data.
        meta = security.image_request('metadata', {'source': str(path)}, reads=[path])
        return (fingerprint, meta.get('dimensions'), meta.get('exif_orientation'), meta.get('icc_sha256'))
    tool = security.resolve_tool('ffmpeg')
    if not tool:
        raise RuntimeError('The media verification tool is unavailable.')
    result = security.bounded_run([tool, '-nostdin', '-v', 'error', '-i', str(path),
        '-map', '0', '-c', 'copy', '-f', 'streamhash', '-hash', 'sha256', '-'],
        reads=[path], timeout=180, max_output=1024*1024)
    if result.returncode or not result.stdout.strip():
        raise ValueError('The media content cannot be verified for date editing. It has been left unchanged.')
    probe_result = security.bounded_run([security.resolve_tool('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], reads=[path], timeout=60)
    if probe_result.returncode:
        raise RuntimeError('The media metadata could not be verified.')
    probe = json.loads(probe_result.stdout)
    # Audio remuxing must retain existing user metadata, including artwork tags.
    def tags(values):
        return {k.casefold(): v for k, v in values.items()
                if k.casefold() not in {'date', 'creation_time', 'com.apple.quicktime.creationdate', 'encoder'}}
    return (result.stdout.strip(), tags(probe.get('format', {}).get('tags', {})),
            [tags(s.get('tags', {})) for s in probe.get('streams', [])])


def write_date(source, output, day):
    if source.suffix.lower() not in SUPPORTED:
        raise ValueError('Date editing is not available for this file format. The file has been left unchanged.')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError('Choose a valid calendar date.')
    chosen = dt.date.fromisoformat(day)
    current = str(embedded(source) or '')
    time = re.search(r'[ T](\d{2}:\d{2}:\d{2})', current)
    clock = time.group(1) if time else '00:00:00'
    stamp = chosen.strftime('%Y:%m:%d') + ' ' + clock
    before = content_identity(source)
    ext = source.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        exiftool(output, ['-overwrite_original', '-P', '-EXIF:DateTimeOriginal=' + stamp,
                         '-XMP-exif:DateTimeOriginal=' + stamp], write=True)
    elif ext in QUICKTIME_EXTENSIONS:
        exiftool(output, ['-overwrite_original', '-P', '-QuickTime:CreateDate=' + stamp,
                         '-Keys:CreationDate=' + day + 'T' + clock + 'Z'], write=True)
    else:
        # Remux only; every original encoded stream is copied and verified.
        output.unlink()  # coordinator created this private staging copy
        tool = security.resolve_tool('ffmpeg')
        result = security.bounded_run([tool, '-nostdin', '-v', 'error', '-i', str(source),
            '-map', '0', '-c', 'copy', '-map_metadata', '0', '-metadata', 'date=' + day,
            '-metadata', 'creation_time=' + day + 'T' + clock + 'Z',
            *(['-write_id3v2', '1'] if ext in {'.aif', '.aiff'} else []), str(output)],
            reads=[source], writes=[output], timeout=180)
        if result.returncode:
            raise RuntimeError('The date could not be saved safely: ' + result.stderr[-1000:])
    if before != content_identity(output):
        raise RuntimeError('The date edit did not preserve the media content and metadata. The original has been left unchanged.')
    if audit.parse_embedded_date(embedded(output)) != chosen:
        raise RuntimeError('The saved date could not be verified. The original has been left unchanged.')


def copy_attributes(source, output):
    """Keep macOS extended attributes, including Finder tags and resource forks."""
    import ctypes
    import os
    import shutil
    shutil.copystat(source, output, follow_symlinks=False)
    libc = ctypes.CDLL('libc.dylib', use_errno=True)
    setter = libc.setxattr
    setter.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    setter.restype = ctypes.c_int
    for key in audit._darwin_listxattr(source):
        data = audit._darwin_getxattr(source, key)
        if setter(os.fsencode(output), key.encode('utf-8'), data, len(data), 0, 1) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        if audit._darwin_getxattr(output, key) != data:
            raise RuntimeError('The original file attributes could not be preserved.')
