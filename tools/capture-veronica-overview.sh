#!/bin/bash
set -euo pipefail

CAPTURE_DIR="${1:?Capture directory required}"
mkdir -p "$CAPTURE_DIR"

DEBUG_APP="/tmp/veronica-ux-baseline-build/Build/Products/Debug/Veronica.app"
RELEASE_APP="/Users/tristan/Developer/veronica-mac-app/.build/release-derived/Build/Products/Release/Veronica.app"

APP=""
EXECUTABLE=""
PID=""

for candidate in "$DEBUG_APP" "$RELEASE_APP"; do
    candidate_executable="$candidate/Contents/MacOS/Veronica"

    candidate_pid="$(
        /usr/bin/swift - "$candidate_executable" <<'SWIFT'
import AppKit
import Foundation

let expected = URL(
    fileURLWithPath: CommandLine.arguments[1]
).resolvingSymlinksInPath().standardizedFileURL.path

for application in NSWorkspace.shared.runningApplications {
    guard application.localizedName == "Veronica",
          let executable = application.executableURL else {
        continue
    }

    let actual = executable
        .resolvingSymlinksInPath()
        .standardizedFileURL.path

    if actual == expected {
        print(application.processIdentifier)
        break
    }
}
SWIFT
    )"

    if [ -n "$candidate_pid" ]; then
        APP="$candidate"
        EXECUTABLE="$candidate_executable"
        PID="$candidate_pid"
        break
    fi
done

if [ -z "$PID" ]; then
    echo "OVERVIEW_CAPTURE=SKIPPED"
    echo "REASON=Neither Debug nor Release application is running"
    exit 1
fi

echo "OVERVIEW_APP=$APP"
echo "OVERVIEW_PID=$PID"

/usr/bin/osascript - "$PID" "$CAPTURE_DIR" <<'APPLESCRIPT'
on pressIdentifier(targetPID, targetIdentifier)
    repeat with attempt from 1 to 15
        set pressed to false

        tell application "System Events"
            set matches to every application process whose unix id is targetPID

            if (count of matches) = 0 then
                error "Veronica process exited."
            end if

            tell item 1 of matches
                set frontmost to true

                if (count of windows) > 0 then
                    set allItems to entire contents of window 1

                    repeat with uiItem in allItems
                        try
                            set identifierValue to value of attribute "AXIdentifier" of uiItem

                            if identifierValue is targetIdentifier then
                                if (value of attribute "AXEnabled" of uiItem) is true then
                                    perform action "AXPress" of uiItem
                                    set pressed to true
                                    exit repeat
                                end if
                            end if
                        end try
                    end repeat
                end if
            end tell
        end tell

        if pressed then return
        delay 1
    end repeat

    error "Button unavailable: " & targetIdentifier
end pressIdentifier

on waitForSheet(targetPID, shouldBeOpen)
    repeat with attempt from 1 to 15
        set sheetCount to -1

        tell application "System Events"
            set matches to every application process whose unix id is targetPID

            if (count of matches) = 0 then
                error "Veronica process exited."
            end if

            tell item 1 of matches
                if (count of windows) > 0 then
                    try
                        set sheetCount to count of sheets of window 1
                    end try
                end if
            end tell
        end tell

        if shouldBeOpen and sheetCount > 0 then return
        if (not shouldBeOpen) and sheetCount = 0 then return

        delay 1
    end repeat

    error "Sheet did not reach expected state."
end waitForSheet

on captureScreen(targetPID, imagePath)
    tell application "System Events"
        set targetProcess to first application process whose unix id is targetPID
        set frontmost of targetProcess to true
    end tell

    delay 2

    set windowID to do shell script "/usr/bin/swift " & quoted form of "/Users/tristan/Developer/veronica-mac-app/tools/find-veronica-window.swift" & " " & (targetPID as text)

    if windowID is "" then
        error "No Veronica window found for capture."
    end if

    do shell script "/usr/sbin/screencapture -x -l " & quoted form of windowID & " " & quoted form of imagePath
end captureScreen

on run argv
    set targetPID to (item 1 of argv) as integer
    set captureDirectory to item 2 of argv

    my waitForSheet(targetPID, false)

    my captureScreen(targetPID, captureDirectory & "/dashboard.png")

    repeat with screenName in {"Settings", "History"}
        set currentName to screenName as text

        if currentName is "Settings" then
            set targetIdentifier to "veronica.openSettings"
            set imageName to "settings.png"
        else
            set targetIdentifier to "veronica.openHistory"
            set imageName to "history.png"
        end if

        my pressIdentifier(targetPID, targetIdentifier)
        my waitForSheet(targetPID, true)

        delay 2

        my captureScreen(targetPID, captureDirectory & "/" & imageName)

        my pressIdentifier(targetPID, "veronica.closeSheet")
        my waitForSheet(targetPID, false)
    end repeat
end run
APPLESCRIPT

/usr/bin/swift - "$CAPTURE_DIR" <<'SWIFT'
import AppKit
import Foundation

let directory = URL(fileURLWithPath: CommandLine.arguments[1])
let output = directory.appendingPathComponent("veronica-navigation-overview.png")

let screens = [
    ("Dashboard", "dashboard.png"),
    ("Settings", "settings.png"),
    ("History", "history.png")
]

let panelWidth = 900
let panelHeight = 650
let titleHeight = 60
let margin = 24
let canvasWidth = panelWidth * 3 + margin * 4
let canvasHeight = panelHeight + titleHeight + margin * 2

guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: canvasWidth,
    pixelsHigh: canvasHeight,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fatalError("Unable to create overview bitmap.")
}

guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fatalError("Unable to create graphics context.")
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context

NSColor.white.setFill()
NSRect(
    x: 0,
    y: 0,
    width: canvasWidth,
    height: canvasHeight
).fill()

let attributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.boldSystemFont(ofSize: 28),
    .foregroundColor: NSColor.black
]

for (index, screen) in screens.enumerated() {
    let imageURL = directory.appendingPathComponent(screen.1)

    guard let image = NSImage(contentsOf: imageURL) else {
        fatalError("Unable to load \(imageURL.path)")
    }

    let x = margin + index * (panelWidth + margin)

    NSAttributedString(
        string: screen.0,
        attributes: attributes
    ).draw(
        at: NSPoint(x: x, y: canvasHeight - margin - 40)
    )

    let availableRect = NSRect(
        x: x,
        y: margin,
        width: panelWidth,
        height: panelHeight
    )

    let scale = min(
        availableRect.width / image.size.width,
        availableRect.height / image.size.height
    )

    let scaledWidth = image.size.width * scale
    let scaledHeight = image.size.height * scale

    image.draw(
        in: NSRect(
            x: availableRect.midX - scaledWidth / 2,
            y: availableRect.midY - scaledHeight / 2,
            width: scaledWidth,
            height: scaledHeight
        ),
        from: .zero,
        operation: .copy,
        fraction: 1
    )

    print("PANEL_ADDED=\(screen.0)")
}

context.flushGraphics()
NSGraphicsContext.restoreGraphicsState()

guard let data = bitmap.representation(
    using: .png,
    properties: [:]
) else {
    fatalError("Unable to encode overview.")
}

try data.write(to: output)
print("OVERVIEW_CREATED=\(output.path)")
SWIFT

for name in dashboard settings history; do
    test -s "$CAPTURE_DIR/$name.png"
done

test -s "$CAPTURE_DIR/veronica-navigation-overview.png"

echo "OVERVIEW_CAPTURE=PASS"
