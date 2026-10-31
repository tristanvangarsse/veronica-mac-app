# Changelog

## 0.16.0 beta 3

- Shows the specific reason a file needs review before its preview, with a matching title in the file list and clear next steps. Combined safety risks are all explained; technical codes remain available in a disclosure.
- Describes missing dates, unreadable or empty files, filename conflicts, unsupported formats, HDR, frame timing, camera metadata and extra tracks without guessing what failed.
- Keeps converted filename extensions consistent with the output format even when date/name standardization is disabled.
- Releases verified backup copies after a recovered failed write through the normal originals-to-Trash workflow. Changed or unrecognized recovery files still block session disposal.
- Adds a direct feedback link in Settings → Support and structured GitHub forms for bug reports and beta feedback.
- Builds support both current and older Homebrew ExifTool launcher layouts while retaining strict checks against external runtime paths.
- Source-mode date editing and first-run checks also resolve the actual Perl program directly in both layouts, keeping shell execution disabled.
- Retains independent folder settings, local processing, recoverable originals, and the existing unsigned beta installation route.
- Sizes the expanded review window using the space below its toolbar, keeping the cleanup footer fully visible.

## 0.13.2 - Native diagnostics workflow

- Adds persistent local logging under `~/Library/Application Support/Veronica/logs/veronica.log` with bounded log rotation.
- Adds Developer Mode for richer local engine diagnostics without changing media policy.
- Adds **Copy Debug Info**, **Export Diagnostics…**, and **Reveal Log in Finder** to Settings and a Diagnostics app menu.
- Diagnostic exports are privacy-sanitized and exclude media files and SQLite database contents.
- Adds `scripts/debug_build_macos.sh` to capture exact Xcode compiler output in `/tmp/veronica-build.log`.
- Logs engine command start/exit/failure information while keeping diagnostics failures non-fatal.
- No conversion, verifier, database, quarantine, rollback, annual-policy, or review behavior changed.

## 0.13.1 - Portable first-run application foundation

- Removes the personal media-root default from the high-level `annual` controller. Annual maintenance now uses the library selected in Veronica settings (or historical SQLite metadata for an upgraded installation).
- Adds a fresh-install `configure-library` command and guarded `settings.json` in `~/Library/Application Support/Veronica`. An existing historical database cannot be silently repointed to another library.
- Makes `ui-snapshot` valid before a database exists, allowing a clean first-launch setup screen instead of an error.
- Adds native first-run **Choose Media Library…** flow and a **Settings** screen for library location, Application Support state, annual policy, and dependency readiness.
- Adds machine-readable runtime/tool preflight data to the native UI.
- Updates `EngineRunner` to prefer a standalone bundled `veronica-engine`, then a private bundled Python runtime, while retaining installed-Python fallback for development builds.
- Adds resource slots and macOS scripts for a standalone PyInstaller engine, bundled media tools, Xcode project generation, and release-readiness checks.
- Adds GitHub Actions CI for Python 3.9 regression tests and a native macOS Swift build.
- Adds third-party distribution notice scaffolding.
- Keeps all conversion, verification, immutable-plan, review, quarantine, rollback, Finder-tag, metadata, VFR, and KEEP_ORIGINAL behavior unchanged.

## 0.12.1

- Fix the macOS XcodeGen project so the bundled Python engine is actually copied into `Veronica.app/Contents/Resources/Engine`.
- No media-processing, database, verification, quarantine, or annual-policy behavior changed.

## 0.12.0 - Human-readable native workflow

- Keeps all media conversion, verification, quarantine, rollback, and review-resolution behavior unchanged.
- Dashboard now presents a clear current-state banner, annual scope, remaining work, recent changes, and a confirmation before starting annual maintenance.
- Activity now reads the engine JSON event stream live while a run is in progress instead of waiting until the process exits.
- Activity events are translated into human-readable planning, staging, verification, KEEP_ORIGINAL, and commit messages.
- Review now explains common review reasons in plain language and can reveal the source file in Finder before a guarded Keep As Is decision.
- History now shows before size, after size, bytes saved, percentage saved, completion date, and Reveal in Finder.
- The read-only UI snapshot now reports current remaining executable work for the latest immutable plan and source/output sizes for recent committed changes.
- Fixes the engine-reported version so the bundled UI snapshot and app release agree on 0.12.0.

