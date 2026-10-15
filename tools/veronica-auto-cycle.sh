#!/bin/bash
set -uo pipefail

PROJECT="/Users/tristan/Developer/veronica-mac-app"
DERIVED="/tmp/veronica-ux-baseline-build"
APP="$DERIVED/Build/Products/Debug/Veronica.app"
ENGINE="$APP/Contents/Resources/Engine"
REPORT_ROOT="$HOME/Desktop/Veronica-Dev-Reports"
RUN_DIR="$REPORT_ROOT/auto-cycle-$(date '+%Y-%m-%d_%H-%M-%S')-$$"
LOCK="/tmp/veronica-auto-cycle.lock"

mkdir -p "$RUN_DIR"

COMMAND="$RUN_DIR/command.sh"
OUTPUT="$RUN_DIR/output.log"
REPORT="$RUN_DIR/report.txt"
SCREENSHOT="$RUN_DIR/veronica-screen.png"

if ! mkdir "$LOCK" 2>/dev/null; then
    echo "Another Veronica automation cycle is running."
    exit 1
fi

trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

cd "$PROJECT" || exit 1

pbpaste > "$COMMAND"

if [ ! -s "$COMMAND" ]; then
    echo "Clipboard is empty."
    exit 1
fi

if grep -Eq 'veronica-auto-cycle\.sh|run-chatgpt-code\.sh|veronica-cycle-launcher' "$COMMAND"; then
    echo "Refusing to execute an automation launcher recursively."
    exit 1
fi

echo "========== EXECUTING COPIED CODE =========="

set +e
/usr/bin/perl -e 'alarm 600; exec @ARGV' /bin/bash "$COMMAND" > "$OUTPUT" 2>&1
RESULT=$?
set -e

echo "Command exit status: $RESULT"

echo "========== SYNCHRONIZING DEVELOPMENT ENGINE =========="

if [ -d "$ENGINE" ]; then
    for FILE in veronica.py media_maintenance.py media_audit.py; do
        if [ -f "$PROJECT/$FILE" ]; then
            cp "$PROJECT/$FILE" "$ENGINE/$FILE"
        fi
    done
fi

echo "========== CAPTURING SCREENSHOT =========="

if pgrep -f '/Veronica.app/Contents/MacOS/Veronica' >/dev/null 2>&1; then
    osascript -e 'tell application "Veronica" to activate' 2>/dev/null || true
    sleep 2
    WINDOW_ID="$(/usr/bin/swift -e '
import AppKit
import CoreGraphics

let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]

if let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] {
    for window in windows {
        let owner = window[kCGWindowOwnerName as String] as? String ?? ""
        let layer = window[kCGWindowLayer as String] as? Int ?? -1
        let number = window[kCGWindowNumber as String] as? Int ?? 0

        if owner == "Veronica" && layer == 0 && number > 0 {
            print(number)
            break
        }
    }
}
' 2>/dev/null || true)"

    if [ -n "$WINDOW_ID" ]; then
        /usr/sbin/screencapture -x -l "$WINDOW_ID" "$SCREENSHOT" 2>/dev/null || true
    fi

    if [ ! -s "$SCREENSHOT" ]; then
        echo "WINDOW_CAPTURE_FAILED_USING_DISPLAY_FALLBACK"
        /usr/sbin/screencapture -x "$SCREENSHOT" 2>/dev/null || true
    fi
fi

# MULTI_SCREEN_OVERVIEW_CAPTURE
# Capture the three principal screens when the development Release app
# is running. Preserve the existing screenshot if this step fails.
OVERVIEW_PATH="$RUN_DIR/veronica-navigation-overview.png"

if "$PROJECT/tools/capture-veronica-overview.sh" "$RUN_DIR"     > "$RUN_DIR/overview-capture.log" 2>&1
then
    if [ -s "$OVERVIEW_PATH" ]; then
        SCREENSHOT="$OVERVIEW_PATH"
        echo "SCREENSHOT_SELECTION=AUTOMATIC_OVERVIEW"
    fi
