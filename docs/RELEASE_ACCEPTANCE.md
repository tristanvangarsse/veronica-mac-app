# Download acceptance test

Run this checklist against the exact DMG intended for release, from a standard macOS account that has never opened Veronica. Use generated media or copies, never the only copy of personal files. Record the macOS version, account type, release tag and DMG SHA-256.

- [ ] Download the DMG in a browser and check the release’s checksum.
- [ ] Open the DMG and inspect its app, Applications shortcut and installation instructions.
- [ ] Copy Veronica to the test account’s own `~/Applications` folder; eject the DMG.
- [ ] Record the actual Gatekeeper message. The user performs any required authentication or “Open Anyway” approval.
- [ ] Open the installed app. First-run preparation completes without installing Homebrew, Python or media tools.
- [ ] Verify the account starts with no folders or inherited personal preferences.
- [ ] Add two test folders and give them different settings; save, close and reopen those settings.
- [ ] Exercise presets/defaults. Existing folders retain their own settings.
- [ ] Scan; cancel a scan and confirm the test sources are unchanged. Rescan successfully.
- [ ] Review every planned change, including an image resize, video conversion, audio conversion, renaming and a missing-date review.
- [ ] Set a missing embedded date manually; verify the result.
- [ ] Run Smart cleanup, verify real output sizes/formats/dimensions and check excluded files stay unchanged.
- [ ] Confirm original copies arrive in this account’s Trash and can be recovered.
- [ ] Inspect the dated change log through Settings → Support.
- [ ] Quit and reopen. Preferences persist and scan records start fresh.
- [ ] Replace an earlier installed version with the beta. Preferences and logs survive; a new scan uses the new settings.
- [ ] Launch offline after first setup.
- [ ] Verify the app was not started from the disk image or the developer’s build directory.

Publish an acceptance report distinguishing native account checks, automated processing checks, and any remaining untested cases. A second account shares the machine’s system software; separately retain the clean-dependency simulation and test another Mac before making broader compatibility claims.
