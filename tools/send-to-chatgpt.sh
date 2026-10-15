#!/bin/bash
set -euo pipefail

REPORT="${1:-}"
SCREENSHOT="${2:-}"
AUTO_SEND="${VERONICA_AUTO_SEND:-1}"
AUTO_ATTACH_SCREENSHOT="${VERONICA_AUTO_ATTACH_SCREENSHOT:-0}"

# Keep screenshot capture and storage enabled.
# Disable automatic image clipboard attachment by default.
# This avoids the suspected ChatGPT clipboard crash trigger.
if [ "$AUTO_ATTACH_SCREENSHOT" != "1" ]; then
    SCREENSHOT=""
    echo "SCREENSHOT_ATTACHMENT=DISABLED"
fi

if [ -z "$REPORT" ] || [ ! -f "$REPORT" ]; then
    echo "ERROR: Report file missing."
    exit 1
fi

echo ""
echo "========== VERONICA REPORT =========="
echo "Saved: $REPORT"

if [ -n "$SCREENSHOT" ] && [ -f "$SCREENSHOT" ]; then
    echo "Screenshot saved: $SCREENSHOT"
fi

SIZE="$(wc -c < "$REPORT" | tr -d ' ')"

if [ "$SIZE" -le 200000 ]; then
    /usr/bin/pbcopy < "$REPORT"
else
    {
        echo "VERONICA DEVELOPMENT REPORT"
        echo "Full report: $REPORT"
        echo ""
        head -c 15000 "$REPORT"
        echo ""
        echo "[Large report truncated for ChatGPT delivery.]"
    } | /usr/bin/pbcopy
fi

if [ "$AUTO_SEND" != "1" ]; then
    echo "Automatic sending disabled."
    exit 0
fi

if ! /usr/bin/pgrep -f '/Applications/ChatGPT Classic.app/Contents/MacOS/ChatGPT' >/dev/null 2>&1; then
    echo "ChatGPT Classic is not running. Report remains saved and copied."
    exit 0
fi

echo "Attempting automatic ChatGPT delivery..."

if /usr/bin/osascript - "$REPORT" "$SCREENSHOT" "${VERONICA_SUBMIT_MESSAGE:-1}" <<'APPLESCRIPT'
on run argv
    set reportPath to item 1 of argv
    set screenshotPath to item 2 of argv
    set submitMessage to item 3 of argv

    set reportText to read (POSIX file reportPath) as «class utf8»

    if screenshotPath is not "" then
        set screenshotFile to POSIX file screenshotPath
        set screenshotData to read screenshotFile as «class PNGf»
    end if

    tell application id "com.openai.chat" to activate
    delay 1

    tell application "System Events"
        tell process "ChatGPT"
            set allItems to entire contents of window 1
            set editorFound to false
            set insertionSucceeded to false
            set insertionError to ""

            repeat with uiItem in allItems
                try
                    set itemRole to value of attribute "AXRole" of uiItem

                    if itemRole is "AXTextArea" then
                        set editorFound to true

                        set existingText to value of attribute "AXValue" of uiItem

                        if existingText is missing value then
                            set existingText to ""
                        end if

                        if existingText is not "" then
                            set insertionError to "Composer is not empty."
                        else
                            set value of attribute "AXValue" of uiItem to reportText
                            delay 0.5

                            set actualText to value of attribute "AXValue" of uiItem

                            if actualText is reportText then
                                set insertionSucceeded to true
                                log "REPORT_INSERTION=PASS"
                            else
                                set insertionError to "Report verification failed."
                            end if
                        end if

                        exit repeat
                    end if

                on error errMsg number errNum
                    if editorFound then
                        set insertionError to errMsg & " (" & errNum & ")"
                        exit repeat
                    end if
                end try
            end repeat

            if not editorFound then
                error "REPORT_INSERTION=FAIL: Editor not found."
            end if

            if not insertionSucceeded then
                error "REPORT_INSERTION=FAIL: " & insertionError
            end if

            if screenshotPath is not "" then
                try
                    set the clipboard to screenshotData

                    delay 0.3

                    set value of attribute "AXFocused" of uiItem to true
                    delay 0.3

                    keystroke "v" using command down
                    delay 2

                    log "SCREENSHOT_PASTE=ATTEMPTED"

                on error errMsg number errNum
                    log "SCREENSHOT_PASTE=FAIL"
                    log "SCREENSHOT_ERROR=" & errMsg
                    log "SCREENSHOT_ERROR_NUMBER=" & errNum
                end try
            else
                log "SCREENSHOT_PASTE=SKIPPED"
            end if

            if submitMessage is "1" then
                delay 3

                set sendPressed to false

                repeat with attemptNumber from 1 to 5
                    set allItems to entire contents of window 1

                    repeat with buttonRef in allItems
                        try
                            set itemRole to value of attribute "AXRole" of buttonRef

                            if itemRole is "AXButton" then
                                set itemHelp to value of attribute "AXHelp" of buttonRef

                                if itemHelp is "Send message (⏎)" then
                                    if (value of attribute "AXEnabled" of buttonRef) is true then
                                        perform action "AXPress" of buttonRef
                                        set sendPressed to true
                                        log "SEND_BUTTON_PRESSED=YES"
                                    end if

                                    exit repeat
                                end if
                            end if
                        end try
                    end repeat

                    if sendPressed then exit repeat
                    delay 1
                end repeat

                if sendPressed is false then
                    error "Automatic submission failed: enabled Send button not found."
                end if
            else
                log "MESSAGE_SUBMISSION=DISABLED"
            end if

        end tell
    end tell
end run
APPLESCRIPT
then
    echo "REPORT_INSERTION=PASS"
    echo "Screenshot paste attempted if an image was supplied."
    if [ "${VERONICA_SUBMIT_MESSAGE:-1}" = "1" ]; then
        echo "MESSAGE_SUBMISSION=REQUESTED"
    else
        echo "MESSAGE_SUBMISSION=DISABLED"
    fi
else
    echo "REPORT_INSERTION_OR_ATTACHMENT=FAIL"
fi

/usr/bin/pbcopy < "$REPORT"
echo "========== DELIVERY COMPLETE =========="
