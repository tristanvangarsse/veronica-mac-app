# Veronica — Screenshot Automation Experiments

Updated: October 10, 2026.

## Safety rules

Document experiments before executing them.

Keep local screenshot capture separate from ChatGPT attachment.

Do not open or switch ChatGPT conversations.

Do not use unverified ChatGPT shortcuts.

Do not paste PNG data through the clipboard until the crash
mechanism is understood and an explicit test is approved.

Preserve the working text-report delivery.

## Experiment 1 — Clipboard PNG paste

Result: FAILED / DISABLED.

Automated text insertion succeeded.

PNG clipboard paste was attempted.

ChatGPT subsequently crashed with EXC_BAD_ACCESS in a
CFPasteboard / NSPasteboard code path.

Crash report:
 ChatGPT-2026-10-10-105559.ips

Causation is suspected, not proven.

Mitigation:
 VERONICA_AUTO_ATTACH_SCREENSHOT=0

## Experiment 2 — Attachment menu

Result: PARTIAL SUCCESS.

Accessibility inspection identified the Attach content button.

The menu exposed Upload file and Upload photo.

The menu was opened and inspected successfully.

## Experiment 3 — Native file picker

Result: INCONCLUSIVE.

One test found Attach content and Upload file and activated both.

No native file picker was positively identified.

Other attempts failed to locate the attachment button.

No screenshot was attached.

## Experiment 4 — Command-O

Result: PROHIBITED FROM REPEAT.

Command-O increased ChatGPT's window count from one to two.

The developer identified the additional window as a temporary chat.

Do not repeat this experiment or navigate ChatGPT conversations.

## Experiment 5 — Recovery journal creation

Result: INCOMPLETE / REPAIR REQUIRED.

The initial script was truncated inside a nested Markdown code fence.

The automated report exited successfully but did not contain the
expected journal verification output.

Repair strategy:
 Use Bash heredocs without nested Markdown code fences.
 Back up existing journal files before replacement.
 Verify contents explicitly.

## Current configuration

Automated text reports: WORKING.

Local screenshots: AVAILABLE.

Automatic screenshot attachment: DISABLED.

PNG clipboard paste: DISABLED BY DEFAULT.

ChatGPT navigation experiments: PROHIBITED.

## Next proposed experiment

Objective:
 Capture a screenshot of the current Veronica Debug app window.

Scope:
 Local macOS screenshot capture only.

Safety:
 No ChatGPT UI automation.
 No clipboard image manipulation.
 No message submission.
 No modifications to the report sender.

Success criteria:
 Screenshot file exists, has nonzero size, and represents the
 current Debug app rather than the older Release app.

Rollback:
 Delete only the newly created test screenshot if necessary.

Afterward:
 Record actual results here before any attachment experiment.

## Experiment 6 — Window-specific capture (20261010-111643)

Result: FAILED.

Attempted to identify Veronica's on-screen window and capture it
using the native macOS window capture API.

Capture directory:
/Users/tristan/Desktop/Veronica-Dev-Reports/window-capture-20261010-111643

No ChatGPT UI interaction occurred.
No clipboard image paste occurred.

Next step: inspect the window-discovery failure before retrying.

## Experiment 7 — Explicit Debug launch and window capture (20261010-111720)

Objective:
Launch the existing Veronica Debug build and capture its actual
application window.

Application:
/tmp/veronica-ux-baseline-build/Build/Products/Debug/Veronica.app

Screenshot destination:
/Users/tristan/Desktop/Veronica-Dev-Reports/debug-window-20261010-111720/veronica-debug-window.png

Safety:
- No ChatGPT UI interaction.
- No clipboard manipulation.
- No message submission.
- No source-code modifications.
- No automation-script modifications.
- Preserve all existing Git changes.

Expected result:
A nonempty PNG containing only the current Debug application window.

Status:
STARTED. Final result follows below.

Experiment 7 result:
CAPTURE SUCCEEDED.

Screenshot:
/Users/tristan/Desktop/Veronica-Dev-Reports/debug-window-20261010-111720/veronica-debug-window.png

The capture command verified that the selected window belonged
to the expected Debug executable.

Visual inspection is still required.

## Experiment 8 — Native attachment safety precheck (20261010-112005)

Objective:
Determine whether ChatGPT's current window configuration permits
a controlled native-file attachment experiment.

