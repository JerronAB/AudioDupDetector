#!/usr/bin/env bash
set -euo pipefail #"strict mode"

ffmpeg -version

WATCH_DIR="/app/assets"
WAIT_TIME=10
MAX_FAILURES=3
FAILURES=0
DB="/app/assets/fingerprints.db"

#Had no idea you can make a function
#like this in Bash
run_python() {
    echo "Starting Python script..."
    if python AudioAdRemover.py; then
        FAILURES=0
        echo "Python completed successfully"
    else
        FAILURES=$((FAILURES + 1))
        echo "Python failed: ($FAILURES/$MAX_FAILURES)"

        if [[ $FAILURES -ge $MAX_FAILURES ]]; then
            echo "3 consecutive failures detected. Removing DB and exiting."
            rm -f "$DB"
            exit 1 #restart container
        fi
    fi
}

#Should run on startup at first by default
echo "Watching for file changes..."
LAST_HASH=""
while true; do
    HASH=$(find "$WATCH_DIR" -type f -exec stat -c '%Y %n' {} \; | sha256sum)
    if [[ "$HASH" != "$LAST_HASH" ]]; then
        LAST_HASH="$HASH"
        run_python
    fi
    sleep "$WAIT_TIME"
done

