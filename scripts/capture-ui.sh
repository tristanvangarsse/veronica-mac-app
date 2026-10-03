#!/bin/zsh
set -euo pipefail

PROJECT="/Users/tristan/Developer/veronica-mac-app"
DESKTOP="/Users/tristan/Desktop"
DERIVED="$PROJECT/build/ui-capture-derived"
OUT_DIR="$DESKTOP/Veronica-UI-Screenshots"
ZIP_PATH="$DESKTOP/Veronica-UI-Screenshots.zip"

cd "$PROJECT"

echo "=== Building Veronica ==="
rm -rf "$DERIVED"

xcodebuild \
  -project macos/Veronica.xcodeproj \
  -scheme Veronica \
  -configuration Debug \
  -derivedDataPath "$DERIVED" \
  build >/dev/null

APP_PATH="$DERIVED/Build/Products/Debug/Veronica.app"

if [[ ! -d "$APP_PATH" ]]; then
    echo "ERROR: app not found:"
    echo "$APP_PATH"
    exit 1
fi

echo "Built app:"
echo "$APP_PATH"

rm -rf "$OUT_DIR"
rm -f "$ZIP_PATH"
mkdir -p "$OUT_DIR"

quit_veronica() {
    osascript -e 'tell application "Veronica" to quit' >/dev/null 2>&1 || true
    sleep 0.8
    pkill -x Veronica >/dev/null 2>&1 || true
    sleep 0.5
}

cleanup() {
    echo
    echo "=== Closing Veronica ==="
    quit_veronica
}

trap cleanup EXIT

