#!/bin/bash
set -euo pipefail

SCREENSHOT="${1:-$HOME/Desktop/Veronica-Dev-Reports/2026-10-10_08-31-58/veronica-screen.png}"

if [ ! -f "$SCREENSHOT" ]; then
    echo "Screenshot not found: $SCREENSHOT"
    exit 1
fi

if ! pgrep -x ChatGPT >/dev/null 2>&1; then
    echo "Open ChatGPT and this temporary conversation first."
    exit 1
fi

echo "Preparing screenshot: $SCREENSHOT"

osascript - "$SCREENSHOT" <<'APPLESCRIPT'
on run argv
    set screenshotPath to item 1 of argv
    set screenshotFile to POSIX file screenshotPath

    tell application "ChatGPT" to activate
    delay 1

    set the clipboard to (read screenshotFile as «class PNGf»)

    tell application "System Events"
        tell process "ChatGPT"
            keystroke "v" using command down
        end tell
    end tell
end run
APPLESCRIPT

echo "Screenshot paste attempted."
echo "Check whether the image appears in the ChatGPT composer."
echo "Nothing has been sent automatically."