## 0.10.0 — Veronica engine foundation

- Introduced the **Veronica** product-facing CLI entry point (`veronica.py`) while keeping the production-proven media engine intact.
- Changed the high-level `annual` default persistent-state location to `~/Library/Application Support/Veronica`.
- Added `migrate-state`, a dry-run-by-default one-time migration from `~/Documents/Media Maintenance`. The applied migration requires a same-filesystem atomic directory rename, runs SQLite `quick_check` before and after, and transactionally rewrites state-internal absolute paths without touching archive paths.
- The default annual command refuses to create a fresh Application Support database when legacy state still exists in Documents, preventing accidental split history.
- Added optional `--events-jsonl` structured progress output for the future native Veronica UI. Existing human-readable Terminal output remains unchanged.
- Added regression coverage for state migration and GUI event streaming. Existing safety/idempotency/VFR/KEEP_ORIGINAL tests continue to pass.
- No image/video conversion policy, verifier, quarantine, rollback, review-resolution, or annual cutoff behavior was weakened or redesigned.

# v0.9.1

- Changes only the high-level `annual` cutoff policy to calendar-year eligibility. A run in year Y now includes media dated through December 31 of Y-2, regardless of the run month/day.
- Examples: 2026-09-22 includes through 2024-12-31 (exclusive planner cutoff 2025-01-01); 2027-01-02 and 2027-02-05 include through 2025-12-31 (exclusive cutoff 2026-01-01).
- Keeps the lower-level `plan` command's existing rolling-date behavior unchanged for compatibility and targeted use.
- Adds integration coverage for September 2026, January 2027, and February 2027 annual runs.
- No conversion, verifier, transaction, quarantine, review-resolution, or KEEP_ORIGINAL behavior changed.

# v0.9.0

- Adds `annual`, the small one-command yearly controller built on the existing immutable plan, staging, verification, bounded commit, quarantine, and reporting primitives.
- `python3 veronica.py annual --yes` defaults to the established personal media root and state directory and derives the annual cutoff from the existing planner using today as the run date.
- Preserves hard internal windows of at most 250 images and 25 videos per batch.
- Refuses to start while live uncommitted verified staging outputs exist.
- Stops before staging if the new immutable plan contains any unresolved `REVIEW` item.
- After staging, commits none of that staging window if any selected result is failed, stale, review-only, or otherwise not commit-ready.
- Stops on any safe commit failure; successful files still retain their existing independent per-file quarantine/rollback transactions.
- Writes a concise annual Markdown report with plan counts, batch results, and committed savings for that annual invocation.
- Does not automate audio conversion because no proven bounded audio commit primitive exists; executable unsupported operations stop for manual action instead of guessing.
- All v0.8.11 VFR/frame-count, KEEP_ORIGINAL, review-resolution, no-autocrop, color-range, Finder-tag, metadata, immutable-plan, quarantine, and rollback safeguards remain unchanged.

# v0.8.11

- Keep suspicious video sources in REVIEW when the declared stream frame count materially disagrees with the decoded presentation-timestamp count, even if the timestamps that are present look CFR-like.
- Adds a regression for the real `2024-06-17_webpage_loading_test.mov` failure shape (118 declared frames vs 103 decoded timestamps), preventing HandBrake retiming from being accepted.
- No verifier, encoder, transaction, or commit-safety checks were weakened.

# v0.8.10

- Restores the documented Python 3.9.6 compatibility by replacing Python 3.10-only `X | None` type-annotation syntax with `Optional[X]`. Runtime behavior and media policies are unchanged.
- Makes the unsupported review-resolution error message version-neutral.

# Changelog

## 0.8.9