else
    echo "SCREENSHOT_SELECTION=STANDARD_FALLBACK"
    echo "OVERVIEW_CAPTURE_LOG=$RUN_DIR/overview-capture.log"
fi

{
    echo "VERONICA AUTOMATED DEVELOPMENT REPORT"
    echo "Date: $(date)"
    echo "Exit code: $RESULT"
    echo ""
    echo "EXECUTED CODE:"
    cat "$COMMAND"
    echo ""
    echo "TERMINAL OUTPUT:"
    echo "Output size: $(wc -c < "$OUTPUT" | tr -d ' ') bytes"
    echo ""
    if [ "$(wc -c < "$OUTPUT")" -le 200000 ]; then
        cat "$OUTPUT"
    else
        head -c 200000 "$OUTPUT"
        echo ""
        echo "[Output truncated at 200 KB. Full output is saved separately.]"
    fi
    echo ""
    echo "GIT STATUS:"
    git status --short --branch
    echo ""
    echo "SCREENSHOT:"
    if [ -f "$SCREENSHOT" ]; then
        echo "$SCREENSHOT"
    else
        echo "Not captured"
    fi
    echo ""
    echo "FULL OUTPUT:"
    echo "$OUTPUT"
} > "$REPORT"

# Use an explicitly selected overview when one is provided.
# Otherwise preserve the standard screenshot.
if [ -n "${VERONICA_OVERVIEW_IMAGE:-}" ]; then
    if [ -s "$VERONICA_OVERVIEW_IMAGE" ]; then
        SCREENSHOT="$VERONICA_OVERVIEW_IMAGE"
        echo "SCREENSHOT_SELECTION=EXPLICIT_OVERVIEW"
        echo "OVERVIEW_IMAGE=$SCREENSHOT"
    else
        echo "SCREENSHOT_SELECTION=STANDARD"
        echo "OVERVIEW_WARNING=Specified overview does not exist"
    fi
fi

echo "========== SENDING TO CHATGPT =========="

if [ -f "$SCREENSHOT" ]; then
    "$PROJECT/tools/send-to-chatgpt.sh" "$REPORT" "$SCREENSHOT"
else
    "$PROJECT/tools/send-to-chatgpt.sh" "$REPORT"
fi

echo "========== QUITTING VERONICA =========="

osascript -e 'tell application "Veronica" to quit' 2>/dev/null || true

for i in 1 2 3 4 5 6 7 8; do
    if ! pgrep -f '/Veronica.app/Contents/MacOS/Veronica' >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if pgrep -f "$APP/Contents/MacOS/Veronica" >/dev/null 2>&1; then
    pkill -f "$APP/Contents/MacOS/Veronica" 2>/dev/null || true
fi

echo "========== TERMINAL CLEANUP =========="

if [[ "${VERONICA_AUTOMATION_WINDOW_ID:-}" =~ ^[0-9]+$ ]]; then
    WINDOW_ID="$VERONICA_AUTOMATION_WINDOW_ID"

    nohup /bin/bash -c '
        sleep 5

        /usr/bin/osascript - "$1" <<'"'"'APPLESCRIPT'"'"'
on run argv
    set targetID to (item 1 of argv) as integer

    tell application "Terminal"
        try
            set targetWindow to first window whose id is targetID

            set verified to false

            repeat with t in tabs of targetWindow
                try
                    set tabHistory to history of t

                    if tabHistory contains "veronica-auto-cycle.sh" then
                        set verified to true
                    end if
                end try
            end repeat

            if verified then
                close targetWindow saving no
            else
                log "Cleanup skipped: automation identity not verified."
            end if

        on error errorMessage
            log "Cleanup skipped: " & errorMessage
        end try
    end tell
end run
APPLESCRIPT
    ' _ "$WINDOW_ID" >/dev/null 2>&1 </dev/null &

    disown 2>/dev/null || true
    echo "Guarded cleanup scheduled for window $WINDOW_ID."
else
    echo "No valid automation window ID. Cleanup skipped."
fi

echo "========== FINISHED =========="
