#!/usr/bin/env python3
"""Read-only media archive inventory and policy audit for macOS.

This program never renames, writes tags, converts, moves, or deletes media files.
Its only writes are its own SQLite database and Markdown report in --output-dir.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import datetime as dt
import hashlib
import json
import mimetypes
import os
import plistlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import unicodedata
import warnings
import media_security as security
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

VERSION = "0.1.4"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".3gp", ".mkv", ".webm", ".mts", ".m2ts"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif", ".flac", ".ogg", ".opus", ".amr", ".m4r"}
MASTER_EXTS = {".raf", ".raw", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".tif", ".tiff"}
PROJECT_EXTS = {".psd", ".psb", ".xmp", ".aup3", ".ai", ".indd", ".blend", ".cos", ".cop", ".cot", ".cof", ".comask", ".fh10"}
DOCUMENT_EXTS = {".pdf", ".csv", ".txt", ".md", ".zip", ".rar", ".7z"}
IGNORED_NAMES = {".DS_Store"}
DATE_YMD = re.compile(r"(?<!\d)(?P<y>19\d{2}|20\d{2})[-_](?P<m>0[1-9]|1[0-2])[-_](?P<d>0[1-9]|[12]\d|3[01])(?=\D|$)")
DATE_YYMMDD = re.compile(r"(?<!\d)(?P<y>\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])[-_](?=\D|$)")
YEAR_DIR = re.compile(r"^(19\d{2}|20\d{2})$")

DEFAULT_EXCLUDED_DIRECTORY_NAMES: list[str] = []

DEFAULT_CONFIG = {
    "date_evidence_policy": "embedded_only",
    "archive_age_years": 2,
    "compressed_tags": ["compressed-v2", "_compressed-v2"],
    "ignore_names": [".DS_Store"],
    "roots": {},
    "excluded_directory_names": DEFAULT_EXCLUDED_DIRECTORY_NAMES,
    "full_hash": False,
    "hash_algorithm": "sha256",
    "probe_media": True,
    "probe_unknown_with_file": True,
    "audio_min_size_mb": 10,
    "image_max_megapixels": 20,
    "streams_image_max_megapixels": 20,
    "photo_library_max_megapixels": 20
}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def run_cmd(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        p = security.bounded_run(args, timeout=timeout, reads=[Path(args[-1])])
        return p.returncode, p.stdout, p.stderr
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def norm_text(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def extension_of(path: Path) -> str:
    return path.suffix.lower()


def classify_extension(ext: str) -> str:
    if ext in IMAGE_EXTS: return "image"
    if ext in VIDEO_EXTS: return "video"
    if ext in AUDIO_EXTS: return "audio"
    if ext in MASTER_EXTS: return "master_image"
    if ext in PROJECT_EXTS: return "project"
    if ext in DOCUMENT_EXTS: return "document"
    if not ext: return "extensionless"
    return "unknown"


def parse_filename_date(name: str) -> Optional[dt.date]:
    m = DATE_YMD.search(name)
    if m:
        try: return dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError: pass
    m = DATE_YYMMDD.search(name)
    if m:
        year = 2000 + int(m["y"]) if int(m["y"]) <= 69 else 1900 + int(m["y"])
        try: return dt.date(year, int(m["m"]), int(m["d"]))
        except ValueError: pass
    return None


def calendar_years_before(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # Feb 29
        return day.replace(year=day.year - years, day=28)


def year_from_parts(parts: Iterable[str]) -> Optional[int]:
    for part in parts:
        if YEAR_DIR.match(part):
            return int(part)
    return None


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb", buffering=1024 * 1024) as f:
        while True:
            block = f.read(4 * 1024 * 1024)
            if not block: break
            h.update(block)
    return h.hexdigest()


def quick_hash(path: Path) -> str:
    """Inventory identity covers all bytes; old sampled plans require reanalysis."""
    h = hashlib.sha256()
    h.update(str(path.stat().st_size).encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_DARWIN_LIBC = None
if sys.platform == "darwin":
    try:
        _DARWIN_LIBC = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        _DARWIN_LIBC.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        _DARWIN_LIBC.getxattr.restype = ctypes.c_ssize_t
        _DARWIN_LIBC.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        _DARWIN_LIBC.listxattr.restype = ctypes.c_ssize_t
    except Exception:
        _DARWIN_LIBC = None


def _darwin_getxattr(path: Path, key: str) -> bytes:
    if _DARWIN_LIBC is None:
        raise OSError("Darwin xattr API unavailable")
    p = os.fsencode(path)
    k = key.encode("utf-8")
    # XATTR_NOFOLLOW = 0x0001. position is 0 for normal extended attributes.
    size = _DARWIN_LIBC.getxattr(p, k, None, 0, 0, 0x0001)
    if size < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))
    if size == 0:
        return b""
    buf = ctypes.create_string_buffer(size)
    got = _DARWIN_LIBC.getxattr(p, k, buf, size, 0, 0x0001)
    if got < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))
    return bytes(buf.raw[:got])


def _darwin_listxattr(path: Path) -> list[str]:
    if _DARWIN_LIBC is None:
        raise OSError("Darwin xattr API unavailable")
    p = os.fsencode(path)
    size = _DARWIN_LIBC.listxattr(p, None, 0, 0x0001)
    if size < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))
    if size == 0:
        return []
    buf = ctypes.create_string_buffer(size)
    got = _DARWIN_LIBC.listxattr(p, buf, size, 0x0001)
    if got < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))
    return sorted(x.decode("utf-8", "replace") for x in bytes(buf.raw[:got]).split(b"\0") if x)


def xattr_backend() -> str:
    if hasattr(os, "getxattr") and hasattr(os, "listxattr"):
        return "python_os"
    if _DARWIN_LIBC is not None:
        return "darwin_ctypes"
    if shutil.which("xattr"):
        return "xattr_cli"
    return "unavailable"


def _getxattr_bytes(path: Path, key: str) -> bytes:
    if hasattr(os, "getxattr"):
        return os.getxattr(path, key, follow_symlinks=False)
    if _DARWIN_LIBC is not None:
        return _darwin_getxattr(path, key)
    xattr_cmd = shutil.which("xattr")
    if xattr_cmd:
        rc, out, err = run_cmd([xattr_cmd, "-px", key, str(path)], timeout=10)
        if rc != 0:
            raise OSError(err.strip() or "xattr command failed")
        try:
            return bytes.fromhex("".join(out.split()))
        except ValueError as exc:
            raise OSError("invalid hex output from xattr") from exc
    raise OSError("no xattr reader available")


def list_xattrs(path: Path) -> list[str]:
    try:
        if hasattr(os, "listxattr"):
            return sorted(os.listxattr(path, follow_symlinks=False))
        if _DARWIN_LIBC is not None:
            return _darwin_listxattr(path)
        xattr_cmd = shutil.which("xattr")
        if xattr_cmd:
            rc, out, _ = run_cmd([xattr_cmd, str(path)], timeout=10)
            return sorted(x.strip() for x in out.splitlines() if x.strip()) if rc == 0 else []
    except OSError:
        pass
    return []


def finder_tags(path: Path) -> list[str]:
    key = "com.apple.metadata:_kMDItemUserTags"
    try:
        raw = _getxattr_bytes(path, key)
        obj = plistlib.loads(raw)
        if isinstance(obj, list):
            # Finder may append a color index after a newline.
            return sorted({str(x).split("\n", 1)[0] for x in obj if str(x).split("\n", 1)[0]})
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    return []


def file_mime(path: Path) -> Optional[str]:
    if not security.resolve_tool("file"):
        return mimetypes.guess_type(path.name)[0]
    rc, out, _ = run_cmd(["file", "--brief", "--mime-type", str(path)], timeout=10)
    return out.strip() if rc == 0 and out.strip() else mimetypes.guess_type(path.name)[0]


def kind_from_mime(mime: Optional[str]) -> Optional[str]:
    if not mime: return None
    if mime.startswith("image/"): return "image"
    if mime.startswith("video/"): return "video"
    if mime.startswith("audio/"): return "audio"
    return None


def probe_ffprobe(path: Path) -> dict[str, Any]:
    if not security.resolve_tool("ffprobe"):
        return {}
    rc, out, err = run_cmd([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,bit_rate,format_name:stream=index,codec_type,codec_name,width,height,channels,sample_rate,avg_frame_rate,r_frame_rate:stream_tags=rotate,creation_time,date,com.apple.quicktime.creationdate:format_tags=creation_time,date,com.apple.quicktime.creationdate",
        "-of", "json", str(path)
    ], timeout=60)
    if rc != 0:
        return {"probe_error": err.strip()[:1000] or f"ffprobe exit {rc}"}
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        return {"probe_error": f"ffprobe JSON: {exc}"}
    result: dict[str, Any] = {}
    fmt = data.get("format", {}) or {}
    for key in ("duration", "bit_rate", "format_name"):
        if key in fmt: result[key] = fmt[key]
    streams = data.get("streams", []) or []
    result.update(embedded_av_date(data))
    result["streams"] = streams
    for s in streams:
        if s.get("codec_type") == "video" and "video_codec" not in result:
            result.update({"video_codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height")})
            tags = s.get("tags") or {}
            if tags.get("rotate") is not None: result["rotation"] = tags.get("rotate")
        if s.get("codec_type") == "audio" and "audio_codec" not in result:
            result.update({"audio_codec": s.get("codec_name"), "channels": s.get("channels"), "sample_rate": s.get("sample_rate")})
    return result


def probe_image(path: Path) -> dict[str, Any]:
    if not security._WORKER:
        try:
            return security.image_request("probe", {"source": str(path.resolve())}, reads=[path])
        except Exception as exc:
            return {"probe_error": "Image could not be opened by the restricted decoder"}
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return {}
    try:
        # Pillow warns for unusually large images. For a local archive scan that is useful
        # audit information, but it should not look like a failed scan in Terminal.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path, formats=security.pillow_formats()) as im:
                frames = int(getattr(im, "n_frames", 1) or 1)
                pixels = int(im.width) * int(im.height)
                max_pixels = getattr(Image, "MAX_IMAGE_PIXELS", None)
                fmt = (im.format or "").upper()
                # JPEG/MPO and PSD can legitimately expose multiple frames/pages without
                # being animations. Animation is only asserted for formats where multiple
                # frames represent temporal playback.
                true_animated = bool(frames > 1 and fmt in {"GIF", "PNG", "WEBP"})
                multi_frame = bool(frames > 1 and not true_animated)
                return {
                    **embedded_image_date(im),
                    "width": im.width,
                    "height": im.height,
                    "megapixels": round(pixels / 1_000_000, 3),
                    "large_image": bool(max_pixels and pixels > max_pixels),
                    "image_format": im.format,
                    "image_mode": im.mode,
                    "animated": true_animated,
                    "multi_frame_image": multi_frame,
                    "frames": frames,
                    "has_alpha": "A" in im.getbands() or "transparency" in im.info,
                    "icc_profile": bool(im.info.get("icc_profile")),
                    "exif_present": bool(im.getexif()) if hasattr(im, "getexif") else False,
                }
    except Exception as exc:
        return {"probe_error": f"Pillow: {exc}"}


def parse_embedded_date(value: Any) -> Optional[dt.date]:
    if not value: return None
    text = str(value)
    # ISO/QuickTime timestamps and EXIF-like timestamps.
    m = re.search(r"(19\d{2}|20\d{2})[-:](\d{2})[-:](\d{2})", text)
    if not m: return None
    try: return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError: return None


def embedded_image_date(image) -> dict[str, Any]:
    """Read capture metadata inside the restricted image worker."""
    exif = image.getexif()
    try:
        photo_exif = exif.get_ifd(34665)
    except (KeyError, ValueError, TypeError, SyntaxError):
        photo_exif = {}
    candidates = []
    for tag, name in ((36867, "DateTimeOriginal"), (36868, "DateTimeDigitized")):
        candidates.extend((name, source.get(tag)) for source in (photo_exif, exif))
    # XMP is embedded metadata too. Read only explicit date fields, without
    # invoking an XML parser or resolving external references.
    xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp") or ""
    if isinstance(xmp, bytes):
        xmp = xmp.decode("utf-8", errors="replace")
    if len(xmp) <= 1024 * 1024:
        for field in ("DateTimeOriginal", "CreateDate"):
            for pattern in (rf'{field}\s*=\s*[\"\']([^\"\']+)', rf'<(?:\w+:)?{field}[^>]*>([^<]+)'):
                for match in re.finditer(pattern, xmp):
                    candidates.append(("XMP " + field, match.group(1)))
    candidates.append(("DateTime", exif.get(306)))
    candidates.extend((key, image.info.get(key)) for key in ("Creation Time", "creation_time", "date:create"))
    for field, value in candidates:
        if parse_embedded_date(value) is not None:
            return {"embedded_creation_time": str(value), "embedded_date_field": field}
    return {}


def embedded_av_date(probe: dict[str, Any]) -> dict[str, Any]:
    sources = [(probe.get("format") or {}).get("tags") or {}]
    sources += [stream.get("tags") or {} for stream in probe.get("streams") or []]
    for key in ("com.apple.quicktime.creationdate", "creation_time", "date"):
        for tags in sources:
            value = next((v for k,v in tags.items() if k.casefold() == key), None)
            if parse_embedded_date(value) is not None:
                return {"embedded_creation_time": value, "embedded_date_field": key}
    return {}


@dataclass
class Decision:
    safety: str
    action: str
    reason: str


def is_photo_library_path(rel: Path, root: Path) -> bool:
    names = {"photo_library", "photo library"}
    return any(part.casefold() in names for part in (*root.parts, *rel.parts[:-1]))


class Auditor:
    def __init__(self, root: Path, config: dict[str, Any], run_date: dt.date, output_dir: Path, full_hashing: bool, probe_media: bool):
        self.root = root.resolve()
        self.config = config
        self.run_date = run_date
        self.cutoff = calendar_years_before(run_date, int(config.get("archive_age_years", 2)))
        self.date_scope = dict(config.get("date_scope") or {"mode": "legacy"})
        self.output_dir = output_dir.resolve()
        self.full_hashing = full_hashing
        self.probe_media = probe_media
        self.root_dev = self.root.stat().st_dev
        self.rows: list[dict[str, Any]] = []
        self.issues: list[tuple[str, str, str]] = []
        self.name_buckets: dict[tuple[str, str], list[str]] = defaultdict(list)

    def relative(self, path: Path) -> Path:
        return path.relative_to(self.root)

    def root_policy(self, rel: Path) -> tuple[str, dict[str, Any]]:
        first = rel.parts[0] if rel.parts else ""
        return first, self.config.get("roots", {}).get(first, {"mode": "unknown"})

    def expected_kind(self, rel: Path) -> Optional[str]:
        return None

    def protected_photo_path(self, rel: Path) -> bool:
        # User-selected directory exclusions apply to every library layout.
        names = {str(value).casefold() for value in self.config.get("excluded_directory_names", DEFAULT_EXCLUDED_DIRECTORY_NAMES)}
        return any(part.casefold() in names for part in rel.parts[:-1])

    def resolve_date(self, row: dict[str, Any]) -> None:
        filename_date = parse_filename_date(row["name"])
        embedded_date = parse_embedded_date(row.get("embedded_creation_time"))
        birth_date = dt.datetime.fromtimestamp(row["birth_ts"]).date() if row.get("birth_ts") else None
        folder_year = row.get("folder_year")
        row["filename_date"] = filename_date.isoformat() if filename_date else None
        row["embedded_date"] = embedded_date.isoformat() if embedded_date else None
        row["birth_date"] = birth_date.isoformat() if birth_date else None
        row["embedded_date_role"] = "authoritative" if embedded_date else None
        # Other dates are retained only as diagnostic information. They never
        # determine eligibility or naming, including when embedded data is absent.
        row["folder_year_mismatch"] = bool(embedded_date and folder_year and embedded_date.year != int(folder_year))
        row["folder_year_role"] = "archive_year"
        row.update(best_date=embedded_date.isoformat() if embedded_date else None,
                   date_confidence="HIGH" if embedded_date else "UNKNOWN",
                   date_source="embedded" if embedded_date else None)

    def decide(self, row: dict[str, Any]) -> Decision:
        rel = Path(row["relpath"])
        root_name, policy = self.root_policy(rel)
        kind = row["detected_kind"]
        ext_kind = row["extension_kind"]
        tags = set(row.get("tags", []))
        compressed_tags = set(self.config.get("compressed_tags", []))

        if row["is_symlink"]:
            return Decision("RED", "PRESERVE", "symlink_not_followed")
        if row.get("cross_filesystem"):
            return Decision("RED", "PRESERVE", "cross_filesystem_boundary")
        if self.protected_photo_path(rel):
            return Decision("RED", "PRESERVE", "excluded_directory")
        if ext_kind in {"master_image", "project", "document"}:
            return Decision("RED", "PRESERVE", f"protected_or_nonmedia_extension:{row['extension'] or '[none]'}")
        if kind not in {"image", "video", "audio"}:
            return Decision("YELLOW", "REVIEW", f"unclassified_content:{kind}")

        # Date scope is evaluated before media diagnostics so files outside the selected
        # scope do not create review noise. Unknown/conflicting dates deliberately continue
        # into the normal review path because Veronica cannot safely determine scope.
        if row.get("best_date") and row.get("date_confidence") not in {"CONFLICT", "UNKNOWN"}:
            best_date = dt.date.fromisoformat(row["best_date"])
            scope_mode = str(self.date_scope.get("mode") or "legacy")

            if scope_mode in {"legacy", "older_than_two_years"}:
                if best_date >= self.cutoff:
                    return Decision("GREEN", "SKIP", "date_scope_excluded")
            elif scope_mode == "within":
                start = dt.date.fromisoformat(str(self.date_scope["start"]))
                end = dt.date.fromisoformat(str(self.date_scope["end"]))
                if not (start <= best_date <= end):
                    return Decision("GREEN", "SKIP", "date_scope_excluded")
            elif scope_mode == "outside":
                start = dt.date.fromisoformat(str(self.date_scope["start"]))
                end = dt.date.fromisoformat(str(self.date_scope["end"]))
                if start <= best_date <= end:
                    return Decision("GREEN", "SKIP", "date_scope_excluded")
            elif scope_mode == "all":
                pass
            else:
                return Decision("YELLOW", "REVIEW", "invalid_date_scope")

        if row.get("size") == 0:
            return Decision("YELLOW", "REVIEW", "empty_file")
        if row.get("probe_error"):
            return Decision("YELLOW", "REVIEW", "media_probe_failed")
        if row.get("extension", "").lower() == ".gif":
            return Decision("RED", "PRESERVE", "gif_preserved_by_manual_policy")
        if row.get("animated"):
            return Decision("RED", "PRESERVE", "true_animated_image")
        expected = row.get("expected_kind")
        if expected and expected != kind:
            return Decision("YELLOW", "REVIEW", f"category_mismatch:expected_{expected}_detected_{kind}")
        if row.get("date_confidence") == "UNKNOWN" or not row.get("best_date"):
            return Decision("YELLOW", "REVIEW", "embedded_date_missing")
        if row.get("date_confidence") == "CONFLICT":
            return Decision("YELLOW", "REVIEW", "date_conflict")
        if row.get("date_confidence") == "LOW":
            return Decision("YELLOW", "REVIEW", "date_low_confidence")
        if not row.get("best_date"):
            return Decision("YELLOW", "REVIEW", "no_eligibility_date")
        if tags & compressed_tags:
            return Decision("GREEN", "SKIP", "already_compressed_tag")

        # Once a file has passed the safety, date, probe, and protected-format
        # checks above, conversion eligibility is determined by detected media
        # type rather than by folder names. Veronica scan folders may use any
        # directory structure.
        if kind == "audio":
            min_bytes = int(
                float(self.config.get("audio_min_size_mb", 10)) * 1024 * 1024
            )
            if int(row.get("size") or 0) <= min_bytes:
                return Decision("GREEN", "SKIP", "audio_below_size_threshold")
            return Decision(
                "GREEN",
                "CANDIDATE",
                "eligible_audio_over_size_threshold",
            )

        if kind == "image":
            return Decision(
                "GREEN",
                "CANDIDATE",
                "eligible_image_for_policy_evaluation",
            )

        if kind == "video":
            return Decision(
                "GREEN",
                "CANDIDATE",
                "eligible_video_for_policy_evaluation",
            )

        return Decision("YELLOW", "REVIEW", "no_media_conversion_policy")

    def scan_file(self, path: Path, is_symlink: bool = False) -> None:
        rel = self.relative(path)
        try:
            st = path.lstat() if is_symlink else path.stat()
        except OSError as exc:
            self.issues.append((str(rel), "stat_failed", str(exc)))
            return
        ext = extension_of(path)
        ext_kind = classify_extension(ext)
        mime = None
        detected_kind = ext_kind
        if ext_kind in {"extensionless", "unknown"} or self.config.get("probe_unknown_with_file", True):
            mime = file_mime(path) if not is_symlink else None
            mime_kind = kind_from_mime(mime)
            if mime_kind: detected_kind = mime_kind
        tags = finder_tags(path) if not is_symlink else []
        xattrs = list_xattrs(path) if not is_symlink else []
        birth_ts = getattr(st, "st_birthtime", None)
        folder_year = year_from_parts(rel.parts[:-1])
        row: dict[str, Any] = {
            "relpath": str(rel), "name": path.name, "normalized_name": norm_text(path.name),
            "parent": str(rel.parent), "extension": ext, "extension_kind": ext_kind,
            "mime": mime, "detected_kind": detected_kind, "size": st.st_size,
            "mtime_ts": st.st_mtime, "birth_ts": birth_ts, "mode": stat.filemode(st.st_mode),
            "device": st.st_dev, "inode": st.st_ino, "is_symlink": is_symlink,
            "cross_filesystem": st.st_dev != self.root_dev, "folder_year": folder_year,
            "tags": tags, "xattrs": xattrs, "expected_kind": self.expected_kind(rel),
            "quick_hash": None, "full_hash": None,
        }
        if not is_symlink:
            try:
                row["quick_hash"] = quick_hash(path)
                if self.full_hashing: row["full_hash"] = file_hash(path, self.config.get("hash_algorithm", "sha256"))
            except (OSError, ValueError) as exc:
                row["hash_error"] = str(exc)

        probe: dict[str, Any] = {}
        # Zero-byte media is classified explicitly and is not sent to decoders/probers.
        if self.probe_media and not is_symlink and st.st_size > 0 and detected_kind in {"video", "audio"}:
            probe = probe_ffprobe(path)
        elif self.probe_media and not is_symlink and st.st_size > 0 and detected_kind == "image":
            probe = probe_image(path)
        row.update(probe)
        self.resolve_date(row)
        decision = self.decide(row)
        row.update(asdict(decision))
        # Detect normalization/case collisions inside a directory before any future renaming.
        collision_key = (row["parent"], unicodedata.normalize("NFC", row["name"]).casefold())
        self.name_buckets[collision_key].append(row["relpath"])
        self.rows.append(row)

    def walk(self, on_progress: Optional[Callable[[int, int], None]] = None) -> None:
        pending_files: list[tuple[Path, bool]] = []

        def visit_file(path: Path, is_symlink: bool) -> None:
            if on_progress is None:
                self.scan_file(path, is_symlink=is_symlink)
            else:
                pending_files.append((path, is_symlink))

        def onerror(exc: OSError) -> None:
            self.issues.append((getattr(exc, "filename", "?"), "walk_error", str(exc)))

        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True, followlinks=False, onerror=onerror):
            dpath = Path(dirpath)
            try:
                if dpath != self.root and dpath.stat().st_dev != self.root_dev:
                    rel = self.relative(dpath)
                    self.issues.append((str(rel), "cross_filesystem_directory", "not descended"))
                    dirnames[:] = []
                    continue
            except OSError:
                dirnames[:] = []
                continue
            # Do not descend into directory symlinks.
            kept = []
            for name in dirnames:
                p = dpath / name
                if p.is_symlink():
                    visit_file(p, is_symlink=True)
                else:
                    kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                if name in set(self.config.get("ignore_names", [])):
                    continue
                p = dpath / name
                visit_file(p, is_symlink=p.is_symlink())

        if on_progress is not None:
            total = len(pending_files)
            on_progress(0, total)
            for completed, (path, is_symlink) in enumerate(pending_files, 1):
                self.scan_file(path, is_symlink=is_symlink)
                on_progress(completed, total)

        collisions = [paths for paths in self.name_buckets.values() if len(paths) > 1]
        collision_members = {p for group in collisions for p in group}
        for row in self.rows:
            if row["relpath"] in collision_members:
                row["name_collision"] = True
                if row["action"] == "CANDIDATE":
                    row.update(safety="YELLOW", action="REVIEW", reason="unicode_or_case_name_collision")
            else:
                row["name_collision"] = False

    def write_sqlite(self, db_path: Path) -> None:
        if db_path.exists(): db_path.unlink()
        con = sqlite3.connect(db_path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE run_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        meta = {"tool_version": VERSION, "root": str(self.root), "run_date": self.run_date.isoformat(), "cutoff": self.cutoff.isoformat(), "full_hash": str(self.full_hashing), "probe_media": str(self.probe_media)}
        con.executemany("INSERT INTO run_meta(key,value) VALUES (?,?)", meta.items())
        con.execute("""CREATE TABLE files (
            relpath TEXT PRIMARY KEY, name TEXT, normalized_name TEXT, parent TEXT, extension TEXT,
            extension_kind TEXT, mime TEXT, detected_kind TEXT, size INTEGER, mtime_ts REAL, birth_ts REAL,
            mode TEXT, device INTEGER, inode INTEGER, is_symlink INTEGER, cross_filesystem INTEGER,
            folder_year INTEGER, tags_json TEXT, xattrs_json TEXT, expected_kind TEXT,
            quick_hash TEXT, full_hash TEXT, filename_date TEXT, embedded_date TEXT, birth_date TEXT,
            best_date TEXT, date_confidence TEXT, date_source TEXT, embedded_date_role TEXT, folder_year_mismatch INTEGER,
            width INTEGER, height INTEGER, duration REAL, bit_rate TEXT, video_codec TEXT, audio_codec TEXT,
            channels INTEGER, sample_rate TEXT, has_alpha INTEGER, animated INTEGER, multi_frame_image INTEGER, frames INTEGER, rotation TEXT,
            probe_error TEXT, name_collision INTEGER, safety TEXT, action TEXT, reason TEXT,
            raw_json TEXT NOT NULL
        )""")
        for r in self.rows:
            vals = {
                "tags_json": json.dumps(r.get("tags", []), ensure_ascii=False),
                "xattrs_json": json.dumps(r.get("xattrs", []), ensure_ascii=False),
                "raw_json": json.dumps(r, ensure_ascii=False, default=str),
            }
            for key in ["relpath","name","normalized_name","parent","extension","extension_kind","mime","detected_kind","size","mtime_ts","birth_ts","mode","device","inode","is_symlink","cross_filesystem","folder_year","expected_kind","quick_hash","full_hash","filename_date","embedded_date","birth_date","best_date","date_confidence","date_source","embedded_date_role","folder_year_mismatch","width","height","duration","bit_rate","video_codec","audio_codec","channels","sample_rate","has_alpha","animated","multi_frame_image","frames","rotation","probe_error","name_collision","safety","action","reason"]:
                vals[key] = r.get(key)
            columns = list(vals.keys())
            con.execute(f"INSERT INTO files ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [vals[c] for c in columns])
        con.execute("CREATE TABLE issues (relpath TEXT, code TEXT, detail TEXT)")
        con.executemany("INSERT INTO issues VALUES (?,?,?)", self.issues)
        con.execute("CREATE INDEX idx_files_action ON files(action)")
        con.execute("CREATE INDEX idx_files_safety ON files(safety)")
        con.execute("CREATE INDEX idx_files_kind ON files(detected_kind)")
        con.execute("CREATE INDEX idx_files_best_date ON files(best_date)")
        con.commit(); con.close()

    def write_analysis_json(self, path: Path) -> None:
        """Write a small diagnostic summary for policy tuning.

        This intentionally exports patterns rather than every row. It includes aggregate
        distributions, bounded samples, and complete lists only for rare/high-value anomalies.
        """
        SAMPLE_LIMIT = 25
        RARE_COMPLETE_LIMIT = 200
        TOP_LARGEST = 20

        def root_of(r: dict[str, Any]) -> str:
            parts = Path(r["relpath"]).parts
            return parts[0] if parts else ""

        def year_of(r: dict[str, Any]) -> str:
            if r.get("best_date"):
                return str(r["best_date"])[:4]
            if r.get("folder_year"):
                return str(r["folder_year"])
            return "unknown"

        def compact_row(r: dict[str, Any]) -> dict[str, Any]:
            keep = [
                "relpath", "detected_kind", "extension", "mime", "size",
                "folder_year", "folder_year_mismatch", "folder_year_role",
                "filename_date", "embedded_date", "embedded_date_role", "birth_date", "best_date",
                "date_confidence", "date_source", "expected_kind", "tags",
                "width", "height", "megapixels", "large_image", "duration", "bit_rate",
                "video_codec", "audio_codec", "channels", "sample_rate", "has_alpha",
                "animated", "multi_frame_image", "frames", "rotation", "probe_error",
                "name_collision", "safety", "action", "reason"
            ]
            return {k: r.get(k) for k in keep if r.get(k) not in (None, False, [], "")}

        def nested_counts(key_fn) -> dict[str, dict[str, int]]:
            out: dict[str, Counter] = defaultdict(Counter)
            for r in self.rows:
                a, b = key_fn(r)
                out[str(a)][str(b)] += 1
            return {k: dict(v.most_common()) for k, v in sorted(out.items())}

        safety = Counter(r["safety"] for r in self.rows)
        actions = Counter(r["action"] for r in self.rows)
        kinds = Counter(r["detected_kind"] for r in self.rows)
        reasons = Counter(r["reason"] for r in self.rows)
        roots = Counter(root_of(r) for r in self.rows)
        extensions = Counter((r.get("extension") or "[none]") for r in self.rows)
        date_conf = Counter((r.get("date_confidence") or "UNKNOWN") for r in self.rows)
        years = Counter(year_of(r) for r in self.rows)
        total_bytes = sum(int(r.get("size") or 0) for r in self.rows)

        samples_by_reason: dict[str, list[dict[str, Any]]] = {}
        complete_rare: dict[str, list[dict[str, Any]]] = {}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in self.rows:
            grouped[r["reason"]].append(r)
        for reason, rows in sorted(grouped.items()):
            if reason in {"eligible_streams_image", "eligible_finished_raster_needs_conversion_policy_check", "too_new", "root_policy_read_only_archive"}:
                continue
            samples_by_reason[reason] = [compact_row(r) for r in rows[:SAMPLE_LIMIT]]
            if len(rows) <= RARE_COMPLETE_LIMIT and (
                "probe" in reason or "unclassified" in reason or "mismatch" in reason
                or "collision" in reason or "unknown" in reason or "boundary" in reason
            ):
                complete_rare[reason] = [compact_row(r) for r in rows]

        anomalies = [r for r in self.rows if (
            r.get("probe_error") or r.get("name_collision") or r.get("large_image")
            or str(r.get("reason", "")).startswith("category_mismatch")
            or str(r.get("reason", "")).startswith("unclassified_content")
        )]

        largest = sorted(self.rows, key=lambda r: int(r.get("size") or 0), reverse=True)[:TOP_LARGEST]
        largest_by_kind = {}
        for kind in sorted(kinds):
            rows = [r for r in self.rows if r.get("detected_kind") == kind]
            largest_by_kind[kind] = [compact_row(r) for r in sorted(rows, key=lambda r: int(r.get("size") or 0), reverse=True)[:TOP_LARGEST]]

        # Finder tag diagnostics. The permanent compressed-v2 tag is a core safety gate,
        # so the summary must prove that macOS tags were actually observed by this run.
        configured_compressed_tags = set(self.config.get("compressed_tags", []))
        tag_counter = Counter(tag for r in self.rows for tag in (r.get("tags") or []))
        files_with_any_tags = sum(1 for r in self.rows if r.get("tags"))
        compressed_rows = [r for r in self.rows if set(r.get("tags") or []) & configured_compressed_tags]
        compressed_by_root = Counter(root_of(r) for r in compressed_rows)
        compressed_by_kind = Counter(r.get("detected_kind") or "unknown" for r in compressed_rows)

        def image_policy_stats(rows: list[dict[str, Any]], target_mp: float) -> dict[str, Any]:
            ext_counts = Counter((r.get("extension") or "[none]") for r in rows)
            known_mp = [r for r in rows if isinstance(r.get("megapixels"), (int, float))]
            above = sum(1 for r in known_mp if float(r["megapixels"]) > target_mp)
            at_or_below = sum(1 for r in known_mp if float(r["megapixels"]) <= target_mp)
            return {
                "files": len(rows),
                "target_megapixels": target_mp,
                "dimensions_known": len(known_mp),
                "dimensions_unknown": len(rows) - len(known_mp),
                "above_target": above,
                "at_or_below_target": at_or_below,
                "jpeg": sum(1 for r in rows if (r.get("extension") or "").lower() in {".jpg", ".jpeg"}),
                "png": sum(1 for r in rows if (r.get("extension") or "").lower() == ".png"),
                "png_with_alpha": sum(1 for r in rows if (r.get("extension") or "").lower() == ".png" and r.get("has_alpha")),
                "true_animated": sum(1 for r in rows if r.get("animated")),
                "multi_frame_jpeg": sum(1 for r in rows if (r.get("extension") or "").lower() in {".jpg", ".jpeg"} and r.get("multi_frame_image")),
                "large_image": sum(1 for r in rows if r.get("large_image")),
                "extensions": dict(ext_counts.most_common()),
            }

        streams_image_rows = [r for r in self.rows if str(r.get("relpath", "")).startswith("Streams/Image/") and r.get("detected_kind") == "image"]
        streams_image_candidates = [r for r in self.rows if r.get("reason") == "eligible_streams_image"]
        photo_finished_candidates = [r for r in self.rows if r.get("reason") == "eligible_finished_raster_needs_conversion_policy_check"]

        audio_rows = [r for r in self.rows if r.get("detected_kind") == "audio" and str(r.get("relpath", "")).startswith("Streams/Audio/")]
        audio_over_threshold = [r for r in audio_rows if int(r.get("size") or 0) > int(float(self.config.get("audio_min_size_mb", 10)) * 1024 * 1024)]
        audio_bitrates = Counter(str(r.get("bit_rate") or "unknown") for r in audio_over_threshold)
        audio_codecs = Counter(str(r.get("audio_codec") or "unknown") for r in audio_over_threshold)
        audio_channels = Counter(str(r.get("channels") or "unknown") for r in audio_over_threshold)
        audio_sample_rates = Counter(str(r.get("sample_rate") or "unknown") for r in audio_over_threshold)

        payload = {
            "schema_version": 3,
            "tool_version": VERSION,
            "root": str(self.root),
            "run_date": self.run_date.isoformat(),
            "eligibility_cutoff": self.cutoff.isoformat(),
            "files_inventoried": len(self.rows),
            "inventoried_bytes": total_bytes,
            "summary": {
                "safety": dict(safety), "actions": dict(actions), "kinds": dict(kinds),
                "roots": dict(roots), "date_confidence": dict(date_conf),
                "reasons": dict(reasons), "extensions": dict(extensions.most_common()),
                "years": dict(sorted(years.items())), "scanner_issues": len(self.issues),
            },
            "finder_tags": {
                "reader_available": xattr_backend() != "unavailable",
                "reader_backend": xattr_backend(),
                "configured_compressed_tags": sorted(configured_compressed_tags),
                "files_with_any_tags": files_with_any_tags,
                "unique_tags": len(tag_counter),
                "top_tags": dict(tag_counter.most_common(50)),
                "files_with_compressed_tag": len(compressed_rows),
                "compressed_tag_by_root": dict(compressed_by_root),
                "compressed_tag_by_kind": dict(compressed_by_kind),
                "already_compressed_skips": reasons.get("already_compressed_tag", 0),
                "candidate_files_without_compressed_tag": sum(1 for r in self.rows if r.get("action") == "CANDIDATE" and not (set(r.get("tags") or []) & configured_compressed_tags)),
            },
            "image_policy": {
                "streams_all_images": image_policy_stats(streams_image_rows, float(self.config.get("streams_image_max_megapixels", 10))),
                "streams_current_candidates": image_policy_stats(streams_image_candidates, float(self.config.get("streams_image_max_megapixels", 10))),
                "photo_library_finished_candidates": image_policy_stats(photo_finished_candidates, float(self.config.get("photo_library_max_megapixels", 20))),
            },
            "audio_policy": {
                "minimum_size_mb": float(self.config.get("audio_min_size_mb", 10)),
                "streams_audio_files": len(audio_rows),
                "over_size_threshold": len(audio_over_threshold),
                "current_candidates": reasons.get("eligible_streams_audio_over_size_threshold", 0),
                "below_threshold_skips": reasons.get("audio_below_size_threshold", 0),
                "bitrates_over_threshold": dict(audio_bitrates.most_common()),
                "codecs_over_threshold": dict(audio_codecs.most_common()),
                "channels_over_threshold": dict(audio_channels.most_common()),
                "sample_rates_over_threshold": dict(audio_sample_rates.most_common()),
                "sample_over_threshold": [compact_row(r) for r in audio_over_threshold[:25]],
            },
            "breakdowns": {
                "reason_by_root": nested_counts(lambda r: (r["reason"], root_of(r))),
                "reason_by_kind": nested_counts(lambda r: (r["reason"], r.get("detected_kind") or "unknown")),
                "reason_by_extension": nested_counts(lambda r: (r["reason"], r.get("extension") or "[none]")),
                "date_confidence_by_root": nested_counts(lambda r: (r.get("date_confidence") or "UNKNOWN", root_of(r))),
                "date_source_by_root": nested_counts(lambda r: (r.get("date_source") or "unknown", root_of(r))),
            },
            "samples_by_reason": samples_by_reason,
            "complete_rare_anomalies_by_reason": complete_rare,
            "notable_anomalies": [compact_row(r) for r in anomalies[:500]],
            "largest_files": [compact_row(r) for r in largest],
            "largest_by_kind": largest_by_kind,
            "scanner_issues": [{"relpath": p, "code": c, "detail": d} for p, c, d in self.issues[:500]],
            "export_limits": {
                "sample_per_reason": SAMPLE_LIMIT, "complete_rare_reason_max_rows": RARE_COMPLETE_LIMIT,
                "notable_anomalies_max": 500, "largest_per_group": TOP_LARGEST, "scanner_issues_max": 500
            }
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    def write_report(self, report_path: Path) -> None:
        actions = Counter(r["action"] for r in self.rows)
        safety = Counter(r["safety"] for r in self.rows)
        kinds = Counter(r["detected_kind"] for r in self.rows)
        reasons = Counter(r["reason"] for r in self.rows)
        roots = Counter((Path(r["relpath"]).parts[0] if Path(r["relpath"]).parts else "") for r in self.rows)
        total_bytes = sum(int(r.get("size") or 0) for r in self.rows)
        photo_folder_mismatches = sum(1 for r in self.rows if r.get("folder_year_mismatch") and str(r.get("relpath", "")).startswith("Photo_Library/"))
        large_images = sum(1 for r in self.rows if r.get("large_image"))
        def gib(n: int) -> str: return f"{n / 1024**3:.2f} GiB"
        lines = [
            "# Media audit report", "",
            f"- Tool version: `{VERSION}`", f"- Root: `{self.root}`", f"- Run date: **{self.run_date.isoformat()}**",
            f"- Eligibility cutoff: **before {self.cutoff.isoformat()}**", f"- Files inventoried: **{len(self.rows):,}**", f"- Inventoried size: **{gib(total_bytes)}**", "",
            "## Safety summary", "",
            "| Safety | Files |", "|---|---:|"
        ]
        for k in ["GREEN", "YELLOW", "RED"]: lines.append(f"| {k} | {safety.get(k, 0):,} |")
        lines += ["", "## Proposed actions (audit only)", "", "| Action | Files |", "|---|---:|"]
        for k, v in actions.most_common(): lines.append(f"| {k} | {v:,} |")
        lines += ["", "## Detected content kinds", "", "| Kind | Files |", "|---|---:|"]
        for k, v in kinds.most_common(): lines.append(f"| {k} | {v:,} |")
        lines += ["", "## Top-level roots", "", "| Root | Files |", "|---|---:|"]
        for k, v in roots.most_common(): lines.append(f"| {k} | {v:,} |")
        lines += ["", "## Most common decisions", "", "| Reason | Files |", "|---|---:|"]
        for k, v in reasons.most_common(30): lines.append(f"| `{k}` | {v:,} |")
        configured_compressed_tags = set(self.config.get("compressed_tags", []))
        files_with_any_tags = sum(1 for r in self.rows if r.get("tags"))
        compressed_tag_files = sum(1 for r in self.rows if set(r.get("tags") or []) & configured_compressed_tags)
        likely_processing_dates = sum(1 for r in self.rows if r.get("embedded_date_role") == "likely_processing_date")
        timezone_boundaries = sum(1 for r in self.rows if r.get("embedded_date_role") == "timezone_boundary")
        multi_frame_jpegs = sum(1 for r in self.rows if (r.get("extension") or "").lower() in {".jpg", ".jpeg"} and r.get("multi_frame_image"))
        empty_files = sum(1 for r in self.rows if int(r.get("size") or 0) == 0)
        lines += ["", "## Advisory observations", "",
                  f"- Photo Library folder-year mismatches (informational, not automatically REVIEW): **{photo_folder_mismatches:,}**",
                  f"- Images above Pillow's normal large-image warning threshold: **{large_images:,}**",
                  f"- Finder-tagged files detected: **{files_with_any_tags:,}**",
                  f"- Files carrying a configured compressed tag: **{compressed_tag_files:,}**",
                  f"- Embedded video dates treated as likely later processing dates: **{likely_processing_dates:,}**",
                  f"- Embedded/filename dates accepted as +/-1 day timezone boundaries: **{timezone_boundaries:,}**",
                  f"- Multi-frame JPEG/MPO-like images (not treated as animation): **{multi_frame_jpegs:,}**",
                  f"- Zero-byte files: **{empty_files:,}**"]
        review = [r for r in self.rows if r["action"] == "REVIEW"]
        if review:
            lines += ["", "## Review queue", "", "The audit does **not** modify these files.", "", "| Path | Kind | Date confidence | Reason |", "|---|---|---|---|"]
            for r in review[:500]:
                path = r["relpath"].replace("|", "\\|")
                lines.append(f"| `{path}` | {r['detected_kind']} | {r.get('date_confidence') or ''} | `{r['reason']}` |")
            if len(review) > 500: lines.append(f"\n_Review queue truncated in Markdown ({len(review)-500:,} more); SQLite contains all rows._")
        if self.issues:
            lines += ["", "## Scanner issues", "", "| Path | Code | Detail |", "|---|---|---|"]
            for p, c, d in self.issues[:200]:
                detail = d.replace('|', '\\|')
                lines.append(f"| `{p}` | `{c}` | {detail} |")
        lines += ["", "## Important", "", "This is a **read-only audit**. `CANDIDATE` means 'eligible for a future conversion-policy evaluation', not 'safe to delete or overwrite'."]
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_config(path: Optional[Path]) -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not path: return cfg
    user = json.loads(path.read_text(encoding="utf-8"))
    def merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict): merge(dst[k], v)
            else: dst[k] = v
    merge(cfg, user)
    return cfg


def command_scan(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not root.is_dir():
        eprint(f"ERROR: media root is not a directory: {root}"); return 2
    output = Path(args.output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    # Refuse to put outputs inside the media archive: keeps the audit self-contained and avoids rescanning itself.
    try:
        output.resolve().relative_to(root.resolve())
        eprint("ERROR: --output-dir must be outside the media root."); return 2
    except ValueError:
        pass
    config = load_config(Path(args.config).expanduser() if args.config else None)
    run_date = dt.date.fromisoformat(args.run_date) if args.run_date else dt.date.today()
    full_hashing = bool(args.full_hash or config.get("full_hash"))
    probe_media = not args.no_probe and bool(config.get("probe_media", True))
    auditor = Auditor(root, config, run_date, output, full_hashing, probe_media)
    print(f"Media Audit {VERSION}")
    print(f"Root: {root}")
    print(f"Cutoff: files before {auditor.cutoff.isoformat()}")
    print("Mode: READ ONLY (media files will not be changed)")
    auditor.walk()
    stamp = run_date.isoformat()
    db_path = output / f"media-audit-{stamp}.sqlite"
    report_path = output / f"media-audit-{stamp}.md"
    analysis_path = output / f"media-audit-summary-{stamp}.json"
    if not args.no_sqlite:
        auditor.write_sqlite(db_path)
    auditor.write_report(report_path)
    auditor.write_analysis_json(analysis_path)
    print(f"Inventoried: {len(auditor.rows):,} files")
    if not args.no_sqlite:
        print(f"Database: {db_path}")
    else:
        print("Database: skipped (--no-sqlite)")
    print(f"Report:   {report_path}")
    print(f"Summary:  {analysis_path}")
    return 0



def command_tags(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not root.is_dir():
        eprint(f"ERROR: media root is not a directory: {root}"); return 2
    output = Path(args.output_dir).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    try:
        output.resolve().relative_to(root.resolve())
        eprint("ERROR: --output-dir must be outside the media root."); return 2
    except ValueError:
        pass
    config = load_config(Path(args.config).expanduser() if args.config else None)
    compressed_tags = set(config.get("compressed_tags", []))
    backend = xattr_backend()
    print(f"Media Audit {VERSION} Finder-tag diagnostic")
    print(f"Root: {root}")
    print(f"xattr backend: {backend}")
    print("Mode: READ ONLY (media files will not be changed)")
    if backend == "unavailable":
        eprint("ERROR: no Finder-tag/xattr reader is available on this system.")
        return 2

    root_dev = root.stat().st_dev
    total = 0
    regular = 0
    tagged = 0
    compressed = 0
    tag_counter: Counter[str] = Counter()
    compressed_by_root: Counter[str] = Counter()
    tagged_by_root: Counter[str] = Counter()
    samples_by_tag: dict[str, list[str]] = defaultdict(list)
    compressed_samples: list[str] = []
    errors: list[dict[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        d = Path(dirpath)
        # Do not cross onto another mounted filesystem.
        kept_dirs = []
        for name in dirnames:
            child = d / name
            try:
                st = child.lstat()
                if stat.S_ISLNK(st.st_mode) or st.st_dev != root_dev:
                    continue
                kept_dirs.append(name)
            except OSError:
                continue
        dirnames[:] = kept_dirs
        for name in filenames:
            path = d / name
            total += 1
            try:
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode) or st.st_dev != root_dev:
                    continue
                regular += 1
                tags = finder_tags(path)
            except OSError as exc:
                if len(errors) < 100:
                    errors.append({"path": str(path.relative_to(root)), "error": str(exc)})
                continue
            if not tags:
                continue
            tagged += 1
            rel = str(path.relative_to(root))
            top = rel.split(os.sep, 1)[0] if os.sep in rel else rel
            tagged_by_root[top] += 1
            for tag in tags:
                tag_counter[tag] += 1
                if len(samples_by_tag[tag]) < 20:
                    samples_by_tag[tag].append(rel)
            if set(tags) & compressed_tags:
                compressed += 1
                compressed_by_root[top] += 1
                if len(compressed_samples) < 100:
                    compressed_samples.append(rel)

    payload = {
        "schema_version": 1,
        "tool_version": VERSION,
        "root": str(root),
        "xattr_backend": backend,
        "configured_compressed_tags": sorted(compressed_tags),
        "files_seen": total,
        "regular_files_checked": regular,
        "files_with_any_tags": tagged,
        "files_with_compressed_tag": compressed,
        "unique_tags": len(tag_counter),
        "top_tags": dict(tag_counter.most_common(100)),
        "tagged_by_root": dict(tagged_by_root),
        "compressed_tag_by_root": dict(compressed_by_root),
        "compressed_samples": compressed_samples,
        "samples_by_tag": dict(samples_by_tag),
        "errors": errors,
    }
    out = output / "media-audit-tags.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Files checked: {regular:,}")
    print(f"Finder-tagged: {tagged:,}")
    print(f"Compressed-tagged: {compressed:,}")
    print(f"Output: {out}")
    return 0

def command_doctor(args: argparse.Namespace) -> int:
    print(f"Media Audit {VERSION} dependency check")
    for tool in ["file", "ffprobe", "exiftool", "xattr"]:
        print(f"{tool:10} {'FOUND ' + shutil.which(tool) if shutil.which(tool) else 'not found (optional)'}")
    try:
        import PIL  # type: ignore
        print(f"Pillow     FOUND {getattr(PIL, '__version__', '')}")
    except ImportError:
        print("Pillow     not found (optional, recommended for image details)")
    print(f"Python     {sys.version.split()[0]}")
    print(f"xattr API  {xattr_backend()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only media archive inventory and safety audit")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="scan a media root without modifying it")
    scan.add_argument("--root", required=True)
    scan.add_argument("--output-dir", required=True)
    scan.add_argument("--config")
    scan.add_argument("--run-date", help="YYYY-MM-DD; defaults to today")
    scan.add_argument("--full-hash", action="store_true", help="SHA-256 every file (slower, enables exact duplicate analysis later)")
    scan.add_argument("--no-probe", action="store_true", help="skip Pillow/ffprobe media probing")
    scan.add_argument("--no-sqlite", action="store_true", help="skip the large full SQLite inventory; still writes Markdown + compact JSON")
    scan.set_defaults(func=command_scan)
    tags = sub.add_parser("tags", help="fast read-only Finder-tag/xattr diagnostic")
    tags.add_argument("--root", required=True)
    tags.add_argument("--output-dir", required=True)
    tags.add_argument("--config")
    tags.set_defaults(func=command_tags)
    doctor = sub.add_parser("doctor", help="show optional dependencies")
    doctor.set_defaults(func=command_doctor)
    args = parser.parse_args()
    return int(args.func(args))

if __name__ == "__main__":
    raise SystemExit(main())