Known facts:
- Debug-window screenshot capture succeeded.
- The report sender works with text-only messages.
- Clipboard PNG paste is disabled due to a suspected crash.
- A previous Command-O test opened an unwanted temporary chat.
- Attachment-button accessibility lookup has been intermittent.

Safety requirements:
- Do not navigate between conversations.
- Do not create new ChatGPT windows.
- Do not use Command-O.
- Do not use the PNG clipboard.
- Do not submit a message.
- Do not modify the working report sender.
- Abort future attachment tests if the window state is ambiguous.

This precheck:
- Records the experiment plan.
- Reads ChatGPT's current window count and metadata.
- Does not click, type, activate, or navigate ChatGPT.

Status:
STARTED. Results follow below.

Experiment 8 result:
Read-only window inspection completed successfully.

The automated report contains the window count and metadata.

No attachment was attempted.

## Experiment 9 — Native attachment picker (20261010-112045)

Objective:
Determine whether ChatGPT's Attach content menu can open
a native Upload file picker without using the clipboard.

Preconditions:
- Exactly one ChatGPT window.
- Empty message composer.
- No existing modal sheet.

Permitted interaction:
- Press the existing Attach content accessibility button.
- Press Upload file if the menu item is clearly identified.
- Inspect the resulting UI.
- Press Cancel if a native file picker is found.

Prohibited:
- No Command-O or other ChatGPT keyboard shortcuts.
- No conversation navigation.
- No new chat windows.
- No file selection.
- No image clipboard paste.
- No message submission.
- No modifications to existing automation.

Status:
STARTED. Result follows below.

Experiment 9 result:
The accessibility test failed or aborted.

No file was intentionally selected or submitted.

Do not retry until the report has been inspected.

## Experiment 10 — Read-only composer diagnostic (20261010-112109)

Objective:
Determine why Experiment 9 could not uniquely identify the
ChatGPT message composer.

Method:
Inspect accessibility metadata for text-entry elements in the
existing ChatGPT window.

Safety:
No clicks, keystrokes, clipboard changes, window activation,
conversation navigation, or message submission.

Privacy:
Do not print the contents of any text field.

Status:
STARTED. Result follows below.

Experiment 10 result:
Read-only accessibility inspection completed.

Review the automated report for text-entry counts and metadata.

No ChatGPT UI interaction occurred.

## Experiment 11 — Attachment pause and capture integration (20261010-112231)

Decision:
Pause native ChatGPT attachment experiments.

Reason:
Experiment 10 found zero accessible text-entry elements despite
earlier successful composer access and working text delivery.

Current safe configuration:
- Automatic text-report delivery remains enabled.
- Automatic screenshot attachment remains disabled.
- PNG clipboard paste remains disabled.
- No ChatGPT conversation navigation is permitted.

Next objective:
Improve screenshot capture for the current Debug build.

This step:
Read-only inspection of existing capture integration.

Status:
INSPECTION STARTED.

## Experiment 12 — Debug-first overview capture (20261010-112252)

Objective:
Prefer the current Debug application for navigation overview
screenshots, with the existing Release application as fallback.

Planned modification:
Update only the application-selection section of the overview helper.

Safety:
- Preserve the existing capture workflow.
- Back up the helper before modification.
- Validate Bash syntax.
- Do not modify the report sender.
- Do not interact with ChatGPT.
- Do not enable clipboard image paste.
- Preserve all uncommitted source changes.

Status:
STARTED.

Experiment 12 result:
Patch applied and Bash syntax verified.

Backup:
/Users/tristan/Desktop/Veronica-Dev-Reports/source-backups/capture-veronica-overview-20261010-112252.sh

The overview helper now prefers a running Debug build and
falls back to a running Release build.

Runtime capture behavior has not yet been tested.

## Experiment 13 — Debug overview runtime verification (20261010-112500)

Objective:
Verify that the updated overview helper captures the current
Debug application's Dashboard, Settings, and History screens.

Application:
/tmp/veronica-ux-baseline-build/Build/Products/Debug/Veronica.app

Output directory:
/Users/tristan/Desktop/Veronica-Dev-Reports/debug-overview-20261010-112500

Plan:
1. Launch the existing Debug application.
2. Run the existing overview helper.
3. Verify all three screen PNGs and the composite PNG.
4. Inspect output metadata.

