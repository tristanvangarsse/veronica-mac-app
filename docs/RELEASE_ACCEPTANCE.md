# Download acceptance test

Run this checklist against the exact DMG intended for release. Use generated media, never the only copy of personal files. Record the macOS version, test method, release tag and DMG SHA-256.

## Routine tests on the current desktop

Quit all Veronica copies in your current account. Prepare a temporary profile and an unchanged app copied from the release DMG:

```sh
.venv/bin/python scripts/prepare_desktop_acceptance.py prepare \
  --dmg /absolute/path/to/final-beta.dmg \
  --previous-dmg /absolute/path/to/previous-version.dmg \
  --fixtures /absolute/path/to/generated-media
```

The helper prints a session file and installed app path under `~/Library/Caches/Veronica Release Tests/`. It moves the normal Application Support profile into that private session, saves macOS app preferences, and starts with empty settings. Open the printed app through the native desktop controls and perform the checklist. Add only the copied generated folders printed by the helper. Other apps and installed dependencies stay intact. A second test session is refused until the first is restored.

For the upgrade check, quit Veronica, run `upgrade --session /absolute/path/to/session.json` with the same helper, then reopen the printed app. The final DMG checksum is checked before replacement. The previous app is retained.

**After every test, including a failed or interrupted test:** quit Veronica and restore the normal profile:

```sh
.venv/bin/python scripts/prepare_desktop_acceptance.py restore \
  --session /absolute/path/to/session.json
```

The helper checks the saved settings before restoration and verifies their bytes afterward. Test settings, logs, generated outputs and the previous app remain in the private session for inspection. Do not open the everyday app until restoration succeeds. If a session is interrupted, its path is recorded in `~/Library/Caches/Veronica Release Tests/active-session.json`; repeat the restore command, rather than starting another test.

## Native checklist

- [ ] Download the DMG in a browser and check the release’s checksum.
- [ ] Open the DMG and inspect its app, Applications shortcut and installation instructions.
- [ ] Copy Veronica to a separate installed location; eject the DMG. The desktop helper does this automatically.
- [ ] Record the actual Gatekeeper message. The user performs any required authentication or “Open Anyway” approval.
- [ ] Open the installed app. First-run preparation completes without installing Homebrew, Python or media tools.
- [ ] Verify the account starts with no folders or inherited personal preferences.
- [ ] Add two test folders and give them different settings; save, close and reopen those settings.
- [ ] Exercise presets/defaults. Existing folders retain their own settings.
- [ ] Scan; cancel a scan and confirm the test sources are unchanged. Rescan successfully.
- [ ] Review every planned change, including an image resize, video conversion, audio conversion, renaming and a missing-date review.
- [ ] Set a missing embedded date manually; verify the result.
- [ ] Run Smart cleanup, verify real output sizes/formats/dimensions and check excluded files stay unchanged.
- [ ] Confirm original copies arrive in this account’s Trash and match their original hashes. Keep them recoverable; never empty the user's Trash.
- [ ] Inspect the dated change log through Settings → Support.
- [ ] Quit and reopen. Preferences persist and scan records start fresh.
- [ ] Replace an earlier installed version with the beta. Preferences and logs survive; a new scan uses the new settings.
- [ ] Launch offline after first setup.
- [ ] Verify the app was not started from the disk image or the developer’s build directory.

## Dependency and first-download coverage

Run `tests/test_clean_install.py --engine /absolute/path/to/VeronicaEngine/veronica-engine` against the final DMG. It relocates the runtime, denies developer-tool paths and networking for helpers, performs real conversions, and verifies safe refusal when a bundled component is missing. This replaces uninstalling the developer's dependencies.

The temporary profile covers fresh preferences, native workflows and upgrades on the current desktop. It does not reproduce every aspect of a separate login or a downloaded app's Gatekeeper approval. Record those separately: occasionally use a standard account or another Mac to download the exact release, install it, and complete any app-specific approval personally. Routine changes do not require repeated account switching. A separate account still shares system software, so keep the dependency-denial test in both workflows.

Publish an acceptance report distinguishing directly observed native checks, tester reports, returned-file verification and automated processing checks. Test another Mac before making broader compatibility claims.
