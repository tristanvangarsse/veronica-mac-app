<div align="center">

<img src="docs/assets/veronica-icon.jpg" width="120" alt="Veronica"/>

# Veronica

### Take care of your media library.

A native macOS app for maintaining media libraries safely.

Veronica scans the folders you choose, plans maintenance before changing anything, verifies replacements before committing them, and stops for human review when it cannot make a safe decision automatically.

**Local-first · Native macOS · Safety-focused · Open source**

</div>

---

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="900" alt="Veronica Dashboard"/>
</p>

## What is Veronica?

Veronica is a macOS utility for maintaining media libraries without blindly rewriting them.

You choose the folders Veronica is allowed to scan. It examines the media inside them, creates a maintenance plan, stages proposed replacements, verifies the results, and only then commits safe changes.

When Veronica cannot make a decision confidently, it stops and asks you instead.

## What Veronica does

- Scans one or more folders you choose
- Plans maintenance before changing files
- Verifies proposed replacements before committing them
- Stops instead of guessing when a file needs review
- Starts a fresh scan session at each launch; replaced originals go to the Mac Trash
- Tracks space saved across completed work
- Supports configurable date scopes
- Can standardize media filenames
- Keeps diagnostics and maintenance data local to your Mac

## How it works

```text
Scan
  ↓
Plan
  ↓
Stage
  ↓
Verify
  ↓
Commit
```

If something needs human judgment:

```text
Scan → Plan → Review → Your decision
```

The guiding rule is simple:

> If Veronica cannot verify that an automatic change is safe, it does not silently commit it.

## Folder settings and presets

Each added folder has an independent processing recipe. Use the settings button beside a folder to adjust media extensions, image export/size/quality, video and audio targets, date scope, filename rules and skipped subfolders. Saving a recipe requires fresh analysis before old staged work can be used. Existing history and recovery records are retained.

App-wide Settings contains reusable presets, the default preset for new folders, and support tools. The built-in presets are **Balanced** (20 MP, JPEG quality70), **Smaller files** (10 MP, quality70) and **Images only**. You can create, duplicate, edit and delete custom presets, or save a folder's recipe as a preset. Presets are copied when applied: editing a preset or changing the default leaves existing folders unchanged.

Folder names never choose a processing policy. Transparent PNGs, GIFs and protected source formats retain their safety rules. Skipped subfolder names start empty and are editable in each recipe. The former automatically filled list is cleared when loading an older recipe; custom exclusion lists are retained. Media folders cannot overlap one another or Veronica's data/recovery directory. Legacy explicit preferences migrate once; previous app defaults remain available as a preset. Media is not modified by setting changes.

## Main sections

### Dashboard

The Dashboard shows the current state of your media library, including indexed media, committed replacements, space saved, items requiring review, and the latest maintenance plan.

### Activity

Activity shows live progress during a run and a record of what happened during the most recent run.

### Review

Review contains files that require a human decision. You can inspect the file and decide whether to preserve it or allow Veronica to process it using its normal policy.

### History

History is the audit trail of media replacements Veronica has actually committed.

### Settings

Settings controls scan folders, date scope, filename policy, Veronica data, runtime readiness, media tools, and diagnostics.

## Safety model

Veronica is designed around staged and verified maintenance rather than destructive bulk processing.

A normal replacement follows this general path:

1. Discover the source file.
2. Determine whether work is required.
3. Create a proposed output separately.
4. Verify the proposed output.
5. Commit the verified replacement.
6. Move replaced originals to the Mac Trash. Temporary scan and transaction records are discarded on quit.

Files that cannot safely proceed through that process are preserved or sent for review.

## Requirements

Veronica is a native macOS application.

Its maintenance engine also checks for the runtime and media tools it needs. Their availability is shown under **Settings → Runtime & media tools**.

## Build from source

Clone the repository:

```bash
git clone https://github.com/tristanvangarsse/veronica-mac-app.git
cd veronica-mac-app
```

Open the Xcode project:

```bash
open macos/Veronica.xcodeproj
```

Or build from Terminal:

```bash
xcodebuild \
  -project macos/Veronica.xcodeproj \
  -scheme Veronica \
  -configuration Debug \
  build
```

## Contributing

Issues, bug reports, UI improvements, documentation fixes, and focused pull requests are welcome.

For visual changes, a before/after screenshot is helpful.

## License

See [LICENSE](LICENSE).

## Security and release checks

See [Security boundaries and release verification](docs/SECURITY.md) for the supported runtime, restricted media workers, interrupted-operation recovery and the local/public release gates. Run Analyze again after upgrading from a release that used sampled source hashes.

## One current local installation

Build with `bash scripts/build_local_app_macos.sh`. After quitting the installed app, use the exact printed bundle path with:

```sh
.venv/bin/python scripts/install_local_app_macos.py /absolute/path/to/Veronica.app
open "$HOME/Applications/Veronica.app"
```

The installer keeps one current `~/Applications/Veronica.app`, verifies its copy and registers it for launching. The previous installation is retained as a validated ZIP under `~/Library/Application Support/Veronica/Build Archives.noindex`. Add `--tidy-older-copies` once to archive old Applications backups and indexed development apps; running copies are left in place. Source code, folder configuration and media are untouched. Local builds retain their isolated output directories; open the installed copy for everyday use.

### Dates while reviewing files

In Review results, select a supported image, video, or audio file and choose **Add date…** or **Edit date…**. **Save date** writes and verifies the embedded date, preserves the encoded media content and existing filesystem dates, and updates that file’s scan decision. The original goes to Trash. The choice persists inside the file across app launches; it does not create a permanent Veronica file-history database. Other files without an embedded date still need review.

Date editing currently supports JPEG, PNG, WebP, MP4, MOV, M4V, M4A, MP3, WAV, AIFF, and FLAC. Unsupported files remain unchanged.

### Custom settings

Folder and preset editors offer 480p, 720p, 1080p, 4K and a custom maximum video dimension (480–7680 px). Format buttons enable or disable each supported extension. Date styles include compact full-year and day-first choices, plus a custom pattern using YYYY (or YY), MM and DD with filename-safe separators and a live example. Photo recompression below the size limit can be disabled. Minimum saving targets are editable: a verified output must be smaller and save either the selected percentage or the selected number of MB before replacing an original. Significant actions use bright green buttons.

### Permanent change logs

Each Smart cleanup creates one dated, readable `.log` file in `~/Library/Application Support/Veronica/Change Logs/`, covering all folders in that run. Manual date edits and restoring an original each create their own small log. Records are appended immediately after completed photo, video or audio conversions, renames, embedded date edits, restores, and moves of retained originals to the Mac Trash. They include timestamps, original and final paths, before/after sizes, processing settings and file hashes where available. Runs that change nothing still record their start and outcome. Structured copies used to recover interrupted writes are kept in the hidden `.records` subfolder; existing combined logs are preserved as an `Earlier changes` archive.

These logs survive quitting, restarting and deleting temporary session data. They are separate from the diagnostic log, contain local media filenames, and are never used to skip files during later scans. A retry queue remains in the temporary session until records are saved, so a log-writing failure cannot silently erase the change history or undo an already completed file replacement. Open them from **Settings → Support → Show change logs** or **Diagnostics → Show Change Logs**.

### First launch on a Mac without developer tools

Veronica includes Python, Pillow, FFmpeg/ffprobe, HandBrakeCLI, ExifTool and their required non-system libraries. First launch prepares and checks the built-in tools automatically, offline, without administrator access or a separate Homebrew installation. Later launches reuse the completed setup while checking component integrity. If the app bundle is incomplete or a component has changed, Veronica asks for the complete app to be reinstalled and leaves media untouched.

Builds relocate and sign the media tools and their entire native library closure, preserving supplied licenses and source provenance in the bundled `MediaTools` folder. The clean-install regression tests operation with network, Homebrew, local tool locations and source checkout access denied.