Safety:
- No ChatGPT UI interaction.
- No image clipboard paste.
- No report-sender modification.
- No source-code modification.
- Preserve all uncommitted Git changes.
- The normal development automation may quit Veronica afterward.

Known limitation:
The helper currently captures the desktop, so unrelated windows
may appear in screenshots.

Status:
STARTED. Results follow below.

Experiment 13 result:
Overview helper failed at runtime.

Review the automated report before retrying.

## Experiment 14 — Reliable overview process discovery (20261010-112529)

Observation:
Experiment 13 failed before capture because the helper could
not identify a running Debug or Release application.

Hypothesis:
Exact matching against the ps command column is too restrictive.

Plan:
1. Back up the current helper.
2. Replace only its process-discovery section.
3. Use NSWorkspace to find the running application.
4. Verify the application's executable path.
5. Preserve Debug-first selection and Release fallback.
6. Validate Bash syntax.
7. Test process discovery without opening navigation sheets.

Safety:
- No ChatGPT UI interaction.
- No clipboard image paste.
- No report-sender changes.
- No changes to Veronica source files.
- Preserve all uncommitted work.

Status:
STARTED.

Experiment 14 result:
Process-discovery implementation updated.
Bash syntax check passed.

Backup:
/Users/tristan/Desktop/Veronica-Dev-Reports/source-backups/capture-veronica-overview-before-pid-fix-20261010-112529.sh

Review the automated report for PROCESS_DISCOVERY_TEST.
Full overview capture has not yet been retested.

## Experiment 16 — ZIP file-reference clipboard test (20261010-112908)

Objective:
Determine whether screenshots can be packaged into one ZIP
and placed on the macOS clipboard as a file reference.

Plan:
1. Find existing Veronica screenshots.
2. Copy selected PNG files into a test directory.
3. Create and verify a ZIP archive.
4. Place a file reference to the ZIP on the clipboard.
5. Read back clipboard metadata to verify the file reference.

Safety:
- Do not paste into ChatGPT.
- Do not interact with ChatGPT UI.
- Do not send a message or change conversations.
- Do not place raw PNG data on the clipboard.
- Do not modify the report sender.
- Do not modify Veronica source code.
- Preserve all uncommitted work.

Status:
STARTED.

Experiment 16 preparation:
ZIP created and archive integrity verified.

ZIP:
/Users/tristan/Desktop/Veronica-Dev-Reports/zip-attachment-test-20261010-112908/veronica-screenshots.zip

Clipboard:
File-reference clipboard test executed.

ChatGPT:
No UI interaction or attachment attempt.

Review automated report for clipboard verification result.

## Experiment 17 — Manual ZIP attachment test (20261010-112930)

Objective:
Determine whether ChatGPT accepts a ZIP file reference
pasted into the existing conversation.

Prerequisite:
Experiment 16 verified ZIP integrity and clipboard alias support.

Procedure:
1. Copy the ZIP file in Finder.
2. Return to the existing ChatGPT conversation.
3. Paste once into the message composer.
4. Observe whether an attachment appears.
5. Do not submit the message until the attachment is verified.

Safety:
- No automated ChatGPT UI interaction.
- No conversation navigation.
- No raw PNG clipboard data.
- No changes to the report sender.
- No automatic message submission.

Status:
AWAITING MANUAL TEST.

## Experiment 18 — Window-only capture implementation review (20261010-113241)

Context:
Experiment 17 successfully delivered a ZIP containing six
Veronica screenshots to the existing ChatGPT conversation.

Objective:
Prepare a reliable window-only overview capture, excluding
Terminal, ChatGPT, and unrelated desktop content.

Plan:
1. Inspect the current capture helper.
2. Identify screenshot function definitions and call sites.
3. Check existing process-ID and window-selection logic.
4. Validate Bash syntax.
5. Identify the latest successful overview image.

Safety:
- Inspection only; no automation script modifications.
- No ChatGPT UI interaction.
- No clipboard changes.
- No application navigation.
- No source-code modifications.
- Preserve all uncommitted work.

Status:
STARTED.

Experiment 18 result:
Read-only capture implementation inspection completed.

Review automated report for:
- Current screenshot function
- Function call sites
- Process-ID handling
- Bash syntax result
- Latest overview image

