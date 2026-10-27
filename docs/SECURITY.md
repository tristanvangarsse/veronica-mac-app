# Security boundaries and release verification

Veronica 0.14 uses full-file identities, registered immutable plans, non-overwriting file installation, and durable recovery journals. Old plans without full-file identities must be recreated with Analyze. Older interrupted commits without a trustworthy recovery record stop maintenance and retain their files for manual review.

## File operations

Every modifying operation locks both its state and library. The per-user lock registry has stable, normalized keys so migration, case aliases and different state folders cannot bypass coordination. State migration locks both endpoints. Locks do not coordinate unrelated editors: Veronica also checks source content before staging, before replacement, after quarantine, and before completing a commit.

Relative paths cannot contain parent traversal or resolve through symbolic links. Publishing uses directory descriptors and non-overwriting links; a crash between linking and unlinking leaves recoverable duplicate entries. Quarantine is retained. Recovery restores known originals, retains generated outputs separately, and refuses to overwrite newer or uncertain files. Startup checks each configured folder, not just the top-level settings directory.

New state folders use owner-only access. Diagnostic exports contain structured summaries and omit free-form errors, filenames and raw log contents. Local developer logs may contain private information and should be reviewed before sharing.

## Untrusted media

Image probing, metadata parsing and conversion execute in a separate restricted process. Only approved image decoders are enabled. Source extensions do not authorize other decoder formats. Image workers have CPU, pixel and output limits; media subprocesses have deadlines and bounded stdout/stderr. Timeout or cancellation terminates the worker process group.

On macOS, workers use a deny-by-default Seatbelt profile with explicit source/output files, private scratch storage and read-only runtime/system libraries. Internet connections and unrelated personal files are denied. Apple AudioComponentRegistrar access permits the existing AAC encoder. The coordinator remains outside App Sandbox to preserve existing archive, metadata and migration behavior. Restricting the decoder is an additional boundary, not protection against a malicious account owner or a compromised operating system. The profile relies on Apple's system sandbox interface: unsupported environments fail closed, and release acceptance must test each supported macOS version.

The production app requires its frozen engine and does not silently fall back to an external Python. Process environments are allowlisted. Production media executables and their complete non-system library closure are bundled, use only bundle-relative load paths, and must match the release manifest. Production never falls back to installed Homebrew/local tools. First-run preparation starts the built-in components offline and records success only after their startup checks pass. Updating a dependency requires rebuilding and approving a new release. These checks do not replace review of native dependency vulnerabilities or provenance.

## Development and release

Use Python 3.14 and the hash-locked environment:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements/development.txt
bash scripts/sync_engine_bundle.sh
bash scripts/build_standalone_engine_macos.sh
.venv/bin/python scripts/run_regressions.py
bash scripts/build_local_app_macos.sh
```

Local app builds write to a unique `.build/local-release.XXXXXXXX/release` directory and print the verified app and DMG paths. Existing app bundles are retained so rebuilding cannot remove the executable or resources of a running copy.

`run_regressions.py --source-only` is available during source iteration. It explicitly defers frozen-engine tests; a release must pass those tests too. The local release build regenerates the frozen engine, compares its source hashes/version/snapshot contract, collects supplied runtime notices, builds and signs the app locally, and checks strict signatures. The actual native runtime/tool minimum macOS version determines the local package's deployment target. The October 2026 build on this machine requires macOS 26; the project's baseline does not establish compatibility for an arbitrary local binary dependency.

Local ad-hoc signing establishes bundle integrity for local testing. Public distribution requires a Developer ID identity, notarization, stapling, clean-machine acceptance, and dependency/license review. `VERONICA_PUBLIC_RELEASE=1 scripts/check_release_readiness_macos.sh <app>` fails unless the public signing and notarization checks pass. No private signing key or notary credential belongs in the repository.

CI pins action revisions, uses read-only repository permissions, installs hash-locked dependencies, runs dependency advisory checks, and tests the actual frozen engine. Native dependencies are recorded by digest; their complete vulnerability status is not inferred from Python's advisory scan.

## Developer helpers

Legacy clipboard launchers now support only named local checks. They never execute clipboard text, send reports to another application, copy raw reports to the clipboard, or capture a desktop automatically. `tools/send-to-chatgpt.sh` retains a local report and prints its location; its compatibility name does not imply delivery. Historical backup files are not supported entry points and are excluded from builds.
