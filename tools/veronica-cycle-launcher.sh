#!/bin/bash
set -euo pipefail

PROJECT="/Users/tristan/Developer/veronica-mac-app"

osascript - "$PROJECT" <<'APPLESCRIPT'
on run argv
    set projectPath to item 1 of argv

    tell application "Terminal"
        set previousIDs to id of every window

        set automationTab to do script "cd " & quoted form of projectPath

        delay 0.7

        set newWindowIDs to id of every window
        set automationWindowID to missing value

        repeat with candidateID in newWindowIDs
            if previousIDs does not contain candidateID then
                set automationWindowID to candidateID
                exit repeat
            end if
        end repeat

        if automationWindowID is missing value then
            error "Could not identify newly created Terminal window. Automation cancelled."
        end if

        log "VERONICA AUTOMATION WINDOW ID: " & automationWindowID

        do script "export VERONICA_AUTOMATION_WINDOW_ID=" & automationWindowID & "; ./tools/veronica-auto-cycle.sh" in automationTab
    end tell
end run
APPLESCRIPT
