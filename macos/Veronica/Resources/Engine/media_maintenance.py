#!/usr/bin/env python3
"""Veronica media planner.

v0.4.1 adds a bounded batch commit wrapper around the proven one-item quarantine transaction.

v0.4.0 added a deliberately one-item commit/quarantine path and explicit rollback.

v0.3.3 added a guaranteed personal Finder-tag preservation probe in staging.

v0.3.2 added native macOS creation-time restoration and live Finder-tag sample selection.

v0.3.1 added diversified staging samples and metadata verification.

v0.3.0 added a staging-only executor. It may create converted copies inside the state
directory, but it never renames, retags, moves, overwrites, or deletes source media.
It verifies immutable-plan source identity before staging and validates staged outputs.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import math
import json
import os
import re
import plistlib
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import time
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import media_audit as audit

VERSION = "0.13.2"
SCHEMA_VERSION = 9
PRODUCT_NAME = "Veronica"
DEFAULT_STATE_DIR = "~/Library/Application Support/Veronica"
LEGACY_STATE_DIR = "~/Documents/Media Maintenance"
SETTINGS_FILENAME = "settings.json"

_EVENT_STREAM = None

DEFAULT_CONFIG: dict[str, Any] = {
    **audit.DEFAULT_CONFIG,
    "legacy_processing_tags": ["compressed-v1", "compressed-v2", "_compressed-v2"],
    "legacy_v2_tags": ["compressed-v2", "_compressed-v2"],
    "personal_tags_exclude": ["compressed-v1", "compressed-v2", "_compressed-v2", "temp-1", "temp-2"],
    "video_preset_file": "preset-720P.json",
    "streams_jpeg_quality": 50,
    "photo_library_jpeg_quality": 70,
    "minimum_saving_percent": 10.0,
    "minimum_saving_bytes": 1048576,
    "stage_copy_personal_finder_tags": True,
    "filename_standardization_enabled": True,
    "filename_date_format": "YYYY-MM-DD_",
    "filename_max_bytes": 180,
    "require_creation_date_before_commit": True,
    "creation_time_tolerance_seconds": 1.0,
    "video_aspect_ratio_tolerance": 0.005,
    "video_duration_tolerance_seconds": 0.10,
    "video_duration_tolerance_fraction": 0.0025,
    "video_frame_rate_tolerance_fraction": 0.01,
    "video_max_storage_edge": 1280,
    "video_review_hdr": True,
    "video_review_extra_streams": True,
    "video_review_vfr": True,
    "video_vfr_min_timing_intervals": 10,
    "video_vfr_cfr_like_max_outside_5_fraction": 0.01,
    "video_vfr_cfr_like_max_p95_p05_spread": 1.05,
    "video_review_multichannel_audio": True,
    "policies": {
        "streams_image": "streams-image-10mp-v1",
        "photo_library_image": "photo-library-image-20mp-v1",
        "streams_video": "streams-video-handbrake-square-pixel-720p-v4-no-autocrop",
        "streams_audio": "streams-audio-mp3-128k-v1",
    },
}


def load_config(path: Optional[Path]) -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path:
        user = json.loads(path.read_text(encoding="utf-8"))
        def merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    merge(dst[k], v)
                else:
                    dst[k] = v
        merge(cfg, user)
    # Auditor uses compressed_tags. Include v2 only: v1 is historical evidence, not current-policy completion.
    cfg["compressed_tags"] = list(cfg.get("legacy_v2_tags", []))
    return cfg


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_state_dir() -> Path:
    return Path(DEFAULT_STATE_DIR).expanduser().resolve()


def legacy_state_dir() -> Path:
    return Path(LEGACY_STATE_DIR).expanduser().resolve()




def settings_path(state_dir: Path) -> Path:
    return state_dir / SETTINGS_FILENAME


def load_product_settings(state_dir: Path) -> dict[str, Any]:
    path = settings_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid_veronica_settings:{exc}")
    return data if isinstance(data, dict) else {}


def save_product_settings(state_dir: Path, data: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = settings_path(state_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def filename_product_settings(state_dir: Path) -> dict[str, Any]:
    """Return validated effective filename settings for the native app."""
    saved = load_product_settings(state_dir)

    enabled = saved.get(
        "filename_standardization_enabled",
        DEFAULT_CONFIG["filename_standardization_enabled"],
    )
    date_format = saved.get(
        "filename_date_format",
        DEFAULT_CONFIG["filename_date_format"],
    )
    max_bytes = saved.get(
        "filename_max_bytes",
        DEFAULT_CONFIG["filename_max_bytes"],
    )

    enabled = bool(enabled)
    date_format = str(date_format or "YYYY-MM-DD_")
    if date_format not in _SUPPORTED_FILENAME_DATE_FORMATS:
        date_format = "YYYY-MM-DD_"

    try:
        max_bytes = int(max_bytes)
    except (TypeError, ValueError):
        max_bytes = int(DEFAULT_CONFIG["filename_max_bytes"])

    max_bytes = min(max(max_bytes, 32), 255)

    return {
        "enabled": enabled,
        "date_format": date_format,
        "max_bytes": max_bytes,
    }


def apply_product_filename_settings(cfg: dict[str, Any], state_dir: Path) -> dict[str, Any]:
    """Overlay persisted Veronica filename preferences onto engine config."""
    result = json.loads(json.dumps(cfg))
    values = filename_product_settings(state_dir)
    result["filename_standardization_enabled"] = values["enabled"]
    result["filename_date_format"] = values["date_format"]
    result["filename_max_bytes"] = values["max_bytes"]
    return result


def date_scope_product_settings(
    state_dir: Path,
    run_date: Optional[dt.date] = None,
) -> dict[str, Any]:
    """Return the validated effective date-scope policy.

    The annual calendar policy is the product default. Explicit saved
    settings may opt into all, within, or outside date scopes.
    """
    saved = load_product_settings(state_dir)
    mode = str(saved.get("date_scope_mode") or "legacy")

    if mode not in {"legacy", "all", "within", "outside"}:
        mode = "all"

    start = saved.get("date_scope_start")
    end = saved.get("date_scope_end")

    if mode in {"within", "outside"}:
        try:
            start_date = dt.date.fromisoformat(str(start))
            end_date = dt.date.fromisoformat(str(end))
        except (TypeError, ValueError):
            mode = "all"
            start = None
            end = None
        else:
            if start_date > end_date:
                mode = "all"
                start = None
                end = None
            else:
                start = start_date.isoformat()
                end = end_date.isoformat()

    if mode == "legacy":
        effective_run_date = run_date or dt.date.today()
        cutoff = _annual_calendar_cutoff(effective_run_date)
        return {
            "mode": "legacy",
            "start": None,
            "end": str(cutoff - dt.timedelta(days=1)),
            "legacy": True,
        }

    return {
        "mode": mode,
        "start": start if mode != "all" else None,
        "end": end if mode != "all" else None,
        "legacy": False,
    }


def apply_product_date_scope_settings(
    cfg: dict[str, Any],
    state_dir: Path,
    run_date: dt.date,
) -> dict[str, Any]:
    result = json.loads(json.dumps(cfg))
    result["date_scope"] = date_scope_product_settings(state_dir, run_date)
    return result



def media_processing_product_settings(state_dir: Path) -> dict[str, bool]:
    """Return which media types Veronica is allowed to process."""
    saved = load_product_settings(state_dir)

    return {
        "images": bool(saved.get("process_images", True)),
        "videos": bool(saved.get("process_videos", True)),
        "audio": bool(saved.get("process_audio", True)),
    }


def apply_product_media_processing_settings(
    cfg: dict[str, Any],
    state_dir: Path,
) -> dict[str, Any]:
    """Overlay persisted media-type preferences onto engine config."""
    result = json.loads(json.dumps(cfg))
    values = media_processing_product_settings(state_dir)

    result["process_images"] = values["images"]
    result["process_videos"] = values["videos"]
    result["process_audio"] = values["audio"]

    return result

def database_archive_root(state_dir: Path) -> Optional[Path]:
    db = state_dir / "media-maintenance.sqlite"
    if not db.exists():
        return None
    con = sqlite3.connect(db)
    try:
        row = con.execute("SELECT value FROM meta WHERE key='root'").fetchone()
    except sqlite3.Error:
        row = None
    finally:
        con.close()
    if not row or not row[0]:
        return None
    return Path(str(row[0])).expanduser().resolve()


def configured_archive_root(state_dir: Path, explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = load_product_settings(state_dir).get("archive_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return database_archive_root(state_dir)


def configured_scan_folders(state_dir: Path) -> list[Path]:
    """Return Veronica's configured scan folders.

    Existing installations are migrated logically: if scan_folders has never
    been written, the historical archive_root/database root becomes the first
    configured folder without modifying the database.
    """
    saved = load_product_settings(state_dir)

    if "scan_folders" in saved:
        raw = saved.get("scan_folders")
        if not isinstance(raw, list):
            return []

        result: list[Path] = []
        seen: set[str] = set()
        for value in raw:
            if not value:
                continue
            folder = Path(str(value)).expanduser().resolve()
            key = str(folder)
            if key in seen:
                continue
            seen.add(key)
            result.append(folder)
        return result

    legacy = saved.get("archive_root")
    if legacy:
        return [Path(str(legacy)).expanduser().resolve()]

    database_root = database_archive_root(state_dir)
    return [database_root] if database_root is not None else []


def scan_folder_state_dir(base_state_dir: Path, folder: Path) -> Path:
    """Return the isolated engine state directory for one configured folder.

    The folder already owned by the historical Veronica database deliberately
    keeps using base_state_dir so all existing history/quarantine/rollback
    records remain valid. Other folders receive deterministic isolated state.
    """
    base_state_dir = base_state_dir.expanduser().resolve()
    folder = folder.expanduser().resolve()

    legacy_root = database_archive_root(base_state_dir)
    if legacy_root is not None and legacy_root == folder:
        return base_state_dir

    folder_id = sha256_text(str(folder))[:16]
    return base_state_dir / "folders" / folder_id


def prepare_scan_folder_state(base_state_dir: Path, folder: Path) -> Path:
    """Prepare one folder's isolated state without disturbing existing history."""
    base_state_dir = base_state_dir.expanduser().resolve()
    folder = folder.expanduser().resolve()
    folder_state = scan_folder_state_dir(base_state_dir, folder)

    existing_root = database_archive_root(folder_state)
    if existing_root is not None and existing_root != folder:
        raise SystemExit(
            "Refusing to reuse Veronica folder state for a different root: "
            f"state={folder_state} database_root={existing_root} requested_root={folder}"
        )

    # The historical/root state already owns its settings. Do not replace its
    # top-level scan_folders list with a one-folder list.
    if folder_state == base_state_dir:
        return folder_state

    parent_filename = filename_product_settings(base_state_dir)
    child = load_product_settings(folder_state)
    child["archive_root"] = str(folder)
    child["scan_folders"] = [str(folder)]
    child["filename_standardization_enabled"] = parent_filename["enabled"]
    child["filename_date_format"] = parent_filename["date_format"]
    child["filename_max_bytes"] = parent_filename["max_bytes"]

    parent_scope = date_scope_product_settings(base_state_dir)
    child["date_scope_mode"] = parent_scope["mode"]
    child["date_scope_start"] = parent_scope.get("start")
    child["date_scope_end"] = parent_scope.get("end")

    # Media-processing preferences are global product settings. Managed
    # per-folder state must inherit them so annual-all cannot silently fall
    # back to the default of processing every media type.
    parent_media = media_processing_product_settings(base_state_dir)
    child["process_images"] = parent_media["images"]
    child["process_videos"] = parent_media["videos"]
    child["process_audio"] = parent_media["audio"]

    parent_saved = load_product_settings(base_state_dir)
    if "media_processing_settings_updated_at" in parent_saved:
        child["media_processing_settings_updated_at"] = (
            parent_saved["media_processing_settings_updated_at"]
        )

    child["managed_by_multi_folder"] = True
    child["parent_state_dir"] = str(base_state_dir)
    save_product_settings(folder_state, child)
    return folder_state


def require_archive_root(state_dir: Path, explicit: Optional[str] = None) -> Path:
    root = configured_archive_root(state_dir, explicit)
    if root is None:
        raise SystemExit("No media library is configured. Choose a media library in Veronica first.")
    if not root.is_dir():
        raise SystemExit(f"Configured media library is unavailable: {root}")
    return root


def dependency_status() -> dict[str, Any]:
    tools = {}
    for name in ("file", "ffprobe", "HandBrakeCLI", "ffmpeg", "xattr"):
        found = shutil.which(name)
        tools[name] = {"available": bool(found), "path": found}
    try:
        import PIL  # type: ignore
        pillow = {"available": True, "version": getattr(PIL, "__version__", None)}
    except Exception:
        pillow = {"available": False, "version": None}
    return {"tools": tools, "pillow": pillow, "python": sys.executable, "python_version": sys.version.split()[0]}


def configure_event_stream(path_text: Optional[str]) -> None:
    """Open an optional JSON-lines event stream for GUI/controller consumers."""
    global _EVENT_STREAM
    if _EVENT_STREAM is not None:
        try:
            _EVENT_STREAM.close()
        except Exception:
            pass
        _EVENT_STREAM = None
    if not path_text:
        return
    path = Path(path_text).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    _EVENT_STREAM = path.open("a", encoding="utf-8", buffering=1)


def close_event_stream() -> None:
    global _EVENT_STREAM
    if _EVENT_STREAM is not None:
        try:
            _EVENT_STREAM.close()
        finally:
            _EVENT_STREAM = None


def emit_event(event: str, **payload: Any) -> None:
    if _EVENT_STREAM is None:
        return
    record = {"event": event, "at": now_iso(), **payload}
    _EVENT_STREAM.write(canonical_json(record) + "\n")
    _EVENT_STREAM.flush()


def _sqlite_quick_check(db_path: Path) -> str:
    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
        return str(row[0]) if row else "no_result"
    finally:
        con.close()


def _rewrite_state_paths(db_path: Path, old_root: Path, new_root: Path) -> int:
    """Rewrite only DB path fields that point inside the relocated state directory."""
    old = str(old_root)
    new = str(new_root)
    columns = [
        ("staging_runs", "staging_dir"),
        ("staging_runs", "report_path"),
        ("staging_items", "output_path"),
        ("commits", "quarantine_dir"),
        ("commits", "report_path"),
        ("commit_items", "quarantine_path"),
        ("commit_items", "final_path"),
        ("rollbacks", "displaced_dir"),
        ("rollbacks", "report_path"),
    ]
    con = sqlite3.connect(str(db_path))
    changed = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        for table, column in columns:
            sql = (
                f"UPDATE {table} SET {column}=? || substr({column}, ?) "
                f"WHERE {column}=? OR {column} LIKE ?"
            )
            cur = con.execute(sql, (new, len(old) + 1, old, old + "/%"))
            changed += int(cur.rowcount or 0)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return changed


def cmd_migrate_state(args: argparse.Namespace) -> int:
    """Safely relocate the legacy state directory into Application Support."""
    # Keep the lexical path spellings as well as their canonical forms.
    # On macOS, for example, /var resolves to /private/var. Historical DB
    # rows may contain either spelling, so migration must recognize both.
    source_input = Path(args.from_dir).expanduser().absolute()
    target_input = Path(args.to_dir).expanduser().absolute()
    source = source_input.resolve()
    target = target_input.resolve()
    db_name = "media-maintenance.sqlite"
    source_db = source / db_name
    target_db = target / db_name

    print(f"{PRODUCT_NAME} {VERSION} state migration")
    print(f"From: {source}")
    print(f"To:   {target}")
    print("Media archive files will not be modified.")

    if source == target:
        raise SystemExit("Source and destination state directories are identical.")
    if not source.is_dir() or not source_db.is_file():
        raise SystemExit(f"Legacy state database not found: {source_db}")
    if target.exists():
        raise SystemExit(f"Destination already exists; refusing to merge state directories: {target}")

    check = _sqlite_quick_check(source_db)
    if check.lower() != "ok":
        raise SystemExit(f"SQLite quick_check failed before migration: {check}")

    source_dev = source.stat().st_dev
    target.parent.mkdir(parents=True, exist_ok=True)
    target_dev = target.parent.stat().st_dev
    if source_dev != target_dev:
        raise SystemExit("Source and destination are on different filesystems; refusing non-atomic state migration.")

    print(f"SQLite quick_check: {check}")
    print("Migration mode: atomic directory rename + guarded SQLite path rewrite")
    if not args.apply:
        print("DRY RUN: nothing moved. Re-run with --apply to perform the migration.")
        return 0

    source.rename(target)
    try:
        changed = _rewrite_state_paths(target_db, source, target)

        # Also rewrite the original lexical path spelling when it differs
        # from the canonical spelling (notably /var vs /private/var on macOS).
        if source_input != source or target_input != target:
            changed += _rewrite_state_paths(target_db, source_input, target_input)

        after = _sqlite_quick_check(target_db)
        if after.lower() != "ok":
            raise RuntimeError(f"SQLite quick_check failed after migration: {after}")
    except Exception:
        try:
            if target.exists() and not source.exists():
                target.rename(source)
        finally:
            raise

    print(f"Migration complete. SQLite path fields rewritten: {changed}")
    print(f"SQLite quick_check after migration: {after}")
    print(f"New state directory: {target}")
    return 0


