# Veronica native application architecture

## Principle

SwiftUI owns presentation, user interaction and native Mac Trash delivery. The engine owns media planning, verification, conversion and crash-safe file transactions. The desktop app keeps no file catalogue or review decisions between launches.

## Runtime layers

```text
SwiftUI
  -> EngineRunner
       -> preferred: Contents/Resources/VeronicaEngine/veronica-engine
       -> Debug only: bundled Engine/veronica.py + supported Python
       -> restricted image worker / bounded native media workers
  -> engine verifies approved media-tool and library digests
       -> preferred release path: Contents/Resources/Tools/bin
       -> approved external dependencies in fixed locations
  -> ~/Library/Application Support/Veronica
  -> selected user media library
```

The coordinator operates on user-selected archives and preserves filesystem metadata/xattrs/birthtime. Media decoders execute in restricted worker processes with explicit file access, private scratch directories, resource limits and no internet access. The coordinator remains outside App Sandbox. See [Security boundaries](SECURITY.md) for guarantees, limits and release gates.

## First run

`ui-snapshot` succeeds even when no state database exists. It returns `configured=false`, allowing SwiftUI to present a folder picker instead of an error. `configure-library` writes only Veronica's Application Support settings and does not touch media.

Existing installations remain compatible: if no settings file exists but SQLite contains the historical archive root, that root is used automatically.

An existing database cannot be repointed to a different archive. This prevents historical source identity, quarantine, rollback, and commit records from becoming associated with unrelated files.

## Native screens

The main window starts compact, with a folder list and independent settings on each row. Adding or removing folders updates configuration without scanning. The green **Scan folders** button explicitly starts a read-only scan; results appear in a compact summary with **Review results** and **Smart cleanup**.

During scanning, **Cancel** (or Escape) cancels the scan task and stops the engine. The window stays in its cancelling state until the engine exits, then returns to the folder list with a cancellation message. Incomplete results never authorize review or cleanup. Folder choices and recipes stay saved, and a fresh scan can start immediately.

**Review results** expands the same window into a searchable, paginated file browser. It includes every scanned plan item, with filters for ready changes, decisions and unchanged files. Selecting a file shows its preview, original size, destination and the conversion settings from the verified frozen plan. Savings are measured after conversion rather than estimated in the scan summary. Changed recipes and replaced scan IDs invalidate review pages.

**Smart cleanup** confirms the planned scope, verifies replacements and moves replaced originals to the Mac Trash. There is no History screen or built-in undo library. App-wide preferences use the standard **Veronica → Settings…** menu and Command-comma; folder-specific settings remain on each folder. Native macOS notification delivery and permission prompts are removed, and launch clears requests left by older versions.

Input decode errors are isolated as `SOURCE_UNREADABLE` only after reconfirming the source matches the frozen scan. Those originals remain unchanged and are skipped for that exact plan, allowing verified files and later windows to continue. Output, metadata, identity and other verification failures still stop the staging window. Completion shows actual optimized/renamed counts and byte savings from committed transactions; stopped and zero-saving runs are labelled explicitly. Skipped inputs remain visible in cleanup details and file review.

## Desktop session lifetime

Only settings and folder recipes persist in the normal preferences tree. EngineRunner creates a unique, privately leased `Sessions.noindex/<UUID>` directory for each launch, passes it explicitly to scan/snapshot/cleanup commands, and copies preferences into it without importing old file records. Frozen plans, staging, review decisions and SQLite transaction data are temporary working data within that session. The app no longer loads or writes a UI snapshot cache.

After cleanup, `desktop-session` reconciles transactions and verifies original identities before exposing folders to the native `FileManager.trashItem` API. A failed Trash operation retains all remaining originals and scratch records. On quit the app cancels running workers, reconciles transactions, delivers remaining originals to Trash and removes the session. After an abnormal exit, the next launch finishes that disposal before starting fresh; a live lease prevents another running app's session from being collected. Uncertain recovery identities retain the session and report an error. Database-only archival history is never created by the desktop path.

Existing pre-session databases, staging and recovery originals are left intact for compatibility and safety. The legacy command-line workflow retains its historical commands and transaction tests; it is separate from the desktop's session-only lifecycle.

## Settings interaction

Folder settings use Photos, Video, Audio and Files & dates panes. Each media pane has an explicit on/off switch; controls for that category appear when it is on. Choosing a preset replaces only the editable draft, even after manual edits. Save changes persists and verifies the complete folder recipe before closing; Cancel discards the draft. Numeric fields hide duplicate native form labels and validate their values before saving.

