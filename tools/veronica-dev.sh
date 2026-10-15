#!/bin/bash

set -u

PROJECT="/Users/tristan/Developer/veronica-mac-app"
DERIVED="/tmp/veronica-ux-baseline-build"
APP="$DERIVED/Build/Products/Debug/Veronica.app"
REPORT_DIR="$HOME/Desktop/Veronica-Dev-Reports"

mkdir -p "$REPORT_DIR"

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
RUN_DIR="$REPORT_DIR/$TIMESTAMP"

mkdir -p "$RUN_DIR"

cd "$PROJECT" || exit 1

echo ""
echo "========================================"
echo "        VERONICA DEV ASSISTANT"
echo "========================================"
echo ""
echo "Report directory: $RUN_DIR"
echo ""

BUILD_RESULT="NOT RUN"
TEST_RESULT="NOT RUN"

echo "========== BUILDING VERONICA =========="

if xcodebuild \
    -project macos/Veronica.xcodeproj \
    -scheme Veronica \
    -configuration Debug \
    -destination 'platform=macOS' \
    -derivedDataPath "$DERIVED" \
    CODE_SIGNING_ALLOWED=NO \
    build > "$RUN_DIR/build.log" 2>&1
then
    BUILD_RESULT="PASSED"
    echo "Build passed."
else
    BUILD_RESULT="FAILED"
    echo "Build failed."
    grep -nE 'error:|BUILD FAILED' "$RUN_DIR/build.log" | tail -50
fi

echo ""
echo "========== RUNNING TESTS =========="

if .venv/bin/python -m pytest -q tests \
    > "$RUN_DIR/tests.log" 2>&1
then
    TEST_RESULT="PASSED"
    echo "Tests passed."
else
    TEST_RESULT="FAILED"
    echo "Tests failed."
fi

echo ""
echo "========== GIT STATUS =========="

git status --short --branch > "$RUN_DIR/git-status.txt"
git diff --stat > "$RUN_DIR/git-diff.txt"

cat "$RUN_DIR/git-status.txt"

echo ""
echo "========== LAUNCHING APP =========="

if [ "$BUILD_RESULT" = "PASSED" ] && [ -d "$APP" ]; then
    open "$APP"
    echo "Veronica launched."
else
    echo "Skipping launch because build failed."
fi

echo ""
echo "========== SCREENSHOT =========="

SCREENSHOT_RESULT="NOT REQUESTED"

if [ "${1:-}" = "--screenshot" ]; then
    echo "Waiting 4 seconds for the app window..."
    sleep 4

    SCREENSHOT="$RUN_DIR/veronica-screen.png"

    if /usr/sbin/screencapture -x "$SCREENSHOT"; then
        SCREENSHOT_RESULT="$SCREENSHOT"
        echo "Screenshot saved."
    else
        SCREENSHOT_RESULT="FAILED"
        echo "Screenshot failed. Check Screen Recording permissions."
    fi
fi

echo ""
echo "========== GENERATING REPORT =========="

{
    echo "VERONICA DEVELOPMENT REPORT"
    echo "Date: $(date)"
    echo "Branch: $(git branch --show-current)"
    echo ""
    echo "BUILD: $BUILD_RESULT"
    echo "TESTS: $TEST_RESULT"
    echo "SCREENSHOT: $SCREENSHOT_RESULT"
    echo ""
    echo "GIT STATUS:"
    cat "$RUN_DIR/git-status.txt"
    echo ""
    echo "DIFF SUMMARY:"
    cat "$RUN_DIR/git-diff.txt"
    echo ""
    echo "TEST OUTPUT:"
    tail -40 "$RUN_DIR/tests.log"
    echo ""
    echo "BUILD ERRORS:"
    grep -nE 'error:|BUILD FAILED' "$RUN_DIR/build.log" | tail -40 || true
    echo ""
    echo "REPORT DIRECTORY:"
    echo "$RUN_DIR"
} > "$RUN_DIR/report.txt"

cat "$RUN_DIR/report.txt"

echo ""
echo "========================================"
echo "               FINISHED"
echo "========================================"
echo ""
echo "Report:"
echo "$RUN_DIR/report.txt"
echo ""

if command -v pbcopy >/dev/null 2>&1; then
    pbcopy < "$RUN_DIR/report.txt"
    echo "The report has been copied to your clipboard."
fi

echo ""
echo "Paste the report into ChatGPT with Command+V."
echo "If you captured a screenshot, attach the PNG separately."

if [ "${1:-}" = "--send" ] || [ "${2:-}" = "--send" ]; then
    echo ""
    echo "========== SENDING TO CHATGPT =========="
    if [ "$SCREENSHOT_RESULT" != "NOT REQUESTED" ] && [ "$SCREENSHOT_RESULT" != "FAILED" ]; then
        "$PROJECT/tools/send-to-chatgpt.sh" "$RUN_DIR/report.txt" "$SCREENSHOT_RESULT"
    else
        "$PROJECT/tools/send-to-chatgpt.sh" "$RUN_DIR/report.txt"
    fi
fi
echo ""
