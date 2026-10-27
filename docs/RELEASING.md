# Prepare a GitHub beta

Run this on an Apple Silicon Mac with the supported Xcode, Python, XcodeGen and media build tools. Customers receive the bundled tools and do not install this development environment.

1. Update the engine version, marketing version and build number together. Update dependency pins and their official artifact hashes deliberately.
2. Install the hash-locked development requirements in `.venv`. Run the dependency audit before building; investigate findings rather than suppressing them.
3. Run `bash scripts/build_local_app_macos.sh`. Keep the exact isolated app path printed at the end. Do not replace an earlier running app or reuse its build directory.
4. Run `.venv/bin/python scripts/run_regressions.py` after the frozen engine is built. Check the final source commit with GitHub CI too.
5. Package that exact verified app and collect matching sources into new output directories:

   ```sh
   release_tag=v0.16.0-beta.1
   release_app=/absolute/path/printed/by/the/build/Veronica.app
   release_output=.build/download-candidate
   .venv/bin/python scripts/build_release_assets.py --app "$release_app" --output "$release_output" --tag "$release_tag"
   .venv/bin/python scripts/collect_release_sources.py --engine "$release_app/Contents/Resources/VeronicaEngine/veronica-engine" --output .build/candidate-sources --cache .build/source-archive-cache
   cp THIRD_PARTY.md .build/candidate-sources/VERONICA_THIRD_PARTY.md
   tar -czf "$release_output/Veronica-${release_tag#v}-ThirdPartySources.tar.gz" -C .build/candidate-sources .
   cp docs/INSTALL.md "$release_output/INSTALL.md"
   ```

   Include the full source commit in `release.json`. Recompute `SHA256SUMS.txt` over the final DMG, source archive, installation guide and release metadata. A changed app requires a newly generated DMG and matching sources; do not reuse an earlier candidate's checksum or acceptance result.

6. Mount the final DMG, verify its app signature and runtime manifest, and run `tests/test_clean_install.py --engine` against its contained engine. Check that all app resources can be read by another standard account.
7. Upload only the named release assets to a **draft prerelease** targeting the full source commit. Verify GitHub's recorded asset digests against the local files.
8. Complete [fresh-account acceptance](RELEASE_ACCEPTANCE.md), including a browser download, first-launch warning, generated-media cleanup and an upgrade preserving settings. Record which checks were automated, observed directly or reported by the tester.
9. After CI and acceptance pass, merge the reviewed source, publish the prerelease, and verify the public page and an anonymous download against the checksum. Keep corresponding sources available with the download.

The current beta uses an ad-hoc signature for integrity and has no Apple Developer ID signature or notarization. Tell customers this clearly and link the app-specific Open Anyway procedure in the installation guide. Never disable system-wide security or remove quarantine as the customer installation procedure. `VERONICA_PUBLIC_RELEASE=1` is reserved for a future Developer ID signed, notarized release and requires those checks to pass.

Preserve personal settings, test originals and unrelated working-tree changes throughout the release. Generated fixtures and temporary account test data must not be included in the public assets.