App Settings has Defaults, Presets and Support tabs. Customizing a built-in preset creates an editable custom copy. Custom defaults are saved and selected for new folders in the same user action. Creating, editing or deleting presets leaves existing folder copies unchanged. Technical details and local logging are under Support > Advanced.

The main app's icon and name occupy the centered native title-bar toolbar alongside the window controls; the review Summary action also uses that toolbar.

## Folder recipes and presets

The date authority is the metadata embedded inside each file: EXIF capture dates (with digitized/creation metadata as embedded fallbacks), embedded PNG/XMP dates, and video/audio creation or recording dates. Filenames, containing folder years and Mac filesystem dates never override or substitute for an embedded date. Disagreements no longer create date-conflict review items. Missing or invalid embedded dates produce `embedded_date_missing` and remain unchanged for review in every date-range mode, including All dates; normal-processing approval cannot bypass that requirement. Frozen plans from the previous date-evidence policy require a fresh scan.

Image conversion retains embedded date metadata. PNG text dates are carried into JPEG as standard XMP, preserving existing XMP content; PNG outputs retain their date text and XMP. Independent verification rejects an image, video or audio replacement if its usable embedded calendar date changes or disappears.

Each configured root owns an immutable-by-default copy of its recipe in its existing isolated state. New folders receive the current default preset once; preparing or analyzing them never overwrites their preferences from the app defaults. Historical SQLite root/state identities remain intact. Legacy explicit recipes migrate without discarding the original flat preferences, and the former app defaults are retained as a custom preset.

A recipe contains media/extension choices and excluded directory names, image/video/audio parameters, date scope and filename policy. No personal top-level folder name selects a conversion or date policy. Generic excluded subfolder names are visible and editable; protected source formats retain their stronger safety boundary.

The snapshot exposes folder recipes, preset catalog and the default preset ID. A settings mutation validates and writes the whole recipe atomically under the state/library locks. Every plan binds a normalized recipe digest and frozen processing configuration. Settings changes hide stale previews and reject old stage/commit/review operations until fresh analysis; preset/default metadata changes alone leave existing folder recipes and valid plans unchanged. Preset application copies the values rather than creating a live inheritance relationship.

Configured roots must not overlap each other or Veronica's data directory, including canonical path aliases, so recovery originals can never become scan input. UI edits are disabled during analysis/optimization; backend locks also enforce this boundary for independent processes.

## Release packaging

A public release bundles Veronica's Python engine as a standalone executable produced on macOS with PyInstaller, so users do not need to install Python or Pillow separately. Production EngineRunner requires that executable. The release gate compares source hashes, versions and the actual executable contract; Debug uses the supported development Python environment.

The video preset is bundled inside PyInstaller's `_internal` data directory, where the frozen coordinator resolves it. The release gate checks that exact runtime path and digest, and the smart-cleanup regression exercises real video conversion through both source and packaged engines.

Media tools are fully bundled. The build copies FFmpeg, ffprobe and HandBrakeCLI with the complete transitive closure of their non-system dynamic libraries, rewrites load commands to bundle-relative paths, removes external search paths and signs each file. The frozen manifest pins the final tool and library digests. Production never falls back to Homebrew, PATH or another locally installed copy. The build retains supplied license files, package receipts, source formulae and exact binary provenance alongside the tools.

On first launch, `prepare-runtime` verifies every shipped component and runs offline startup checks for video, audio and date editing. It writes a private, version-bound setup receipt only after every check succeeds. Later launches verify integrity again and reuse the successful setup for the same runtime. The UI shows “Getting Veronica ready…” during preparation. Users do not install Python, Pillow, FFmpeg, HandBrake, ExifTool or Homebrew; the application supplies its own non-system components. macOS supplies system utilities and Perl. A missing or altered component stops preparation and requests the complete app be reinstalled, without changing media or downloading code.

`tests/test_clean_install.py` relocates the engine, uses an empty home and system-only PATH, and checks startup with Homebrew, local tools, checkout and network access denied. Native media helpers are tested under those restrictions, and actual conversions/date edits run in their production worker sandboxes without developer-library access. It also tests fresh/repeated setup and refusal of missing tools/libraries. This simulates absence of developer dependencies on a supported Mac; operating-system installation and Gatekeeper acceptance remain separate checks.

Apple Developer ID signing and notarization must occur on macOS with the release maintainer's credentials.
