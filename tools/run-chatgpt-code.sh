#!/bin/bash

set -euo pipefail

PROJECT="/Users/tristan/Developer/veronica-mac-app"
REPORT_DIR="$HOME/Desktop/Veronica-Dev-Reports"
TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
RUN_DIR="$REPORT_DIR/chatgpt-command-$TIMESTAMP"
LOCK_DIR="/tmp/veronica-chatgpt-runner.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "Another ChatGPT command is already running."
    exit 1
fi

trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

mkdir -p "$RUN_DIR"

COMMAND_FILE="$RUN_DIR/command.sh"
OUTPUT_FILE="$RUN_DIR/output.log"
REPORT_FILE="$RUN_DIR/report.txt"

pbpaste > "$COMMAND_FILE"

if [ ! -s "$COMMAND_FILE" ]; then
    echo "Clipboard is empty."
    exit 1
fi

if grep -Eq 'run-chatgpt-code\.sh|veronica-dev\.sh.*--send' "$COMMAND_FILE"; then
    echo "Refusing to execute an automation launcher recursively."
    exit 1
fi

echo "========== EXECUTING CHATGPT COMMAND =========="
cat "$COMMAND_FILE"
echo ""

cd "$PROJECT"

set +e
/usr/bin/perl -e 'alarm 300; exec @ARGV' /bin/bash "$COMMAND_FILE" > "$OUTPUT_FILE" 2>&1
EXIT_CODE=$?
set -e

{
    echo "VERONICA AUTOMATED COMMAND REPORT"
    echo "Date: $(date)"
    echo "Exit code: $EXIT_CODE"
    echo ""
    echo "COMMAND:"
    cat "$COMMAND_FILE"
    echo ""
    echo "OUTPUT:"
    tail -150 "$OUTPUT_FILE"
    echo ""
    echo "GIT STATUS:"
    git status --short --branch
    echo ""
    echo "Full output: $OUTPUT_FILE"
} > "$REPORT_FILE"

cat "$REPORT_FILE"

if [ -x "$PROJECT/tools/send-to-chatgpt.sh" ]; then
    "$PROJECT/tools/send-to-chatgpt.sh" "$REPORT_FILE"
else
    echo ""
    echo "Report saved, but tools/send-to-chatgpt.sh was not found."
fi

exit "$EXIT_CODE"