wait_for_process() {
    local i
    for i in {1..80}; do
        if pgrep -x Veronica >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

wait_for_ui_ready() {
    local section="$1"
    local start_size="${2:-0}"
    local log_file="$HOME/Library/Application Support/Veronica/logs/veronica.log"
    local current_size=0
    local new_log=""
    local i

    echo "Waiting for Veronica to finish loading $section..."

    for i in {1..80}; do
        if ! pgrep -x Veronica >/dev/null 2>&1; then
            echo "ERROR: Veronica exited while loading section: $section"
            return 1
        fi

        if [[ -f "$log_file" ]]; then
            current_size="$(stat -f%z "$log_file" 2>/dev/null || echo 0)"

            if [[ "$current_size" -gt "$start_size" ]]; then
                new_log="$(tail -c +$((start_size + 1)) "$log_file" 2>/dev/null || true)"

                if [[ "$new_log" == *"[Engine] Command ui-snapshot exited 0"* ]]; then
                    local count
                    count="$(window_count | tr -d '[:space:]')"

                    if [[ ! "$count" =~ '^[0-9]+$' ]] || [[ "$count" -lt 1 ]]; then
                        echo "ERROR: Veronica has no window after loading section: $section"
                        return 1
                    fi

                    echo "Veronica finished loading $section with $count window(s)."
                    sleep 0.5
                    return 0
                fi
            fi
        fi

        sleep 0.25
    done

    echo "ERROR: Timed out waiting for Veronica to finish loading section: $section"
    return 1
}
window_count() {
    osascript <<'APPLESCRIPT' 2>/dev/null || echo 0
tell application "System Events"
    if not (exists process "Veronica") then
        return 0
    end if

    tell process "Veronica"
        return count of windows
    end tell
end tell
APPLESCRIPT
}

wait_for_window() {
    local i
    local count

    for i in {1..120}; do
        count="$(window_count | tr -d '[:space:]')"

        if [[ "$count" =~ '^[0-9]+$' ]] && [[ "$count" -gt 0 ]]; then
            echo "Window count: $count"
            return 0
        fi

        sleep 0.25
    done

    return 1
}

focus_and_position() {
    osascript <<'APPLESCRIPT'
tell application "System Events"
    tell process "Veronica"
        set frontmost to true

        repeat 40 times
            if (count of windows) > 0 then exit repeat
            delay 0.1
        end repeat

        if (count of windows) = 0 then
            error "Veronica has no windows"
        end if

        set position of window 1 to {120, 80}
        set size of window 1 to {1180, 820}
    end tell
end tell
APPLESCRIPT
}

window_bounds() {
    osascript <<'APPLESCRIPT'
tell application "System Events"
    tell process "Veronica"
        if (count of windows) = 0 then
            error "Veronica has no windows"
        end if

        set p to position of window 1
        set s to size of window 1

        return ((item 1 of p) as text) & "," & ¬
            ((item 2 of p) as text) & "," & ¬
            ((item 1 of s) as text) & "," & ¬
            ((item 2 of s) as text)
    end tell
end tell
APPLESCRIPT
}

capture_current_window() {
    local filename="$1"
    local bounds

    bounds="$(window_bounds)"
    echo "Bounds: $bounds"

    screencapture \
      -x \
      -R"$bounds" \
      "$OUT_DIR/$filename.png"

    if [[ ! -s "$OUT_DIR/$filename.png" ]]; then
        echo "ERROR: screenshot not created:"
        echo "$OUT_DIR/$filename.png"
        exit 1
    fi

    echo "Saved: $OUT_DIR/$filename.png"
}

log_size() {
    local log_file="$HOME/Library/Application Support/Veronica/logs/veronica.log"

    if [[ -f "$log_file" ]]; then
        stat -f%z "$log_file" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

launch_section() {
    local section="$1"

    quit_veronica

    local ui_log_start
    ui_log_start="$(log_size)"

    open -na "$APP_PATH" --args --ui-section "$section"

    if ! wait_for_process; then
        echo "ERROR: Veronica process never started."
        exit 1
    fi

    if ! wait_for_window; then
        echo "ERROR: Veronica started but never exposed a window."
        exit 1
    fi

    focus_and_position

    if ! wait_for_ui_ready "$section" "$ui_log_start"; then
        exit 1
    fi

    sleep 0.5
}

capture_section() {
    local section="$1"
    local filename="$2"

    echo
    echo "=== Capturing $section ==="

    launch_section "$section"
    capture_current_window "$filename"
}

capture_section dashboard dashboard
capture_section activity activity
capture_section review review
capture_section history history

echo
echo "=== Capturing Settings top ==="
launch_section settings
capture_current_window settings

echo
echo "=== Capturing Settings bottom ==="
quit_veronica

SETTINGS_BOTTOM_LOG_START="$(log_size)"

open -na "$APP_PATH" --args --ui-section settings --ui-settings-bottom

if ! wait_for_process; then
    echo "ERROR: Veronica process never started for Settings bottom."
    exit 1
fi

if ! wait_for_window; then
    echo "ERROR: Veronica started but never exposed a window for Settings bottom."
    exit 1
fi

focus_and_position

if ! wait_for_ui_ready settings "$SETTINGS_BOTTOM_LOG_START"; then
    exit 1
fi

capture_current_window settings-bottom

echo
echo "=== SHA-256 CHECK ==="
shasum -a 256 "$OUT_DIR"/*.png

UNIQUE_COUNT="$(
    shasum -a 256 "$OUT_DIR"/*.png |
    awk '{print $1}' |
    sort -u |
    wc -l |
    tr -d ' '
)"

echo
echo "Unique screenshots: $UNIQUE_COUNT / 6"

if [[ "$UNIQUE_COUNT" -ne 6 ]]; then
    echo "ERROR: expected 6 visually distinct screenshots, got $UNIQUE_COUNT."
    echo "One or more UI sections may not have rendered or scrolled correctly."
    exit 1
fi

echo
echo "=== Creating zip ==="
cd "$DESKTOP"
zip -rq "$(basename "$ZIP_PATH")" "$(basename "$OUT_DIR")"

echo
echo "=== SUCCESS ==="
ls -lh "$OUT_DIR"

echo
echo "Zip:"
ls -lh "$ZIP_PATH"

echo
echo "Upload:"
echo "$ZIP_PATH"