No capture code was changed.

## Experiment 19 — Window-only overview capture (20261010-113306)

Objective:
Replace full-desktop screenshots with captures of Veronica's
visible application window.

Implementation:
1. Back up the overview helper.
2. Add a Swift window-ID lookup utility.
3. Match CoreGraphics windows to the verified application PID.
4. Select the largest visible normal-layer window.
5. Use screencapture with its window-ID option.
6. Preserve Dashboard, Settings, and History navigation.

Validation:
- Bash syntax.
- Swift compilation.
- AppleScript compilation.

Safety:
- No ChatGPT UI interaction.
- No clipboard manipulation.
- No report-sender changes.
- No Veronica application-source changes.
- No automatic ZIP attachment.
- Preserve all uncommitted work.

Status:
STARTED.

Experiment 19 result:
Window-only capture implementation applied.

Backup:
/Users/tristan/Desktop/Veronica-Dev-Reports/source-backups/capture-veronica-overview-before-window-only-20261010-113306.sh

Swift utility:
tools/find-veronica-window.swift

Validation:
Bash syntax passed.
Swift typecheck passed.
AppleScript compilation passed.

Runtime screenshot verification remains pending.

## Experiment 20 — Window-only runtime verification (20261010-113329)

Objective:
Verify the new window-only capture implementation against
the current Debug build.

Plan:
1. Launch the Debug application.
2. Capture Dashboard, Settings, and History.
3. Generate the navigation overview.
4. Verify all four PNG files.
5. Check image dimensions and file sizes.
6. Package the four screenshots into a ZIP.

Safety:
- No ChatGPT UI interaction.
- No clipboard manipulation.
- No automatic attachment.
- No report-sender modification.
- No application-source modification.
- Preserve all uncommitted changes.

Output:
/Users/tristan/Desktop/Veronica-Dev-Reports/window-only-test-20261010-113329

Status:
STARTED.

Experiment 20 result:
Runtime capture succeeded.

Verified:
- dashboard.png
- settings.png
- history.png
- veronica-navigation-overview.png

Review ZIP:
/Users/tristan/Desktop/Veronica-Dev-Reports/window-only-test-20261010-113329/veronica-window-only-screenshots.zip

Visual verification remains pending.

## Experiment 21 — Dashboard UX finishing session (20261010-113528)

Time budget:
20 minutes maximum.

Goal:
Make the Dashboard's primary action more prominent and
clarify the distinction between previous analysis results
and the next action.

Plan:
1. Inspect current Dashboard implementation.
2. Apply one small, backed-up UX improvement.
3. Validate Debug build.
4. Capture result and prepare end-of-day handoff.

Safety:
- Preserve all uncommitted changes.
- No automatic ZIP attachment.
- No clipboard image manipulation.
- No ChatGPT navigation.
- Stop if the change becomes larger than expected.

Status:
STARTED — read-only inspection.

Experiment 21 — focused follow-up inspection (20261010-113550)

Purpose:
Inspect the existing results actions and next-step card
before making one small Dashboard UX improvement.

Scope:
ContentView.swift, lines 520–920.

Safety:
Read-only inspection. No application-source changes.
No clipboard or ChatGPT UI manipulation.

Experiment 21 — final Dashboard patch (20261010-113613)

Goal:
Place a prominent Analyze Library action inside the
"Ready for a fresh look" next-step card.

Scope:
- Modify only ContentView.swift.
- Preserve the existing bottom action.
- Preserve analysis availability checks.
- Preserve optimization confirmation and safety logic.
- Run a Debug build.

Safety:
- Back up source before editing.
- No ChatGPT UI interaction.
- No clipboard manipulation.
- No automatic ZIP attachment.
- Preserve all uncommitted work.

Status:
STARTED.

Experiment 21 result:
Dashboard next-step card now includes a prominent
Analyze Library action when previous results are shown.

Existing bottom action preserved.
Optimization safety logic unchanged.

Debug build: PASS.

Source backup:
/Users/tristan/Desktop/Veronica-Dev-Reports/source-backups/ContentView-before-final-dashboard-20261010-113613.swift

Build log:
/Users/tristan/Desktop/Veronica-Dev-Reports/dashboard-final-build-20261010-113613.log

Visual verification pending.
