# Veronica — Development Recovery Journal

Updated: October 10, 2026.

## Project

Repository: /Users/tristan/Developer/veronica-mac-app

Branch: feature/ux-redesign

Native SwiftUI macOS media optimizer.

Preserve original media, quarantine and rollback guarantees,
existing source changes, and user data.

## Workflow

The developer copies one complete Bash block and presses
Command-Shift-Option-R.

The existing automation runs the code and sends a development report
to the current ChatGPT conversation.

Development reports:
~/Desktop/Veronica-Dev-Reports/

Source backups:
~/Desktop/Veronica-Dev-Reports/source-backups/

IMPORTANT: Avoid nested Markdown code fences inside executable
Bash blocks because they may truncate the code extracted by automation.

## UX status

The results screen contains a new "Your next step" card in
macos/Veronica/Sources/ContentView.swift.

It responds to stale analysis, unavailable folders, missing tools,
optimization readiness, review items, and completion.

The Debug build passed after fixing an initial model-type and
string-interpolation error.

Debug application:
 /tmp/veronica-ux-baseline-build/Build/Products/Debug/Veronica.app

Build command:
 xcodebuild -project macos/Veronica.xcodeproj -scheme Veronica -configuration Debug -derivedDataPath /tmp/veronica-ux-baseline-build CODE_SIGNING_ALLOWED=NO build

## Screenshot status

Local screenshot capture works.

An overview helper exists, but has previously captured an older
Release build instead of the current Debug build.

Next priority: capture the current Debug app window reliably,
without including unrelated desktop windows.

## ChatGPT crash

ChatGPT Classic crashed on October 10, 2026 during an automated
delivery attempt involving PNG clipboard paste.

Crash report:
 ChatGPT-2026-10-10-105559.ips

The crash involved CFPasteboard / NSPasteboard operations.

The screenshot paste is a plausible cause, not conclusively proven.

Text-report delivery is working.

Automatic screenshot attachment is disabled by default in:
 tools/send-to-chatgpt.sh

Default:
 VERONICA_AUTO_ATTACH_SCREENSHOT=0

Do not restore clipboard PNG paste without a controlled safety test.

## ChatGPT UI safety

Accessibility inspection found:
 Attach content
 Upload file
 Upload photo

One test activated Attach content and Upload file, but no file picker
was conclusively identified.

Other tests intermittently failed to locate the attachment button.

A Command-O experiment opened a second ChatGPT window, identified
by the developer as a temporary chat.

DO NOT:
 - Send Command-O to ChatGPT.
 - Open or switch ChatGPT conversations.
 - Create temporary chats.
 - Use unverified ChatGPT keyboard shortcuts.
 - Re-enable PNG clipboard attachment casually.
 - Modify the working report sender without a backup.

## Source-control safety

Preserve all uncommitted changes.

Never run git reset --hard or git clean -fd.

Create timestamped backups before modifying existing files.

## Next priorities

1. Verify this recovery journal.
2. Improve window-specific capture of the current Debug app.
3. Continue results-screen UX refinement.
4. Test screenshot delivery separately and conservatively.
5. Record every experiment before executing it.

## Recovery procedure

After a ChatGPT crash or conversation reset:

1. Read this file.
2. Read docs/development/SCREENSHOT-EXPERIMENTS.md.
3. Inspect the latest development report.
4. Run git status --short --branch.
5. Resume with one complete Bash block per step.
6. Never assume an image was attached merely because its path
   appears in a report.