- Replaces the old `avg_frame_rate` versus `r_frame_rate` VFR review decision with a conservative two-stage classifier. The cheap summary-rate mismatch remains the trigger for deeper inspection, but final classification now uses decoded presentation timestamps.
- A source with a summary-rate mismatch is considered CFR-like only when at least 99% of positive frame intervals are within +/-5% of the median, the p95/p05 interval spread is at most 1.05x, and there are no duplicate or backwards presentation timestamps.
- Sources outside those bounds remain `video_source_review:variable_frame_rate`; backwards or duplicate timestamps receive explicit review reasons instead of being silently treated as ordinary VFR.
- Frame timing is probed only for videos that trip the cheap summary-rate mismatch, avoiding a frame-by-frame probe for normal videos. Staging repeats the same source-risk check before conversion.
- For executable videos cleared as CFR-like, the immutable plan records the timestamp analysis and classification in `target.source_video` for auditability.
- HandBrake remains on the existing v4 CFR/no-autocrop policy. This release does not weaken the output verifier or automatically convert genuinely timing-variable sources.
- Adds regression coverage for CFR-like false positives, genuine VFR cadence, duplicate PTS, and non-monotonic PTS.

All existing immutable-plan, review-resolution, KEEP_ORIGINAL, quarantine, rollback, no-auto-crop, color-range, Finder-tag, metadata, and verification safeguards remain unchanged.

## 0.8.8

- Adds a separate `review_resolutions` history for durable human decisions; it does not overload conversion `disposition_history` or `KEEP_ORIGINAL`.
- Adds `resolve-review` with an explicit `KEEP_AS_IS` resolution for one immutable-plan `REVIEW` item. The command verifies the live source against the frozen plan before recording anything and never modifies media.
- Future plans emit `SKIP_REVIEW_RESOLVED` only when asset identity, source quick hash/size, and the exact review reason still match. Changed content or a changed review classification returns to `REVIEW`.
- Applies review resolutions after video source-risk classification, so VFR and other derived review reasons cannot be bypassed by an unrelated historical decision.
- Adds regression coverage proving source hash, source size, and review-reason changes invalidate a stored human resolution.

All existing immutable-plan, quarantine, commit, rollback, KEEP_ORIGINAL, no-auto-crop, color-range, Finder-tag, metadata, and verification safeguards remain unchanged.

## 0.8.7

- Fixes durable `KEEP_ORIGINAL` persistence for images and audio; v0.8.6 accidentally hardcoded two persistence/backfill paths to `CONVERT_VIDEO`.
- Backfills existing image/video/audio `KEEP_ORIGINAL` staging results into disposition history when the state database is opened.
- `stage` / `next-batch` now record `KEEP_ORIGINAL` for all conversion media types, guarded by asset identity, source quick hash/size, operation, and policy version.
- Future plans now honor unchanged same-policy `KEEP_ORIGINAL` decisions for images, videos, and audio via `SKIP_KEEP_ORIGINAL`.
- Adds a regression test reproducing the image case (`sketch_002.png`-style negative saving) and verifies source-hash and policy changes invalidate the decision.

All commit, quarantine, rollback, no-auto-crop, color-range, Finder-tag, metadata, and verification safeguards remain unchanged.

## 0.8.6

- Makes `KEEP_ORIGINAL` a durable successful disposition rather than unfinished work.
- Persists video `KEEP_ORIGINAL` decisions against asset identity, source quick hash, source size, operation, and policy version.
- Backfills qualifying `KEEP_ORIGINAL` decisions from existing staging history when the state database is opened by v0.8.6.
- `stage` / `next-batch` now skip unchanged same-policy files already resolved as `KEEP_ORIGINAL`.
- `run-status` now reports `kept-original` separately and excludes those files from `remaining` and modeled remaining savings.
- Future plans emit `SKIP_KEEP_ORIGINAL` when the same unchanged source is encountered under the same policy.
- A changed source hash/size or changed policy deliberately invalidates the old keep-original decision and allows reevaluation.

All existing quarantine, commit, rollback, no-auto-crop, color-range, Finder-tag, metadata, and verification safeguards remain unchanged.

## 0.11.1 - Native Veronica app foundation

- Added the first native macOS SwiftUI application source under `macos/`.
- Added Dashboard, Activity, Review, and History views.
- The app launches the existing Python engine; media policy and commit logic are not duplicated in Swift.
- Activity captures engine output while annual maintenance is running.
- Review supports the existing guarded `KEEP_AS_IS` resolution with confirmation.
- History exposes recent committed files and Finder reveal actions.
- Added read-only `ui-snapshot` JSON for native UI state.
- `status`, `run-status`, and `resolve-review` now default to `~/Library/Application Support/Veronica`.
- Added an engine-bundle synchronization script and regression test.
- Added MIT open-source license while retaining copyright.
