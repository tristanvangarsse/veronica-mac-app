# Try the Veronica beta

The beta is free and open source. It supports Apple Silicon Macs running macOS 26 or later. It is not signed with an Apple Developer ID or notarized by Apple; follow the [installation guide](INSTALL.md) for the first-opening warning. No additional Python or media tools are needed.

## A small first test

1. Download the DMG from [GitHub Releases](https://github.com/tristanvangarsse/veronica-mac-app/releases), install it and eject the disk image.
2. Make a separate copy of a small folder with photos, videos or audio. Add that copy to Veronica.
3. Open the folder's settings and check the formats, size/quality, date range and filename options. Each folder has its own settings.
4. Scan. Scanning leaves your media unchanged. Open Review results and check the explanation for each planned action. Try a file without an embedded date.
5. Run Smart cleanup. Verify that the resulting files open, have the expected dimensions/formats and retain the metadata you care about.
6. Keep the replaced originals in Trash until you have checked the results. Do not empty Trash as part of testing.
7. Quit and reopen. Check your settings, scan again and tell us if work repeats unexpectedly or the results are confusing.

Useful feedback includes installation trouble, unclear review reasons, unexpected filenames, playback or metadata changes, cancellation, recovery, accessibility, performance and anything that makes you hesitate before cleanup. An ordinary screenshot of the interface is helpful only after removing private paths and filenames.

## Send feedback

Open **Settings → Support → Report a problem or share beta feedback** or choose a [GitHub form](https://github.com/tristanvangarsse/veronica-mac-app/issues/new/choose). GitHub requires an account. You can also reply to the Reddit beta post. Include:

- Veronica version **and build number** from Veronica → About Veronica;
- macOS version and Mac chip;
- what you did, what you expected and what happened;
- whether the original is still intact and whether the issue repeats using a disposable copy.

Do not attach private media, full paths, credentials or unreviewed logs. Support can export a diagnostic ZIP that omits media filenames; review its contents yourself before choosing to attach it. Dated change logs contain local media paths and should not be posted publicly unchanged. Veronica does not submit reports or upload media automatically.

## What beta means

Automated checks and local testing reduce risk but cannot guarantee every library, codec, storage device or future macOS release. Use copies for evaluation and keep your own backup. Current published binaries support Apple Silicon/macOS 26; other hardware or system versions need separate testing.

Feedback will guide the next release. There is no paid tier or payment requirement in this beta.
