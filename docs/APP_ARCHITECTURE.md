# Veronica native application architecture

## Principle

SwiftUI owns presentation and user interaction. The existing engine remains the only implementation of media planning, verification, conversion, commit, quarantine, rollback, and durable review semantics.

## Runtime layers

```text
SwiftUI
  -> EngineRunner
       -> preferred: Contents/Resources/VeronicaEngine/veronica-engine
       -> development fallback: bundled Engine/veronica.py + Python 3
  -> engine discovers tools on PATH
       -> preferred release path: Contents/Resources/Tools/bin
       -> development fallback: installed tools
  -> ~/Library/Application Support/Veronica
  -> selected user media library
```

The application is deliberately not sandboxed yet because the engine must operate on a user-selected archive and preserve filesystem metadata/xattrs/birthtime. Public distribution should use Developer ID signing/notarization and a deliberate entitlements review rather than enabling sandboxing casually.

## First run

`ui-snapshot` succeeds even when no state database exists. It returns `configured=false`, allowing SwiftUI to present a folder picker instead of an error. `configure-library` writes only Veronica's Application Support settings and does not touch media.

Existing installations remain compatible: if no settings file exists but SQLite contains the historical archive root, that root is used automatically.

An existing database cannot be repointed to a different archive. This prevents historical source identity, quarantine, rollback, and commit records from becoming associated with unrelated files.

## Native screens

- Dashboard: current state and annual action.
- Activity: live JSON-lines engine events.
- Review: unresolved current-plan decisions.
- History: committed replacements.
- Settings: selected library, state location, annual policy, and dependency readiness.

## Release packaging

A public release bundles Veronica's Python engine as a standalone executable produced on macOS with PyInstaller, so users do not need to install Python or Pillow separately. EngineRunner automatically prefers that bundled executable.

Media tools use a deliberate two-tier lookup model. EngineRunner prefers executables bundled under `Contents/Resources/Tools/bin`, then checks conventional Homebrew/local locations (`/opt/homebrew/bin` and `/usr/local/bin`) before the inherited `PATH`. The current supported distribution model therefore allows `ffmpeg`/`ffprobe` and `HandBrakeCLI` to be installed externally, including through Homebrew. The native Settings UI reports missing dependencies and maintenance remains disabled until all required tools are available.

A future fully self-contained release may bundle redistributable macOS builds of FFmpeg/ffprobe and HandBrakeCLI. Such binaries must be genuinely relocatable and their license obligations must be satisfied. The repository's staging script remains intentionally conservative: it can copy local binaries for testing but refuses to call them portable when `otool` exposes external non-system dependencies. Homebrew binaries with absolute `/opt/homebrew/...` dynamic-library dependencies must not be treated as self-contained merely because the executable itself was copied into the app bundle.

Apple Developer ID signing and notarization must occur on macOS with the release maintainer's credentials.