def init_db(path: Path, root: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY,
      started_at TEXT NOT NULL,
      completed_at TEXT,
      run_date TEXT NOT NULL,
      cutoff TEXT NOT NULL,
      root TEXT NOT NULL,
      tool_version TEXT NOT NULL,
      files_seen INTEGER DEFAULT 0,
      status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS assets (
      asset_id INTEGER PRIMARY KEY,
      relpath TEXT UNIQUE NOT NULL,
      size INTEGER NOT NULL,
      mtime_ns INTEGER NOT NULL,
      birth_ts REAL,
      inode INTEGER,
      device INTEGER,
      quick_hash TEXT,
      full_hash TEXT,
      detected_kind TEXT,
      extension TEXT,
      best_date TEXT,
      date_confidence TEXT,
      width INTEGER,
      height INTEGER,
      megapixels REAL,
      duration REAL,
      bit_rate TEXT,
      video_codec TEXT,
      audio_codec TEXT,
      tags_json TEXT NOT NULL,
      personal_tags_json TEXT NOT NULL,
      xattrs_json TEXT NOT NULL,
      last_safety TEXT,
      last_audit_action TEXT,
      last_reason TEXT,
      last_seen_run TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS legacy_history (
      asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
      legacy_tag TEXT NOT NULL,
      imported_at TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'finder_tag',
      PRIMARY KEY(asset_id, legacy_tag)
    );
    CREATE TABLE IF NOT EXISTS processing_history (
      history_id INTEGER PRIMARY KEY,
      asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
      policy_version TEXT NOT NULL,
      operation TEXT NOT NULL,
      status TEXT NOT NULL,
      processed_at TEXT,
      source_quick_hash TEXT,
      source_full_hash TEXT,
      output_quick_hash TEXT,
      output_full_hash TEXT,
      details_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS plans (
      plan_id TEXT PRIMARY KEY,
      created_at TEXT NOT NULL,
      run_id TEXT NOT NULL REFERENCES runs(run_id),
      run_date TEXT NOT NULL,
      cutoff TEXT NOT NULL,
      status TEXT NOT NULL,
      item_count INTEGER NOT NULL,
      executable_count INTEGER NOT NULL,
      review_count INTEGER NOT NULL,
      plan_sha256 TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS plan_items (
      plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
      seq INTEGER NOT NULL,
      asset_id INTEGER NOT NULL REFERENCES assets(asset_id),
      relpath TEXT NOT NULL,
      source_quick_hash TEXT,
      source_size INTEGER NOT NULL,
      source_mtime_ns INTEGER NOT NULL,
      operation TEXT NOT NULL,
      policy_version TEXT,
      reason TEXT NOT NULL,
      target_json TEXT NOT NULL,
      executable INTEGER NOT NULL,
      PRIMARY KEY(plan_id, seq)
    );
    CREATE TABLE IF NOT EXISTS staging_runs (
      staging_id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      started_at TEXT NOT NULL,
      completed_at TEXT,
      status TEXT NOT NULL,
      staging_dir TEXT NOT NULL,
      report_path TEXT
    );
    CREATE TABLE IF NOT EXISTS staging_items (
      staging_id TEXT NOT NULL REFERENCES staging_runs(staging_id) ON DELETE CASCADE,
      relpath TEXT NOT NULL,
      operation TEXT NOT NULL,
      status TEXT NOT NULL,
      source_size INTEGER,
      output_size INTEGER,
      saving_bytes INTEGER,
      saving_percent REAL,
      output_path TEXT,
      verification_json TEXT NOT NULL DEFAULT '{}',
      error TEXT,
      PRIMARY KEY(staging_id, relpath)
    );
    CREATE TABLE IF NOT EXISTS disposition_history (
      disposition_id INTEGER PRIMARY KEY,
      asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
      plan_id TEXT,
      policy_version TEXT NOT NULL,
      operation TEXT NOT NULL,
      disposition TEXT NOT NULL,
      decided_at TEXT NOT NULL,
      source_quick_hash TEXT,
      source_size INTEGER,
      details_json TEXT NOT NULL DEFAULT '{}',
      UNIQUE(asset_id, policy_version, operation, disposition, source_quick_hash)
    );
    CREATE TABLE IF NOT EXISTS review_resolutions (
      resolution_id INTEGER PRIMARY KEY,
      asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
      plan_id TEXT,
      review_reason TEXT NOT NULL,
      resolution TEXT NOT NULL,
      decided_at TEXT NOT NULL,
      source_quick_hash TEXT NOT NULL,
      source_size INTEGER NOT NULL,
      details_json TEXT NOT NULL DEFAULT '{}',
      UNIQUE(asset_id, review_reason, resolution, source_quick_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_review_resolution_asset ON review_resolutions(asset_id,review_reason,resolution);
    CREATE INDEX IF NOT EXISTS idx_disposition_asset ON disposition_history(asset_id,operation,policy_version,disposition);
    CREATE INDEX IF NOT EXISTS idx_assets_seen ON assets(last_seen_run);
    CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(detected_kind);
    CREATE INDEX IF NOT EXISTS idx_legacy_tag ON legacy_history(legacy_tag);
    CREATE INDEX IF NOT EXISTS idx_plan_items_operation ON plan_items(operation);
    CREATE TABLE IF NOT EXISTS commits (
      commit_id TEXT PRIMARY KEY,
      staging_id TEXT NOT NULL,
      plan_id TEXT NOT NULL,
      started_at TEXT NOT NULL,
      completed_at TEXT,
      status TEXT NOT NULL,
      quarantine_dir TEXT NOT NULL,
      report_path TEXT
    );
    CREATE TABLE IF NOT EXISTS commit_items (
      commit_id TEXT NOT NULL REFERENCES commits(commit_id) ON DELETE CASCADE,
      relpath TEXT NOT NULL,
      operation TEXT NOT NULL,
      status TEXT NOT NULL,
      source_original_sha256 TEXT,
      staged_sha256 TEXT,
      final_sha256 TEXT,
      quarantine_path TEXT,
      final_path TEXT,
      details_json TEXT NOT NULL DEFAULT '{}',
      PRIMARY KEY(commit_id, relpath)
    );
    CREATE TABLE IF NOT EXISTS rollbacks (
      rollback_id TEXT PRIMARY KEY,
      commit_id TEXT NOT NULL,
      started_at TEXT NOT NULL,
      completed_at TEXT,
      status TEXT NOT NULL,
      displaced_dir TEXT NOT NULL,
      report_path TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_commit_items_relpath ON commit_items(relpath);
    """)
    # v0.8.6: backfill durable KEEP_ORIGINAL decisions from earlier staging history.
    # The exact source hash + policy guard prevents stale decisions from suppressing
    # work after a file or policy changes.
    con.execute("""
      INSERT OR IGNORE INTO disposition_history(
        asset_id,plan_id,policy_version,operation,disposition,decided_at,source_quick_hash,source_size,details_json
      )
      SELECT pi.asset_id,sr.plan_id,pi.policy_version,si.operation,'KEEP_ORIGINAL',
             COALESCE(sr.completed_at,sr.started_at),pi.source_quick_hash,pi.source_size,si.verification_json
      FROM staging_items si
      JOIN staging_runs sr ON sr.staging_id=si.staging_id
      JOIN plan_items pi ON pi.plan_id=sr.plan_id AND pi.relpath=si.relpath
      WHERE si.status='KEEP_ORIGINAL' AND si.operation IN ('CONVERT_IMAGE','CONVERT_VIDEO','CONVERT_AUDIO') AND pi.policy_version IS NOT NULL
    """)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('root',?)", (str(root.resolve()),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('tool_version',?)", (VERSION,))
    con.commit()
    return con


def upsert_asset(con: sqlite3.Connection, row: dict[str, Any], run_id: str, cfg: dict[str, Any]) -> int:
    legacy_exclude = set(cfg.get("personal_tags_exclude", []))
    tags = sorted(set(row.get("tags", [])))
    personal_tags = [t for t in tags if t not in legacy_exclude]
    path = Path(row["relpath"])
    mtime_ns = int(float(row.get("mtime_ts") or 0) * 1_000_000_000)
    values = (
        row["relpath"], int(row.get("size") or 0), mtime_ns, row.get("birth_ts"), row.get("inode"), row.get("device"),
        row.get("quick_hash"), row.get("full_hash"), row.get("detected_kind"), row.get("extension"), row.get("best_date"),
        row.get("date_confidence"), row.get("width"), row.get("height"), row.get("megapixels"), row.get("duration"),
        row.get("bit_rate"), row.get("video_codec"), row.get("audio_codec"), canonical_json(tags), canonical_json(personal_tags),
        canonical_json(row.get("xattrs", [])), row.get("safety"), row.get("action"), row.get("reason"), run_id,
    )
    con.execute("""
      INSERT INTO assets(relpath,size,mtime_ns,birth_ts,inode,device,quick_hash,full_hash,detected_kind,extension,best_date,date_confidence,
                         width,height,megapixels,duration,bit_rate,video_codec,audio_codec,tags_json,personal_tags_json,xattrs_json,
                         last_safety,last_audit_action,last_reason,last_seen_run,active)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
      ON CONFLICT(relpath) DO UPDATE SET
        size=excluded.size,mtime_ns=excluded.mtime_ns,birth_ts=excluded.birth_ts,inode=excluded.inode,device=excluded.device,
        quick_hash=excluded.quick_hash,full_hash=excluded.full_hash,detected_kind=excluded.detected_kind,extension=excluded.extension,
        best_date=excluded.best_date,date_confidence=excluded.date_confidence,width=excluded.width,height=excluded.height,
        megapixels=excluded.megapixels,duration=excluded.duration,bit_rate=excluded.bit_rate,video_codec=excluded.video_codec,
        audio_codec=excluded.audio_codec,tags_json=excluded.tags_json,personal_tags_json=excluded.personal_tags_json,xattrs_json=excluded.xattrs_json,
        last_safety=excluded.last_safety,last_audit_action=excluded.last_audit_action,last_reason=excluded.last_reason,last_seen_run=excluded.last_seen_run,active=1
    """, values)
    asset_id = int(con.execute("SELECT asset_id FROM assets WHERE relpath=?", (str(path),)).fetchone()[0])
    legacy_tags = set(cfg.get("legacy_processing_tags", [])) & set(tags)
    for tag in sorted(legacy_tags):
        con.execute("INSERT OR IGNORE INTO legacy_history(asset_id,legacy_tag,imported_at) VALUES(?,?,?)", (asset_id, tag, now_iso()))
    return asset_id


def historical_keep_original(con: sqlite3.Connection, asset_id: int, operation: str, policy_version: Optional[str], current_quick_hash: Optional[str], current_size: Optional[int] = None) -> Optional[sqlite3.Row]:
    """Return durable KEEP_ORIGINAL evidence only for the same asset content and policy.
    A changed file or changed policy must be evaluated again.
    """
    if not policy_version or not current_quick_hash:
        return None
    row = con.execute(
        "SELECT * FROM disposition_history WHERE asset_id=? AND operation=? AND policy_version=? "
        "AND disposition='KEEP_ORIGINAL' AND source_quick_hash=? ORDER BY disposition_id DESC LIMIT 1",
        (asset_id, operation, policy_version, current_quick_hash),
    ).fetchone()
    if row is not None and current_size is not None and row["source_size"] is not None and int(row["source_size"]) != int(current_size):
        return None
    return row


def historical_review_resolution(
    con: sqlite3.Connection,
    asset_id: int,
    review_reason: Optional[str],
    current_quick_hash: Optional[str],
    current_size: Optional[int] = None,
    resolution: Optional[str] = None,
) -> Optional[sqlite3.Row]:
    """Return a durable human review resolution only for the same content and reason.

    Review resolutions are deliberately separate from conversion dispositions such as
    KEEP_ORIGINAL. A changed source or a changed review reason must be reconsidered.
    """
    if not review_reason or not current_quick_hash:
        return None

    sql = (
        "SELECT * FROM review_resolutions WHERE asset_id=? AND review_reason=? "
        "AND source_quick_hash=?"
    )
    values: list[Any] = [asset_id, review_reason, current_quick_hash]

    if resolution is not None:
        sql += " AND resolution=?"
        values.append(resolution)

    sql += " ORDER BY resolution_id DESC LIMIT 1"

    row = con.execute(sql, tuple(values)).fetchone()
    if row is not None and current_size is not None and int(row["source_size"]) != int(current_size):
        return None
    return row


def apply_historical_review_resolution(con: sqlite3.Connection, item: dict[str, Any]) -> dict[str, Any]:
    """Resolve an otherwise-REVIEW plan item when an exact guarded human decision exists."""
    if item.get("operation") != "REVIEW":
        return item
    resolved = historical_review_resolution(
        con,
        int(item["asset_id"]),
        item.get("reason"),
        item.get("source_quick_hash"),
        int(item.get("source_size") or 0),
        resolution="KEEP_AS_IS",
    )
    if resolved is None:
        return item
    target = dict(item.get("target") or {})
    target.update({
        "review_resolution": resolved["resolution"],
        "review_resolved_at": resolved["decided_at"],
        "review_original_reason": item.get("reason"),
    })
    item.update(
        operation="SKIP_REVIEW_RESOLVED",
        policy_version=None,
        executable=False,
        reason="sqlite_review_resolution_same_source_reason",
        target=target,
    )
    return item


def resolved_keep_original_relpaths(con: sqlite3.Connection, plan_id: str, operation: Optional[str] = None) -> set[str]:
    sql = """
      SELECT DISTINCT pi.relpath
      FROM plan_items pi
      JOIN disposition_history dh ON dh.asset_id=pi.asset_id
       AND dh.operation=pi.operation
       AND dh.policy_version=pi.policy_version
       AND dh.disposition='KEEP_ORIGINAL'
       AND dh.source_quick_hash=pi.source_quick_hash
      WHERE pi.plan_id=?
    """
    vals=[plan_id]
    if operation:
        sql += " AND pi.operation=?"; vals.append(operation)
    return {str(r[0]) for r in con.execute(sql, tuple(vals)).fetchall()}


def historical_video_completion(con: sqlite3.Connection, asset_id: int, current_quick_hash: Optional[str], current_full_hash: Optional[str] = None) -> Optional[sqlite3.Row]:
    """Return the latest committed Veronica video conversion if the active file
    still matches the output identity recorded by that commit. Historical policy versions
    remain accepted completion evidence; a later policy upgrade must not re-transcode an
    unchanged archive asset merely because the preferred policy changed.
    """
    rows = con.execute(
        "SELECT history_id,policy_version,processed_at,output_quick_hash,output_full_hash,details_json "
        "FROM processing_history WHERE asset_id=? AND operation='CONVERT_VIDEO' AND status='COMMITTED' "
        "ORDER BY history_id DESC",
        (asset_id,),
    ).fetchall()
    for r in rows:
        oq = r["output_quick_hash"]
        of = r["output_full_hash"]
        if current_full_hash and of and current_full_hash == of:
            return r
        if current_quick_hash and oq and current_quick_hash == oq:
            return r
    return None


_CANONICAL_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")
_SUPPORTED_FILENAME_DATE_FORMATS = {"YYYY-MM-DD_"}


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Return the longest UTF-8-safe prefix no larger than max_bytes."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    encoded = encoded[:max_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def canonical_media_filename(
    relpath: str,
    best_date: Optional[str],
    target_extension: Optional[str],
    cfg: dict[str, Any],
) -> Optional[str]:
    """Return the configured canonical filename for one media asset.

    The resolved audit best_date is the only date authority here. Filename
    normalization must not independently reinterpret filesystem metadata.
    """
    if not cfg.get("filename_standardization_enabled", True):
        return None
    if not best_date:
        return None

    date_format = str(cfg.get("filename_date_format") or "YYYY-MM-DD_")
    if date_format not in _SUPPORTED_FILENAME_DATE_FORMATS:
        raise ValueError(f"unsupported filename_date_format:{date_format}")

    try:
        date_value = dt.date.fromisoformat(str(best_date))
    except ValueError:
        return None

    original = Path(relpath)
    stem = _CANONICAL_DATE_PREFIX.sub("", original.stem, count=1)
    stem = stem.strip()
    if not stem:
        stem = "media"

    extension = target_extension if target_extension is not None else original.suffix
    if extension and not extension.startswith("."):
        extension = "." + extension

    prefix = date_value.strftime("%Y-%m-%d") + "_"

    configured_max = int(cfg.get("filename_max_bytes") or 180)
    if configured_max < 32:
        configured_max = 32

    # APFS/HFS+ filename components have a hard ceiling. Keep our own safety
    # ceiling at 255 UTF-8 bytes even when configuration requests something larger.
    max_bytes = min(configured_max, 255)

    fixed_bytes = len((prefix + extension).encode("utf-8"))
    available_stem_bytes = max_bytes - fixed_bytes
    if available_stem_bytes < 1:
        raise ValueError("filename_max_bytes_too_small_for_date_and_extension")

    stem = _truncate_utf8(stem, available_stem_bytes).rstrip()
    if not stem:
        stem = "media"
        stem = _truncate_utf8(stem, available_stem_bytes)
        if not stem:
            raise ValueError("filename_max_bytes_too_small_for_safe_stem")

    return prefix + stem + extension


def apply_filename_policy(
    item: dict[str, Any],
    row: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Attach canonical destination naming or turn an eligible skip into RENAME."""
    # A disabled media type must remain completely untouched.
    # Filename standardization must not turn it into an executable rename.
    if item.get("operation") == "SKIP_MEDIA_TYPE_DISABLED":
        return item

    if not cfg.get("filename_standardization_enabled", True):
        return item

    if item.get("operation") in {"REVIEW", "PRESERVE", "SKIP_TOO_NEW"}:
        return item

    if row.get("detected_kind") not in {"image", "video", "audio"}:
        return item

    best_date = row.get("best_date")
    if not best_date:
        return item

    target_extension: Optional[str] = None
    if item.get("operation") == "CONVERT_IMAGE":
        fmt = str((item.get("target") or {}).get("format") or "").lower()
        target_extension = ".png" if fmt == "png" else ".jpg"
    elif item.get("operation") == "CONVERT_VIDEO":
        target_extension = ".mp4"
    elif item.get("operation") == "CONVERT_AUDIO":
        target_extension = ".mp3"

    filename = canonical_media_filename(
        str(item["relpath"]),
        str(best_date),
        target_extension,
        cfg,
    )
    if not filename:
        return item

    rel = Path(item["relpath"])
    final_relpath = (rel.parent / filename).as_posix()

    target = dict(item.get("target") or {})
    target.update({
        "final_relpath": final_relpath,
        "filename_standardization": True,
        "filename_date": str(best_date),
        "filename_date_format": str(cfg.get("filename_date_format") or "YYYY-MM-DD_"),
        "filename_max_bytes": min(int(cfg.get("filename_max_bytes") or 180), 255),
    })
    item["target"] = target

    if final_relpath == item["relpath"]:
        return item

    if item.get("operation") in {"CONVERT_IMAGE", "CONVERT_VIDEO", "CONVERT_AUDIO"}:
        # Conversion stays the primary operation. Commit installs the verified
        # result directly at the canonical pathname.
        return item

    # Safe media which otherwise required no byte conversion still needs its
    # naming policy applied.
    if item.get("operation", "").startswith("SKIP"):
        item["operation"] = "RENAME"
        item["policy_version"] = "filename-standardization-v1"
        item["reason"] = "filename_not_canonical"
        item["executable"] = True

    return item


def make_item(row: dict[str, Any], asset_id: int, cfg: dict[str, Any]) -> dict[str, Any]:
    rel = Path(row["relpath"])
    root = rel.parts[0] if rel.parts else ""
    kind = row.get("detected_kind")
    tags = set(row.get("tags", []))
    v2 = bool(tags & set(cfg.get("legacy_v2_tags", [])))
    v1 = "compressed-v1" in tags
    policies = cfg.get("policies", {})

    base = {
        "asset_id": asset_id,
        "relpath": row["relpath"],
        "source_quick_hash": row.get("quick_hash"),
        "source_size": int(row.get("size") or 0),
        "source_mtime_ns": int(float(row.get("mtime_ts") or 0) * 1_000_000_000),
        "operation": "SKIP",
        "policy_version": None,
        "reason": row.get("reason") or "unspecified",
        "target": {},
        "executable": False,
    }

    # Explicit preserve decisions remain the strongest safety boundary.
    if row.get("action") == "PRESERVE":
        base.update(operation="PRESERVE", reason=row.get("reason") or "audit_preserve")
        return base

    # User-visible media-type preferences are a hard processing boundary.
    # Disabled types remain inventoried and auditable, but Veronica plans no
    # conversion, filename modification, or processing-related review for them.
    media_enabled = {
        "image": bool(cfg.get("process_images", True)),
        "video": bool(cfg.get("process_videos", True)),
        "audio": bool(cfg.get("process_audio", True)),
    }

    if kind in media_enabled and not media_enabled[kind]:
        base.update(
            operation="SKIP_MEDIA_TYPE_DISABLED",
            policy_version=None,
            reason=f"{kind}_processing_disabled_by_user",
            target={"media_type": kind},
            executable=False,
        )
        return base

    # Veronica is a media-maintenance tool. Ordinary files that are not
    # detected as image, video, or audio remain inventoried for auditability,
    # but they are not maintenance work and must not create Review noise.
    #
    # Explicit PRESERVE decisions above remain stronger, so protected files,
    # symlinks, filesystem boundaries, and other safety cases are unchanged.
    if kind not in media_enabled:
        base.update(
            operation="SKIP_NONMEDIA",
            policy_version=None,
            reason=row.get("reason") or f"nonmedia_content:{kind}",
            target={"detected_kind": kind},
            executable=False,
        )
        return base

    # Audit review decisions apply only to enabled media.
    if row.get("action") == "REVIEW":
        base.update(operation="REVIEW", reason=row.get("reason") or "audit_review")
        return base
    if row.get("reason") == "too_new":
        base.update(operation="SKIP_TOO_NEW", reason="too_new")
        return base
    if row.get("reason") == "audio_below_size_threshold":
        base.update(operation="SKIP_NO_BENEFIT", reason="audio_below_size_threshold")
        return base

    # Legacy v2 means the file passed the old v2 pipeline. For images we additionally
    # verify it still meets the current dimensional policy; a mismatch becomes review.
    if v2:
        if kind == "image":
            target_mp = float(cfg.get("streams_image_max_megapixels", 10) if root == "Streams" else cfg.get("photo_library_max_megapixels", 20))
            mp = row.get("megapixels")
            if mp is not None and float(mp) > target_mp + 0.01:
                base.update(operation="REVIEW", reason="legacy_v2_but_image_exceeds_current_target", target={"max_megapixels": target_mp})
                return base
        base.update(operation="SKIP_LEGACY_V2", reason="legacy_v2_processing_evidence")
        return base

    # compressed-v1 is historical evidence only; it does not satisfy v2/current policy.
    legacy_note = "legacy_v1_present; " if v1 else ""

    if row.get("action") != "CANDIDATE":
        base.update(operation="SKIP", reason=row.get("reason") or "not_candidate")
        return base

    # Historical named roots retain their special policy where applicable,
    # while arbitrary user-configured folders use the general media policy.
    is_photo_library = root == "Photo_Library"

    if kind == "image":
        target_mp = float(
            cfg.get(
                "photo_library_max_megapixels" if is_photo_library else "streams_image_max_megapixels",
                20 if is_photo_library else 10,
            )
        )
        mp = row.get("megapixels")
        if mp is None:
            base.update(operation="REVIEW", reason="image_dimensions_unknown")
        elif float(mp) <= target_mp:
            base.update(
                operation="SKIP_NO_BENEFIT",
                reason="image_at_or_below_target",
                target={"max_megapixels": target_mp},
            )
        elif row.get("animated"):
            base.update(operation="PRESERVE", reason="true_animated_image")
        else:
            ext = (row.get("extension") or "").lower()
            fmt = "png" if ext == ".png" and row.get("has_alpha") else "jpeg"
            policy_key = "photo_library_image" if is_photo_library else "streams_image"
            reason = (
                "photo_library_image_above_target"
                if is_photo_library
                else "image_above_target"
            )
            base.update(
                operation="CONVERT_IMAGE",
                policy_version=policies.get(policy_key),
                reason=legacy_note + reason,
                target={
                    "max_megapixels": target_mp,
                    "format": fmt,
                    "preserve_alpha": bool(row.get("has_alpha")),
                },
                executable=True,
            )
        return base

    if kind == "video":
        base.update(
            operation="CONVERT_VIDEO",
            policy_version=policies.get("streams_video"),
            reason=legacy_note + "eligible_unprocessed_video",
            target={
                "preset": cfg.get("video_preset_file", "preset-720P.json"),
                "container": "mp4",
            },
            executable=True,
        )
        return base

    if kind == "audio":
        min_bytes = int(float(cfg.get("audio_min_size_mb", 10)) * 1024 * 1024)
        if int(row.get("size") or 0) <= min_bytes:
            base.update(operation="SKIP_NO_BENEFIT", reason="audio_below_size_threshold")
        else:
            # Avoid lossy re-encoding if already around/below the target bitrate.
            br = int(row.get("bit_rate") or 0) if str(row.get("bit_rate") or "").isdigit() else 0
            if row.get("audio_codec") == "mp3" and br and br <= 140000:
                base.update(operation="SKIP_NO_BENEFIT", reason="audio_already_near_128kbps")
            else:
                base.update(operation="CONVERT_AUDIO", policy_version=policies.get("streams_audio"), reason=legacy_note + "audio_over_10mb",
                            target={"codec": "mp3", "bitrate_kbps": 128}, executable=True)
        return base

    base.update(operation="REVIEW", reason="no_phase2_policy")
    return base


def write_plan_files(state_dir: Path, plan: dict[str, Any]) -> tuple[Path, Path]:
    json_path = state_dir / f"plan-{plan['run_date']}-{plan['plan_id'][:12]}.json"
    md_path = state_dir / f"plan-{plan['run_date']}-{plan['plan_id'][:12]}.md"
    json_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    ops = Counter(i["operation"] for i in plan["items"])
    lines = [
        "# Veronica Plan", "",
        f"- Tool version: `{VERSION}`",
        f"- Plan ID: `{plan['plan_id']}`",
        f"- Run date: **{plan['run_date']}**",
        f"- Eligibility cutoff: **before {plan['cutoff']}**",
        f"- Root: `{plan['root']}`",
        f"- Files inventoried: **{plan['files_inventoried']:,}**",
        f"- Legacy v2 imports seen: **{plan['legacy']['v2_assets']:,}**",
        f"- Legacy v1 imports seen: **{plan['legacy']['v1_assets']:,}**",
        f"- Video policy: `{plan.get('policy_snapshot',{}).get('policies',{}).get('streams_video')}`",
        "", "## Planned decisions", "", "| Operation | Files |", "|---|---:|",
    ]
    for k, v in ops.most_common():
        lines.append(f"| `{k}` | {v:,} |")
    lines += ["", "## Executable operations", "", "These are planned only. **No media files have been modified.**", ""]
    executable = [i for i in plan["items"] if i["executable"]]
    for i in executable[:200]:
        lines.append(f"- `{i['operation']}` — `{i['relpath']}` — {i['reason']}")
    if len(executable) > 200:
        lines.append(f"- … {len(executable)-200:,} more executable items are present in the JSON plan.")
    review = [i for i in plan["items"] if i["operation"] == "REVIEW"]
    lines += ["", "## Manual review", ""]
    if not review:
        lines.append("No review items.")
    else:
        for i in review[:200]:
            lines.append(f"- `{i['relpath']}` — {i['reason']}")
        if len(review) > 200:
            lines.append(f"- … {len(review)-200:,} more review items are present in the JSON plan.")
    lines += ["", "## Safety", "", "The plan is immutable. Image and video commits must verify source identity against this exact plan before touching media. Video commit additionally requires an exact policy-version match.", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path



def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    required = {"plan_id", "root", "items", "run_date", "cutoff"}
    missing = required - set(plan)
    if missing:
        raise SystemExit(f"Invalid plan, missing: {', '.join(sorted(missing))}")
    return plan


def verify_source_against_item(root: Path, item: dict[str, Any]) -> tuple[bool, str]:
    path = root / item["relpath"]
    if not path.exists(): return False, "source_missing"
    if not path.is_file(): return False, "source_not_regular_file"
    st = path.stat()
    if int(st.st_size) != int(item["source_size"]): return False, "source_size_changed"
    planned_mtime = int(item.get("source_mtime_ns") or 0)
    if planned_mtime and abs(int(st.st_mtime_ns) - planned_mtime) > 1_000_000:
        return False, "source_mtime_changed"
    qh = audit.quick_hash(path)
    if item.get("source_quick_hash") and qh != item["source_quick_hash"]:
        return False, "source_quick_hash_changed"
    return True, "source_verified"


def target_dimensions(width: int, height: int, max_mp: float) -> tuple[int, int]:
    pixels = width * height
    limit = max_mp * 1_000_000.0
    if pixels <= limit: return width, height
    scale = (limit / pixels) ** 0.5
    return max(1, round(width * scale)), max(1, round(height * scale))


ATTR_BIT_MAP_COUNT = 5
ATTR_CMN_CRTIME = 0x00000200


class _DarwinAttrList(ctypes.Structure):
    _fields_ = [
        ("bitmapcount", ctypes.c_ushort),
        ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    ]


class _DarwinTimespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


def creation_time_backend() -> str:
    if sys.platform != "darwin":
        return "unavailable_non_macos"
    try:
        libc = ctypes.CDLL("libc.dylib", use_errno=True)
        getattr(libc, "setattrlist")
        return "darwin_setattrlist"
    except Exception:
        if Path("/usr/bin/SetFile").exists():
            return "SetFile"
        return "unavailable"


def set_creation_time(path: Path, timestamp: Optional[float]) -> tuple[bool, str]:
    """Restore macOS birth/creation time without touching source media.

    Uses setattrlist(2) when available. SetFile is only a fallback because it is
    part of Apple developer tools and may not exist on every Mac.
    """
    if timestamp is None:
        return False, "source_creation_time_unavailable"
    if sys.platform != "darwin":
        return False, "not_macos"
    sec = int(timestamp)
    nsec = int(round((float(timestamp) - sec) * 1_000_000_000))
    if nsec >= 1_000_000_000:
        sec += 1; nsec -= 1_000_000_000
    try:
        libc = ctypes.CDLL("libc.dylib", use_errno=True)
        func = libc.setattrlist
        func.argtypes = [ctypes.c_char_p, ctypes.POINTER(_DarwinAttrList), ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
        func.restype = ctypes.c_int
        al = _DarwinAttrList()
        al.bitmapcount = ATTR_BIT_MAP_COUNT
        al.commonattr = ATTR_CMN_CRTIME
        ts = _DarwinTimespec(sec, nsec)
        rc = func(os.fsencode(path), ctypes.byref(al), ctypes.byref(ts), ctypes.sizeof(ts), 0)
        if rc == 0:
            return True, "darwin_setattrlist"
        err = ctypes.get_errno()
        native_error = os.strerror(err)
    except Exception as exc:
        native_error = str(exc)
    setfile = Path("/usr/bin/SetFile")
    if setfile.exists():
        # SetFile expects MM/DD/YYYY HH:MM:SS in local time.
        stamp = dt.datetime.fromtimestamp(float(timestamp)).strftime("%m/%d/%Y %H:%M:%S")
        proc = subprocess.run([str(setfile), "-d", stamp, str(path)], capture_output=True, text=True)
        if proc.returncode == 0:
            return True, "SetFile"
        return False, "SetFile_failed:" + proc.stderr.strip()
    return False, "setattrlist_failed:" + native_error


def restore_stage_filesystem_metadata(src: Path, dst: Path) -> dict[str, Any]:
    src_st = src.stat()
    birth = getattr(src_st, "st_birthtime", None)
    birth_ok, birth_backend = set_creation_time(dst, birth)
    # Set mtime last so creation-time tooling cannot accidentally alter it.
    os.utime(dst, ns=(src_st.st_atime_ns, src_st.st_mtime_ns))
    return {"creation_time_set": birth_ok, "creation_time_backend": birth_backend}


def copy_personal_finder_tags_xattr(src: Path, dst: Path, cfg: dict[str, Any]) -> tuple[bool, str, list[str]]:
    if sys.platform != "darwin": return False, "not_macos", []
    key = "com.apple.metadata:_kMDItemUserTags"
    try:
        raw = audit._darwin_getxattr(src, key)
    except Exception as exc:
        if getattr(exc, "errno", None) in {61, 93}: return True, "no_tags", []
        return False, f"read_failed:{exc}", []
    try:
        values = plistlib.loads(raw)
        if not isinstance(values, list): return False, "unexpected_tag_plist", []
        excluded = set(cfg.get("personal_tags_exclude", []))
        kept_raw = []
        kept_names = []
        for value in values:
            if not isinstance(value, str): continue
            name = value.split("\n", 1)[0]
            if name in excluded: continue
            kept_raw.append(value); kept_names.append(name)
        if not kept_raw:
            return True, "no_personal_tags", []
        filtered = plistlib.dumps(kept_raw, fmt=plistlib.FMT_BINARY)
        proc = subprocess.run(["/usr/bin/xattr", "-wx", key, filtered.hex(), str(dst)], capture_output=True, text=True)
        if proc.returncode != 0: return False, "write_failed:" + proc.stderr.strip(), kept_names
        return True, "personal_tags_copied", kept_names
    except Exception as exc:
        return False, f"write_failed:{exc}", []

def read_finder_tags_safe(path: Path) -> list[str]:
    try:
        return audit.finder_tags(path)
    except Exception:
        return []


def choose_personal_tag_probe(con: sqlite3.Connection, root: Path, cfg: dict[str, Any], excluded_relpaths: set[str]) -> Optional[dict[str, Any]]:
    """Choose one live, regular media file with at least one non-workflow Finder tag.

    This probe is independent of conversion eligibility. It exists only to prove that the
    workflow-tag filtering/copy code preserves personal Finder tags end-to-end.
    """
    excluded_tags = set(cfg.get("personal_tags_exclude", []))
    rows = list(con.execute(
        "SELECT relpath,detected_kind,personal_tags_json FROM assets WHERE active=1 AND detected_kind IN ('image','video','audio') ORDER BY relpath"
    ))
    candidates = []
    for r in rows:
        rel = r["relpath"]
        if rel in excluded_relpaths:
            continue
        src = root / rel
        if not src.is_file() or src.is_symlink():
            continue
        live = [t for t in read_finder_tags_safe(src) if t not in excluded_tags]
        if not live:
            continue
        candidates.append((rel, live, r["detected_kind"]))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    rel, tags, kind = candidates[0]
    return {"relpath": rel, "detected_kind": kind, "personal_tags": tags, "operation": "TAG_PROBE_COPY", "sample_reason": "required_personal_finder_tag_probe"}


def run_personal_tag_probe(root: Path, stage_dir: Path, probe: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    src = root / probe["relpath"]
    rel = Path(probe["relpath"])
    out = stage_dir / "tag-probe" / rel.parent / (rel.stem + ".__tag_probe" + rel.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    before = audit.quick_hash(src)
    shutil.copyfile(src, out)
    # Preserve file-system dates only to make the diagnostic copy representative.
    fs_restore = restore_stage_filesystem_metadata(src, out)
    tag_ok, tag_backend, copied_names = copy_personal_finder_tags_xattr(src, out, cfg)
    after = audit.quick_hash(src)
    out_hash = audit.quick_hash(out)
    excluded = set(cfg.get("personal_tags_exclude", []))
    src_tags = read_finder_tags_safe(src)
    expected = sorted(t for t in src_tags if t not in excluded)
    out_tags = sorted(read_finder_tags_safe(out))
    leaked = sorted(t for t in out_tags if t in excluded)
    ok = bool(expected) and tag_ok and before == after == out_hash and out_tags == expected and not leaked
    return {
        "relpath": probe["relpath"],
        "operation": "TAG_PROBE_COPY",
        "sample_reason": probe.get("sample_reason"),
        "status": "TAG_PROBE_VERIFIED" if ok else "TAG_PROBE_FAILED",
        "output_path": str(out),
        "source_quick_hash_before": before,
        "source_quick_hash_after": after,
        "output_quick_hash": out_hash,
        "source_unchanged": before == after,
        "byte_identical_copy": before == out_hash,
        "source_finder_tags": src_tags,
        "expected_personal_tags": expected,
        "staged_finder_tags": out_tags,
        "legacy_tags_leaked": leaked,
        "tag_copy_ok": tag_ok,
        "tag_copy_backend": tag_backend,
        "tag_copy_reported_names": copied_names,
        "filesystem_restore": fs_restore,
        "diagnostic_only": True,
        "commit_eligible": False,
    }


def convert_image_stage(src: Path, dst: Path, item: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image
    root_name = Path(item["relpath"]).parts[0]
    max_mp = float(item.get("target", {}).get("max_megapixels") or (cfg.get("streams_image_max_megapixels", 10) if root_name == "Streams" else cfg.get("photo_library_max_megapixels", 20)))
    fmt = item.get("target", {}).get("format", "jpeg")
    quality = int(cfg.get("streams_jpeg_quality", 50) if root_name == "Streams" else cfg.get("photo_library_jpeg_quality", 70))
    with Image.open(src) as im:
        source_format = im.format
        source_size = im.size
        out_wh = target_dimensions(im.width, im.height, max_mp)
        work = im.copy()
        if work.size != out_wh:
            work.thumbnail(out_wh, Image.Resampling.LANCZOS)
        exif = im.info.get("exif")
        icc = im.info.get("icc_profile")
        save_kw: dict[str, Any] = {}
        if exif: save_kw["exif"] = exif
        if icc: save_kw["icc_profile"] = icc
        dst.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "png":
            dst = dst.with_suffix(".png")
            work.save(dst, format="PNG", optimize=True, **save_kw)
        else:
            dst = dst.with_suffix(".jpg")
            if work.mode not in ("RGB", "L"):
                # Non-alpha image formats may still decode to palette/CMYK. Alpha is planned as PNG.
                if "A" in work.getbands():
                    raise RuntimeError("unexpected_alpha_for_jpeg_target")
                work = work.convert("RGB")
            work.save(dst, format="JPEG", quality=quality, optimize=True, **save_kw)
    tag_copy = (True, "disabled", [])
    if cfg.get("stage_copy_personal_finder_tags", True):
        tag_copy = copy_personal_finder_tags_xattr(src, dst, cfg)
    fs_restore = restore_stage_filesystem_metadata(src, dst)
    return {"output_path": str(dst), "source_format": source_format, "source_dimensions": source_size, "target_dimensions": out_wh, "finder_tags_copy": tag_copy, "filesystem_restore": fs_restore}


def ffprobe_json(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe: raise RuntimeError("ffprobe_not_found")
    p = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-show_chapters", "-of", "json", str(path)], capture_output=True, text=True)
    if p.returncode != 0: raise RuntimeError("ffprobe_failed:" + p.stderr.strip())
    return json.loads(p.stdout)


def primary_stream(info: dict[str, Any], kind: str) -> Optional[dict[str, Any]]:
    for s in info.get("streams", []):
        if s.get("codec_type") == kind: return s
    return None


def duration_from_probe(info: dict[str, Any]) -> Optional[float]:
    try: return float(info.get("format", {}).get("duration"))
    except Exception: return None


def convert_video_stage(src: Path, dst: Path, item: dict[str, Any], cfg: dict[str, Any], package_dir: Path) -> dict[str, Any]:
    hb = shutil.which("HandBrakeCLI")
    if not hb: raise RuntimeError("HandBrakeCLI_not_found")
    preset_ref = Path(item.get("target", {}).get("preset") or cfg.get("video_preset_file", "preset-720P.json"))
    preset_path = preset_ref if preset_ref.is_absolute() else package_dir / preset_ref
    if not preset_path.exists(): raise RuntimeError(f"preset_not_found:{preset_path}")
    preset_name = "PRESET v4 square-pixel no-autocrop"
    try:
        d = json.loads(preset_path.read_text(encoding="utf-8"))
        preset_name = d["PresetList"][0]["PresetName"]
    except Exception:
        pass
    # Do not rely on preset crop/geometry fields alone. HandBrakeCLI has its own
    # picture-option layer, and explicit CLI options are the authoritative archive
    # policy. Compute the full-frame square-pixel target independently and pass it
    # directly to HandBrake. The staged verifier repeats the same calculation from
    # ffprobe output, so command construction and verification remain independent
    # safety gates.
    source_info = ffprobe_json(src)
    source_video = video_stream_summary(source_info)
    max_edge = int(cfg.get("video_max_storage_edge", 1280))
    expected_dims = expected_full_frame_square_dimensions(source_video, max_edge)
    if not expected_dims:
        raise RuntimeError("video_full_frame_dimensions_unavailable")
    expected_w, expected_h = (int(expected_dims[0]), int(expected_dims[1]))

    dst = dst.with_suffix(".mp4")
    dst.parent.mkdir(parents=True, exist_ok=True)
    source_color_range = str(source_video.get("color_range") or "").lower()
    # HandBrake presets commonly default output range to limited. For archive
    # conversions, make source range preservation explicit instead of relying on
    # preset/default behavior. ffprobe reports full range as `pc` and limited as
    # `tv`; HandBrakeCLI expects `full` / `limited`. Unknown sources use `auto`
    # and the independent verifier still enforces any known source signaling.
    if source_color_range == "pc":
        handbrake_color_range = "full"
    elif source_color_range == "tv":
        handbrake_color_range = "limited"
    else:
        handbrake_color_range = "auto"

    picture_args = [
        "--crop-mode", "none",
        "--crop", "0:0:0:0",
        "--non-anamorphic",
        "--color-range", handbrake_color_range,
        "-w", str(expected_w),
        "-l", str(expected_h),
    ]
    cmd = [
        hb, "--preset-import-file", str(preset_path), "-Z", preset_name,
        *picture_args,
        "-i", str(src), "-o", str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("HandBrakeCLI_failed:" + proc.stderr[-3000:].strip())
    tag_copy = (True, "disabled", [])
    if cfg.get("stage_copy_personal_finder_tags", True):
        tag_copy = copy_personal_finder_tags_xattr(src, dst, cfg)
    fs_restore = restore_stage_filesystem_metadata(src, dst)
    return {
        "output_path": str(dst),
        "handbrake_preset": preset_name,
        "crop_policy": "full-frame-no-autocrop",
        "requested_crop": [0, 0, 0, 0],
        "expected_full_frame_dimensions": [expected_w, expected_h],
        "source_color_range": source_video.get("color_range"),
        "requested_handbrake_color_range": handbrake_color_range,
        "handbrake_cli_picture_args": picture_args,
        "finder_tags_copy": tag_copy,
        "filesystem_restore": fs_restore,
    }


def convert_audio_stage(src: Path, dst: Path, item: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg: raise RuntimeError("ffmpeg_not_found")
    dst = dst.with_suffix(".mp3")
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "128k", str(dst)], capture_output=True, text=True)
    if proc.returncode != 0: raise RuntimeError("ffmpeg_failed:" + proc.stderr[-3000:].strip())
    tag_copy = (True, "disabled", [])
    if cfg.get("stage_copy_personal_finder_tags", True): tag_copy = copy_personal_finder_tags_xattr(src, dst, cfg)
    fs_restore = restore_stage_filesystem_metadata(src, dst)
    return {"output_path": str(dst), "finder_tags_copy": tag_copy, "filesystem_restore": fs_restore}


def filesystem_metadata(path: Path) -> dict[str, Any]:
    st = path.stat()
    birth = getattr(st, "st_birthtime", None)
    return {
        "mtime_ns": int(st.st_mtime_ns),
        "mtime_iso": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(),
        "birth_ts": birth,
        "birth_iso": dt.datetime.fromtimestamp(birth, dt.timezone.utc).isoformat() if birth is not None else None,
    }


def image_metadata(path: Path) -> dict[str, Any]:
    from PIL import Image
    with Image.open(path) as im:
        exif_blob = im.info.get("exif") or b""
        icc = im.info.get("icc_profile") or b""
        exif = im.getexif()
        def ev(tag: int) -> Any:
            try:
                v = exif.get(tag)
                return str(v) if v is not None else None
            except Exception:
                return None
        return {
            "format": im.format,
            "mode": im.mode,
            "dimensions": [im.width, im.height],
            "megapixels": round(im.width * im.height / 1_000_000.0, 3),
            "icc_present": bool(icc),
            "icc_sha256": hashlib.sha256(icc).hexdigest() if icc else None,
            "exif_present": bool(exif_blob),
            "exif_sha256": hashlib.sha256(exif_blob).hexdigest() if exif_blob else None,
            "exif_orientation": ev(274),
            "exif_datetime": ev(306),
            "exif_datetime_original": ev(36867),
            "exif_datetime_digitized": ev(36868),
            "gps_present": bool(exif.get_ifd(34853)) if 34853 in exif else False,
        }


def asset_metadata_map(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in con.execute("SELECT relpath,width,height,megapixels,extension,personal_tags_json,size,duration,bit_rate,video_codec,audio_codec FROM assets WHERE active=1"):
        try: tags=json.loads(r["personal_tags_json"] or "[]")
        except Exception: tags=[]
        out[r["relpath"]] = {
            "width":r["width"],"height":r["height"],"megapixels":r["megapixels"],"extension":r["extension"],
            "personal_tags":tags,"size":r["size"],"duration":r["duration"],"bit_rate":r["bit_rate"],
            "video_codec":r["video_codec"],"audio_codec":r["audio_codec"]
        }
    return out


def select_stage_items(plan: dict[str, Any], limits: dict[str, int], strategy: str, assets: dict[str, dict[str, Any]], root: Path, cfg: dict[str, Any], excluded_relpaths: Optional[set[str]] = None) -> list[dict[str, Any]]:
    excluded_relpaths = excluded_relpaths or set()
    executable=[i for i in plan["items"] if i.get("executable") and i.get("operation") in limits and i.get("relpath") not in excluded_relpaths]
    selected=[]
    # Non-image operations retain plan order; image sampling can be deliberately diverse.
    if strategy != "diverse":
        counts=Counter()
        for i in executable:
            op=i["operation"]
            if counts[op] < limits[op]:
                i=dict(i); i["sample_reason"]="plan_order"
                selected.append(i); counts[op]+=1
        return selected
    images=[i for i in executable if i["operation"]=="CONVERT_IMAGE"]
    want=limits.get("CONVERT_IMAGE",0)
    used=set()
    def choose(label, predicate, key=None, reverse=False):
        if len([x for x in selected if x["operation"]=="CONVERT_IMAGE"]) >= want: return
        pool=[i for i in images if i["relpath"] not in used and predicate(i, assets.get(i["relpath"],{}))]
        if not pool: return
        if key: pool.sort(key=lambda i:key(i, assets.get(i["relpath"],{})), reverse=reverse)
        item=dict(pool[0]); item["sample_reason"]=label; used.add(item["relpath"]); selected.append(item)
    choose("photo_library_jpeg", lambda i,a: i["relpath"].startswith("Photo_Library/") and str(a.get("extension") or "").lower() in {".jpg",".jpeg"})
    choose("streams_jpeg", lambda i,a: i["relpath"].startswith("Streams/Image/") and str(a.get("extension") or "").lower() in {".jpg",".jpeg"})
    choose("png", lambda i,a: str(a.get("extension") or "").lower()==".png")
    # Verify tags live from Finder rather than trusting migrated DB metadata for this sample.
    def has_live_personal_tags(i: dict[str, Any], a: dict[str, Any]) -> bool:
        tags = read_finder_tags_safe(root / i["relpath"])
        excluded = set(cfg.get("personal_tags_exclude", []))
        return any(t not in excluded for t in tags)
    choose("personal_finder_tags", has_live_personal_tags)
    choose("near_target", lambda i,a: bool(a.get("megapixels")), key=lambda i,a: (float(a.get("megapixels") or 1e9) / float(i.get("target",{}).get("max_megapixels") or 1)) )
    choose("largest_megapixels", lambda i,a: bool(a.get("megapixels")), key=lambda i,a: float(a.get("megapixels") or 0), reverse=True)
    choose("largest_file", lambda i,a: True, key=lambda i,a: int(a.get("size") or 0), reverse=True)
    # Fill remainder deterministically across the plan.
    for i in images:
        if len([x for x in selected if x["operation"]=="CONVERT_IMAGE"]) >= want: break
        if i["relpath"] in used: continue
        x=dict(i); x["sample_reason"]="diverse_fill"; used.add(x["relpath"]); selected.append(x)
    # Add a deliberately diverse video sample. This uses cheap inventory metadata first,
    # then live Finder tags; expensive ffprobe checks happen only for the selected files.
    videos=[i for i in executable if i["operation"]=="CONVERT_VIDEO"]
    vwant=limits.get("CONVERT_VIDEO",0)
    vused=set()
    def vchoose(label, predicate, key=None, reverse=False):
        if len([x for x in selected if x["operation"]=="CONVERT_VIDEO"]) >= vwant: return
        pool=[i for i in videos if i["relpath"] not in vused and predicate(i, assets.get(i["relpath"],{}))]
        if not pool: return
        if key: pool.sort(key=lambda i:key(i, assets.get(i["relpath"],{})), reverse=reverse)
        x=dict(pool[0]); x["sample_reason"]=label; vused.add(x["relpath"]); selected.append(x)
    if vwant:
        vchoose("video_landscape", lambda i,a: int(a.get("width") or 0) > int(a.get("height") or 0))
        vchoose("video_portrait", lambda i,a: int(a.get("height") or 0) > int(a.get("width") or 0))
        vchoose("video_mov", lambda i,a: str(a.get("extension") or "").lower()==".mov")
        vchoose("video_mp4", lambda i,a: str(a.get("extension") or "").lower()==".mp4")
        vchoose("video_m4v", lambda i,a: str(a.get("extension") or "").lower()==".m4v")
        vchoose("video_non_h264", lambda i,a: bool(a.get("video_codec")) and str(a.get("video_codec")).lower()!="h264")
        vchoose("video_personal_finder_tags", lambda i,a: any(t not in set(cfg.get("personal_tags_exclude",[])) for t in read_finder_tags_safe(root/i["relpath"])))
        vchoose("video_longest", lambda i,a: a.get("duration") is not None, key=lambda i,a: float(a.get("duration") or 0), reverse=True)
        vchoose("video_largest", lambda i,a: True, key=lambda i,a: int(a.get("size") or 0), reverse=True)
        vchoose("video_smallest", lambda i,a: True, key=lambda i,a: int(a.get("size") or 0))
        for i in videos:
            if len([x for x in selected if x["operation"]=="CONVERT_VIDEO"]) >= vwant: break
            if i["relpath"] in vused: continue
            x=dict(i); x["sample_reason"]="video_diverse_fill"; vused.add(x["relpath"]); selected.append(x)
    # Audio remains plan-order for now.
    n=0
    for i in executable:
        if i["operation"]=="CONVERT_AUDIO" and n < limits.get("CONVERT_AUDIO",0):
            x=dict(i); x["sample_reason"]="plan_order"; selected.append(x); n+=1
    return selected


def stream_counts(info: dict[str, Any]) -> dict[str, int]:
    c = Counter(str(s.get("codec_type") or "unknown") for s in info.get("streams", []))
    return dict(c)


def _ratio_value(value: Any) -> Optional[float]:
    if value in (None, "", "0:1", "0/1", "N/A"):
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        t = str(value).strip()
        sep = ":" if ":" in t else "/" if "/" in t else None
        if sep:
            a, b = t.split(sep, 1)
            bval = float(b)
            return float(a) / bval if bval else None
        return float(t)
    except Exception:
        return None


def _fps_value(value: Any) -> Optional[float]:
    return _ratio_value(value)


def _rotation_degrees(v: dict[str, Any]) -> int:
    tags = v.get("tags", {}) or {}
    try:
        if "rotate" in tags:
            return int(float(tags.get("rotate") or 0)) % 360
    except Exception:
        pass
    for side in v.get("side_data_list", []) or []:
        if "rotation" in side:
            try:
                return int(round(float(side.get("rotation") or 0))) % 360
            except Exception:
                pass
    return 0


def _display_aspect(v: dict[str, Any]) -> Optional[float]:
    dar = _ratio_value(v.get("display_aspect_ratio"))
    if dar:
        return dar
    w = _ratio_value(v.get("width")); h = _ratio_value(v.get("height"))
    if not w or not h:
        return None
    sar = _ratio_value(v.get("sample_aspect_ratio")) or 1.0
    ratio = (w * sar) / h
    if _rotation_degrees(v) in (90, 270) and ratio:
        ratio = 1.0 / ratio
    return ratio


def _stream_signature(info: dict[str, Any]) -> list[dict[str, Any]]:
    out=[]
    for s in info.get("streams", []) or []:
        out.append({
            "index": s.get("index"), "type": s.get("codec_type"), "codec": s.get("codec_name"),
            "profile": s.get("profile"), "language": (s.get("tags", {}) or {}).get("language"),
            "disposition": {k:v for k,v in (s.get("disposition", {}) or {}).items() if v},
        })
    return out


def _hdr_dolby_reasons(info: dict[str, Any]) -> list[str]:
    v = primary_stream(info, "video") or {}
    reasons=[]
    transfer = str(v.get("color_transfer") or "").lower()
    primaries = str(v.get("color_primaries") or "").lower()
    codec_tag = str(v.get("codec_tag_string") or "").lower()
    profile = str(v.get("profile") or "").lower()
    if transfer in {"smpte2084", "arib-std-b67"}:
        reasons.append(f"hdr_transfer:{transfer}")
    if primaries == "bt2020" and transfer:
        reasons.append(f"wide_gamut:{primaries}")
    if codec_tag in {"dvh1", "dvhe"} or "dolby vision" in profile:
        reasons.append("dolby_vision")
    for side in v.get("side_data_list", []) or []:
        txt = " ".join(str(x) for x in side.values()).lower()
        typ = str(side.get("side_data_type") or "").lower()
        if "dovi" in txt or "dolby vision" in txt or "dovi" in typ:
            reasons.append("dolby_vision_side_data")
        if "mastering display metadata" in typ or "content light level metadata" in typ:
            reasons.append("hdr_mastering_metadata")
    return sorted(set(reasons))


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def video_frame_timing_summary(path: Path) -> dict[str, Any]:
    """Inspect decoded video presentation timestamps without modifying media.

    This is intentionally used only when the cheap avg/r_frame_rate heuristic says a
    source might be VFR. It preserves timestamp order (no sorting/deduplication) so
    duplicate or backwards PTS remain visible as anomalies.
    """
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe_not_found")
    p = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "frame=best_effort_timestamp_time:stream=nb_frames",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError("ffprobe_frame_timing_failed:" + p.stderr.strip())
    data = json.loads(p.stdout)
    timestamps: list[float] = []
    for frame in data.get("frames", []) or []:
        value = frame.get("best_effort_timestamp_time")
        if value is None:
            continue
        try:
            timestamps.append(float(value))
        except (TypeError, ValueError):
            continue
    declared_frame_count = None
    streams = data.get("streams", []) or []
    if streams:
        raw_count = streams[0].get("nb_frames")
        try:
            if raw_count not in (None, "", "N/A"):
                declared_frame_count = int(raw_count)
        except (TypeError, ValueError):
            declared_frame_count = None
    raw_deltas = [b - a for a, b in zip(timestamps, timestamps[1:])]
    duplicates = sum(1 for d in raw_deltas if d == 0)
    backwards = sum(1 for d in raw_deltas if d < 0)
    intervals = [d for d in raw_deltas if d > 0]
    if not intervals:
        raise RuntimeError("insufficient_positive_frame_timestamps")
    median = statistics.median(intervals)
    mean = statistics.mean(intervals)
    deviations = [abs(v - median) / median for v in intervals] if median > 0 else []
    p05 = _percentile(intervals, 0.05)
    p95 = _percentile(intervals, 0.95)
    spread = (p95 / p05) if p05 is not None and p95 is not None and p05 > 0 else None
    outside_5_fraction = (sum(1 for d in deviations if d > 0.05) / len(intervals)) if deviations else 1.0
    return {
        "timestamp_count": len(timestamps),
        "declared_frame_count": declared_frame_count,
        "positive_interval_count": len(intervals),
        "duplicate_pts_count": duplicates,
        "backwards_pts_count": backwards,
        "interval_median_ms": round(median * 1000.0, 6),
        "interval_mean_ms": round(mean * 1000.0, 6),
        "interval_min_ms": round(min(intervals) * 1000.0, 6),
        "interval_max_ms": round(max(intervals) * 1000.0, 6),
        "interval_p05_ms": round(p05 * 1000.0, 6) if p05 is not None else None,
        "interval_p95_ms": round(p95 * 1000.0, 6) if p95 is not None else None,
        "p95_p05_spread": round(spread, 6) if spread is not None else None,
        "outside_5_percent": round(outside_5_fraction * 100.0, 6),
    }


def classify_video_frame_timing(timing: dict[str, Any], cfg: dict[str, Any]) -> str:
    declared = timing.get("declared_frame_count")
    timestamp_count = timing.get("timestamp_count")
    if declared is not None and timestamp_count is not None:
        try:
            declared_i = int(declared)
            timestamp_i = int(timestamp_count)
            diff = abs(declared_i - timestamp_i)
            # A material disagreement means the stream metadata and decoded
            # presentation timeline do not describe the same frame population.
            # Do not promote such a source out of manual review merely because
            # the timestamps that are present have CFR-like spacing.
            if declared_i > 0 and diff > 1 and (diff / declared_i) > 0.01:
                return "frame_count_mismatch"
        except (TypeError, ValueError):
            pass
    if int(timing.get("backwards_pts_count") or 0) > 0:
        return "non_monotonic"
    if int(timing.get("duplicate_pts_count") or 0) > 0:
        return "duplicate_pts"
    intervals = int(timing.get("positive_interval_count") or 0)
    min_intervals = int(cfg.get("video_vfr_min_timing_intervals", 10))
    if intervals < min_intervals:
        return "insufficient_timing_sample"
    outside_raw = timing.get("outside_5_percent")
    outside_5 = float(outside_raw) / 100.0 if outside_raw is not None else 1.0
    spread = timing.get("p95_p05_spread")
    max_outside = float(cfg.get("video_vfr_cfr_like_max_outside_5_fraction", 0.01))
    max_spread = float(cfg.get("video_vfr_cfr_like_max_p95_p05_spread", 1.05))
    if spread is not None and outside_5 <= max_outside and float(spread) <= max_spread:
        return "cfr_like"
    return "variable"


def video_source_review_reasons(info: dict[str, Any], cfg: dict[str, Any], frame_timing: Optional[dict[str, Any]] = None) -> list[str]:
    reasons=[]
    if cfg.get("video_review_hdr", True):
        reasons.extend(_hdr_dolby_reasons(info))
    counts=stream_counts(info)
    if cfg.get("video_review_vfr", True):
        vs = video_stream_summary(info)
        if vs.get("summary_rate_mismatch"):
            if frame_timing is None:
                reasons.append("variable_frame_rate")
            else:
                timing_class = classify_video_frame_timing(frame_timing, cfg)
                if timing_class == "frame_count_mismatch":
                    reasons.append("frame_count_mismatch")
                elif timing_class == "non_monotonic":
                    reasons.append("non_monotonic_frame_timestamps")
                elif timing_class == "duplicate_pts":
                    reasons.append("duplicate_frame_timestamps")
                elif timing_class in {"variable", "insufficient_timing_sample"}:
                    reasons.append("variable_frame_rate")
    if cfg.get("video_review_multichannel_audio", True):
        a = primary_stream(info, "audio") or {}
        try:
            if int(a.get("channels") or 0) > 2:
                reasons.append(f"multichannel_audio:{a.get('channels')}")
        except Exception:
            pass
    if cfg.get("video_review_extra_streams", True):
        if counts.get("video", 0) != 1:
            reasons.append(f"video_stream_count:{counts.get('video',0)}")
        if counts.get("audio", 0) > 1:
            reasons.append(f"multiple_audio_streams:{counts.get('audio',0)}")
        for kind in ("subtitle", "data", "attachment"):
            if counts.get(kind, 0):
                reasons.append(f"extra_{kind}_streams:{counts.get(kind,0)}")
        if len(info.get("chapters", []) or []) > 0:
            # HandBrake may preserve chapters, but this must be explicitly verified before commit support.
            reasons.append(f"chapters_present:{len(info.get('chapters',[]) or [])}")
    return sorted(set(reasons))


def video_stream_summary(info: dict[str, Any]) -> dict[str, Any]:
    v = primary_stream(info, "video") or {}
    a = primary_stream(info, "audio") or {}
    fmt = info.get("format", {}) or {}
    tags = fmt.get("tags", {}) or {}
    vt = v.get("tags", {}) or {}
    rotation = _rotation_degrees(v)
    sar = v.get("sample_aspect_ratio")
    dar = v.get("display_aspect_ratio")
    dar_value = _display_aspect(v)
    avg_fps = _fps_value(v.get("avg_frame_rate"))
    nominal_fps = _fps_value(v.get("r_frame_rate"))
    vfr_delta = abs(avg_fps-nominal_fps) if avg_fps is not None and nominal_fps is not None else None
    summary_rate_mismatch = bool(vfr_delta is not None and vfr_delta > 0.01)
    return {
        "stream_counts": stream_counts(info),
        "stream_signature": _stream_signature(info),
        "chapter_count": len(info.get("chapters", []) or []),
        "video_codec": v.get("codec_name"),
        "video_profile": v.get("profile"),
        "codec_tag": v.get("codec_tag_string"),
        "width": v.get("width"),
        "height": v.get("height"),
        "sample_aspect_ratio": sar,
        "display_aspect_ratio": dar,
        "display_aspect_ratio_value": round(dar_value, 8) if dar_value is not None else None,
        "rotation": rotation,
        "pix_fmt": v.get("pix_fmt"),
        "avg_frame_rate": v.get("avg_frame_rate"),
        "r_frame_rate": v.get("r_frame_rate"),
        "avg_fps": round(avg_fps, 6) if avg_fps is not None else None,
        "nominal_fps": round(nominal_fps, 6) if nominal_fps is not None else None,
        "summary_rate_mismatch": summary_rate_mismatch,
        "likely_variable_frame_rate": summary_rate_mismatch,
        "audio_codec": a.get("codec_name"),
        "audio_channels": a.get("channels"),
        "audio_channel_layout": a.get("channel_layout"),
        "audio_sample_rate": a.get("sample_rate"),
        "format_name": fmt.get("format_name"),
        "creation_time": tags.get("creation_time") or vt.get("creation_time"),
        "color_range": v.get("color_range"),
        "color_space": v.get("color_space"),
        "color_transfer": v.get("color_transfer"),
        "color_primaries": v.get("color_primaries"),
        "chroma_location": v.get("chroma_location"),
        "hdr_dolby_reasons": _hdr_dolby_reasons(info),
    }


def _round_even(value: float) -> int:
    n = max(2, int(round(value)))
    if n % 2:
        n += 1 if (value - int(value)) >= 0.5 else -1
    return max(2, n)


def expected_full_frame_square_dimensions(source_video: dict[str, Any], max_edge: int) -> Optional[list[int]]:
    """Expected square-pixel dimensions when the entire displayed frame is retained.

    This is intentionally independent of HandBrake's crop detector. It uses the
    source display aspect ratio and no-upscale policy, allowing only codec-friendly
    even-pixel rounding.
    """
    try:
        w = int(source_video.get("width") or 0)
        h = int(source_video.get("height") or 0)
        dar = float(source_video.get("display_aspect_ratio_value") or 0)
    except Exception:
        return None
    if w <= 0 or h <= 0 or dar <= 0:
        return None
    rotation = int(source_video.get("rotation") or 0) % 360
    # For ordinary non-rotated sources, the stored edge determines no-upscale.
    # For 90/270-degree material, use displayed orientation for target geometry.
    display_w, display_h = (h, w) if rotation in (90, 270) else (w, h)
    if max(display_w, display_h) <= max_edge:
        # Preserve the displayed frame dimensions when already within bounds.
        return [_round_even(display_w), _round_even(display_h)]
    if dar >= 1.0:
        ew = max_edge
        eh = _round_even(ew / dar)
    else:
        eh = max_edge
        ew = _round_even(eh * dar)
    return [int(ew), int(eh)]


def verify_staged_output(src: Path, out: Path, item: dict[str, Any], cfg: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not out.exists() or not out.is_file(): return "FAILED", {"error": "output_missing"}
    source_size = src.stat().st_size; output_size = out.stat().st_size
    saving = source_size - output_size
    saving_pct = (saving / source_size * 100.0) if source_size else 0.0
    v: dict[str, Any] = {"source_size": source_size, "output_size": output_size, "saving_bytes": saving, "saving_percent": round(saving_pct, 3)}
    op = item["operation"]
    try:
        if op == "CONVERT_IMAGE":
            from PIL import Image
            with Image.open(out) as oi:
                oi.verify()
            src_im = image_metadata(src); out_im = image_metadata(out)
            v["source_image"] = src_im; v["output_image"] = out_im
            v["output_dimensions"] = out_im["dimensions"]
            v["output_megapixels"] = out_im["megapixels"]
            target_mp = float(item.get("target", {}).get("max_megapixels") or 0)
            v["dimensions_ok"] = not target_mp or v["output_megapixels"] <= target_mp + 0.02
            if not v["dimensions_ok"]: return "FAILED", v | {"error": "image_target_exceeded"}
            v["icc_profile_preserved"] = src_im["icc_sha256"] == out_im["icc_sha256"]
            v["exif_blob_preserved"] = src_im["exif_sha256"] == out_im["exif_sha256"]
            v["exif_orientation_preserved"] = src_im["exif_orientation"] == out_im["exif_orientation"]
        elif op in {"CONVERT_VIDEO", "CONVERT_AUDIO"}:
            sinfo = ffprobe_json(src); oinfo = ffprobe_json(out)
            sd = duration_from_probe(sinfo); od = duration_from_probe(oinfo)
            v["source_duration"] = sd; v["output_duration"] = od
            if sd is not None and od is not None:
                tol = max(float(cfg.get("video_duration_tolerance_seconds", 0.10)), sd * float(cfg.get("video_duration_tolerance_fraction", 0.0025)))
                v["duration_delta"] = abs(sd-od)
                v["duration_tolerance_seconds"] = tol
                if abs(sd-od) > tol: return "FAILED", v | {"error": "duration_mismatch"}
            if op == "CONVERT_VIDEO":
                sv = primary_stream(sinfo, "video"); ov = primary_stream(oinfo, "video")
                if not sv: return "FAILED", v | {"error": "source_video_stream_missing"}
                if not ov: return "FAILED", v | {"error": "output_video_stream_missing"}
                v["source_video"] = video_stream_summary(sinfo)
                v["output_video"] = video_stream_summary(oinfo)
                v["output_video_codec"] = ov.get("codec_name")
                v["output_dimensions"] = [ov.get("width"), ov.get("height")]
                max_edge = int(cfg.get("video_max_storage_edge", 1280))
                v["max_storage_edge"] = max_edge
                v["storage_dimensions_ok"] = max(int(ov.get("width") or 0), int(ov.get("height") or 0)) <= max_edge
                if not v["storage_dimensions_ok"]:
                    return "FAILED", v | {"error": "video_dimensions_exceed_target"}

                # v0.6.2 archive policy: staged video must be square-pixel.
                # HandBrake's legacy PRESET v2 used anamorphic PAR; we now explicitly
                # disable that behavior and independently verify the result here.
                output_sar = str(v["output_video"].get("sample_aspect_ratio") or "").strip().lower()
                v["square_pixels_required"] = bool(cfg.get("video_require_square_pixels", True))
                v["output_square_pixels"] = output_sar in {"1:1", "1/1", "1", "1.0"}
                if v["square_pixels_required"] and not v["output_square_pixels"]:
                    return "FAILED", v | {"error": "output_not_square_pixel"}

                # Display aspect ratio, including source SAR/PAR and rotation, must remain stable.
                sdar=v["source_video"].get("display_aspect_ratio_value")
                odar=v["output_video"].get("display_aspect_ratio_value")
                if sdar is None or odar is None:
                    return "FAILED", v | {"error": "display_aspect_ratio_unavailable"}
                aspect_delta=abs(float(sdar)-float(odar))/max(abs(float(sdar)),1e-9)
                v["display_aspect_ratio_relative_delta"] = aspect_delta
                v["display_aspect_ratio_tolerance"] = float(cfg.get("video_aspect_ratio_tolerance",0.005))
                v["display_aspect_ratio_preserved"] = aspect_delta <= v["display_aspect_ratio_tolerance"]
                if not v["display_aspect_ratio_preserved"]:
                    return "FAILED", v | {"error": "display_aspect_ratio_changed"}

                # v0.8.1 production policy: no implicit HandBrake cropping.
                # The expected geometry is computed independently from the full source
                # display frame. This catches a future preset regression even when DAR
                # happens to remain within tolerance.
                v["crop_policy"] = str(cfg.get("video_crop_policy", "full-frame-no-autocrop"))
                v["requested_crop"] = [0, 0, 0, 0]
                if bool(cfg.get("video_require_full_frame", True)):
                    expected_dims = expected_full_frame_square_dimensions(v["source_video"], max_edge)
                    v["expected_full_frame_dimensions"] = expected_dims
                    actual_dims = [int(ov.get("width") or 0), int(ov.get("height") or 0)]
                    tol_px = int(cfg.get("video_full_frame_dimension_tolerance_pixels", 2))
                    v["full_frame_dimension_tolerance_pixels"] = tol_px
                    v["full_frame_geometry_preserved"] = bool(expected_dims and all(abs(a-b) <= tol_px for a,b in zip(actual_dims, expected_dims)))
                    if not v["full_frame_geometry_preserved"]:
                        return "FAILED", v | {"error": "unexpected_crop_or_geometry_change"}

                src_counts=stream_counts(sinfo); out_counts=stream_counts(oinfo)
                v["stream_counts_preserved"] = all(out_counts.get(k,0)==src_counts.get(k,0) for k in ("video","audio","subtitle","data","attachment"))
                if not v["stream_counts_preserved"]:
                    return "FAILED", v | {"error": "stream_counts_changed"}
                v["chapter_count_preserved"] = len(sinfo.get("chapters",[]) or []) == len(oinfo.get("chapters",[]) or [])
                if not v["chapter_count_preserved"]:
                    return "FAILED", v | {"error": "chapter_count_changed"}

                sa = primary_stream(sinfo, "audio"); oa = primary_stream(oinfo, "audio")
                if sa and not oa: return "FAILED", v | {"error": "audio_stream_lost"}
                if sa and oa:
                    v["audio_channels_preserved"] = sa.get("channels") == oa.get("channels")
                    v["audio_sample_rate_preserved"] = str(sa.get("sample_rate")) == str(oa.get("sample_rate"))
                    v["audio_codec_source"] = sa.get("codec_name"); v["audio_codec_output"] = oa.get("codec_name")
                    if not v["audio_channels_preserved"]: return "FAILED", v | {"error": "audio_channels_changed"}
                    if not v["audio_sample_rate_preserved"]: return "FAILED", v | {"error": "audio_sample_rate_changed"}

                sfps=v["source_video"].get("avg_fps"); ofps=v["output_video"].get("avg_fps")
                if sfps is not None and ofps is not None:
                    fps_delta=abs(float(sfps)-float(ofps))/max(abs(float(sfps)),1e-9)
                    v["frame_rate_relative_delta"] = fps_delta
                    v["frame_rate_tolerance"] = float(cfg.get("video_frame_rate_tolerance_fraction",0.01))
                    v["frame_rate_preserved"] = fps_delta <= v["frame_rate_tolerance"]
                    if not v["frame_rate_preserved"]: return "FAILED", v | {"error": "frame_rate_changed"}

                # Color signaling is safety-critical: preserve known source values exactly.
                color_keys=("color_range","color_space","color_transfer","color_primaries","chroma_location")
                v["color_metadata_checks"]={}
                for key in color_keys:
                    srcval=v["source_video"].get(key); outval=v["output_video"].get(key)
                    ok_color = srcval in (None, "", "unknown") or srcval == outval
                    v["color_metadata_checks"][key]={"source":srcval,"output":outval,"preserved":ok_color}
                    if not ok_color: return "FAILED", v | {"error": f"color_metadata_changed:{key}"}

                v["embedded_creation_time_preserved"] = (
                    not v["source_video"].get("creation_time")
                    or v["source_video"].get("creation_time") == v["output_video"].get("creation_time")
                )
                if not v["embedded_creation_time_preserved"]:
                    return "FAILED", v | {"error": "embedded_creation_time_changed"}
                source_rotation = int(v["source_video"].get("rotation") or 0) % 360
                output_rotation = int(v["output_video"].get("rotation") or 0) % 360

                # HandBrake may normalize 90/270-degree display-matrix rotation
                # into the encoded pixel geometry. For example, a source stored
                # as 848x480 + rotation 270 may correctly become 480x848 +
                # rotation 0. That is visual preservation, not a rotation loss.
                #
                # Keep exact metadata equality as the normal case. Accept baked
                # 90/270-degree normalization only when the independently
                # verified full-frame geometry and display aspect ratio agree.
                rotation_metadata_equal = source_rotation == output_rotation
                rotation_baked_into_pixels = (
                    source_rotation in {90, 270}
                    and output_rotation == 0
                    and bool(v.get("full_frame_geometry_preserved"))
                    and bool(v.get("display_aspect_ratio_preserved"))
                )

                v["rotation_metadata_equal"] = rotation_metadata_equal
                v["rotation_baked_into_pixels"] = rotation_baked_into_pixels
                v["rotation_preserved"] = (
                    rotation_metadata_equal
                    or rotation_baked_into_pixels
                )

                if not v["rotation_preserved"]:
                    return "FAILED", v | {"error": "rotation_changed"}
            else:
                oa = primary_stream(oinfo, "audio")
                if not oa: return "FAILED", v | {"error": "output_audio_stream_missing"}
                v["output_audio_codec"] = oa.get("codec_name")
    except Exception as exc:
        return "FAILED", v | {"error": f"verification_exception:{exc}"}
    min_pct = float(cfg.get("minimum_saving_percent", 10.0))
    min_bytes = int(cfg.get("minimum_saving_bytes", 1048576))
    v["minimum_saving_percent"] = min_pct; v["minimum_saving_bytes"] = min_bytes
    worthwhile = output_size < source_size and (saving_pct >= min_pct or saving >= min_bytes)
    v["worthwhile_saving"] = worthwhile
    if not worthwhile: return "KEEP_ORIGINAL", v
    src_fs = filesystem_metadata(src); out_fs = filesystem_metadata(out)
    v["source_filesystem"] = src_fs; v["output_filesystem"] = out_fs
    v["mtime_preserved"] = abs(int(src_fs["mtime_ns"]) - int(out_fs["mtime_ns"])) <= 1_000_000
    sb=src_fs.get("birth_ts"); ob=out_fs.get("birth_ts")
    birth_tol = float(cfg.get("creation_time_tolerance_seconds", 1.0))
    if sb is None or ob is None:
        v["creation_time_delta_seconds"] = None
        v["creation_time_tolerance_seconds"] = birth_tol
        v["creation_date_preserved"] = None
    else:
        birth_delta = abs(float(sb) - float(ob))
        v["creation_time_delta_seconds"] = round(birth_delta, 6)
        v["creation_time_tolerance_seconds"] = birth_tol
        # APFS/macOS birth-time round trips can quantize to adjacent whole seconds.
        # Accept only the configured narrow tolerance; larger drift remains a blocker.
        v["creation_date_preserved"] = birth_delta <= birth_tol
    v["metadata_commit_blockers"] = []
    if cfg.get("require_creation_date_before_commit", True) and v["creation_date_preserved"] is not True:
        v["metadata_commit_blockers"].append("creation_date_not_preserved")
    # Finder tag copy validation only for tags that exist on source.
    src_tags = read_finder_tags_safe(src); out_tags = read_finder_tags_safe(out)
    excluded = set(cfg.get("personal_tags_exclude", []))
    expected_personal = sorted(t for t in src_tags if t not in excluded)
    v["source_finder_tags"] = src_tags; v["expected_personal_tags"] = expected_personal; v["staged_finder_tags"] = out_tags
    v["personal_finder_tags_match"] = expected_personal == sorted(out_tags)
    if cfg.get("stage_copy_personal_finder_tags", True) and expected_personal and not v["personal_finder_tags_match"]:
        return "FAILED", v | {"error": "personal_finder_tags_not_preserved_in_staging"}
    if any(t in excluded for t in out_tags):
        return "FAILED", v | {"error": "legacy_workflow_tag_leaked_into_staging"}
    v["metadata_ready_for_commit"] = not bool(v.get("metadata_commit_blockers"))
    return "STAGED_VERIFIED", v


def preflight_free_space(state_dir: Path, estimated_bytes: int, label: str) -> dict[str, int]:
    usage = shutil.disk_usage(state_dir)
    reserve = 256 * 1024 * 1024
    required = max(0, int(estimated_bytes)) + reserve
    if usage.free < required:
        raise SystemExit(f"Insufficient free disk space for {label}: need about {required/1024**3:.2f} GiB including reserve, have {usage.free/1024**3:.2f} GiB")
    return {"free_bytes": int(usage.free), "estimated_bytes": int(estimated_bytes), "reserve_bytes": reserve, "required_bytes": required}


def stage_space_estimate(selected: list[dict[str, Any]], root: Path) -> int:
    total = 0
    for item in selected:
        try:
            total += (root / item["relpath"]).stat().st_size
        except OSError:
            pass
    return int(total * 1.25)


def commit_space_estimate(candidates: list[dict[str, Any]]) -> int:
    total = 0
    for r in candidates:
        try:
            total += Path(r.get("output_path", "")).stat().st_size
        except OSError:
            pass
    return int(total * 1.10)


def validate_stage_limits(args: argparse.Namespace) -> None:
    if args.max_images < 0 or args.max_images > 250:
        raise SystemExit("--max-images must be between 0 and 250")
    if args.max_videos < 0 or args.max_videos > 50:
        raise SystemExit("--max-videos must be between 0 and 50; v0.8.1 keeps video staging windowed")
    if args.max_audio < 0 or args.max_audio > 10:
        raise SystemExit("--max-audio must be between 0 and 10")


def cmd_stage(args: argparse.Namespace) -> int:
    validate_stage_limits(args)
    plan_path = Path(args.plan).expanduser().resolve()
    plan = load_plan(plan_path)
    root = Path(plan["root"]).resolve()
    if not root.is_dir(): raise SystemExit(f"Plan root is unavailable: {root}")
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists(): raise SystemExit(f"State database not found: {db_path}")
    cfg = load_config(Path(args.config).expanduser() if args.config else None)
    package_dir = Path(__file__).resolve().parent
    # Ensure plan is the exact plan registered in DB.
    con = init_db(db_path, root); con.row_factory = sqlite3.Row
    dbplan = con.execute("SELECT * FROM plans WHERE plan_id=?", (plan["plan_id"],)).fetchone()
    if not dbplan: raise SystemExit("Plan is not registered in this state database")
    staging_id = sha256_text(canonical_json({"plan_id": plan["plan_id"], "started": now_iso()}))[:16]
    stage_dir = state_dir / "staging" / staging_id
    stage_dir.mkdir(parents=True, exist_ok=False)
    con.execute("INSERT INTO staging_runs(staging_id,plan_id,started_at,status,staging_dir) VALUES(?,?,?,?,?)", (staging_id,plan["plan_id"],now_iso(),"RUNNING",str(stage_dir)))
    con.commit()
    limits = {"CONVERT_IMAGE": int(args.max_images), "CONVERT_VIDEO": int(args.max_videos), "CONVERT_AUDIO": int(args.max_audio)}
    if limits["CONVERT_IMAGE"] < 0 or limits["CONVERT_IMAGE"] > 250:
        raise SystemExit("--max-images must be between 0 and 250 in v0.6.1")
    assets = asset_metadata_map(con)
    committed_before = already_committed_relpaths(db_path)
    resolved_before = resolved_keep_original_relpaths(con, plan["plan_id"])
    excluded_before = committed_before | resolved_before
    selected = select_stage_items(plan, limits, args.sample_strategy, assets, root, cfg, excluded_before)
    expected_video_policy = str((cfg.get("policies") or {}).get("streams_video") or "")
    mismatched_video = [i for i in selected if i.get("operation") == "CONVERT_VIDEO" and str(i.get("policy_version") or "") != expected_video_policy]
    if mismatched_video:
        con.execute("UPDATE staging_runs SET completed_at=?,status=? WHERE staging_id=?", (now_iso(), "FAILED_POLICY_MISMATCH", staging_id))
        con.commit(); con.close()
        shutil.rmtree(stage_dir, ignore_errors=True)
        got = str(mismatched_video[0].get("policy_version") or "")
        raise SystemExit(f"Frozen plan video policy is {got!r}, but this build/config requires {expected_video_policy!r}. Regenerate the plan before staging video.")
    preflight = preflight_free_space(state_dir, stage_space_estimate(selected, root), "staging")
    counts = Counter(i["operation"] for i in selected)
    tag_probe = None
    if args.require_personal_tag_sample:
        tag_probe = choose_personal_tag_probe(con, root, cfg, {i["relpath"] for i in selected})
        if tag_probe is None:
            con.execute("UPDATE staging_runs SET completed_at=?,status=? WHERE staging_id=?", (now_iso(), "FAILED_NO_PERSONAL_TAG_SAMPLE", staging_id))
            con.commit(); con.close()
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise SystemExit("No live personally tagged media file was found for the required tag-preservation probe")
    print(f"Veronica {VERSION} staging executor")
    emit_event("staging_started", plan_id=plan["plan_id"], selected_images=counts["CONVERT_IMAGE"], selected_videos=counts["CONVERT_VIDEO"], selected_audio=counts["CONVERT_AUDIO"])
    print(f"Plan: {plan['plan_id']}")
    print(f"Mode: STAGING ONLY — source media will not be modified")
    print(f"Selected: images={counts['CONVERT_IMAGE']} videos={counts['CONVERT_VIDEO']} audio={counts['CONVERT_AUDIO']}")
    print(f"Already committed and skipped: {len(committed_before)}")
    print(f"KEEP_ORIGINAL resolved and skipped: {len(resolved_before)}")
    print(f"Disk preflight: {preflight['free_bytes']/1024**3:.2f} GiB free; estimated staging need {preflight['required_bytes']/1024**3:.2f} GiB incl. reserve")
    if tag_probe:
        print(f"Tag probe: {tag_probe['relpath']} tags={tag_probe['personal_tags']}")
    results=[]
    for idx,item in enumerate(selected,1):
        src=root/item["relpath"]
        ok, why=verify_source_against_item(root,item)
        rec={"relpath":item["relpath"],"operation":item["operation"],"status":"", "source_verification":why,
             "sample_reason":item.get("sample_reason","unspecified"), "policy_version":item.get("policy_version")}
        if not ok:
            rec["status"]="STALE_PLAN"; rec["error"]=why; results.append(rec)
            print(f"[{idx}/{len(selected)}] STALE {item['relpath']} ({why})")
            continue
        if item["operation"] == "CONVERT_VIDEO":
            try:
                source_probe = ffprobe_json(src)
                source_summary = video_stream_summary(source_probe)
                frame_timing = None
                if cfg.get("video_review_vfr", True) and source_summary.get("summary_rate_mismatch"):
                    frame_timing = video_frame_timing_summary(src)
                review_reasons = video_source_review_reasons(source_probe, cfg, frame_timing)
            except Exception as exc:
                rec["status"]="FAILED"; rec["error"]=f"source_video_probe_failed:{exc}"; results.append(rec)
                print(f"[{idx}/{len(selected)}] FAILED          {item['relpath']} ({rec['error']})")
                continue
            if review_reasons:
                rec["status"]="REVIEW_SOURCE"
                rec["review_reasons"]=review_reasons
                rec["source_video"]=video_stream_summary(source_probe)
                if frame_timing is not None:
                    rec["source_video"]["frame_timing"] = frame_timing
                    rec["source_video"]["frame_timing_classification"] = classify_video_frame_timing(frame_timing, cfg)
                results.append(rec)
                print(f"[{idx}/{len(selected)}] REVIEW_SOURCE   {item['relpath']} ({', '.join(review_reasons)})")
                continue
        rel=Path(item["relpath"])
        marker=(item.get("source_quick_hash") or "nohash")[:8]
        outbase=stage_dir/"outputs"/rel.parent/f"{rel.stem}.__stage_{marker}{rel.suffix}"
        try:
            if item["operation"]=="CONVERT_IMAGE": meta=convert_image_stage(src,outbase,item,cfg)
            elif item["operation"]=="CONVERT_VIDEO": meta=convert_video_stage(src,outbase,item,cfg,package_dir)
            else: meta=convert_audio_stage(src,outbase,item,cfg)
            out=Path(meta["output_path"])
            status,verification=verify_staged_output(src,out,item,cfg)
            rec.update(status=status, output_path=str(out), conversion=meta, verification=verification)
            print(f"[{idx}/{len(selected)}] {status:<15} {item['relpath']}  {verification.get('saving_percent',0):.1f}%")
            emit_event("stage_item", index=idx, total=len(selected), relpath=item["relpath"], operation=item["operation"], status=status, saving_percent=verification.get("saving_percent",0))
        except Exception as exc:
            rec["status"]="FAILED"; rec["error"]=str(exc)
            print(f"[{idx}/{len(selected)}] FAILED          {item['relpath']} ({exc})")
            emit_event("stage_item", index=idx, total=len(selected), relpath=item["relpath"], operation=item["operation"], status="FAILED", error=str(exc))
        results.append(rec)
    if tag_probe:
        try:
            probe_result = run_personal_tag_probe(root, stage_dir, tag_probe, cfg)
        except Exception as exc:
            probe_result = {"relpath": tag_probe["relpath"], "operation": "TAG_PROBE_COPY", "sample_reason": tag_probe.get("sample_reason"), "status": "TAG_PROBE_FAILED", "error": str(exc), "diagnostic_only": True, "commit_eligible": False}
        results.append(probe_result)
        print(f"[tag-probe] {probe_result['status']:<18} {tag_probe['relpath']} tags={probe_result.get('expected_personal_tags', [])}")
    report={"schema_version":1,"tool_version":VERSION,"staging_id":staging_id,"plan_id":plan["plan_id"],"root":str(root),"created_at":now_iso(),"stage_dir":str(stage_dir),"preflight":preflight,"already_committed_skipped":len(committed_before),"keep_original_resolved_skipped":len(resolved_before),"results":results}
    report_json=state_dir/f"staging-{staging_id}.json"
    report_md=state_dir/f"staging-{staging_id}.md"
    report_json.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    rc=Counter(r["status"] for r in results)
    lines=["# Veronica Staging Report","",f"- Tool version: `{VERSION}`",f"- Plan: `{plan['plan_id']}`",f"- Staging ID: `{staging_id}`",f"- Source root: `{root}`",f"- Staging directory: `{stage_dir}`","","## Results","","| Status | Files |","|---|---:|"]
    for k,v in rc.most_common(): lines.append(f"| `{k}` | {v} |")
    verified=[r for r in results if r.get("status")=="STAGED_VERIFIED"]
    verified_images=[r for r in verified if r.get("operation")=="CONVERT_IMAGE"]
    verified_videos=[r for r in verified if r.get("operation")=="CONVERT_VIDEO"]
    commit_ready=sum(1 for r in verified_images if r.get("verification",{}).get("metadata_ready_for_commit") is True)
    metadata_blocked=sum(1 for r in verified_images if r.get("verification",{}).get("metadata_ready_for_commit") is False)
    lines += ["","## Commit readiness","",f"- Image outputs ready for commit: **{commit_ready}**",f"- Image outputs blocked by metadata requirements: **{metadata_blocked}**",f"- Verified video outputs ready for policy-locked video commit: **{len(verified_videos)}**","","A metadata blocker does not change the source file. Verified videos may be committed with the policy-locked one-file or bounded batch commands; every committed original is quarantined independently."]
    probes=[r for r in results if r.get("operation")=="TAG_PROBE_COPY"]
    if probes:
        pr=probes[0]
        lines += ["","## Personal Finder-tag probe","",f"- Status: **{pr.get('status')}**",f"- Source: `{pr.get('relpath')}`",f"- Expected personal tags: `{pr.get('expected_personal_tags',[])}`",f"- Staged tags: `{pr.get('staged_finder_tags',[])}`",f"- Source unchanged: `{pr.get('source_unchanged')}`",f"- Byte-identical diagnostic copy: `{pr.get('byte_identical_copy')}`",f"- Legacy workflow tags leaked: `{pr.get('legacy_tags_leaked',[])}`","","This probe is diagnostic only and can never be committed."]
    lines += ["","## Items",""]
    for r in results:
        if r.get("operation") == "TAG_PROBE_COPY":
            lines.append(f"- `{r['status']}` — `{r['relpath']}` — sample `{r.get('sample_reason','unspecified')}` — diagnostic only")
            continue
        ver=r.get("verification",{})
        sv=ver.get("saving_percent")
        saving=f" — saving {sv:.1f}%" if isinstance(sv,(int,float)) else ""
        err=f" — {r.get('error')}" if r.get("error") else ""
        reason=f" — sample `{r.get('sample_reason','unspecified')}`"
        lines.append(f"- `{r['status']}` — `{r['relpath']}`{saving}{reason}{err}")
        if r.get("status")=="REVIEW_SOURCE":
            lines.append(f"  - **source review reasons:** `{r.get('review_reasons',[])}`")
            sv=r.get("source_video",{})
            if sv:
                lines.append(f"  - source geometry: stored {sv.get('width')}x{sv.get('height')}; SAR `{sv.get('sample_aspect_ratio')}`; DAR `{sv.get('display_aspect_ratio')}`; rotation `{sv.get('rotation')}`")
                lines.append(f"  - streams: `{sv.get('stream_counts')}`; chapters: `{sv.get('chapter_count')}`; HDR/Dolby flags: `{sv.get('hdr_dolby_reasons')}`")
        if r.get("status") in {"STAGED_VERIFIED","KEEP_ORIGINAL"}:
            si=ver.get("source_image",{}); oi=ver.get("output_image",{})
            if si and oi:
                lines.append(f"  - dimensions: {si.get('dimensions')} ({si.get('megapixels')} MP) → {oi.get('dimensions')} ({oi.get('megapixels')} MP)")
                lines.append(f"  - ICC preserved: `{ver.get('icc_profile_preserved')}`; EXIF blob preserved: `{ver.get('exif_blob_preserved')}`; orientation preserved: `{ver.get('exif_orientation_preserved')}`")
            if r.get("operation")=="CONVERT_VIDEO" and ver.get("source_video"):
                svi=ver.get("source_video",{}); ovi=ver.get("output_video",{})
                lines.append(f"  - video: {svi.get('video_codec')} {svi.get('width')}x{svi.get('height')} → {ovi.get('video_codec')} {ovi.get('width')}x{ovi.get('height')}")
                lines.append(f"  - aspect: SAR `{svi.get('sample_aspect_ratio')}` / DAR `{svi.get('display_aspect_ratio')}` → SAR `{ovi.get('sample_aspect_ratio')}` / DAR `{ovi.get('display_aspect_ratio')}`; display ratio preserved: `{ver.get('display_aspect_ratio_preserved')}`; square pixels: `{ver.get('output_square_pixels')}`")
                lines.append(f"  - crop policy: `{ver.get('crop_policy')}`; requested crop: `{ver.get('requested_crop')}`; expected full-frame dimensions: `{ver.get('expected_full_frame_dimensions')}`; full-frame geometry preserved: `{ver.get('full_frame_geometry_preserved')}`")
                lines.append(f"  - frame rate: `{svi.get('avg_frame_rate')}` → `{ovi.get('avg_frame_rate')}`; preserved: `{ver.get('frame_rate_preserved')}`; source VFR-like: `{svi.get('likely_variable_frame_rate')}`")
                lines.append(f"  - duration delta: `{ver.get('duration_delta')}` s (tolerance `{ver.get('duration_tolerance_seconds')}`); source/output streams: `{svi.get('stream_counts')}` → `{ovi.get('stream_counts')}`")
                lines.append(f"  - audio: {svi.get('audio_codec')} {svi.get('audio_channels')}ch @{svi.get('audio_sample_rate')} → {ovi.get('audio_codec')} {ovi.get('audio_channels')}ch @{ovi.get('audio_sample_rate')}; channels preserved: `{ver.get('audio_channels_preserved')}`; sample rate preserved: `{ver.get('audio_sample_rate_preserved')}`")
                lines.append(f"  - color metadata: `{ver.get('color_metadata_checks')}`")
                lines.append(f"  - embedded creation time preserved: `{ver.get('embedded_creation_time_preserved')}`; rotation preserved: `{ver.get('rotation_preserved')}`; chapters preserved: `{ver.get('chapter_count_preserved')}`")
            lines.append(f"  - mtime preserved: `{ver.get('mtime_preserved')}`; creation date preserved: `{ver.get('creation_date_preserved')}`; creation-time delta: `{ver.get('creation_time_delta_seconds')}` s")
            lines.append(f"  - personal Finder tags match: `{ver.get('personal_finder_tags_match')}`; tags: `{ver.get('expected_personal_tags',[])}`")
            if ver.get("metadata_commit_blockers"):
                lines.append(f"  - **commit blocker:** `{', '.join(ver.get('metadata_commit_blockers',[]))}`")
    lines += ["","## Safety","","No source media were replaced, renamed, moved, retagged, or deleted. All generated media is confined to the staging directory. `KEEP_ORIGINAL` means the staged output validated but did not meet the configured benefit threshold.",""]
    report_md.write_text("\n".join(lines),encoding="utf-8")
    selected_by_rel = {i["relpath"]: i for i in selected}
    for r in results:
        ver=r.get("verification",{})
        con.execute("INSERT OR REPLACE INTO staging_items(staging_id,relpath,operation,status,source_size,output_size,saving_bytes,saving_percent,output_path,verification_json,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(staging_id,r["relpath"],r["operation"],r["status"],ver.get("source_size"),ver.get("output_size"),ver.get("saving_bytes"),ver.get("saving_percent"),r.get("output_path"),canonical_json(ver),r.get("error")))
        if r.get("status") == "KEEP_ORIGINAL" and r.get("operation") in {"CONVERT_IMAGE", "CONVERT_VIDEO", "CONVERT_AUDIO"}:
            item = selected_by_rel.get(r.get("relpath"))
            if item is not None:
                con.execute(
                    "INSERT OR IGNORE INTO disposition_history(asset_id,plan_id,policy_version,operation,disposition,decided_at,source_quick_hash,source_size,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
                    (item.get("asset_id"), plan["plan_id"], item.get("policy_version"), item.get("operation"),
                     "KEEP_ORIGINAL", now_iso(), item.get("source_quick_hash"), item.get("source_size"), canonical_json(ver)),
                )
    con.execute("UPDATE staging_runs SET completed_at=?,status=?,report_path=? WHERE staging_id=?",(now_iso(),"COMPLETE",str(report_md),staging_id)); con.commit(); con.close()
    print("Results: " + ", ".join(f"{k}={v}" for k,v in rc.items()))
    print(f"Staging directory: {stage_dir}")
    print(f"Report: {report_md}")
    print(f"JSON: {report_json}")
    return 0


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def fsync_file(path: Path) -> None:
    with path.open("rb") as f:
        os.fsync(f.fileno())


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def find_plan_item(plan: dict[str, Any], relpath: str) -> Optional[dict[str, Any]]:
    for item in plan.get("items", []):
        if item.get("relpath") == relpath:
            return item
    return None


def load_staging_report(state_dir: Path, staging_id: str) -> dict[str, Any]:
    path = state_dir / f"staging-{staging_id}.json"
    if not path.exists():
        raise SystemExit(f"Staging report not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("staging_id") != staging_id:
        raise SystemExit("Staging report ID mismatch")
    return data


def choose_commit_candidate(report: dict[str, Any], relpath: Optional[str]) -> dict[str, Any]:
    candidates = [r for r in report.get("results", [])
                  if r.get("status") == "STAGED_VERIFIED"
                  and r.get("operation") == "CONVERT_IMAGE"
                  and r.get("verification", {}).get("metadata_ready_for_commit") is True]
    if relpath:
        candidates = [r for r in candidates if r.get("relpath") == relpath]
        if not candidates:
            raise SystemExit("Requested relpath is not a commit-ready staged image in this staging run")
    if not candidates:
        raise SystemExit("No commit-ready staged images found")
    return candidates[0]


def commit_one(args: argparse.Namespace, quiet: bool = False) -> dict[str, Any]:
    if not args.yes:
        raise SystemExit("Commit requires --yes. This command changes one file in Media and quarantines the original.")
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")
    report = load_staging_report(state_dir, args.staging_id)
    plan_id = report.get("plan_id")
    plan_candidates = sorted(state_dir.glob(f"plan-*-{str(plan_id)[:12]}.json"))
    if not plan_candidates:
        raise SystemExit(f"Frozen plan JSON not found for plan {plan_id}")
    plan = load_plan(plan_candidates[-1])
    root = Path(plan["root"]).resolve()
    cfg = load_config(Path(args.config).expanduser() if args.config else None)
    if root.stat().st_dev != state_dir.stat().st_dev:
        raise SystemExit("v0.4.0 requires Media and the state directory to be on the same filesystem for atomic quarantine/rollback")
    staged = choose_commit_candidate(report, args.relpath)
    relpath = staged["relpath"]
    item = find_plan_item(plan, relpath)
    if not item or item.get("operation") != "CONVERT_IMAGE" or not item.get("executable"):
        raise SystemExit("Plan item is no longer an executable image conversion")
    source = root / relpath
    staged_path = Path(staged.get("output_path", "")).resolve()
    if not staged_path.is_file():
        raise SystemExit(f"Staged output missing: {staged_path}")
    expected_stage_root = (state_dir / "staging" / args.staging_id).resolve()
    if expected_stage_root not in staged_path.parents:
        raise SystemExit("Staged output is outside the expected staging directory")
    ok, why = verify_source_against_item(root, item)
    if not ok:
        raise SystemExit(f"Refusing commit: frozen plan is stale for {relpath}: {why}")
    # Re-verify staged media immediately before any source mutation.
    status, verification = verify_staged_output(source, staged_path, item, cfg)
    if status != "STAGED_VERIFIED" or verification.get("metadata_ready_for_commit") is not True:
        raise SystemExit(f"Refusing commit: staged output no longer verifies ({status})")
    final_relpath = str((item.get("target") or {}).get("final_relpath") or relpath)
    final_rel = Path(final_relpath)
    if final_rel.is_absolute() or ".." in final_rel.parts:
        raise SystemExit("Refusing commit: invalid final_relpath in frozen plan")
    final_path = root / final_rel
    if final_path != source and final_path.exists():
        raise SystemExit(f"Refusing commit: destination already exists: {final_path}")

    original_sha = sha256_file(source)
    staged_sha = sha256_file(staged_path)
    commit_id = sha256_text(canonical_json({"staging_id": args.staging_id, "relpath": relpath, "started": now_iso()}))[:16]
    quarantine_dir = state_dir / "quarantine" / commit_id
    quarantine_path = quarantine_dir / relpath
    quarantine_path.parent.mkdir(parents=True, exist_ok=False)

    con = init_db(db_path, root)
    con.row_factory = sqlite3.Row
    asset_row = con.execute(
        "SELECT asset_id FROM assets WHERE relpath=?",
        (relpath,),
    ).fetchone()
    if not asset_row:
        con.close()
        raise SystemExit("Refusing commit: source asset is missing from the state database")
    asset_id = int(asset_row["asset_id"])

    if final_relpath != relpath:
        conflict = con.execute(
            "SELECT asset_id FROM assets WHERE relpath=? AND asset_id<>?",
            (final_relpath, asset_id),
        ).fetchone()
        if conflict:
            con.close()
            raise SystemExit(
                f"Refusing commit: destination relpath already belongs to another "
                f"database asset: {final_relpath}"
            )

    con.execute("INSERT INTO commits(commit_id,staging_id,plan_id,started_at,status,quarantine_dir) VALUES(?,?,?,?,?,?)",
                (commit_id, args.staging_id, plan_id, now_iso(), "RUNNING", str(quarantine_dir)))
    con.commit()

    final_tmp = final_path.parent / f".{final_path.name}.media-maintenance-{commit_id}.tmp"
    moved_to_quarantine = False
    installed = False
    details: dict[str, Any] = {
        "precommit_verification": verification,
        "asset_id": asset_id,
        "original_relpath": relpath,
        "final_relpath": final_relpath,
        "policy_version": item.get("policy_version"),
    }
    try:
        # Atomic move of the original out of Media; never delete it.
        os.replace(source, quarantine_path)
        moved_to_quarantine = True
        fsync_dir(source.parent); fsync_dir(quarantine_path.parent)
        # Copy staged bytes into a same-directory temp, then atomically install.
        shutil.copyfile(staged_path, final_tmp)
        fsync_file(final_tmp)
        # Reapply staged filesystem metadata and personal tags to the temp copy.
        st = staged_path.stat()
        set_creation_time(final_tmp, getattr(st, "st_birthtime", None))
        os.utime(final_tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        staged_personal_tags = [t for t in read_finder_tags_safe(staged_path) if t not in set(cfg.get("personal_tags_exclude", []))]
        if staged_personal_tags:
            tag_ok, tag_msg, copied = copy_personal_finder_tags_xattr(staged_path, final_tmp, cfg)
            if not tag_ok:
                raise RuntimeError(f"could_not_copy_personal_tags_to_final_temp:{tag_msg}")
        else:
            tag_ok, tag_msg, copied = True, "no_personal_tags", []
        if sha256_file(final_tmp) != staged_sha:
            raise RuntimeError("temp_copy_hash_mismatch")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(final_tmp, final_path)
        installed = True
        fsync_dir(final_path.parent)
        final_sha = sha256_file(final_path)
        if final_sha != staged_sha:
            raise RuntimeError("final_hash_mismatch")
        final_status, final_ver = verify_staged_output(quarantine_path, final_path, item, cfg)
        details["final_verification"] = final_ver
        if final_status != "STAGED_VERIFIED" or final_ver.get("metadata_ready_for_commit") is not True:
            raise RuntimeError(f"final_media_verification_failed:{final_status}")

        fst = final_path.stat()
        con.execute(
            "UPDATE assets SET relpath=?,size=?,mtime_ns=?,birth_ts=?,quick_hash=?,full_hash=?,"
            "extension=?,active=1 WHERE asset_id=?",
            (
                final_relpath,
                int(fst.st_size),
                int(fst.st_mtime_ns),
                getattr(fst, "st_birthtime", None),
                audit.quick_hash(final_path),
                final_sha,
                final_path.suffix.lower(),
                asset_id,
            ),
        )

        con.execute("INSERT INTO processing_history(asset_id,policy_version,operation,status,processed_at,source_quick_hash,source_full_hash,output_quick_hash,output_full_hash,details_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, item.get("policy_version"), item.get("operation"), "COMMITTED", now_iso(),
                     item.get("source_quick_hash"), original_sha, audit.quick_hash(final_path), final_sha,
                     canonical_json({"commit_id": commit_id, "staging_id": args.staging_id,
                                     "original_relpath": relpath, "final_relpath": final_relpath})))
        con.execute("INSERT INTO commit_items(commit_id,relpath,operation,status,source_original_sha256,staged_sha256,final_sha256,quarantine_path,final_path,details_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (commit_id, relpath, item["operation"], "COMMITTED", original_sha, staged_sha, final_sha,
                     str(quarantine_path), str(final_path), canonical_json(details)))
        report_path = state_dir / f"commit-{commit_id}.md"
        report_path.write_text("\n".join([
            "# Veronica Commit Report", "",
            f"- Tool version: `{VERSION}`", f"- Commit ID: `{commit_id}`", f"- Staging ID: `{args.staging_id}`",
            f"- Original file: `{relpath}`", f"- Installed file: `{final_relpath}`",
            f"- Original quarantine: `{quarantine_path}`", "",
            "## Result", "", "- Status: **COMMITTED**", f"- Original SHA-256: `{original_sha}`", f"- Final SHA-256: `{final_sha}`",
            f"- Saving: **{verification.get('saving_percent',0):.1f}%**", "", "## Safety", "",
            "The original was not deleted. It remains in quarantine and can be restored with the rollback command.", ""
        ]), encoding="utf-8")
        con.execute("UPDATE commits SET completed_at=?,status='COMMITTED',report_path=? WHERE commit_id=?", (now_iso(), str(report_path), commit_id))
        con.commit()
        result = {"status": "COMMITTED", "relpath": relpath, "final_relpath": final_relpath,
                  "commit_id": commit_id, "quarantine_path": str(quarantine_path),
                  "report_path": str(report_path),
                  "saving_percent": float(verification.get("saving_percent",0) or 0)}
        if not quiet:
            print(f"Veronica {VERSION} commit")
            print("Mode: ONE-FILE COMMIT WITH QUARANTINE")
            print(f"COMMITTED: {relpath} -> {final_relpath}")
            print(f"Original quarantine: {quarantine_path}")
            print(f"Report: {report_path}")
            print(f"Commit ID: {commit_id}")
        return result
    except Exception as exc:
        # Best-effort automatic rollback: remove/move installed candidate, restore original.
        rollback_note = str(exc)
        try:
            if final_tmp.exists():
                final_tmp.unlink()
            if moved_to_quarantine and quarantine_path.exists():
                if final_path.exists():
                    failed_dir = state_dir / "failed-commit-output" / commit_id / final_relpath
                    failed_dir.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final_path, failed_dir)
                os.replace(quarantine_path, source)
                fsync_dir(source.parent)
                restored_sha = sha256_file(source)
                if restored_sha != original_sha:
                    rollback_note += "; automatic_restore_hash_mismatch"
                else:
                    rollback_note += "; original_restored"
        finally:
            con.execute("INSERT OR REPLACE INTO commit_items(commit_id,relpath,operation,status,source_original_sha256,staged_sha256,quarantine_path,final_path,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
                        (commit_id, relpath, item["operation"], "FAILED_ROLLED_BACK", original_sha, staged_sha,
                         str(quarantine_path), str(final_path), canonical_json({"error": rollback_note, **details})))
            con.execute("UPDATE commits SET completed_at=?,status='FAILED_ROLLED_BACK' WHERE commit_id=?", (now_iso(), commit_id))
            con.commit(); con.close()
        raise SystemExit(f"Commit failed safely: {rollback_note}")
    finally:
        try:
            con.close()
        except Exception:
            pass




def choose_audio_commit_candidate(report: dict[str, Any], relpath: str) -> dict[str, Any]:
    candidates = [
        r for r in report.get("results", [])
        if r.get("status") == "STAGED_VERIFIED"
        and r.get("operation") == "CONVERT_AUDIO"
        and r.get("verification", {}).get("metadata_ready_for_commit") is True
        and r.get("relpath") == relpath
    ]
    if not candidates:
        raise SystemExit(
            "Requested relpath is not a verified staged audio file in this staging run"
        )
    return candidates[0]


def commit_one_audio(args: argparse.Namespace, quiet: bool = False) -> dict[str, Any]:
    if not args.yes:
        raise SystemExit(
            "Audio commit requires --yes. This command changes exactly one audio file "
            "and quarantines the original."
        )

    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")

    report = load_staging_report(state_dir, args.staging_id)
    plan_id = report.get("plan_id")
    plan_candidates = sorted(
        state_dir.glob(f"plan-*-{str(plan_id)[:12]}.json")
    )
    if not plan_candidates:
        raise SystemExit(f"Frozen plan JSON not found for plan {plan_id}")

    plan = load_plan(plan_candidates[-1])
    root = Path(plan["root"]).resolve()
    cfg = load_config(Path(args.config).expanduser() if args.config else None)

    if root.stat().st_dev != state_dir.stat().st_dev:
        raise SystemExit(
            "Audio commit requires Media and the state directory on the same "
            "filesystem for atomic quarantine/rollback"
        )

    staged = choose_audio_commit_candidate(report, args.relpath)
    relpath = staged["relpath"]
    item = find_plan_item(plan, relpath)

    if (
        not item
        or item.get("operation") != "CONVERT_AUDIO"
        or not item.get("executable")
    ):
        raise SystemExit("Plan item is no longer an executable audio conversion")

    # Lock commit to the exact frozen/current audio policy, just as video
    # commit is locked to its frozen/current video policy.
    plan_policy = (
        (plan.get("policy_snapshot", {}).get("policies", {}) or {})
        .get("streams_audio")
    )
    if not plan_policy:
        raise SystemExit("Refusing audio commit: frozen plan has no audio policy")

    policies = {
        "required": plan_policy,
        "plan": plan_policy,
        "item": item.get("policy_version"),
        "staged": staged.get("policy_version"),
        "config": (cfg.get("policies", {}) or {}).get("streams_audio"),
    }
    if len(set(policies.values())) != 1:
        raise SystemExit(
            "Refusing audio commit: policy mismatch: "
            + ", ".join(f"{k}={v}" for k, v in policies.items())
        )

    source = root / relpath
    staged_path = Path(staged.get("output_path", "")).resolve()

    if not staged_path.is_file():
        raise SystemExit(f"Staged output missing: {staged_path}")

    expected_stage_root = (
        state_dir / "staging" / args.staging_id
    ).resolve()
    if expected_stage_root not in staged_path.parents:
        raise SystemExit("Staged output is outside the expected staging directory")

    ok, why = verify_source_against_item(root, item)
    if not ok:
        raise SystemExit(
            f"Refusing audio commit: frozen plan is stale for {relpath}: {why}"
        )

    status, verification = verify_staged_output(
        source, staged_path, item, cfg
    )
    if (
        status != "STAGED_VERIFIED"
        or verification.get("metadata_ready_for_commit") is not True
    ):
        raise SystemExit(
            f"Refusing audio commit: staged output no longer verifies ({status})"
        )

    final_relpath = str(
        (item.get("target") or {}).get("final_relpath")
        or Path(relpath).with_suffix(".mp3").as_posix()
    )
    final_rel = Path(final_relpath)

    if final_rel.is_absolute() or ".." in final_rel.parts:
        raise SystemExit(
            "Refusing audio commit: invalid final_relpath in frozen plan"
        )

    final_path = root / final_rel

    if final_path != source and final_path.exists():
        raise SystemExit(
            f"Refusing audio commit: destination already exists: {final_path}"
        )

    original_sha = sha256_file(source)
    staged_sha = sha256_file(staged_path)

    commit_id = sha256_text(
        canonical_json(
            {
                "staging_id": args.staging_id,
                "relpath": relpath,
                "operation": "CONVERT_AUDIO",
                "started": now_iso(),
            }
        )
    )[:16]

    quarantine_dir = state_dir / "quarantine" / commit_id
    quarantine_path = quarantine_dir / relpath
    quarantine_path.parent.mkdir(parents=True, exist_ok=False)

    con = init_db(db_path, root)
    con.row_factory = sqlite3.Row

    asset_row = con.execute(
        "SELECT asset_id FROM assets WHERE relpath=?",
        (relpath,),
    ).fetchone()

    if not asset_row:
        con.close()
        raise SystemExit(
            "Refusing audio commit: source asset is missing from the state database"
        )

    asset_id = int(asset_row["asset_id"])

    if final_relpath != relpath:
        conflict = con.execute(
            "SELECT asset_id FROM assets WHERE relpath=? AND asset_id<>?",
            (final_relpath, asset_id),
        ).fetchone()

        if conflict:
            con.close()
            raise SystemExit(
                "Refusing audio commit: destination relpath already belongs "
                f"to another database asset: {final_relpath}"
            )

    con.execute(
        "INSERT INTO commits("
        "commit_id,staging_id,plan_id,started_at,status,quarantine_dir"
        ") VALUES(?,?,?,?,?,?)",
        (
            commit_id,
            args.staging_id,
            plan_id,
            now_iso(),
            "RUNNING",
            str(quarantine_dir),
        ),
    )
    con.commit()

    final_tmp = (
        final_path.parent
        / f".{final_path.name}.media-maintenance-{commit_id}.tmp"
    )
    moved_to_quarantine = False

    details: dict[str, Any] = {
        "precommit_verification": verification,
        "asset_id": asset_id,
        "original_relpath": relpath,
        "final_relpath": final_relpath,
        "policy_version": item.get("policy_version"),
    }

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # Original leaves the library atomically but is never deleted.
        os.replace(source, quarantine_path)
        moved_to_quarantine = True
        fsync_dir(source.parent)
        fsync_dir(quarantine_path.parent)

        # Install a separately verified staged copy.
        shutil.copyfile(staged_path, final_tmp)
        fsync_file(final_tmp)

        st = staged_path.stat()
        set_creation_time(final_tmp, getattr(st, "st_birthtime", None))
        os.utime(final_tmp, ns=(st.st_atime_ns, st.st_mtime_ns))

        staged_personal_tags = [
            t
            for t in read_finder_tags_safe(staged_path)
            if t not in set(cfg.get("personal_tags_exclude", []))
        ]
        if staged_personal_tags:
            tag_ok, tag_msg, _ = copy_personal_finder_tags_xattr(
                staged_path, final_tmp, cfg
            )
            if not tag_ok:
                raise RuntimeError(
                    f"could_not_copy_personal_tags_to_final_temp:{tag_msg}"
                )

        if sha256_file(final_tmp) != staged_sha:
            raise RuntimeError("temp_copy_hash_mismatch")

        os.replace(final_tmp, final_path)
        fsync_dir(final_path.parent)

        final_sha = sha256_file(final_path)
        if final_sha != staged_sha:
            raise RuntimeError("final_hash_mismatch")

        final_status, final_ver = verify_staged_output(
            quarantine_path, final_path, item, cfg
        )
        details["final_verification"] = final_ver

        if (
            final_status != "STAGED_VERIFIED"
            or final_ver.get("metadata_ready_for_commit") is not True
        ):
            raise RuntimeError(
                f"final_audio_verification_failed:{final_status}"
            )

        fst = final_path.stat()

        con.execute(
            "UPDATE assets SET "
            "relpath=?,size=?,mtime_ns=?,birth_ts=?,quick_hash=?,full_hash=?,"
            "extension=?,audio_codec=?,active=1 WHERE asset_id=?",
            (
                final_relpath,
                int(fst.st_size),
                int(fst.st_mtime_ns),
                getattr(fst, "st_birthtime", None),
                audit.quick_hash(final_path),
                final_sha,
                final_path.suffix.lower(),
                final_ver.get("output_audio_codec"),
                asset_id,
            ),
        )

        con.execute(
            "INSERT INTO processing_history("
            "asset_id,policy_version,operation,status,processed_at,"
            "source_quick_hash,source_full_hash,output_quick_hash,"
            "output_full_hash,details_json"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                asset_id,
                item.get("policy_version"),
                "CONVERT_AUDIO",
                "COMMITTED",
                now_iso(),
                item.get("source_quick_hash"),
                original_sha,
                audit.quick_hash(final_path),
                final_sha,
                canonical_json(
                    {
                        "commit_id": commit_id,
                        "staging_id": args.staging_id,
                        "original_relpath": relpath,
                        "final_relpath": final_relpath,
                    }
                ),
            ),
        )

        con.execute(
            "INSERT INTO commit_items("
            "commit_id,relpath,operation,status,source_original_sha256,"
            "staged_sha256,final_sha256,quarantine_path,final_path,details_json"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                commit_id,
                relpath,
                "CONVERT_AUDIO",
                "COMMITTED",
                original_sha,
                staged_sha,
                final_sha,
                str(quarantine_path),
                str(final_path),
                canonical_json(details),
            ),
        )

        report_path = state_dir / f"commit-{commit_id}.md"
        report_path.write_text(
            "\n".join(
                [
                    "# Veronica Audio Commit Report",
                    "",
                    f"- Tool version: `{VERSION}`",
                    f"- Commit ID: `{commit_id}`",
                    f"- Staging ID: `{args.staging_id}`",
                    f"- Policy: `{item.get('policy_version')}`",
                    f"- Original file: `{relpath}`",
                    f"- Installed file: `{final_relpath}`",
                    f"- Original quarantine: `{quarantine_path}`",
                    "",
                    "## Result",
                    "",
                    "- Status: **COMMITTED**",
                    f"- Original SHA-256: `{original_sha}`",
                    f"- Final SHA-256: `{final_sha}`",
                    f"- Saving: **{verification.get('saving_percent', 0):.1f}%**",
                    "",
                    "## Safety",
                    "",
                    "The original was not deleted. It remains in quarantine "
                    "and can be restored with the rollback command.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        con.execute(
            "UPDATE commits SET completed_at=?,status='COMMITTED',report_path=? "
            "WHERE commit_id=?",
            (now_iso(), str(report_path), commit_id),
        )
        con.commit()

        result = {
            "status": "COMMITTED",
            "relpath": relpath,
            "final_relpath": final_relpath,
            "commit_id": commit_id,
            "policy_version": item.get("policy_version"),
            "quarantine_path": str(quarantine_path),
            "report_path": str(report_path),
            "saving_percent": float(
                verification.get("saving_percent", 0) or 0
            ),
        }

        if not quiet:
            print(f"Veronica {VERSION} audio commit")
            print("Mode: ONE-AUDIO COMMIT WITH POLICY LOCK + QUARANTINE")
            print(f"COMMITTED: {relpath} -> {final_relpath}")
            print(f"Policy: {item.get('policy_version')}")
            print(f"Original quarantine: {quarantine_path}")
            print(f"Report: {report_path}")
            print(f"Commit ID: {commit_id}")

        return result

    except Exception as exc:
        rollback_note = str(exc)

        try:
            if final_tmp.exists():
                final_tmp.unlink()

            if moved_to_quarantine and quarantine_path.exists():
                if final_path.exists():
                    failed = (
                        state_dir
                        / "failed-commit-output"
                        / commit_id
                        / final_relpath
                    )
                    failed.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final_path, failed)

                os.replace(quarantine_path, source)
                fsync_dir(source.parent)

                if sha256_file(source) == original_sha:
                    rollback_note += "; original_restored"
                else:
                    rollback_note += "; automatic_restore_hash_mismatch"

        finally:
            con.execute(
                "INSERT OR REPLACE INTO commit_items("
                "commit_id,relpath,operation,status,source_original_sha256,"
                "staged_sha256,quarantine_path,final_path,details_json"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    commit_id,
                    relpath,
                    "CONVERT_AUDIO",
                    "FAILED_ROLLED_BACK",
                    original_sha,
                    staged_sha,
                    str(quarantine_path),
                    str(final_path),
                    canonical_json({"error": rollback_note, **details}),
                ),
            )
            con.execute(
                "UPDATE commits SET completed_at=?,status='FAILED_ROLLED_BACK' "
                "WHERE commit_id=?",
                (now_iso(), commit_id),
            )
            con.commit()

        raise SystemExit(
            f"Audio commit failed safely: {rollback_note}"
        )

    finally:
        try:
            con.close()
        except Exception:
            pass


def choose_video_commit_candidate(report: dict[str, Any], relpath: str) -> dict[str, Any]:
    candidates = [r for r in report.get("results", [])
                  if r.get("status") == "STAGED_VERIFIED"
                  and r.get("operation") == "CONVERT_VIDEO"
                  and r.get("verification", {}).get("metadata_ready_for_commit") is True
                  and r.get("relpath") == relpath]
    if not candidates:
        raise SystemExit("Requested relpath is not a verified staged video in this staging run")
    return candidates[0]


def commit_one_video(args: argparse.Namespace, quiet: bool = False) -> dict[str, Any]:
    if not args.yes:
        raise SystemExit("Video commit requires --yes. This command changes exactly one video in Media and quarantines the original.")
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")
    report = load_staging_report(state_dir, args.staging_id)
    plan_id = report.get("plan_id")
    plan_candidates = sorted(state_dir.glob(f"plan-*-{str(plan_id)[:12]}.json"))
    if not plan_candidates:
        raise SystemExit(f"Frozen plan JSON not found for plan {plan_id}")
    plan = load_plan(plan_candidates[-1])
    root = Path(plan["root"]).resolve()
    cfg = load_config(Path(args.config).expanduser() if args.config else None)
    if root.stat().st_dev != state_dir.stat().st_dev:
        raise SystemExit("Video commit requires Media and the state directory on the same filesystem for atomic quarantine/rollback")

    staged = choose_video_commit_candidate(report, args.relpath)
    item = find_plan_item(plan, args.relpath)
    if not item or item.get("operation") != "CONVERT_VIDEO" or not item.get("executable"):
        raise SystemExit("Plan item is not an executable video conversion")

    plan_policy = (plan.get("policy_snapshot", {}).get("policies", {}) or {}).get("streams_video")
    if not plan_policy:
        raise SystemExit("Refusing video commit: frozen plan has no video policy")
    required_policy = plan_policy
    staged_policy = staged.get("policy_version")
    item_policy = item.get("policy_version")
    config_policy = (cfg.get("policies", {}) or {}).get("streams_video")
    policies = {"required": required_policy, "plan": plan_policy, "item": item_policy, "staged": staged_policy, "config": config_policy}
    if len(set(policies.values())) != 1:
        raise SystemExit("Refusing video commit: policy mismatch: " + ", ".join(f"{k}={v}" for k,v in policies.items()))

    source = root / item["relpath"]
    staged_path = Path(staged.get("output_path", "")).resolve()
    if not staged_path.is_file():
        raise SystemExit(f"Staged output missing: {staged_path}")
    expected_stage_root = (state_dir / "staging" / args.staging_id).resolve()
    if expected_stage_root not in staged_path.parents:
        raise SystemExit("Staged output is outside the expected staging directory")
    ok, why = verify_source_against_item(root, item)
    if not ok:
        raise SystemExit(f"Refusing video commit: frozen plan is stale for {item['relpath']}: {why}")
    status, verification = verify_staged_output(source, staged_path, item, cfg)
    if status != "STAGED_VERIFIED" or verification.get("metadata_ready_for_commit") is not True:
        raise SystemExit(f"Refusing video commit: staged output no longer verifies ({status})")
    if verification.get("output_square_pixels") is not True:
        raise SystemExit("Refusing video commit: output is not square-pixel")

    planned_final_relpath = str(
        (item.get("target") or {}).get("final_relpath")
        or (Path(item["relpath"]).with_suffix(".mp4").as_posix())
    )
    final_rel = Path(planned_final_relpath)
    if final_rel.is_absolute() or ".." in final_rel.parts:
        raise SystemExit("Refusing video commit: invalid final_relpath in frozen plan")
    final_relpath = final_rel.as_posix()
    final_path = root / final_rel

    if final_path != source and final_path.exists():
        raise SystemExit(f"Refusing video commit: destination already exists: {final_path}")

    original_sha = sha256_file(source)
    staged_sha = sha256_file(staged_path)
    commit_id = sha256_text(canonical_json({"staging_id": args.staging_id, "relpath": item["relpath"], "started": now_iso()}))[:16]
    quarantine_dir = state_dir / "quarantine" / commit_id
    quarantine_path = quarantine_dir / item["relpath"]
    quarantine_path.parent.mkdir(parents=True, exist_ok=False)
    con = init_db(db_path, root)
    asset_row = con.execute("SELECT asset_id FROM assets WHERE relpath=?", (item["relpath"],)).fetchone()
    if not asset_row:
        con.close(); raise SystemExit("Refusing video commit: source asset is missing from the state database")
    asset_id = int(asset_row[0])
    if final_relpath != item["relpath"]:
        conflict = con.execute("SELECT asset_id FROM assets WHERE relpath=? AND asset_id<>?", (final_relpath, asset_id)).fetchone()
        if conflict:
            con.close(); raise SystemExit(f"Refusing video commit: destination relpath already belongs to another database asset: {final_relpath}")
    con.execute("INSERT INTO commits(commit_id,staging_id,plan_id,started_at,status,quarantine_dir) VALUES(?,?,?,?,?,?)",
                (commit_id, args.staging_id, plan_id, now_iso(), "RUNNING", str(quarantine_dir)))
    con.commit()

    final_tmp = final_path.parent / f".{final_path.name}.media-maintenance-{commit_id}.tmp"
    moved_to_quarantine = False
    details: dict[str, Any] = {"precommit_verification": verification, "policy_version": item_policy,
                               "asset_id": asset_id, "original_relpath": item["relpath"], "final_relpath": final_relpath}
    try:
        os.replace(source, quarantine_path)
        moved_to_quarantine = True
        fsync_dir(source.parent); fsync_dir(quarantine_path.parent)
        shutil.copyfile(staged_path, final_tmp)
        fsync_file(final_tmp)
        st = staged_path.stat()
        set_creation_time(final_tmp, getattr(st, "st_birthtime", None))
        os.utime(final_tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        staged_personal_tags = [t for t in read_finder_tags_safe(staged_path) if t not in set(cfg.get("personal_tags_exclude", []))]
        if staged_personal_tags:
            tag_ok, tag_msg, _ = copy_personal_finder_tags_xattr(staged_path, final_tmp, cfg)
            if not tag_ok:
                raise RuntimeError(f"could_not_copy_personal_tags_to_final_temp:{tag_msg}")
        if sha256_file(final_tmp) != staged_sha:
            raise RuntimeError("temp_copy_hash_mismatch")
        os.replace(final_tmp, final_path)
        fsync_dir(final_path.parent)
        final_sha = sha256_file(final_path)
        if final_sha != staged_sha:
            raise RuntimeError("final_hash_mismatch")
        final_status, final_ver = verify_staged_output(quarantine_path, final_path, item, cfg)
        details["final_verification"] = final_ver
        if final_status != "STAGED_VERIFIED" or final_ver.get("metadata_ready_for_commit") is not True:
            raise RuntimeError(f"final_media_verification_failed:{final_status}")
        if final_ver.get("output_square_pixels") is not True:
            raise RuntimeError("final_output_not_square_pixel")

        # Transfer durable asset identity to the installed .mp4 path, then attach
        # processing history to that same asset_id so next year's planner can skip it.
        fst = final_path.stat()
        con.execute("UPDATE assets SET relpath=?,size=?,mtime_ns=?,birth_ts=?,quick_hash=?,full_hash=?,extension=?,video_codec=?,active=1 WHERE asset_id=?",
                    (final_relpath, int(fst.st_size), int(fst.st_mtime_ns), getattr(fst, "st_birthtime", None),
                     audit.quick_hash(final_path), final_sha, final_path.suffix.lower(), final_ver.get("output_video_codec"), asset_id))
        con.execute("INSERT INTO processing_history(asset_id,policy_version,operation,status,processed_at,source_quick_hash,source_full_hash,output_quick_hash,output_full_hash,details_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, item_policy, item["operation"], "COMMITTED", now_iso(), item.get("source_quick_hash"), original_sha,
                     audit.quick_hash(final_path), final_sha, canonical_json({"commit_id": commit_id, "staging_id": args.staging_id,
                                                                            "original_relpath": item["relpath"], "final_relpath": final_relpath})))
        con.execute("INSERT INTO commit_items(commit_id,relpath,operation,status,source_original_sha256,staged_sha256,final_sha256,quarantine_path,final_path,details_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (commit_id, item["relpath"], item["operation"], "COMMITTED", original_sha, staged_sha, final_sha,
                     str(quarantine_path), str(final_path), canonical_json(details)))
        report_path = state_dir / f"commit-{commit_id}.md"
        report_path.write_text("\n".join([
            "# Veronica Video Commit Report", "",
            f"- Tool version: `{VERSION}`", f"- Commit ID: `{commit_id}`", f"- Staging ID: `{args.staging_id}`",
            f"- Policy: `{item_policy}`", f"- Original file: `{item['relpath']}`", f"- Installed file: `{final_relpath}`",
            f"- Original quarantine: `{quarantine_path}`", "", "## Result", "", "- Status: **COMMITTED**",
            f"- Original SHA-256: `{original_sha}`", f"- Final SHA-256: `{final_sha}`",
            f"- Saving: **{verification.get('saving_percent',0):.1f}%**", "", "## Safety", "",
            "The original was not deleted. It remains in quarantine and can be restored with the rollback command.", ""
        ]), encoding="utf-8")
        con.execute("UPDATE commits SET completed_at=?,status='COMMITTED',report_path=? WHERE commit_id=?", (now_iso(), str(report_path), commit_id))
        con.commit()
        result = {
            "status": "COMMITTED",
            "relpath": item["relpath"],
            "final_relpath": final_relpath,
            "commit_id": commit_id,
            "policy_version": item_policy,
            "quarantine_path": str(quarantine_path),
            "report_path": str(report_path),
            "saving_percent": float(verification.get("saving_percent", 0) or 0),
        }
        if not quiet:
            print(f"Veronica {VERSION} video commit")
            print("Mode: ONE-VIDEO COMMIT WITH POLICY LOCK + QUARANTINE")
            print(f"COMMITTED: {item['relpath']} -> {final_relpath}")
            print(f"Policy: {item_policy}")
            print(f"Original quarantine: {quarantine_path}")
            print(f"Report: {report_path}")
            print(f"Commit ID: {commit_id}")
        return result
    except Exception as exc:
        rollback_note = str(exc)
        try:
            if final_tmp.exists(): final_tmp.unlink()
            if moved_to_quarantine and quarantine_path.exists():
                if final_path.exists():
                    failed = state_dir / "failed-commit-output" / commit_id / final_relpath
                    failed.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final_path, failed)
                os.replace(quarantine_path, source)
                fsync_dir(source.parent)
                if sha256_file(source) == original_sha:
                    rollback_note += "; original_restored"
                else:
                    rollback_note += "; automatic_restore_hash_mismatch"
        finally:
            con.execute("INSERT OR REPLACE INTO commit_items(commit_id,relpath,operation,status,source_original_sha256,staged_sha256,quarantine_path,final_path,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
                        (commit_id, item["relpath"], item["operation"], "FAILED_ROLLED_BACK", original_sha, staged_sha,
                         str(quarantine_path), str(final_path), canonical_json({"error": rollback_note, **details})))
            con.execute("UPDATE commits SET completed_at=?,status='FAILED_ROLLED_BACK' WHERE commit_id=?", (now_iso(), commit_id))
            con.commit(); con.close()
        raise SystemExit(f"Video commit failed safely: {rollback_note}")
    finally:
        try: con.close()
        except Exception: pass



def commit_one_rename(args: argparse.Namespace, quiet: bool = False) -> dict[str, Any]:
    if not args.yes:
        raise SystemExit(
            "Rename commit requires --yes. This command changes exactly one archive pathname "
            "and quarantines the original path transactionally."
        )

    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")

    plan_path = Path(args.plan).expanduser().resolve()
    plan = load_plan(plan_path)
    root = Path(plan["root"]).resolve()

    item = find_plan_item(plan, args.relpath)
    if not item or item.get("operation") != "RENAME" or not item.get("executable"):
        raise SystemExit("Plan item is not an executable rename")

    source = root / item["relpath"]
    final_relpath = str((item.get("target") or {}).get("final_relpath") or "")
    if not final_relpath:
        raise SystemExit("Rename plan item has no canonical final_relpath")

    final_path = root / final_relpath
    if final_path == source:
        raise SystemExit("Rename destination is identical to source")
    if final_path.exists():
        raise SystemExit(f"Refusing rename commit: destination already exists: {final_path}")

    ok, why = verify_source_against_item(root, item)
    if not ok:
        raise SystemExit(
            f"Refusing rename commit: frozen plan is stale for {item['relpath']}: {why}"
        )

    if source.stat().st_dev != state_dir.stat().st_dev:
        raise SystemExit(
            "Rename commit requires Media and the state directory on the same filesystem "
            "for atomic quarantine/rollback"
        )

    original_sha = sha256_file(source)
    commit_id = sha256_text(
        canonical_json(
            {
                "plan_id": plan["plan_id"],
                "relpath": item["relpath"],
                "operation": "RENAME",
                "started": now_iso(),
            }
        )
    )[:16]

    quarantine_dir = state_dir / "quarantine" / commit_id
    quarantine_path = quarantine_dir / item["relpath"]
    quarantine_path.parent.mkdir(parents=True, exist_ok=False)

    con = init_db(db_path, root)
    con.row_factory = sqlite3.Row

    asset_row = con.execute(
        "SELECT asset_id FROM assets WHERE relpath=?",
        (item["relpath"],),
    ).fetchone()
    if not asset_row:
        con.close()
        raise SystemExit("Refusing rename commit: source asset is missing from the state database")
    asset_id = int(asset_row["asset_id"])

    conflict = con.execute(
        "SELECT asset_id FROM assets WHERE relpath=? AND asset_id<>?",
        (final_relpath, asset_id),
    ).fetchone()
    if conflict:
        con.close()
        raise SystemExit(
            f"Refusing rename commit: destination relpath already belongs to another "
            f"database asset: {final_relpath}"
        )

    con.execute(
        "INSERT INTO commits(commit_id,staging_id,plan_id,started_at,status,quarantine_dir) "
        "VALUES(?,?,?,?,?,?)",
        (
            commit_id,
            "rename-only",
            plan["plan_id"],
            now_iso(),
            "RUNNING",
            str(quarantine_dir),
        ),
    )
    con.commit()

    moved_to_quarantine = False
    installed = False

    details = {
        "asset_id": asset_id,
        "original_relpath": item["relpath"],
        "final_relpath": final_relpath,
        "policy_version": item.get("policy_version"),
        "filename_standardization": True,
    }

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)

        # First move original into Veronica quarantine atomically.
        os.replace(source, quarantine_path)
        moved_to_quarantine = True
        fsync_dir(source.parent)
        fsync_dir(quarantine_path.parent)

        # Then atomically install the exact same bytes at the canonical pathname.
        os.replace(quarantine_path, final_path)
        installed = True
        fsync_dir(final_path.parent)

        final_sha = sha256_file(final_path)
        if final_sha != original_sha:
            raise RuntimeError("rename_final_hash_mismatch")

        # Put a byte-identical rollback copy back into quarantine.
        #
        # copy2 preserves ordinary filesystem metadata where supported, but macOS
        # creation time is restored explicitly so rollback does not silently replace
        # the asset's original birth date with the time the quarantine copy was made.
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_path, quarantine_path)

        final_stat = final_path.stat()
        creation_ok, creation_msg = set_creation_time(
            quarantine_path,
            getattr(final_stat, "st_birthtime", None),
        )
        if getattr(final_stat, "st_birthtime", None) is not None and not creation_ok:
            raise RuntimeError(
                f"rename_quarantine_creation_time_restore_failed:{creation_msg}"
            )

        fsync_file(quarantine_path)
        fsync_dir(quarantine_path.parent)

        if sha256_file(quarantine_path) != original_sha:
            raise RuntimeError("rename_quarantine_copy_hash_mismatch")

        fst = final_path.stat()
        con.execute(
            "UPDATE assets SET relpath=?,size=?,mtime_ns=?,birth_ts=?,quick_hash=?,full_hash=?,"
            "extension=?,active=1 WHERE asset_id=?",
            (
                final_relpath,
                int(fst.st_size),
                int(fst.st_mtime_ns),
                getattr(fst, "st_birthtime", None),
                audit.quick_hash(final_path),
                final_sha,
                final_path.suffix.lower(),
                asset_id,
            ),
        )

        con.execute(
            "INSERT INTO processing_history("
            "asset_id,policy_version,operation,status,processed_at,"
            "source_quick_hash,source_full_hash,output_quick_hash,output_full_hash,details_json"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                asset_id,
                item.get("policy_version"),
                "RENAME",
                "COMMITTED",
                now_iso(),
                item.get("source_quick_hash"),
                original_sha,
                audit.quick_hash(final_path),
                final_sha,
                canonical_json(
                    {
                        "commit_id": commit_id,
                        "original_relpath": item["relpath"],
                        "final_relpath": final_relpath,
                    }
                ),
            ),
        )

        con.execute(
            "INSERT INTO commit_items("
            "commit_id,relpath,operation,status,source_original_sha256,staged_sha256,"
            "final_sha256,quarantine_path,final_path,details_json"
            ") VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                commit_id,
                item["relpath"],
                "RENAME",
                "COMMITTED",
                original_sha,
                original_sha,
                final_sha,
                str(quarantine_path),
                str(final_path),
                canonical_json(details),
            ),
        )

        report_path = state_dir / f"commit-{commit_id}.md"
        report_path.write_text(
            "\n".join(
                [
                    "# Veronica Rename Commit Report",
                    "",
                    f"- Tool version: `{VERSION}`",
                    f"- Commit ID: `{commit_id}`",
                    f"- Original file: `{item['relpath']}`",
                    f"- Installed file: `{final_relpath}`",
                    f"- Rollback quarantine: `{quarantine_path}`",
                    "",
                    "## Result",
                    "",
                    "- Status: **COMMITTED**",
                    f"- SHA-256: `{final_sha}`",
                    "",
                    "## Safety",
                    "",
                    "The file contents were not converted. The pathname was standardized "
                    "transactionally, and a byte-identical rollback copy remains in quarantine.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        con.execute(
            "UPDATE commits SET completed_at=?,status='COMMITTED',report_path=? WHERE commit_id=?",
            (now_iso(), str(report_path), commit_id),
        )
        con.commit()

        result = {
            "status": "COMMITTED",
            "relpath": item["relpath"],
            "final_relpath": final_relpath,
            "commit_id": commit_id,
            "quarantine_path": str(quarantine_path),
            "report_path": str(report_path),
        }

        if not quiet:
            print(f"Veronica {VERSION} rename commit")
            print("Mode: ONE-FILE ATOMIC RENAME WITH QUARANTINE")
            print(f"COMMITTED: {item['relpath']} -> {final_relpath}")
            print(f"Rollback quarantine: {quarantine_path}")
            print(f"Report: {report_path}")
            print(f"Commit ID: {commit_id}")

        return result

    except Exception as exc:
        rollback_note = str(exc)

        try:
            # If canonical destination exists, put it back at the original path.
            if final_path.exists():
                if source.exists():
                    failed = state_dir / "failed-commit-output" / commit_id / final_relpath
                    failed.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(final_path, failed)
                else:
                    os.replace(final_path, source)

            # If only the quarantine copy exists, restore from that.
            if not source.exists() and quarantine_path.exists():
                os.replace(quarantine_path, source)

            if source.exists() and sha256_file(source) == original_sha:
                rollback_note += "; original_restored"
            else:
                rollback_note += "; automatic_restore_hash_mismatch_or_missing"

        finally:
            con.execute(
                "INSERT OR REPLACE INTO commit_items("
                "commit_id,relpath,operation,status,source_original_sha256,staged_sha256,"
                "quarantine_path,final_path,details_json"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    commit_id,
                    item["relpath"],
                    "RENAME",
                    "FAILED_ROLLED_BACK",
                    original_sha,
                    original_sha,
                    str(quarantine_path),
                    str(final_path),
                    canonical_json({"error": rollback_note, **details}),
                ),
            )
            con.execute(
                "UPDATE commits SET completed_at=?,status='FAILED_ROLLED_BACK' WHERE commit_id=?",
                (now_iso(), commit_id),
            )
            con.commit()

        raise SystemExit(f"Rename commit failed safely: {rollback_note}")

    finally:
        try:
            con.close()
        except Exception:
            pass


def cmd_commit_rename(args: argparse.Namespace) -> int:
    commit_one_rename(args, quiet=False)
    return 0


def cmd_commit_video(args: argparse.Namespace) -> int:
    commit_one_video(args, quiet=False)
    return 0


def cmd_commit_audio(args: argparse.Namespace) -> int:
    commit_one_audio(args, quiet=False)
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    commit_one(args, quiet=False)
    return 0


def already_committed_relpaths(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT DISTINCT relpath FROM commit_items WHERE status='COMMITTED'").fetchall()
        return {str(r[0]) for r in rows}
    finally:
        con.close()


def cmd_commit_batch(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("Batch commit requires --yes. This command can change up to 25 image files in Media; every original is quarantined separately.")
    if args.max_items < 1 or args.max_items > 250:
        raise SystemExit("--max-items must be between 1 and 250; v0.6.0 has a hard safety cap of 250")
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")
    report = load_staging_report(state_dir, args.staging_id)
    candidates = [r for r in report.get("results", [])
                  if r.get("status") == "STAGED_VERIFIED"
                  and r.get("operation") == "CONVERT_IMAGE"
                  and r.get("verification", {}).get("metadata_ready_for_commit") is True]
    requested = list(args.relpath or [])
    if requested:
        by_rel = {r.get("relpath"): r for r in candidates}
        missing = [r for r in requested if r not in by_rel]
        if missing:
            raise SystemExit("Requested relpath(s) are not commit-ready in this staging run: " + ", ".join(missing))
        candidates = [by_rel[r] for r in requested]
    committed_before = already_committed_relpaths(db_path)
    candidates = [r for r in candidates if r.get("relpath") not in committed_before]
    if not candidates:
        raise SystemExit("No new commit-ready staged images remain in this staging run")
    selected = candidates[:args.max_items]
    preflight = preflight_free_space(state_dir, commit_space_estimate(selected), "batch commit")
    batch_id = sha256_text(canonical_json({"staging_id": args.staging_id, "started": now_iso(), "relpaths": [r["relpath"] for r in selected]}))[:16]
    print(f"Veronica {VERSION} batch commit")
    print("Mode: BOUNDED IMAGE BATCH — EACH FILE HAS ITS OWN QUARANTINE TRANSACTION")
    print(f"Batch ID: {batch_id}")
    print(f"Selected: {len(selected)} image(s); hard cap=250")
    print(f"Already committed and skipped: {len(committed_before)}")
    print(f"Disk preflight: {preflight['free_bytes']/1024**3:.2f} GiB free; estimated commit need {preflight['required_bytes']/1024**3:.2f} GiB incl. reserve")
    results: list[dict[str, Any]] = []
    for idx, r in enumerate(selected, 1):
        rel = r["relpath"]
        one_args = argparse.Namespace(staging_id=args.staging_id, state_dir=args.state_dir, config=args.config, relpath=rel, yes=True)
        try:
            res = commit_one(one_args, quiet=True)
            results.append(res)
            print(f"[{idx}/{len(selected)}] COMMITTED {rel}  commit={res['commit_id']}")
            emit_event("commit_item", media="image", index=idx, total=len(selected), relpath=rel, status="COMMITTED", commit_id=res["commit_id"])
        except SystemExit as exc:
            # commit_one's internal failure path restores the original before raising.
            results.append({"status":"FAILED_SAFE","relpath":rel,"error":str(exc)})
            print(f"[{idx}/{len(selected)}] FAILED_SAFE {rel}  {exc}")
        except Exception as exc:
            results.append({"status":"FAILED_SAFE","relpath":rel,"error":repr(exc)})
            print(f"[{idx}/{len(selected)}] FAILED_SAFE {rel}  {exc}")
    counts = Counter(r["status"] for r in results)
    report_path = state_dir / f"batch-commit-{batch_id}.md"
    lines = [
        "# Veronica Batch Commit Report", "",
        f"- Tool version: `{VERSION}`", f"- Batch ID: `{batch_id}`", f"- Staging ID: `{args.staging_id}`",
        f"- Selected files: **{len(selected)}**", f"- Already committed and skipped: **{len(committed_before)}**", f"- Disk free at preflight: **{preflight['free_bytes']/1024**3:.2f} GiB**", f"- Estimated commit requirement incl. reserve: **{preflight['required_bytes']/1024**3:.2f} GiB**", "", "## Results", "",
        "| Status | Files |", "|---|---:|"
    ]
    for k,v in counts.items(): lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Items", ""]
    for r in results:
        if r["status"] == "COMMITTED":
            lines.append(f"- `COMMITTED` — `{r['relpath']}` — commit `{r['commit_id']}` — saving {r.get('saving_percent',0):.1f}%")
            lines.append(f"  - original quarantine: `{r['quarantine_path']}`")
        else:
            lines.append(f"- `FAILED_SAFE` — `{r['relpath']}` — {r.get('error','unknown error')}")
    lines += ["", "## Recovery", "", "Every successful file has its own commit ID and can be rolled back independently with the existing `rollback` command. A failure in one item does not roll back or invalidate other successful items.", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print("Results: " + ", ".join(f"{k}={v}" for k,v in counts.items()))
    print(f"Batch report: {report_path}")
    return 0 if counts.get("FAILED_SAFE",0) == 0 else 1


def cmd_commit_audio_batch(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit(
            "Audio batch commit requires --yes. This command can change up to "
            "10 audio files; every original is quarantined independently."
        )

    if args.max_items < 1 or args.max_items > 10:
        raise SystemExit(
            "--max-items must be between 1 and 10 for audio"
        )

    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"

    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")

    report = load_staging_report(state_dir, args.staging_id)

    candidates = [
        r for r in report.get("results", [])
        if r.get("status") == "STAGED_VERIFIED"
        and r.get("operation") == "CONVERT_AUDIO"
        and r.get("verification", {}).get("metadata_ready_for_commit") is True
    ]

    requested = list(args.relpath or [])
    if requested:
        by_rel = {r.get("relpath"): r for r in candidates}
        missing = [r for r in requested if r not in by_rel]
        if missing:
            raise SystemExit(
                "Requested relpath(s) are not commit-ready audio files in this "
                "staging run: " + ", ".join(missing)
            )
        candidates = [by_rel[r] for r in requested]

    committed_before = already_committed_relpaths(db_path)
    candidates = [
        r for r in candidates
        if r.get("relpath") not in committed_before
    ]

    if not candidates:
        raise SystemExit(
            "No new commit-ready staged audio files remain in this staging run"
        )

    selected = candidates[:args.max_items]
    preflight = preflight_free_space(
        state_dir,
        commit_space_estimate(selected),
        "audio batch commit",
    )

    batch_id = sha256_text(
        canonical_json(
            {
                "staging_id": args.staging_id,
                "started": now_iso(),
                "relpaths": [r["relpath"] for r in selected],
            }
        )
    )[:16]

    print(f"Veronica {VERSION} audio batch commit")
    print(
        "Mode: BOUNDED AUDIO BATCH — POLICY LOCKED; "
        "EACH FILE HAS ITS OWN QUARANTINE TRANSACTION"
    )
    print(f"Batch ID: {batch_id}")
    print(f"Selected: {len(selected)} audio file(s); hard cap=10")
    print(f"Already committed and skipped: {len(committed_before)}")
    print(
        f"Disk preflight: {preflight['free_bytes']/1024**3:.2f} GiB free; "
        f"estimated commit need {preflight['required_bytes']/1024**3:.2f} GiB "
        "incl. reserve"
    )

    results: list[dict[str, Any]] = []

    for idx, r in enumerate(selected, 1):
        rel = r["relpath"]
        one_args = argparse.Namespace(
            staging_id=args.staging_id,
            state_dir=args.state_dir,
            config=args.config,
            relpath=rel,
            yes=True,
        )

        try:
            res = commit_one_audio(one_args, quiet=True)
            results.append(res)
            print(
                f"[{idx}/{len(selected)}] COMMITTED "
                f"{rel} -> {res['final_relpath']}  commit={res['commit_id']}"
            )
            emit_event(
                "commit_item",
                media="audio",
                index=idx,
                total=len(selected),
                relpath=rel,
                final_relpath=res["final_relpath"],
                status="COMMITTED",
                commit_id=res["commit_id"],
            )

        except SystemExit as exc:
            results.append(
                {
                    "status": "FAILED_SAFE",
                    "relpath": rel,
                    "error": str(exc),
                }
            )
            print(
                f"[{idx}/{len(selected)}] FAILED_SAFE {rel}  {exc}"
            )

        except Exception as exc:
            results.append(
                {
                    "status": "FAILED_SAFE",
                    "relpath": rel,
                    "error": repr(exc),
                }
            )
            print(
                f"[{idx}/{len(selected)}] FAILED_SAFE {rel}  {exc}"
            )

    counts = Counter(r["status"] for r in results)

    report_path = state_dir / f"audio-batch-commit-{batch_id}.md"
    lines = [
        "# Veronica Audio Batch Commit Report",
        "",
        f"- Tool version: `{VERSION}`",
        f"- Batch ID: `{batch_id}`",
        f"- Staging ID: `{args.staging_id}`",
        f"- Selected files: **{len(selected)}**",
        f"- Already committed and skipped: **{len(committed_before)}**",
        "",
        "## Results",
        "",
        "| Status | Files |",
        "|---|---:|",
    ]

    for k, v in counts.items():
        lines.append(f"| `{k}` | {v} |")

    lines += ["", "## Items", ""]

    for r in results:
        if r["status"] == "COMMITTED":
            lines.append(
                f"- `COMMITTED` — `{r['relpath']}` → "
                f"`{r['final_relpath']}` — commit `{r['commit_id']}` — "
                f"saving {r.get('saving_percent', 0):.1f}%"
            )
            lines.append(
                f"  - policy: `{r['policy_version']}`"
            )
            lines.append(
                f"  - original quarantine: `{r['quarantine_path']}`"
            )
        else:
            lines.append(
                f"- `FAILED_SAFE` — `{r['relpath']}` — "
                f"{r.get('error', 'unknown error')}"
            )

    lines += [
        "",
        "## Recovery",
        "",
        "Every successful audio conversion has its own commit ID and can be "
        "rolled back independently. A failed item is restored automatically "
        "and does not invalidate other successful items.",
        "",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(
        "Results: "
        + ", ".join(f"{k}={v}" for k, v in counts.items())
    )
    print(f"Batch report: {report_path}")

    return 0 if counts.get("FAILED_SAFE", 0) == 0 else 1


def cmd_commit_video_batch(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("Video batch commit requires --yes. This command can change up to 3 videos in Media; every original is quarantined independently.")
    if args.max_items < 1 or args.max_items > 25:
        raise SystemExit("--max-items must be between 1 and 25; v0.8.0 has a hard safety cap of 25 videos")
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")
    report = load_staging_report(state_dir, args.staging_id)
    candidates = [r for r in report.get("results", [])
                  if r.get("status") == "STAGED_VERIFIED"
                  and r.get("operation") == "CONVERT_VIDEO"
                  and r.get("verification", {}).get("metadata_ready_for_commit") is True]
    requested = list(args.relpath or [])
    if requested:
        by_rel = {r.get("relpath"): r for r in candidates}
        missing = [r for r in requested if r not in by_rel]
        if missing:
            raise SystemExit("Requested relpath(s) are not commit-ready videos in this staging run: " + ", ".join(missing))
        candidates = [by_rel[r] for r in requested]
    # A video commit may move the durable asset path from .mov/.m4v to .mp4, while
    # commit_items intentionally retains the original relpath. This is exactly what
    # we need here: never attempt the same staged source twice.
    committed_before = already_committed_relpaths(db_path)
    candidates = [r for r in candidates if r.get("relpath") not in committed_before]
    if not candidates:
        raise SystemExit("No new commit-ready staged videos remain in this staging run")
    selected = candidates[:args.max_items]
    preflight = preflight_free_space(state_dir, commit_space_estimate(selected), "video batch commit")
    batch_id = sha256_text(canonical_json({"staging_id": args.staging_id, "started": now_iso(), "relpaths": [r["relpath"] for r in selected]}))[:16]
    print(f"Veronica {VERSION} video batch commit")
    print("Mode: BOUNDED VIDEO BATCH — POLICY LOCKED; EACH FILE HAS ITS OWN QUARANTINE TRANSACTION")
    print(f"Batch ID: {batch_id}")
    print(f"Selected: {len(selected)} video(s); hard cap=25")
    print(f"Already committed and skipped: {len(committed_before)}")
    print(f"Disk preflight: {preflight['free_bytes']/1024**3:.2f} GiB free; estimated commit need {preflight['required_bytes']/1024**3:.2f} GiB incl. reserve")
    results: list[dict[str, Any]] = []
    for idx, r in enumerate(selected, 1):
        rel = r["relpath"]
        one_args = argparse.Namespace(staging_id=args.staging_id, state_dir=args.state_dir, config=args.config, relpath=rel, yes=True)
        try:
            res = commit_one_video(one_args, quiet=True)
            results.append(res)
            print(f"[{idx}/{len(selected)}] COMMITTED {rel} -> {res['final_relpath']}  commit={res['commit_id']}")
            emit_event("commit_item", media="video", index=idx, total=len(selected), relpath=rel, final_relpath=res["final_relpath"], status="COMMITTED", commit_id=res["commit_id"])
        except SystemExit as exc:
            results.append({"status": "FAILED_SAFE", "relpath": rel, "error": str(exc)})
            print(f"[{idx}/{len(selected)}] FAILED_SAFE {rel}  {exc}")
        except Exception as exc:
            results.append({"status": "FAILED_SAFE", "relpath": rel, "error": repr(exc)})
            print(f"[{idx}/{len(selected)}] FAILED_SAFE {rel}  {exc}")
    counts = Counter(r["status"] for r in results)
    report_path = state_dir / f"video-batch-commit-{batch_id}.md"
    lines = [
        "# Veronica Video Batch Commit Report", "",
        f"- Tool version: `{VERSION}`", f"- Batch ID: `{batch_id}`", f"- Staging ID: `{args.staging_id}`",
        f"- Selected files: **{len(selected)}**", f"- Already committed and skipped: **{len(committed_before)}**",
        f"- Disk free at preflight: **{preflight['free_bytes']/1024**3:.2f} GiB**",
        f"- Estimated commit requirement incl. reserve: **{preflight['required_bytes']/1024**3:.2f} GiB**",
        "", "## Results", "", "| Status | Files |", "|---|---:|"
    ]
    for k, v in counts.items():
        lines.append(f"| `{k}` | {v} |")
    lines += ["", "## Items", ""]
    for r in results:
        if r["status"] == "COMMITTED":
            lines.append(f"- `COMMITTED` — `{r['relpath']}` → `{r['final_relpath']}` — commit `{r['commit_id']}` — saving {r.get('saving_percent',0):.1f}%")
            lines.append(f"  - policy: `{r['policy_version']}`")
            lines.append(f"  - original quarantine: `{r['quarantine_path']}`")
        else:
            lines.append(f"- `FAILED_SAFE` — `{r['relpath']}` — {r.get('error','unknown error')}")
    lines += ["", "## Recovery", "",
              "Every successful video has its own commit ID and can be rolled back independently with the existing `rollback` command. A failed item is restored automatically and does not invalidate other successful items.", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print("Results: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Batch report: {report_path}")
    return 0 if counts.get("FAILED_SAFE", 0) == 0 else 1

def cmd_rollback(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("Rollback requires --yes")
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists(): raise SystemExit(f"State database not found: {db_path}")
    con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row
    commit = con.execute("SELECT * FROM commits WHERE commit_id=?", (args.commit_id,)).fetchone()
    if not commit or commit["status"] != "COMMITTED":
        raise SystemExit("Commit ID is not in COMMITTED state")
    items = list(con.execute("SELECT * FROM commit_items WHERE commit_id=? AND status='COMMITTED'", (args.commit_id,)))
    if len(items) != 1:
        raise SystemExit("v0.4.0 rollback supports exactly one committed item")
    r = items[0]
    current = Path(r["final_path"]); original = Path(r["quarantine_path"])
    try:
        d = json.loads(r["details_json"] or "{}")
    except Exception:
        d = {}
    asset_id = d.get("asset_id")
    original_relpath = d.get("original_relpath") or r["relpath"]
    final_relpath = d.get("final_relpath")
    policy_version = d.get("policy_version")
    # Image commits restore to the same pathname. Video commits may have changed
    # only the extension (.m4v/.mov -> .mp4), so restore the original filename too.
    restore_path = current if not final_relpath or final_relpath == original_relpath else current.with_name(Path(original_relpath).name)
    if restore_path != current and restore_path.exists():
        raise SystemExit(f"Refusing rollback: original pathname is occupied: {restore_path}")
    if not current.is_file() or not original.is_file():
        raise SystemExit("Rollback prerequisites missing: current file or quarantined original is unavailable")
    current_sha = sha256_file(current)
    if current_sha != r["final_sha256"]:
        raise SystemExit("Refusing rollback: current Media file changed since commit")
    if sha256_file(original) != r["source_original_sha256"]:
        raise SystemExit("Refusing rollback: quarantined original hash does not match commit record")
    rollback_id = sha256_text(canonical_json({"commit_id": args.commit_id, "started": now_iso()}))[:16]
    displaced_dir = state_dir / "rollback-displaced" / rollback_id
    displaced = displaced_dir / (final_relpath or r["relpath"])
    displaced.parent.mkdir(parents=True, exist_ok=False)
    con.execute("INSERT INTO rollbacks(rollback_id,commit_id,started_at,status,displaced_dir) VALUES(?,?,?,?,?)", (rollback_id,args.commit_id,now_iso(),"RUNNING",str(displaced_dir)))
    con.commit()
    try:
        os.replace(current, displaced)
        os.replace(original, restore_path)
        fsync_dir(restore_path.parent)
        if sha256_file(restore_path) != r["source_original_sha256"]:
            raise RuntimeError("restored_original_hash_mismatch")
        # If a video commit changed .mov/.m4v to .mp4, return durable asset identity
        # to the original relpath and mark that processing-history event rolled back.
        if asset_id and final_relpath and final_relpath != original_relpath:
            con.execute("UPDATE assets SET relpath=?,active=1 WHERE asset_id=?", (original_relpath, int(asset_id)))
        if asset_id and policy_version:
            con.execute("UPDATE processing_history SET status='ROLLED_BACK' WHERE asset_id=? AND policy_version=? AND operation=? AND status='COMMITTED'",
                        (int(asset_id), policy_version, r["operation"]))
        report_path = state_dir / f"rollback-{rollback_id}.md"
        report_path.write_text("\n".join(["# Veronica Rollback Report","",f"- Rollback ID: `{rollback_id}`",f"- Commit ID: `{args.commit_id}`",f"- Restored: `{restore_path}`",f"- Displaced committed output: `{displaced}`","","- Status: **ROLLED_BACK**",""]),encoding="utf-8")
        con.execute("UPDATE rollbacks SET completed_at=?,status='ROLLED_BACK',report_path=? WHERE rollback_id=?",(now_iso(),str(report_path),rollback_id))
        con.execute("UPDATE commit_items SET status='ROLLED_BACK' WHERE commit_id=? AND relpath=?",(args.commit_id,r["relpath"]))
        con.execute("UPDATE commits SET status='ROLLED_BACK' WHERE commit_id=?",(args.commit_id,))
        con.commit()
        print(f"ROLLED_BACK: {r['relpath']}")
        print(f"Displaced committed output: {displaced}")
        print(f"Report: {report_path}")
        return 0
    except Exception as exc:
        # Try to put committed output back if restoration did not complete safely.
        if not current.exists() and displaced.exists():
            os.replace(displaced, current)
        # If the original was restored to a renamed path before a later failure,
        # move it back to quarantine so the commit state is not half-rolled-back.
        if restore_path != current and restore_path.exists() and not original.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            os.replace(restore_path, original)
        con.execute("UPDATE rollbacks SET completed_at=?,status='FAILED' WHERE rollback_id=?",(now_iso(),rollback_id)); con.commit()
        raise SystemExit(f"Rollback failed: {exc}")
    finally:
        con.close()

def cmd_doctor() -> int:
    print(f"Veronica {VERSION} dependency check")
    for name in ["file", "ffprobe", "HandBrakeCLI", "ffmpeg", "xattr"]:
        p = audit.shutil.which(name)
        print(f"{name:<12} {'FOUND ' + p if p else 'not found' + (' (needed only for execution)' if name in {'HandBrakeCLI','ffmpeg'} else '')}")
    try:
        import PIL
        print(f"Pillow       FOUND {PIL.__version__}")
    except Exception:
        print("Pillow       not found")
    print(f"Python       {sys.version.split()[0]}")
    print(f"xattr API    {audit.xattr_backend()}")
    print(f"birthtime API {creation_time_backend()}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Root does not exist or is not a directory: {root}")
    cfg = load_config(Path(args.config).expanduser() if args.config else None)
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    cfg = apply_product_filename_settings(cfg, state_dir)
    cfg = apply_product_media_processing_settings(cfg, state_dir)
    run_date = dt.date.fromisoformat(args.run_date) if args.run_date else dt.date.today()
    cfg = apply_product_date_scope_settings(cfg, state_dir, run_date)

    auditor = audit.Auditor(root, cfg, run_date, state_dir, full_hashing=False, probe_media=True)
    cutoff_override = getattr(args, "cutoff_override", None)
    if cutoff_override:
        auditor.cutoff = dt.date.fromisoformat(cutoff_override)
    print(f"Veronica {VERSION} planner")
    print(f"Root: {root}")
    scope = dict(cfg.get("date_scope") or {})
    scope_mode = scope.get("mode", "legacy")

    # Compatibility output retained for existing tests/tools.
    print(f"Cutoff: files before {auditor.cutoff.isoformat()}")

    if scope_mode == "legacy":
        print(f"Date scope: legacy annual policy, through {scope.get('end')}")
    elif scope_mode == "all":
        print("Date scope: all dates")
    elif scope_mode == "within":
        print(f"Date scope: only within {scope.get('start')} through {scope.get('end')}")
    elif scope_mode == "outside":
        print(f"Date scope: outside {scope.get('start')} through {scope.get('end')}")
    print("Mode: PLAN ONLY (media files will not be changed)")
    auditor.walk()

    # Explicitly account for ignore-name exclusions; this reconciles the previous 44,235 tag scan
    # vs 43,846 audit count when .DS_Store is the only ignored name.
    ignored_counts = Counter()
    ignore_names = set(cfg.get("ignore_names", []))
    for dirpath, _, filenames in os.walk(root, topdown=True, followlinks=False):
        for name in filenames:
            if name in ignore_names:
                ignored_counts[name] += 1

    run_id = sha256_text(canonical_json({"root": str(root), "run_date": run_date.isoformat(), "started": now_iso()}))[:24]
    db_path = state_dir / "media-maintenance.sqlite"
    con = init_db(db_path, root)
    con.execute("UPDATE assets SET active=0")
    con.execute("INSERT INTO runs(run_id,started_at,run_date,cutoff,root,tool_version,status) VALUES(?,?,?,?,?,?,?)",
                (run_id, now_iso(), run_date.isoformat(), auditor.cutoff.isoformat(), str(root), VERSION, "SCANNING"))

    items = []
    legacy_v1 = legacy_v2 = 0
    for row in auditor.rows:
        asset_id = upsert_asset(con, row, run_id, cfg)
        tags = set(row.get("tags", []))
        if "compressed-v1" in tags: legacy_v1 += 1
        if tags & set(cfg.get("legacy_v2_tags", [])): legacy_v2 += 1
        # PROCESS_NORMALLY is deliberately narrow. It may override only the
        # auditor's date uncertainty for this exact source identity. It does not
        # bypass any later media-policy or source-risk review.
        process_normally = None
        if row.get("action") == "REVIEW" and (
            "date_low_confidence" in str(row.get("reason") or "")
            or "date_conflict" in str(row.get("reason") or "")
        ):
            process_normally = historical_review_resolution(
                con,
                asset_id,
                row.get("reason"),
                row.get("quick_hash"),
                int(row.get("size") or 0),
                resolution="PROCESS_NORMALLY",
            )

        policy_row = row
        if process_normally is not None:
            policy_row = dict(row)
            policy_row["action"] = "CANDIDATE"

        item = make_item(policy_row, asset_id, cfg)
        item = apply_filename_policy(item, row, cfg)

        # A file already produced and committed by Veronica remains complete
        # when the active bytes still match the exact committed output.
        #
        # This check must precede date-only REVIEW handling. HandBrake outputs
        # may contain a new embedded creation_time while Veronica deliberately
        # restores the source filesystem dates. A later audit can therefore
        # report date_conflict even though the installed video is exactly the
        # verified output Veronica committed.
        #
        # Preserve hard safety/product boundaries: only override a date-related
        # REVIEW for an enabled video. Other review reasons continue normally.
        historical_date_review = (
            row.get("detected_kind") == "video"
            and item.get("operation") == "REVIEW"
            and (
                "date_low_confidence" in str(item.get("reason") or "")
                or "date_conflict" in str(item.get("reason") or "")
            )
        )
        if historical_date_review:
            historical = historical_video_completion(
                con, asset_id, row.get("quick_hash"), row.get("full_hash")
            )
            if historical is not None:
                item.update(
                    operation="SKIP_PROCESSED_VIDEO",
                    policy_version=None,
                    executable=False,
                    reason="sqlite_historical_video_processing_history",
                    target={
                        **item.get("target", {}),
                        "completed_policy_version": historical["policy_version"],
                        "completed_at": historical["processed_at"],
                        "accepted_as_historical_completion": True,
                        "suppressed_review_reason": row.get("reason"),
                    },
                )

        if process_normally is not None:
            item["target"] = {
                **item.get("target", {}),
                "review_resolution": "PROCESS_NORMALLY",
                "review_resolved_at": process_normally["decided_at"],
                "review_original_reason": row.get("reason"),
            }

        # A previous KEEP_ORIGINAL result is a successful terminal disposition for the
        # same source content under the same policy. It is not unfinished work.
        if item.get("operation") in {"CONVERT_IMAGE", "CONVERT_VIDEO", "CONVERT_AUDIO"} and item.get("executable"):
            kept = historical_keep_original(
                con, asset_id, item.get("operation"), item.get("policy_version"),
                row.get("quick_hash"), int(row.get("size") or 0)
            )
            if kept is not None:
                item.update(
                    operation="SKIP_KEEP_ORIGINAL", policy_version=None, executable=False,
                    reason="sqlite_keep_original_same_source_policy",
                    target={**item.get("target", {}),
                            "resolved_disposition": "KEEP_ORIGINAL",
                            "resolved_at": kept["decided_at"],
                            "resolved_policy_version": kept["policy_version"]},
                )

        # Durable Veronica video history is completion evidence across policy
        # upgrades, provided the active file still matches the output identity that was
        # recorded at commit time. This makes annual planning idempotent after the
        # .m4v/.mov -> .mp4 path migration and prevents an unchanged v3 result from being
        # re-transcoded simply because v4 is now the preferred policy. If the installed
        # file changed after commit, the hash guard deliberately stops matching and the
        # asset is evaluated normally.
        if item.get("operation") == "CONVERT_VIDEO" and item.get("executable"):
            historical = historical_video_completion(
                con, asset_id, row.get("quick_hash"), row.get("full_hash")
            )
            if historical is not None:
                item.update(
                    operation="SKIP_PROCESSED_VIDEO",
                    policy_version=None,
                    executable=False,
                    reason="sqlite_historical_video_processing_history",
                    target={
                        **item.get("target", {}),
                        "completed_policy_version": historical["policy_version"],
                        "completed_at": historical["processed_at"],
                        "accepted_as_historical_completion": True,
                    },
                )

        # v0.7.0 freezes source-risk classification into the plan itself. Risky videos
        # are not executable, so staging/commit cannot accidentally reinterpret them later.
        if item.get("operation") == "CONVERT_VIDEO" and item.get("executable"):
            try:
                source_path = root / item["relpath"]
                source_probe = ffprobe_json(source_path)
                source_summary = video_stream_summary(source_probe)
                frame_timing = None
                if cfg.get("video_review_vfr", True) and source_summary.get("summary_rate_mismatch"):
                    frame_timing = video_frame_timing_summary(source_path)
                review_reasons = video_source_review_reasons(source_probe, cfg, frame_timing)
                source_video = video_stream_summary(source_probe)
                if frame_timing is not None:
                    source_video["frame_timing"] = frame_timing
                    source_video["frame_timing_classification"] = classify_video_frame_timing(frame_timing, cfg)
                    item["target"] = {**item.get("target", {}), "source_video": source_video}
                if review_reasons:
                    item.update(operation="REVIEW", executable=False,
                                reason="video_source_review:" + ",".join(review_reasons),
                                target={**item.get("target", {}),
                                        "review_reasons": review_reasons,
                                        "source_video": source_video})
            except Exception as exc:
                item.update(operation="REVIEW", executable=False,
                            reason="video_source_probe_failed",
                            target={**item.get("target", {}), "probe_error": str(exc)})
        # Database history, not Finder tags, is authoritative for work completed by
        # Veronica itself. Exact current-policy history remains useful for image
        # and audio operations; video historical completion is handled above because a
        # policy upgrade does not invalidate an unchanged archival result.
        if item.get("executable") and item.get("policy_version"):
            done = con.execute(
                "SELECT 1 FROM processing_history WHERE asset_id=? AND policy_version=? AND status='COMMITTED' LIMIT 1",
                (asset_id, item.get("policy_version")),
            ).fetchone()
            if done:
                item.update(operation="SKIP_CURRENT_POLICY", executable=False,
                            reason="sqlite_current_policy_processing_history", target=item.get("target", {}))

        # Human review decisions are durable but narrowly guarded. They are applied only
        # after all planner/source-risk classification so the exact review reason is known.
        # Changed content or a changed reason falls back to REVIEW automatically.
        item = apply_historical_review_resolution(con, item)
        items.append(item)

    con.execute("UPDATE runs SET files_seen=?, completed_at=?, status='PLANNED' WHERE run_id=?", (len(auditor.rows), now_iso(), run_id))
    con.commit()

    # Plan ID is derived from the exact ordered decision payload, making it immutable/reproducible.
    items.sort(key=lambda x: x["relpath"])
    # Detect canonical filename collisions before freezing the immutable plan.
    #
    # This catches:
    # - two different source assets mapping to the same canonical destination;
    # - a canonical destination already occupied by a different active asset.
    #
    # Collision handling is deliberately conservative: affected items become
    # REVIEW and are never automatically renamed or overwritten.
    planned_destinations: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        final_relpath = str((item.get("target") or {}).get("final_relpath") or "")
        if not final_relpath or final_relpath == item.get("relpath"):
            continue
        planned_destinations.setdefault(final_relpath, []).append(item)

    canonical_collision_paths: set[str] = set()

    # Multiple planned items converging on one destination.
    for final_relpath, grouped in planned_destinations.items():
        if len(grouped) > 1:
            canonical_collision_paths.add(final_relpath)

    # Destination already occupied by a different active archive asset.
    for final_relpath, grouped in planned_destinations.items():
        source_relpaths = {str(i.get("relpath")) for i in grouped}
        occupied = con.execute(
            "SELECT relpath FROM assets WHERE active=1 AND relpath=?",
            (final_relpath,),
        ).fetchone()
        if occupied is not None and str(occupied["relpath"]) not in source_relpaths:
            canonical_collision_paths.add(final_relpath)

    if canonical_collision_paths:
        for item in items:
            final_relpath = str((item.get("target") or {}).get("final_relpath") or "")
            if final_relpath not in canonical_collision_paths:
                continue

            target = dict(item.get("target") or {})
            target["filename_collision"] = True
            target["filename_collision_destination"] = final_relpath

            item.update(
                operation="REVIEW",
                policy_version=None,
                executable=False,
                reason="filename_collision",
                target=target,
            )

    plan_core = {
        "schema_version": 1,
        "tool_version": VERSION,
        "root": str(root),
        "run_id": run_id,
        "run_date": run_date.isoformat(),
        "cutoff": auditor.cutoff.isoformat(),
        "date_scope": dict(cfg.get("date_scope") or {}),
        "files_inventoried": len(auditor.rows),
        "ignored_files": dict(ignored_counts),
        "legacy": {"v1_assets": legacy_v1, "v2_assets": legacy_v2},
        "policy_snapshot": {
            "policies": dict(cfg.get("policies", {})),
            "video": {
                "preset_file": cfg.get("video_preset_file"),
                "max_storage_edge": cfg.get("video_max_storage_edge"),
                "require_square_pixels": cfg.get("video_require_square_pixels"),
                "aspect_ratio_tolerance": cfg.get("video_aspect_ratio_tolerance"),
                "frame_rate_tolerance_fraction": cfg.get("video_frame_rate_tolerance_fraction"),
                "review_vfr": cfg.get("video_review_vfr"),
                "review_hdr": cfg.get("video_review_hdr"),
                "review_extra_streams": cfg.get("video_review_extra_streams"),
                "review_multichannel_audio": cfg.get("video_review_multichannel_audio"),
            },
        },
        "items": items,
    }
    plan_id = sha256_text(canonical_json(plan_core))
    plan = {**plan_core, "plan_id": plan_id, "created_at": now_iso()}
    plan_sha = sha256_text(canonical_json(plan))
    exec_count = sum(1 for i in items if i["executable"])
    review_count = sum(1 for i in items if i["operation"] == "REVIEW")
    con.execute("INSERT INTO plans(plan_id,created_at,run_id,run_date,cutoff,status,item_count,executable_count,review_count,plan_sha256) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (plan_id, plan["created_at"], run_id, run_date.isoformat(), auditor.cutoff.isoformat(), "PLANNED", len(items), exec_count, review_count, plan_sha))
    for seq, i in enumerate(items, 1):
        con.execute("INSERT INTO plan_items(plan_id,seq,asset_id,relpath,source_quick_hash,source_size,source_mtime_ns,operation,policy_version,reason,target_json,executable) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (plan_id, seq, i["asset_id"], i["relpath"], i["source_quick_hash"], i["source_size"], i["source_mtime_ns"], i["operation"], i["policy_version"], i["reason"], canonical_json(i["target"]), int(i["executable"])))
    con.commit(); con.close()

    json_path, md_path = write_plan_files(state_dir, plan)
    ops = Counter(i["operation"] for i in items)
    print(f"Inventoried: {len(auditor.rows):,} files")
    if ignored_counts:
        print("Ignored: " + ", ".join(f"{k}={v:,}" for k,v in ignored_counts.items()))
    print(f"Legacy v2 imported: {legacy_v2:,}")
    print(f"Legacy v1 imported: {legacy_v1:,}")
    print(f"Executable planned: {exec_count:,}")
    print(f"Review: {review_count:,}")
    for op, n in ops.most_common():
        print(f"  {op:<24} {n:>7,}")
    print(f"State DB: {db_path}")
    print(f"Plan JSON: {json_path}")
    print(f"Plan report: {md_path}")
    return 0


def _uncommitted_staged_rows(con: sqlite3.Connection, operation: Optional[str] = None, plan_id: Optional[str] = None) -> list[sqlite3.Row]:
    sql = """
        SELECT si.staging_id,si.relpath,si.operation,si.status,si.output_path,si.saving_bytes,si.saving_percent
        FROM staging_items si
        JOIN staging_runs sr ON sr.staging_id=si.staging_id
        WHERE si.status='STAGED_VERIFIED'
          AND NOT EXISTS (
              SELECT 1 FROM commit_items ci
              WHERE ci.relpath=si.relpath AND ci.status='COMMITTED'
          )
    """
    params: tuple[Any, ...] = ()
    clauses=[]
    vals=[]
    if operation:
        clauses.append("si.operation=?"); vals.append(operation)
    if plan_id:
        clauses.append("sr.plan_id=?"); vals.append(plan_id)
    if clauses: sql += " AND " + " AND ".join(clauses)
    params=tuple(vals)
    sql += " ORDER BY si.staging_id,si.relpath"
    return list(con.execute(sql, params))


def cmd_run_status(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    db = state_dir / "media-maintenance.sqlite"
    if not db.exists():
        raise SystemExit(f"No state database found: {db}")
    plan_path = Path(args.plan).expanduser().resolve() if args.plan else None
    if plan_path:
        plan = load_plan(plan_path)
        plan_id = plan["plan_id"]
    else:
        con = sqlite3.connect(db); con.row_factory = sqlite3.Row
        row = con.execute("SELECT plan_id FROM plans ORDER BY created_at DESC LIMIT 1").fetchone(); con.close()
        if not row: raise SystemExit("No plan found")
        plan_id = row["plan_id"]
        matches = sorted(state_dir.glob(f"plan-*-{plan_id[:12]}.json"))
        plan = load_plan(matches[-1]) if matches else None
    # Ensure schema migrations/backfills (including durable KEEP_ORIGINAL dispositions)
    # are applied before status accounting.
    status_root = Path(plan["root"]).resolve() if plan else Path(sqlite3.connect(db).execute("SELECT value FROM meta WHERE key='root'").fetchone()[0])
    mig = init_db(db, status_root); mig.close()
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    items = list(con.execute("SELECT operation,COUNT(*) n FROM plan_items WHERE plan_id=? GROUP BY operation", (plan_id,)))
    ops = {r["operation"]: int(r["n"]) for r in items}
    plan_by_op: dict[str,set[str]] = {"CONVERT_IMAGE":set(),"CONVERT_VIDEO":set(),"CONVERT_AUDIO":set()}
    source_size: dict[str,int] = {}
    if plan:
        for i in plan.get("items", []):
            op=i.get("operation")
            if i.get("executable") and op in plan_by_op:
                plan_by_op[op].add(i["relpath"])
                source_size[i["relpath"]]=int(i.get("source_size") or 0)
    committed_rows = list(con.execute("SELECT relpath,operation,details_json FROM commit_items WHERE status='COMMITTED'"))
    committed_by_op: dict[str,set[str]] = {"CONVERT_IMAGE":set(),"CONVERT_VIDEO":set(),"CONVERT_AUDIO":set()}
    saved_by_op = Counter()
    for r in committed_rows:
        op=r["operation"]
        if op in committed_by_op: committed_by_op[op].add(str(r["relpath"]))
        try:
            d=json.loads(r["details_json"] or "{}")
            b=int(d.get("precommit_verification",{}).get("saving_bytes") or d.get("verification",{}).get("saving_bytes") or d.get("saving_bytes") or 0)
            saved_by_op[op]+=b
        except Exception:
            pass
    resolved_by_op: dict[str,set[str]] = {
        "CONVERT_IMAGE": resolved_keep_original_relpaths(con, plan_id, "CONVERT_IMAGE"),
        "CONVERT_VIDEO": resolved_keep_original_relpaths(con, plan_id, "CONVERT_VIDEO"),
        "CONVERT_AUDIO": resolved_keep_original_relpaths(con, plan_id, "CONVERT_AUDIO"),
    }
    pending_rows=_uncommitted_staged_rows(con, plan_id=plan_id)
    pending_by_op=Counter(r["operation"] for r in pending_rows)
    # Median saving percentages from verified staging history are used only as a rough forecast.
    medians: dict[str,float] = {}
    import statistics
    for op in ("CONVERT_IMAGE","CONVERT_VIDEO","CONVERT_AUDIO"):
        vals=[float(r[0]) for r in con.execute("SELECT saving_percent FROM staging_items WHERE operation=? AND status='STAGED_VERIFIED' AND saving_percent IS NOT NULL AND saving_percent>0",(op,)).fetchall()]
        if vals: medians[op]=float(statistics.median(vals))
    stage_rows = list(con.execute("SELECT status,COUNT(*) n FROM staging_items GROUP BY status"))
    stage_counts = {r["status"]:int(r["n"]) for r in stage_rows}
    con.close()
    print(f"Veronica {VERSION} run status")
    print(f"Plan: {plan_id}")
    if plan and plan.get("video_policy_version"): print(f"Video policy: {plan['video_policy_version']}")
    for label,op in (("Images","CONVERT_IMAGE"),("Videos","CONVERT_VIDEO"),("Audio","CONVERT_AUDIO")):
        planned=int(ops.get(op,0))
        committed=len(committed_by_op[op] & plan_by_op[op]) if plan_by_op[op] else len(committed_by_op[op])
        kept=len(resolved_by_op[op] & plan_by_op[op]) if plan_by_op[op] else len(resolved_by_op[op])
        remaining=max(0,planned-committed-kept)
        print(f"{label}: planned={planned:,} committed={committed:,} kept-original={kept:,} remaining={remaining:,} staged-pending={pending_by_op.get(op,0):,}")
    print(f"Manual review in plan: {int(ops.get('REVIEW',0)):,}")
    print("Staging records: " + ", ".join(f"{k}={v:,}" for k,v in sorted(stage_counts.items())))
    total_saved=sum(saved_by_op.values())
    print(
        f"Recorded committed savings: {total_saved/1024**3:.2f} GiB "
        f"(images {saved_by_op['CONVERT_IMAGE']/1024**3:.2f}, "
        f"videos {saved_by_op['CONVERT_VIDEO']/1024**3:.2f}, "
        f"audio {saved_by_op['CONVERT_AUDIO']/1024**3:.2f})"
    )
    estimates=[]
    for op in ("CONVERT_IMAGE","CONVERT_VIDEO","CONVERT_AUDIO"):
        if op not in medians or not plan_by_op[op]: continue
        remaining_rels=plan_by_op[op]-committed_by_op[op]-resolved_by_op[op]
        est=sum(source_size.get(r,0) for r in remaining_rels)*(medians[op]/100.0)
        estimates.append((op,est,medians[op]))
    if estimates:
        print("Modeled remaining savings (diagnostic; based on median verified staging savings):")
        for op,est,med in estimates:
            print(f"  {op}: ~{est/1024**3:.2f} GiB using median {med:.1f}%")
    print(f"Uncommitted verified staged outputs: {len(pending_rows):,}")
    print(f"Quarantine directories: {sum(1 for p in (state_dir/'quarantine').glob('*') if p.is_dir()) if (state_dir/'quarantine').exists() else 0:,}")
    return 0


def cmd_next_batch(args: argparse.Namespace) -> int:
    state_dir=Path(args.state_dir).expanduser().resolve()
    db=state_dir/"media-maintenance.sqlite"
    if not db.exists(): raise SystemExit(f"No state database found: {db}")
    op = {
        "image": "CONVERT_IMAGE",
        "video": "CONVERT_VIDEO",
        "audio": "CONVERT_AUDIO",
    }[args.media]
    plan=load_plan(Path(args.plan).expanduser().resolve())
    plan_id=plan["plan_id"]
    hard = {"image": 250, "video": 50, "audio": 10}[args.media]
    if args.count < 1 or args.count > hard:
        raise SystemExit(f"--count must be between 1 and {hard} for {args.media}")
    con=sqlite3.connect(db); con.row_factory=sqlite3.Row
    pending=_uncommitted_staged_rows(con,op,plan_id); con.close()
    live=[]
    for r in pending:
        out=r["output_path"]
        if out and Path(out).exists(): live.append(r)
    if live and not args.allow_overlap:
        ids=sorted({r["staging_id"] for r in live})
        print(f"Refusing to stage a new {args.media} window: {len(live)} uncommitted verified output(s) already exist.")
        print("Staging IDs: " + ", ".join(ids[:10]))
        print("Commit or clean those staging runs first, or use --allow-overlap deliberately.")
        return 2
    ns=argparse.Namespace(plan=args.plan,state_dir=args.state_dir,config=args.config,
                          max_images=args.count if args.media=="image" else 0,
                          max_videos=args.count if args.media=="video" else 0,
                          max_audio=args.count if args.media=="audio" else 0,
                          sample_strategy="first",require_personal_tag_sample=False)
    return cmd_stage(ns)


def _staging_dir_size(path: Path) -> int:
    total=0
    if path.exists():
        for q in path.rglob('*'):
            if q.is_file():
                try: total+=q.stat().st_size
                except OSError: pass
    return total


def cmd_cleanup_superseded(args: argparse.Namespace) -> int:
    state_dir=Path(args.state_dir).expanduser().resolve()
    db=state_dir/"media-maintenance.sqlite"
    if not db.exists(): raise SystemExit(f"No state database found: {db}")
    plan=load_plan(Path(args.plan).expanduser().resolve()) if args.plan else None
    plan_id=plan.get("plan_id") if plan else None
    con=sqlite3.connect(db); con.row_factory=sqlite3.Row
    runs=list(con.execute("SELECT staging_id,plan_id,status,staging_dir FROM staging_runs ORDER BY started_at"))
    committed=already_committed_relpaths(db)
    candidates=[]; blocked=[]
    for run in runs:
        rows=list(con.execute("SELECT relpath,operation,status FROM staging_items WHERE staging_id=?",(run["staging_id"],)))
        # Runs from an older frozen plan are superseded by definition when --plan is supplied.
        superseded = bool(plan_id and run["plan_id"] != plan_id)
        blockers=[] if superseded else [r for r in rows if r["status"]=='STAGED_VERIFIED' and r["operation"] in ('CONVERT_IMAGE','CONVERT_VIDEO','CONVERT_AUDIO') and r["relpath"] not in committed]
        path=Path(run["staging_dir"])
        rec={"id":run["staging_id"],"path":path,"size":_staging_dir_size(path),"blockers":len(blockers),"superseded":superseded}
        (blocked if blockers else candidates).append(rec)
    con.close()
    print(f"Veronica {VERSION} superseded staging cleanup")
    print(f"Safe-to-remove staging directories: {len(candidates)}")
    print(f"Blocked staging directories: {len(blocked)}")
    print(f"Potential reclaim: {sum(r['size'] for r in candidates)/1024**3:.2f} GiB")
    for r in candidates[:20]: print(f"  SAFE {r['id']}  {r['size']/1024**2:.1f} MiB" + ("  superseded-plan" if r.get("superseded") else ""))
    for r in blocked[:10]: print(f"  KEEP {r['id']}  uncommitted_verified={r['blockers']}")
    if not args.apply:
        print("DRY RUN: nothing deleted. Re-run with --apply to remove only SAFE staging directories; reports, SQLite, and quarantine remain.")
        return 0
    for r in candidates:
        if r["path"].exists(): shutil.rmtree(r["path"])
    print(f"Removed {len(candidates)} safe staging directories. Reports, SQLite state, and quarantine were preserved.")
    return 0

def cmd_cleanup(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    if not args.staging_id:
        raise SystemExit("v0.6.0 cleanup requires --staging-id; quarantine is never deleted automatically")
    report = load_staging_report(state_dir, args.staging_id)
    db = state_dir / "media-maintenance.sqlite"
    committed = already_committed_relpaths(db) if db.exists() else set()
    blockers=[]
    for r in report.get("results",[]):
        if r.get("status")=="STAGED_VERIFIED" and r.get("operation") in ("CONVERT_IMAGE","CONVERT_VIDEO","CONVERT_AUDIO") and r.get("verification",{}).get("metadata_ready_for_commit") is True:
            if r.get("relpath") not in committed:
                blockers.append(r.get("relpath"))
    stage_dir = state_dir / "staging" / args.staging_id
    size=0
    if stage_dir.exists():
        for p in stage_dir.rglob('*'):
            if p.is_file():
                try: size += p.stat().st_size
                except OSError: pass
    print(f"Veronica {VERSION} cleanup")
    print(f"Staging ID: {args.staging_id}")
    print(f"Staging directory: {stage_dir}")
    print(f"Approximate reclaimable size: {size/1024**2:.1f} MiB")
    print(f"Uncommitted commit-ready media: {len(blockers)}")
    if blockers:
        print("Refusing cleanup because this staging run still contains commit-ready media that are not currently committed.")
        return 1
    if not args.apply:
        print("DRY RUN: nothing deleted. Re-run with --apply to remove only this staging directory; reports and quarantine remain.")
        return 0
    if stage_dir.exists(): shutil.rmtree(stage_dir)
    print("Removed staging directory. Reports, SQLite state, and quarantine were preserved.")
    return 0


def cmd_resolve_review(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("Refusing durable review resolution without --yes")
    plan_path = Path(args.plan).expanduser().resolve()
    plan = load_plan(plan_path)
    state_dir = Path(args.state_dir).expanduser().resolve()
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        raise SystemExit(f"State database not found: {db_path}")
    root = Path(plan["root"]).expanduser().resolve()
    items = [i for i in plan.get("items", []) if i.get("relpath") == args.relpath]
    if len(items) != 1:
        raise SystemExit(f"Expected exactly one plan item for {args.relpath!r}; found {len(items)}")
    item = items[0]
    if item.get("operation") != "REVIEW":
        raise SystemExit(f"Plan item is not REVIEW: operation={item.get('operation')} reason={item.get('reason')}")
    if args.resolution not in {"KEEP_AS_IS", "PROCESS_NORMALLY"}:
        raise SystemExit(f"Unsupported review resolution: {args.resolution}")

    if args.resolution == "PROCESS_NORMALLY":
        reason = str(item.get("reason") or "")
        if "date_low_confidence" not in reason and "date_conflict" not in reason:
            raise SystemExit(
                "PROCESS_NORMALLY is supported only for date-related review items. "
                "This safety review cannot be bypassed."
            )

    ok, why = verify_source_against_item(root, item)
    if not ok:
        raise SystemExit(f"Refusing stale review resolution: {why}")

    con = init_db(db_path, root)
    try:
        db_item = con.execute(
            "SELECT asset_id,source_quick_hash,source_size,operation,reason FROM plan_items WHERE plan_id=? AND relpath=?",
            (plan["plan_id"], args.relpath),
        ).fetchone()
        if db_item is None:
            raise SystemExit("Plan item is missing from SQLite; refusing to record resolution")
        if db_item["operation"] != "REVIEW" or db_item["reason"] != item.get("reason"):
            raise SystemExit("Plan JSON and SQLite review classification disagree; refusing to record resolution")
        if db_item["source_quick_hash"] != item.get("source_quick_hash") or int(db_item["source_size"]) != int(item.get("source_size") or 0):
            raise SystemExit("Plan JSON and SQLite source identity disagree; refusing to record resolution")

        details = {
            "note": args.note or "",
            "recorded_by_tool_version": VERSION,
            "plan_target": item.get("target") or {},
        }
        con.execute(
            "INSERT OR IGNORE INTO review_resolutions(asset_id,plan_id,review_reason,resolution,decided_at,source_quick_hash,source_size,details_json) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (int(db_item["asset_id"]), plan["plan_id"], item["reason"], args.resolution, now_iso(),
             item.get("source_quick_hash"), int(item.get("source_size") or 0), canonical_json(details)),
        )
        con.commit()
        stored = historical_review_resolution(
            con,
            int(db_item["asset_id"]),
            item["reason"],
            item.get("source_quick_hash"),
            int(item.get("source_size") or 0),
            resolution=args.resolution,
        )
        if stored is None:
            raise SystemExit("Review resolution was not persisted")
        print(f"Review resolution recorded: {args.resolution}")
        print(f"Plan: {plan['plan_id']}")
        print(f"File: {args.relpath}")
        print(f"Review reason: {item['reason']}")
        print(f"Source quick hash: {item.get('source_quick_hash')}")
        print(f"Source size: {int(item.get('source_size') or 0):,} bytes")
        print("Media file unchanged. Future plans will honor this decision only while source identity and review reason still match.")
        return 0
    finally:
        con.close()


def cmd_configure_filenames(args: argparse.Namespace) -> int:
    """Persist the user-visible filename policy without modifying media."""
    state_dir = Path(args.state_dir).expanduser().resolve()

    if args.enabled not in {"true", "false"}:
        raise SystemExit("--enabled must be true or false")

    if args.date_format not in _SUPPORTED_FILENAME_DATE_FORMATS:
        raise SystemExit(
            "Unsupported filename date format. "
            "This build supports: " + ", ".join(sorted(_SUPPORTED_FILENAME_DATE_FORMATS))
        )

    max_bytes = int(args.max_bytes)
    if max_bytes < 32 or max_bytes > 255:
        raise SystemExit("--max-bytes must be between 32 and 255")

    current = load_product_settings(state_dir)
    current["filename_standardization_enabled"] = args.enabled == "true"
    current["filename_date_format"] = args.date_format
    current["filename_max_bytes"] = max_bytes
    current["filename_settings_updated_at"] = now_iso()
    save_product_settings(state_dir, current)

    print(json.dumps(
        filename_product_settings(state_dir),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0



def cmd_configure_media_types(args: argparse.Namespace) -> int:
    """Persist which media types Veronica is permitted to modify."""
    state_dir = Path(args.state_dir).expanduser().resolve()

    values = {
        "images": args.images,
        "videos": args.videos,
        "audio": args.audio,
    }

    for name, value in values.items():
        if value not in {"true", "false"}:
            raise SystemExit(f"--{name} must be true or false")

    current = load_product_settings(state_dir)
    current["process_images"] = args.images == "true"
    current["process_videos"] = args.videos == "true"
    current["process_audio"] = args.audio == "true"
    current["media_processing_settings_updated_at"] = now_iso()

    save_product_settings(state_dir, current)

    print(json.dumps(
        media_processing_product_settings(state_dir),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0

def cmd_configure_date_scope(args: argparse.Namespace) -> int:
    """Persist the date range used to decide which media is eligible."""
    state_dir = Path(args.state_dir).expanduser().resolve()
    mode = str(args.mode)

    if mode not in {"all", "within", "outside"}:
        raise SystemExit("--mode must be all, within, or outside")

    start = args.start
    end = args.end

    if mode in {"within", "outside"}:
        if not start or not end:
            raise SystemExit("--start and --end are required for within/outside modes")
        try:
            start_date = dt.date.fromisoformat(start)
            end_date = dt.date.fromisoformat(end)
        except ValueError:
            raise SystemExit("--start and --end must use YYYY-MM-DD")
        if start_date > end_date:
            raise SystemExit("--start must be on or before --end")
        start = start_date.isoformat()
        end = end_date.isoformat()
    else:
        start = None
        end = None

    current = load_product_settings(state_dir)
    current["date_scope_mode"] = mode
    current["date_scope_start"] = start
    current["date_scope_end"] = end
    current["date_scope_updated_at"] = now_iso()
    save_product_settings(state_dir, current)

    print(json.dumps(
        date_scope_product_settings(state_dir),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


def cmd_configure_folders(args: argparse.Namespace) -> int:
    """Add/remove folders Veronica should scan without repointing old state."""
    state_dir = Path(args.state_dir).expanduser().resolve()
    current = load_product_settings(state_dir)
    folders = configured_scan_folders(state_dir)

    def normalized(value: str) -> Path:
        return Path(value).expanduser().resolve()

    for value in args.add or []:
        folder = normalized(value)
        if not folder.is_dir():
            raise SystemExit(f"Folder does not exist or is not a directory: {folder}")
        if folder not in folders:
            folders.append(folder)

    remove = {normalized(value) for value in (args.remove or [])}
    folders = [folder for folder in folders if folder not in remove]

    # Reject overlapping roots. Scanning both /Photos and /Photos/2024 would
    # otherwise process the same file twice.
    for index, left in enumerate(folders):
        for right in folders[index + 1:]:
            try:
                right.relative_to(left)
                raise SystemExit(
                    f"Configured folders may not overlap: {left} contains {right}"
                )
            except ValueError:
                pass
            try:
                left.relative_to(right)
                raise SystemExit(
                    f"Configured folders may not overlap: {right} contains {left}"
                )
            except ValueError:
                pass

    current["scan_folders"] = [str(folder) for folder in folders]
    current["scan_folders_updated_at"] = now_iso()

    # archive_root remains a compatibility field for the historical database.
    # Never repoint it merely because folders were added/removed.
    if "archive_root" not in current:
        database_root = database_archive_root(state_dir)
        if database_root is not None:
            current["archive_root"] = str(database_root)

    save_product_settings(state_dir, current)

    payload = {
        "scan_folders": [str(folder) for folder in folders],
        "unavailable_scan_folders": [
            str(folder) for folder in folders if not folder.is_dir()
        ],
        "state_dir": str(state_dir),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_configure_library(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Media library does not exist or is not a directory: {root}")
    existing_root = database_archive_root(state_dir)
    if existing_root is not None and existing_root != root:
        raise SystemExit(
            f"This Veronica database belongs to a different media library: {existing_root}. "
            "To protect historical identity and rollback state, Veronica will not repoint an existing database to another library."
        )
    current = load_product_settings(state_dir)
    current["archive_root"] = str(root)
    current["configured_at"] = now_iso()
    save_product_settings(state_dir, current)
    print(json.dumps({"archive_root": str(root), "state_dir": str(state_dir)}, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).expanduser().resolve()
    root = configured_archive_root(state_dir, getattr(args, "root", None))
    payload = dependency_status()
    payload.update({
        "version": VERSION,
        "state_dir": str(state_dir),
        "database_exists": (state_dir / "media-maintenance.sqlite").exists(),
        "archive_root": str(root) if root else None,
        "archive_available": bool(root and root.is_dir()),
    })
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _ui_snapshot_for_folder(root: Path, state_dir: Path, recent_limit: int) -> dict[str, Any]:
    """Read UI state for exactly one configured folder/state database."""
    db = state_dir / "media-maintenance.sqlite"

    result = {
        "root": str(root),
        "state_dir": str(state_dir),
        "database": str(db),
        "database_exists": db.exists(),
        "active_assets": 0,
        "committed_outputs": 0,
        "rolled_back_outputs": 0,
        "total_saving_bytes": 0,
        "quarantine_directories": 0,
        "latest_plan": None,
        "unresolved_reviews": [],
        "recent_changes": [],
    }

    if not db.exists():
        return result

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        result["active_assets"] = int(
            con.execute("SELECT COUNT(*) FROM assets WHERE active=1").fetchone()[0]
        )
        result["committed_outputs"] = int(
            con.execute(
                "SELECT COUNT(*) FROM commit_items WHERE status='COMMITTED'"
            ).fetchone()[0]
        )
        result["rolled_back_outputs"] = int(
            con.execute(
                "SELECT COUNT(*) FROM commit_items WHERE status='ROLLED_BACK'"
            ).fetchone()[0]
        )
        result["total_saving_bytes"] = int(
            con.execute(
                "SELECT COALESCE(SUM(si.saving_bytes),0) "
                "FROM commit_items ci "
                "JOIN commits c ON c.commit_id=ci.commit_id "
                "JOIN staging_items si "
                "ON si.staging_id=c.staging_id AND si.relpath=ci.relpath "
                "WHERE ci.status='COMMITTED'"
            ).fetchone()[0] or 0
        )

        latest = con.execute(
            "SELECT * FROM plans ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        if latest is not None:
            plan_id = str(latest["plan_id"])
            plan_candidates = sorted(
                state_dir.glob(f"plan-*-{plan_id[:12]}.json")
            )
            plan_path = str(plan_candidates[-1]) if plan_candidates else None

            rows = con.execute(
                "SELECT pi.asset_id,pi.relpath,pi.reason,"
                "pi.source_quick_hash,pi.source_size "
                "FROM plan_items pi "
                "WHERE pi.plan_id=? AND pi.operation='REVIEW' "
                "ORDER BY pi.seq",
                (plan_id,),
            ).fetchall()

            unresolved_reviews = []

            for row in rows:
                resolved = con.execute(
                    "SELECT 1 FROM review_resolutions rr "
                    "WHERE rr.asset_id=? AND rr.review_reason=? "
                    "AND rr.resolution IN ('KEEP_AS_IS','PROCESS_NORMALLY') "
                    "AND rr.source_quick_hash=? AND rr.source_size=? "
                    "LIMIT 1",
                    (
                        int(row["asset_id"]),
                        row["reason"],
                        row["source_quick_hash"],
                        int(row["source_size"]),
                    ),
                ).fetchone()

                if resolved is None:
                    unresolved_reviews.append({
                        "root": str(root),
                        "state_dir": str(state_dir),
                        "relpath": row["relpath"],
                        "reason": row["reason"],
                        "source_size": int(row["source_size"]),
                        "plan_path": plan_path,
                    })

            remaining_executable_count = None

            if plan_path:
                try:
                    frozen_plan = load_plan(Path(plan_path))
                    remaining_executable_count = len(
                        _annual_remaining(frozen_plan, state_dir)
                    )
                except Exception:
                    remaining_executable_count = None

            result["unresolved_reviews"] = unresolved_reviews
            result["latest_plan"] = {
                "plan_id": plan_id,
                "created_at": latest["created_at"],
                "run_date": latest["run_date"],
                "cutoff": latest["cutoff"],
                "item_count": int(latest["item_count"]),
                "executable_count": int(latest["executable_count"]),
                "remaining_executable_count": remaining_executable_count,
                "review_count": int(latest["review_count"]),
                "unresolved_review_count": len(unresolved_reviews),
                "plan_path": plan_path,
            }

        recent = con.execute(
            "SELECT ci.commit_id,ci.relpath,ci.operation,ci.final_path,"
            "c.completed_at,"
            "COALESCE(si.source_size,0) source_size,"
            "COALESCE(si.output_size,0) output_size,"
            "COALESCE(si.saving_bytes,0) saving_bytes,"
            "COALESCE(si.saving_percent,0) saving_percent "
            "FROM commit_items ci "
            "JOIN commits c ON c.commit_id=ci.commit_id "
            "LEFT JOIN staging_items si "
            "ON si.staging_id=c.staging_id AND si.relpath=ci.relpath "
            "WHERE ci.status='COMMITTED' "
            "ORDER BY COALESCE(c.completed_at,c.started_at) DESC "
            "LIMIT ?",
            (int(recent_limit),),
        ).fetchall()

        result["recent_changes"] = [{
            "root": str(root),
            "state_dir": str(state_dir),
            "commit_id": row["commit_id"],
            "relpath": row["relpath"],
            "operation": row["operation"],
            "final_path": row["final_path"],
            "completed_at": row["completed_at"],
            "source_size": int(row["source_size"] or 0),
            "output_size": int(row["output_size"] or 0),
            "saving_bytes": int(row["saving_bytes"] or 0),
            "saving_percent": float(row["saving_percent"] or 0.0),
        } for row in recent]

    finally:
        con.close()

    quarantine = state_dir / "quarantine"
    if quarantine.exists():
        result["quarantine_directories"] = sum(
            1 for item in quarantine.iterdir() if item.is_dir()
        )

    return result


def cmd_ui_snapshot(args: argparse.Namespace) -> int:
    """Return an aggregated read-only snapshot for every configured folder."""
    state_dir = Path(args.state_dir).expanduser().resolve()
    db = state_dir / "media-maintenance.sqlite"

    scan_folders = configured_scan_folders(state_dir)
    unavailable_scan_folders = [
        folder for folder in scan_folders if not folder.is_dir()
    ]

    today = dt.date.today()
    cutoff = _annual_calendar_cutoff(today)

    folder_states = [
        _ui_snapshot_for_folder(
            folder,
            scan_folder_state_dir(state_dir, folder),
            int(args.recent_limit),
        )
        for folder in scan_folders
    ]

    active_assets = sum(x["active_assets"] for x in folder_states)
    committed_outputs = sum(x["committed_outputs"] for x in folder_states)
    rolled_back_outputs = sum(x["rolled_back_outputs"] for x in folder_states)
    total_saving_bytes = sum(x["total_saving_bytes"] for x in folder_states)
    quarantine_directories = sum(
        x["quarantine_directories"] for x in folder_states
    )

    unresolved_reviews = []
    recent_changes = []
    latest_plans = []

    for folder_state in folder_states:
        unresolved_reviews.extend(folder_state["unresolved_reviews"])
        recent_changes.extend(folder_state["recent_changes"])

        if folder_state["latest_plan"] is not None:
            latest_plans.append(folder_state["latest_plan"])

    recent_changes.sort(
        key=lambda item: item.get("completed_at") or "",
        reverse=True,
    )
    recent_changes = recent_changes[:int(args.recent_limit)]

    latest_plan = None

    if latest_plans:
        remaining_values = [
            plan["remaining_executable_count"]
            for plan in latest_plans
        ]

        if all(value is not None for value in remaining_values):
            remaining_executable_count = sum(
                int(value) for value in remaining_values
            )
        else:
            remaining_executable_count = None

        latest_created = max(
            str(plan["created_at"]) for plan in latest_plans
        )
        latest_run_date = max(
            str(plan["run_date"]) for plan in latest_plans
        )
        latest_cutoff = max(
            str(plan["cutoff"]) for plan in latest_plans
        )

        if len(latest_plans) == 1:
            aggregate_plan_id = latest_plans[0]["plan_id"]
            aggregate_plan_path = latest_plans[0]["plan_path"]
        else:
            aggregate_plan_id = "multi-" + sha256_text(
                canonical_json(sorted(plan["plan_id"] for plan in latest_plans))
            )[:24]
            aggregate_plan_path = None

        latest_plan = {
            "plan_id": aggregate_plan_id,
            "created_at": latest_created,
            "run_date": latest_run_date,
            "cutoff": latest_cutoff,
            "item_count": sum(
                int(plan["item_count"]) for plan in latest_plans
            ),
            "executable_count": sum(
                int(plan["executable_count"]) for plan in latest_plans
            ),
            "remaining_executable_count": remaining_executable_count,
            "review_count": sum(
                int(plan["review_count"]) for plan in latest_plans
            ),
            "unresolved_review_count": len(unresolved_reviews),
            "plan_path": aggregate_plan_path,
        }

    legacy_root = configured_archive_root(state_dir)

    payload = {
        "version": VERSION,
        "configured": bool(scan_folders),
        "database_exists": any(
            folder_state["database_exists"] for folder_state in folder_states
        ),
        "state_dir": str(state_dir),
        "database": str(db),

        # Compatibility only. Native UI uses scan_folders and per-item roots.
        "archive_root": str(legacy_root) if legacy_root else None,

        # Compatibility name; now means every configured scan folder is available.
        "archive_available": (
            bool(scan_folders) and not unavailable_scan_folders
        ),

        "scan_folders": [str(folder) for folder in scan_folders],
        "unavailable_scan_folders": [
            str(folder) for folder in unavailable_scan_folders
        ],
        "active_assets": active_assets,
        "committed_outputs": committed_outputs,
        "rolled_back_outputs": rolled_back_outputs,
        "total_saving_bytes": total_saving_bytes,
        "quarantine_directories": quarantine_directories,
        "annual": {
            "run_year": today.year,
            "include_through": str(cutoff - dt.timedelta(days=1)),
            "cutoff_exclusive": str(cutoff),
        },
        "latest_plan": latest_plan,
        "unresolved_reviews": unresolved_reviews,
        "recent_changes": recent_changes,
        "filename_policy": filename_product_settings(state_dir),
        "media_processing": media_processing_product_settings(state_dir),
        "date_scope": date_scope_product_settings(state_dir, today),
        "preflight": dependency_status(),
    }

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    db = Path(args.state_dir).expanduser().resolve() / "media-maintenance.sqlite"
    if not db.exists():
        raise SystemExit(f"No state database found: {db}")
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    print(f"Veronica {VERSION} state")
    print(f"Database: {db}")
    print(f"Assets: {con.execute('SELECT COUNT(*) FROM assets WHERE active=1').fetchone()[0]:,} active")
    legacy_v1 = con.execute("SELECT COUNT(*) FROM legacy_history WHERE legacy_tag='compressed-v1'").fetchone()[0]
    legacy_v2 = con.execute("SELECT COUNT(DISTINCT asset_id) FROM legacy_history WHERE legacy_tag IN ('compressed-v2','_compressed-v2')").fetchone()[0]
    print(f"Legacy v1: {legacy_v1:,}")
    print(f"Legacy v2: {legacy_v2:,}")
    committed = con.execute("SELECT COUNT(*) FROM commit_items WHERE status='COMMITTED'").fetchone()[0]
    rolled = con.execute("SELECT COUNT(*) FROM commit_items WHERE status='ROLLED_BACK'").fetchone()[0]
    print(f"Committed outputs: {committed:,}")
    print(f"Rolled back outputs: {rolled:,}")
    last = con.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 1").fetchone()
    if last:
        print(f"Latest plan: {last['plan_id']}")
        print(f"  date: {last['run_date']}  items: {last['item_count']:,}  executable: {last['executable_count']:,}  review: {last['review_count']:,}")
    con.close()
    return 0



def _annual_remaining(plan: dict[str, Any], state_dir: Path) -> list[dict[str, Any]]:
    """Return executable plan items that do not already have a terminal disposition."""
    db_path = state_dir / "media-maintenance.sqlite"
    committed = already_committed_relpaths(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        kept = resolved_keep_original_relpaths(con, plan["plan_id"])
    finally:
        con.close()
    terminal = committed | kept
    return [i for i in plan.get("items", []) if i.get("executable") and i.get("relpath") not in terminal]


def _annual_live_pending(state_dir: Path) -> list[sqlite3.Row]:
    db_path = state_dir / "media-maintenance.sqlite"
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = _uncommitted_staged_rows(con)
    finally:
        con.close()
    return [r for r in rows if r["output_path"] and Path(r["output_path"]).exists()]


def _latest_staging_id_for_plan(state_dir: Path, plan_id: str) -> Optional[str]:
    con = sqlite3.connect(state_dir / "media-maintenance.sqlite")
    try:
        row = con.execute(
            "SELECT staging_id FROM staging_runs WHERE plan_id=? ORDER BY started_at DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return str(row[0]) if row else None
    finally:
        con.close()


def _annual_write_report(state_dir: Path, plan: dict[str, Any], status: str, started_at: str,
                         batch_records: list[dict[str, Any]], note: Optional[str] = None) -> Path:
    finished_at = now_iso()
    ops = Counter(i.get("operation") for i in plan.get("items", []))
    report = state_dir / f"annual-{plan['run_date']}-{plan['plan_id'][:12]}.md"
    lines = [
        "# Veronica Annual Report", "",
        f"- Tool version: `{VERSION}`",
        f"- Status: **{status}**",
        f"- Run date: **{plan['run_date']}**",
        f"- Cutoff: **before {plan['cutoff']}**",
        f"- Plan ID: `{plan['plan_id']}`",
        f"- Started: `{started_at}`",
        f"- Finished: `{finished_at}`",
        f"- Files inventoried: **{plan.get('files_inventoried', 0):,}**",
        f"- Executable planned: **{sum(1 for i in plan.get('items', []) if i.get('executable')):,}**",
        f"- Review items: **{sum(1 for i in plan.get('items', []) if i.get('operation') == 'REVIEW'):,}**",
        "", "## Plan decisions", "", "| Operation | Files |", "|---|---:|",
    ]
    for op, count in ops.most_common():
        lines.append(f"| `{op}` | {count:,} |")
    lines += ["", "## Automated batches", ""]
    if batch_records:
        total_saved = sum(int(rec.get("committed_saving_bytes", 0) or 0) for rec in batch_records)
        lines.append(f"- Committed savings in this annual run: **{total_saved/1024**3:.2f} GiB**")
        for rec in batch_records:
            lines.append(
                f"- staging `{rec['staging_id']}`: staged_verified={rec.get('verified',0)}, "
                f"keep_original={rec.get('kept',0)}, committed_renames={rec.get('committed_renames',0)}, "
                f"committed_images={rec.get('committed_images',0)}, "
                f"committed_videos={rec.get('committed_videos',0)}, "
                f"committed_audio={rec.get('committed_audio',0)}, "
                f"committed_saving={int(rec.get('committed_saving_bytes',0) or 0)/1024**2:.1f} MiB"
            )
    else:
        lines.append("- No conversion batch was committed.")
    if note:
        lines += ["", "## Stop reason", "", note]
    lines += ["", "## Safety", "",
              "Conversions were staged and independently verified before commit. Each committed original has its own quarantine transaction and remains independently rollbackable. The annual controller stops before committing a staging window if any selected item reports an anomaly.", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _annual_calendar_cutoff(run_date: dt.date) -> dt.date:
    """Return the exclusive cutoff for the annual calendar-year policy.

    A run in year Y includes media dated through December 31 of Y-2,
    so the planner cutoff is January 1 of Y-1. The month/day of the
    annual invocation does not affect eligibility.
    """
    return dt.date(run_date.year - 1, 1, 1)


def cmd_annual_all(args: argparse.Namespace) -> int:
    """Run the proven single-folder annual controller for every configured folder."""
    if not args.yes:
        raise SystemExit(
            "Annual maintenance can commit verified media. "
            "Re-run with --yes to acknowledge bounded commit operations."
        )

    base_state_dir = Path(args.state_dir).expanduser().resolve()
    folders = configured_scan_folders(base_state_dir)

    if not folders:
        raise SystemExit(
            "No folders are configured. Add at least one folder in Veronica Settings first."
        )

    unavailable = [folder for folder in folders if not folder.is_dir()]
    if unavailable:
        print("Refusing annual run because configured folder(s) are unavailable:")
        for folder in unavailable:
            print(f"  {folder}")
        return 2

    print(f"Veronica {VERSION} multi-folder annual maintenance")
    print(f"Configured folders: {len(folders)}")
    print("Each folder uses an independent state database.")
    print("Any REVIEW item, staging anomaly, or commit failure stops the full run.")

    for index, folder in enumerate(folders, 1):
        folder_state = prepare_scan_folder_state(base_state_dir, folder)

        print("")
        print("=" * 72)
        print(f"Folder {index}/{len(folders)}")
        print(f"Root: {folder}")
        print(f"State: {folder_state}")
        print("=" * 72)

        child_args = argparse.Namespace(
            root=str(folder),
            state_dir=str(folder_state),
            config=args.config,
            run_date=args.run_date,
            rename_batch=args.rename_batch,
            image_batch=args.image_batch,
            video_batch=args.video_batch,
            audio_batch=args.audio_batch,
            yes=True,
            events_jsonl=args.events_jsonl,
        )

        rc = cmd_annual(child_args)
        if rc != 0:
            print("")
            print(
                f"STOP: folder {index}/{len(folders)} did not complete safely: {folder}"
            )
            print("Remaining configured folders were not processed.")
            return rc

    print("")
    print("=" * 72)
    print("MULTI-FOLDER ANNUAL MAINTENANCE COMPLETE")
    print(f"Folders completed: {len(folders)}")
    print("=" * 72)
    return 0


def cmd_annual(args: argparse.Namespace) -> int:
    """One-command yearly controller built only from the existing proven primitives."""
    if not args.yes:
        raise SystemExit("Annual maintenance can commit verified media. Re-run with --yes to acknowledge bounded commit operations.")
    if args.rename_batch < 1 or args.rename_batch > 250:
        raise SystemExit("--rename-batch must be between 1 and 250")
    if args.image_batch < 1 or args.image_batch > 250:
        raise SystemExit("--image-batch must be between 1 and 250")
    if args.video_batch < 1 or args.video_batch > 25:
        raise SystemExit("--video-batch must be between 1 and 25")
    if args.audio_batch < 1 or args.audio_batch > 10:
        raise SystemExit("--audio-batch must be between 1 and 10")

    state_dir = Path(args.state_dir).expanduser().resolve()
    root = require_archive_root(state_dir, args.root)
    if not state_dir.exists() and state_dir == default_state_dir() and legacy_state_dir().exists():
        raise SystemExit(
            f"Legacy Veronica state exists at {legacy_state_dir()}. "
            "Refusing to create a second state database. Run `python3 media_maintenance.py migrate-state` "
            "first (dry run), then repeat with `--apply`."
        )
    state_dir.mkdir(parents=True, exist_ok=True)
    started_at = now_iso()
    configure_event_stream(args.events_jsonl)
    emit_event("annual_started", version=VERSION, root=str(root), state_dir=str(state_dir), started_at=started_at)

    pending = _annual_live_pending(state_dir)
    if pending:
        ids = sorted({str(r["staging_id"]) for r in pending})
        print(f"Refusing annual run: {len(pending)} uncommitted verified staged output(s) already exist.")
        print("Staging IDs: " + ", ".join(ids[:10]))
        print("Commit, inspect, or clean those outputs before starting a new annual plan.")
        return 2

    annual_run_date = dt.date.fromisoformat(args.run_date) if args.run_date else dt.date.today()
    annual_cutoff = _annual_calendar_cutoff(annual_run_date)

    scope = date_scope_product_settings(state_dir, annual_run_date)

    print(f"Veronica {VERSION} maintenance")
    print("Mode: ONE-COMMAND CONTROLLER WITH BOUNDED STAGING/COMMIT WINDOWS")
    print("Safety: REVIEW items remain pending; any staging, verification, or commit anomaly stops automation")

    if scope["mode"] == "legacy":
        print(f"Date scope: current annual policy through {scope['end']}")
    elif scope["mode"] == "all":
        print("Date scope: all dates")
    elif scope["mode"] == "within":
        print(f"Date scope: only within {scope['start']} through {scope['end']}")
    elif scope["mode"] == "outside":
        print(f"Date scope: outside {scope['start']} through {scope['end']}")

    emit_event(
        "annual_cutoff",
        run_date=annual_run_date.isoformat(),
        cutoff=annual_cutoff.isoformat(),
        include_through=scope.get("end"),
    )

    plan_args = argparse.Namespace(
        root=str(root),
        state_dir=str(state_dir),
        config=args.config,
        run_date=annual_run_date.isoformat(),
        cutoff_override=annual_cutoff.isoformat(),
    )
    rc = cmd_plan(plan_args)
    if rc != 0:
        return rc

    run_date = annual_run_date.isoformat()
    con = sqlite3.connect(state_dir / "media-maintenance.sqlite")
    try:
        row = con.execute(
            "SELECT plan_id FROM plans WHERE run_date=? ORDER BY created_at DESC LIMIT 1",
            (run_date,),
        ).fetchone()
    finally:
        con.close()
    if not row:
        raise SystemExit("Annual controller could not locate the immutable plan it just created")
    plan_id = str(row[0])
    plan_path = state_dir / f"plan-{run_date}-{plan_id[:12]}.json"
    plan = load_plan(plan_path)
    emit_event("plan_complete", plan_id=plan["plan_id"], plan_path=str(plan_path), inventoried=plan.get("files_inventoried", 0), executable=sum(1 for i in plan.get("items", []) if i.get("executable")), review=sum(1 for i in plan.get("items", []) if i.get("operation") == "REVIEW"))

    reviews = [i for i in plan.get("items", []) if i.get("operation") == "REVIEW"]
    if reviews:
        print(
            f"Plan contains {len(reviews)} REVIEW item(s). "
            "They will remain pending while unrelated safe executable work continues."
        )
        for item in reviews[:20]:
            print(f"  REVIEW {item['relpath']} — {item.get('reason')}")
        if len(reviews) > 20:
            print(f"  ... and {len(reviews)-20} more")

    remaining = _annual_remaining(plan, state_dir)
    unsupported = [
        i for i in remaining
        if i.get("operation") not in {"RENAME", "CONVERT_IMAGE", "CONVERT_VIDEO", "CONVERT_AUDIO"}
    ]
    if unsupported:
        kinds = Counter(i.get("operation") for i in unsupported)
        msg = "Executable operation(s) are not supported by the annual controller: " + ", ".join(f"{k}={v}" for k,v in kinds.items())
        print("STOP: " + msg)
        report = _annual_write_report(state_dir, plan, "NEEDS_MANUAL_ACTION", started_at, [], msg)
        print(f"Annual report: {report}")
        return 2

    batches: list[dict[str, Any]] = []
    guard = 0
    while remaining:
        guard += 1
        if guard > 10000:
            raise SystemExit("Annual controller safety guard triggered: too many batches")
        counts = Counter(i.get("operation") for i in remaining)

        # Filename-only normalization is its own bounded transaction class.
        # Each item uses the same per-file quarantine + rollback guarantees as
        # conversion commits, but does not enter media conversion staging.
        rename_items = [
            i for i in remaining
            if i.get("operation") == "RENAME"
        ][:args.rename_batch]

        if rename_items:
            print(
                f"\nAnnual batch {guard}: "
                f"remaining renames={counts.get('RENAME',0)} "
                f"images={counts.get('CONVERT_IMAGE',0)} "
                f"videos={counts.get('CONVERT_VIDEO',0)} "
                f"audio={counts.get('CONVERT_AUDIO',0)}"
            )
            emit_event(
                "batch_started",
                batch_number=guard,
                remaining_renames=counts.get("RENAME", 0),
                remaining_images=counts.get("CONVERT_IMAGE", 0),
                remaining_videos=counts.get("CONVERT_VIDEO", 0),
                remaining_audio=counts.get("CONVERT_AUDIO", 0),
            )

            rec = {
                "staging_id": "rename-only",
                "verified": 0,
                "kept": 0,
                "committed_renames": 0,
                "committed_images": 0,
                "committed_videos": 0,
                "committed_audio": 0,
                "committed_saving_bytes": 0,
            }

            for idx, rename_item in enumerate(rename_items, 1):
                relpath = str(rename_item["relpath"])
                rename_args = argparse.Namespace(
                    plan=str(plan_path),
                    state_dir=str(state_dir),
                    relpath=relpath,
                    yes=True,
                )
                try:
                    result = commit_one_rename(rename_args, quiet=True)
                except SystemExit as exc:
                    report = _annual_write_report(
                        state_dir,
                        plan,
                        "STOPPED_COMMIT_FAILURE",
                        started_at,
                        batches + [rec],
                        f"Rename commit failed safely for `{relpath}`: {exc}",
                    )
                    print(f"STOP: rename commit failed safely for {relpath}: {exc}")
                    print(f"Annual report: {report}")
                    return 2

                rec["committed_renames"] += 1
                print(
                    f"[{idx}/{len(rename_items)}] RENAMED "
                    f"{relpath} -> {result['final_relpath']}"
                )
                emit_event(
                    "commit_item",
                    media="rename",
                    index=idx,
                    total=len(rename_items),
                    relpath=relpath,
                    final_relpath=result["final_relpath"],
                    status="COMMITTED",
                    commit_id=result["commit_id"],
                )

            batches.append(rec)

            new_remaining = _annual_remaining(plan, state_dir)
            if len(new_remaining) >= len(remaining):
                report = _annual_write_report(
                    state_dir,
                    plan,
                    "STOPPED_NO_PROGRESS",
                    started_at,
                    batches,
                    "A bounded rename batch completed without reducing remaining executable work.",
                )
                print(f"STOP: annual controller made no progress. Annual report: {report}")
                return 2

            remaining = new_remaining
            continue

        max_images = min(args.image_batch, counts.get("CONVERT_IMAGE", 0))
        max_videos = min(args.video_batch, counts.get("CONVERT_VIDEO", 0))
        max_audio = min(args.audio_batch, counts.get("CONVERT_AUDIO", 0))
        print(
            f"\nAnnual batch {guard}: "
            f"remaining renames={counts.get('RENAME',0)} "
            f"images={counts.get('CONVERT_IMAGE',0)} "
            f"videos={counts.get('CONVERT_VIDEO',0)} "
            f"audio={counts.get('CONVERT_AUDIO',0)}"
        )
        emit_event(
            "batch_started",
            batch_number=guard,
            remaining_renames=counts.get("RENAME", 0),
            remaining_images=counts.get("CONVERT_IMAGE", 0),
            remaining_videos=counts.get("CONVERT_VIDEO", 0),
            remaining_audio=counts.get("CONVERT_AUDIO", 0),
        )
        stage_args = argparse.Namespace(
            plan=str(plan_path), state_dir=str(state_dir), config=args.config,
            max_images=max_images, max_videos=max_videos, max_audio=max_audio,
            sample_strategy="first", require_personal_tag_sample=False,
        )
        rc = cmd_stage(stage_args)
        if rc != 0:
            report = _annual_write_report(state_dir, plan, "STOPPED_ANOMALY", started_at, batches, "Staging command returned a non-zero status.")
            print(f"Annual report: {report}")
            return rc
        staging_id = _latest_staging_id_for_plan(state_dir, plan["plan_id"])
        if not staging_id:
            raise SystemExit("Annual controller could not locate the staging run it just created")
        staging = load_staging_report(state_dir, staging_id)
        results = [r for r in staging.get("results", []) if r.get("operation") in {"CONVERT_IMAGE", "CONVERT_VIDEO", "CONVERT_AUDIO"}]
        anomalous = [r for r in results if r.get("status") not in {"STAGED_VERIFIED", "KEEP_ORIGINAL"}]
        blocked = [r for r in results if r.get("status") == "STAGED_VERIFIED" and r.get("verification", {}).get("metadata_ready_for_commit") is not True]
        rec = {
            "staging_id": staging_id,
            "verified": sum(1 for r in results if r.get("status") == "STAGED_VERIFIED"),
            "kept": sum(1 for r in results if r.get("status") == "KEEP_ORIGINAL"),
            "committed_images": 0, "committed_videos": 0, "committed_audio": 0, "committed_saving_bytes": 0,
        }
        batches.append(rec)
        if anomalous or blocked:
            print("STOP: staging anomaly detected; nothing from this staging window will be committed.")
            for r in (anomalous + blocked)[:20]:
                err = r.get("error") or r.get("verification", {}).get("error") or "metadata_not_commit_ready"
                print(f"  {r.get('status')} {r.get('relpath')} — {err}")
            report = _annual_write_report(state_dir, plan, "STOPPED_ANOMALY", started_at, batches,
                                          f"Staging `{staging_id}` contains an anomalous or non-commit-ready result. Verified outputs remain staged for inspection.")
            print(f"Annual report: {report}")
            return 2

        image_ready = [r for r in results if r.get("status") == "STAGED_VERIFIED" and r.get("operation") == "CONVERT_IMAGE"]
        video_ready = [r for r in results if r.get("status") == "STAGED_VERIFIED" and r.get("operation") == "CONVERT_VIDEO"]
        audio_ready = [r for r in results if r.get("status") == "STAGED_VERIFIED" and r.get("operation") == "CONVERT_AUDIO"]
        if image_ready:
            commit_args = argparse.Namespace(staging_id=staging_id, state_dir=str(state_dir), config=args.config,
                                             max_items=len(image_ready), relpath=None, yes=True)
            rc = cmd_commit_batch(commit_args)
            if rc != 0:
                report = _annual_write_report(state_dir, plan, "STOPPED_COMMIT_FAILURE", started_at, batches,
                                              f"Image commit batch from staging `{staging_id}` reported a safe failure.")
                print(f"Annual report: {report}")
                return rc
            rec["committed_images"] = len(image_ready)
            rec["committed_saving_bytes"] += sum(int(r.get("verification", {}).get("saving_bytes") or 0) for r in image_ready)
        if video_ready:
            commit_args = argparse.Namespace(staging_id=staging_id, state_dir=str(state_dir), config=args.config,
                                             max_items=len(video_ready), relpath=None, yes=True)
            rc = cmd_commit_video_batch(commit_args)
            if rc != 0:
                report = _annual_write_report(state_dir, plan, "STOPPED_COMMIT_FAILURE", started_at, batches,
                                              f"Video commit batch from staging `{staging_id}` reported a safe failure.")
                print(f"Annual report: {report}")
                return rc
            rec["committed_videos"] = len(video_ready)
            rec["committed_saving_bytes"] += sum(int(r.get("verification", {}).get("saving_bytes") or 0) for r in video_ready)

        if audio_ready:
            commit_args = argparse.Namespace(
                staging_id=staging_id,
                state_dir=str(state_dir),
                config=args.config,
                max_items=len(audio_ready),
                relpath=None,
                yes=True,
            )
            rc = cmd_commit_audio_batch(commit_args)
            if rc != 0:
                report = _annual_write_report(
                    state_dir,
                    plan,
                    "STOPPED_COMMIT_FAILURE",
                    started_at,
                    batches,
                    f"Audio commit batch from staging `{staging_id}` reported a safe failure.",
                )
                print(f"Annual report: {report}")
                return rc
            rec["committed_audio"] = len(audio_ready)
            rec["committed_saving_bytes"] += sum(
                int(r.get("verification", {}).get("saving_bytes") or 0)
                for r in audio_ready
            )

        new_remaining = _annual_remaining(plan, state_dir)
        if len(new_remaining) >= len(remaining):
            report = _annual_write_report(state_dir, plan, "STOPPED_NO_PROGRESS", started_at, batches,
                                          "A bounded batch completed without reducing remaining executable work.")
            print(f"STOP: annual controller made no progress. Annual report: {report}")
            return 2
        remaining = new_remaining

    unresolved_reviews = [
        i for i in plan.get("items", [])
        if i.get("operation") == "REVIEW"
    ]

    final_status = (
        "COMPLETE_WITH_REVIEW"
        if unresolved_reviews
        else "COMPLETE"
    )

    final_note = (
        f"All safe executable work completed. "
        f"{len(unresolved_reviews)} review item(s) remain pending."
        if unresolved_reviews
        else "All safe executable work completed and no review items remain."
    )

    report = _annual_write_report(
        state_dir,
        plan,
        final_status,
        started_at,
        batches,
        final_note,
    )

    print("\nAnnual maintenance COMPLETE")
    print(f"Plan: {plan_path}")
    print(f"Annual report: {report}")

    if unresolved_reviews:
        print(
            f"Safe executable work is complete; "
            f"{len(unresolved_reviews)} REVIEW item(s) remain pending."
        )
    else:
        print("No executable work or unresolved REVIEW items remain.")

    emit_event(
        "annual_complete",
        plan_id=plan["plan_id"],
        plan_path=str(plan_path),
        report=str(report),
        batches=batches,
        unresolved_reviews=len(unresolved_reviews),
        status=final_status,
    )
    close_event_stream()
    return 0

def main() -> int:
    p = argparse.ArgumentParser(description="Veronica engine with resumable workflows and per-file quarantine")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    pm = sub.add_parser("migrate-state", help="dry-run/perform the one-time move from Documents into ~/Library/Application Support/Veronica")
    pm.add_argument("--from-dir", default=LEGACY_STATE_DIR)
    pm.add_argument("--to-dir", default=DEFAULT_STATE_DIR)
    pm.add_argument("--apply", action="store_true", help="perform the atomic migration; default is dry-run")
    paa = sub.add_parser("annual-all", help="run annual maintenance across all configured scan folders using isolated per-folder state")
    paa.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    paa.add_argument("--config")
    paa.add_argument("--run-date", help="YYYY-MM-DD; defaults to today")
    paa.add_argument("--rename-batch", type=int, default=250, help="bounded filename-only rename window; max 250")
    paa.add_argument("--image-batch", type=int, default=250, help="bounded image staging/commit window; max 250")
    paa.add_argument("--video-batch", type=int, default=25, help="bounded video staging/commit window; max 25")
    paa.add_argument("--audio-batch", type=int, default=10, help="bounded audio staging/commit window; max 10")
    paa.add_argument("--yes", action="store_true", help="required acknowledgement that verified media may be committed")
    paa.add_argument("--events-jsonl", help="optional JSON-lines progress/event file for the Veronica GUI")

    pa = sub.add_parser("annual", help="one-command yearly plan/stage/verify/commit/report controller; stops on REVIEW or any anomaly")
    pa.add_argument("--root", help="media library root; defaults to Veronica settings")
    pa.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pa.add_argument("--config")
    pa.add_argument("--run-date", help="YYYY-MM-DD; defaults to today")
    pa.add_argument("--rename-batch", type=int, default=250, help="bounded filename-only rename window; max 250")
    pa.add_argument("--image-batch", type=int, default=250, help="bounded image staging/commit window; max 250")
    pa.add_argument("--video-batch", type=int, default=25, help="bounded video staging/commit window; max 25")
    pa.add_argument("--audio-batch", type=int, default=10, help="bounded audio staging/commit window; max 10")
    pa.add_argument("--yes", action="store_true", help="required acknowledgement that verified media may be committed")
    pa.add_argument("--events-jsonl", help="optional JSON-lines progress/event file for the Veronica GUI")
    pp = sub.add_parser("plan", help="scan, migrate legacy tags to SQLite, and create an immutable plan")
    pp.add_argument("--root", required=True)
    pp.add_argument("--state-dir", required=True)
    pp.add_argument("--config")
    pp.add_argument("--run-date", help="YYYY-MM-DD; defaults to today")
    pst = sub.add_parser("stage", help="convert selected items into staging and verify them; image/video production windows are policy-bound and independently quarantined on commit")
    pst.add_argument("--plan", required=True, help="path to frozen plan JSON")
    pst.add_argument("--state-dir", required=True)
    pst.add_argument("--config")
    pst.add_argument("--max-images", type=int, default=5)
    pst.add_argument("--max-videos", type=int, default=2)
    pst.add_argument("--max-audio", type=int, default=0)
    pst.add_argument("--sample-strategy", choices=["diverse","first"], default="diverse")
    pst.add_argument("--require-personal-tag-sample", action="store_true", help="also run a diagnostic byte-identical staging copy of one live personally tagged media file and verify its Finder tags")
    pc = sub.add_parser("commit", help="commit exactly one verified staged image; original is quarantined")
    pc.add_argument("--staging-id", required=True)
    pc.add_argument("--state-dir", required=True)
    pc.add_argument("--config")
    pc.add_argument("--relpath", required=True, help="exact staged relpath to commit")
    pc.add_argument("--yes", action="store_true", help="required explicit acknowledgement")
    pca = sub.add_parser("commit-audio", help="commit exactly one policy-matched verified staged audio file; original is quarantined")
    pca.add_argument("--staging-id", required=True)
    pca.add_argument("--state-dir", required=True)
    pca.add_argument("--config")
    pca.add_argument("--relpath", required=True, help="exact original audio relpath from the frozen plan")
    pca.add_argument("--yes", action="store_true", help="required explicit acknowledgement")

    pcab = sub.add_parser("commit-audio-batch", help="commit up to 10 policy-matched verified staged audio files; each original is quarantined independently")
    pcab.add_argument("--staging-id", required=True)
    pcab.add_argument("--state-dir", required=True)
    pcab.add_argument("--config")
    pcab.add_argument("--max-items", type=int, default=10)
    pcab.add_argument("--relpath", action="append", help="optional exact original audio relpath; repeat to choose explicit files")
    pcab.add_argument("--yes", action="store_true", help="required explicit acknowledgement")

    pcv = sub.add_parser("commit-video", help="commit exactly one policy-matched verified staged video; original is quarantined and .mov/.m4v becomes .mp4")
    pcv.add_argument("--staging-id", required=True)
    pcv.add_argument("--state-dir", required=True)
    pcv.add_argument("--config")
    pcv.add_argument("--relpath", required=True, help="exact original video relpath from the frozen plan")
    pcv.add_argument("--yes", action="store_true", help="required explicit acknowledgement")
    pcvb = sub.add_parser("commit-video-batch", help="commit up to 25 policy-matched verified staged videos; each original is quarantined independently")
    pcvb.add_argument("--staging-id", required=True)
    pcvb.add_argument("--state-dir", required=True)
    pcvb.add_argument("--config")
    pcvb.add_argument("--max-items", type=int, default=10)
    pcvb.add_argument("--relpath", action="append", help="optional exact original video relpath; repeat to choose explicit files")
    pcvb.add_argument("--yes", action="store_true", help="required explicit acknowledgement")
    pcb = sub.add_parser("commit-batch", help="commit up to 250 verified staged images; each original is quarantined independently and reruns skip completed items")
    pcb.add_argument("--staging-id", required=True)
    pcb.add_argument("--state-dir", required=True)
    pcb.add_argument("--config")
    pcb.add_argument("--max-items", type=int, default=25)
    pcb.add_argument("--relpath", action="append", help="optional exact staged relpath; repeat to choose explicit files")
    pcb.add_argument("--yes", action="store_true", help="required explicit acknowledgement")
    pcr = sub.add_parser("commit-rename", help="commit exactly one canonical filename rename with quarantine and rollback support")
    pcr.add_argument("--plan", required=True, help="path to frozen plan JSON")
    pcr.add_argument("--state-dir", required=True)
    pcr.add_argument("--relpath", required=True, help="exact original relpath from the frozen plan")
    pcr.add_argument("--yes", action="store_true", help="required explicit acknowledgement")
    prb = sub.add_parser("rollback", help="restore the quarantined original for one committed item")
    prb.add_argument("--commit-id", required=True)
    prb.add_argument("--state-dir", required=True)
    prb.add_argument("--yes", action="store_true", help="required explicit acknowledgement")
    prr = sub.add_parser("resolve-review", help="record a guarded durable human resolution for one immutable-plan REVIEW item; never modifies media")
    prr.add_argument("--plan", required=True, help="path to frozen plan JSON containing the REVIEW item")
    prr.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    prr.add_argument("--relpath", required=True, help="exact REVIEW relpath from the frozen plan")
    prr.add_argument("--resolution", choices=["KEEP_AS_IS", "PROCESS_NORMALLY"], required=True)
    prr.add_argument("--note", help="optional human rationale stored in SQLite audit history")
    prr.add_argument("--yes", action="store_true", help="required explicit acknowledgement of the durable database decision")
    pfn = sub.add_parser("configure-filenames", help="store Veronica filename-standardization preferences")
    pfn.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pfn.add_argument("--enabled", choices=["true", "false"], required=True)
    pfn.add_argument("--date-format", default="YYYY-MM-DD_")
    pfn.add_argument("--max-bytes", type=int, required=True)

    pmedia = sub.add_parser("configure-media-types", help="store which media types Veronica may process")
    pmedia.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pmedia.add_argument("--images", choices=["true", "false"], required=True)
    pmedia.add_argument("--videos", choices=["true", "false"], required=True)
    pmedia.add_argument("--audio", choices=["true", "false"], required=True)

    pscope = sub.add_parser("configure-date-scope", help="store Veronica date-scope preferences")
    pscope.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pscope.add_argument("--mode", choices=["all", "within", "outside"], required=True)
    pscope.add_argument("--start", help="inclusive YYYY-MM-DD start date")
    pscope.add_argument("--end", help="inclusive YYYY-MM-DD end date")

    pfolders = sub.add_parser("configure-folders", help="add or remove folders Veronica should scan")
    pfolders.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pfolders.add_argument("--add", action="append", default=[])
    pfolders.add_argument("--remove", action="append", default=[])

    pcfg = sub.add_parser("configure-library", help="store the selected media library in Veronica Application Support")
    pcfg.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pcfg.add_argument("--root", required=True)
    ppf = sub.add_parser("preflight", help="JSON dependency and configuration status for the native app")
    ppf.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    ppf.add_argument("--root")
    pui = sub.add_parser("ui-snapshot", help="read-only JSON summary for the native Veronica app")
    pui.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    pui.add_argument("--root", help="optional media library override")
    pui.add_argument("--recent-limit", type=int, default=50)
    ps = sub.add_parser("status")
    ps.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    prs = sub.add_parser("run-status", help="show unified image/video progress, staging backlog, review counts, and savings")
    prs.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    prs.add_argument("--plan")
    pnb = sub.add_parser("next-batch", help="stage the next production window; refuses overlap with uncommitted verified outputs by default")
    pnb.add_argument("--plan", required=True)
    pnb.add_argument("--state-dir", required=True)
    pnb.add_argument("--config")
    pnb.add_argument("--media", choices=["image","video","audio"], required=True)
    pnb.add_argument("--count", type=int, required=True)
    pnb.add_argument("--allow-overlap", action="store_true", help="deliberately allow duplicate staging while older verified outputs remain uncommitted")
    pcs = sub.add_parser("cleanup-superseded", help="dry-run/remove staging directories with no uncommitted verified image/video outputs; never deletes quarantine")
    pcs.add_argument("--state-dir", required=True)
    pcs.add_argument("--plan")
    pcs.add_argument("--apply", action="store_true")
    pcl = sub.add_parser("cleanup", help="conservatively remove one fully consumed staging directory; never deletes quarantine")
    pcl.add_argument("--state-dir", required=True)
    pcl.add_argument("--staging-id", required=True)
    pcl.add_argument("--apply", action="store_true")
    args = p.parse_args()
    if args.cmd == "doctor": return cmd_doctor()
    if args.cmd == "migrate-state": return cmd_migrate_state(args)
    if args.cmd == "annual-all": return cmd_annual_all(args)
    if args.cmd == "annual": return cmd_annual(args)
    if args.cmd == "plan": return cmd_plan(args)
    if args.cmd == "stage": return cmd_stage(args)
    if args.cmd == "commit": return cmd_commit(args)
    if args.cmd == "commit-audio": return cmd_commit_audio(args)
    if args.cmd == "commit-audio-batch": return cmd_commit_audio_batch(args)
    if args.cmd == "commit-video": return cmd_commit_video(args)
    if args.cmd == "commit-video-batch": return cmd_commit_video_batch(args)
    if args.cmd == "commit-batch": return cmd_commit_batch(args)
    if args.cmd == "commit-rename": return cmd_commit_rename(args)
    if args.cmd == "rollback": return cmd_rollback(args)
    if args.cmd == "resolve-review": return cmd_resolve_review(args)
    if args.cmd == "configure-filenames": return cmd_configure_filenames(args)
    if args.cmd == "configure-media-types": return cmd_configure_media_types(args)
    if args.cmd == "configure-date-scope": return cmd_configure_date_scope(args)
    if args.cmd == "configure-folders": return cmd_configure_folders(args)
    if args.cmd == "configure-library": return cmd_configure_library(args)
    if args.cmd == "preflight": return cmd_preflight(args)
    if args.cmd == "ui-snapshot": return cmd_ui_snapshot(args)
    if args.cmd == "status": return cmd_status(args)
    if args.cmd == "run-status": return cmd_run_status(args)
    if args.cmd == "next-batch": return cmd_next_batch(args)
    if args.cmd == "cleanup-superseded": return cmd_cleanup_superseded(args)
    if args.cmd == "cleanup": return cmd_cleanup(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
