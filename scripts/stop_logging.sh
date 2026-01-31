#!/bin/bash
#
# Stop script that cleanly stops journal logging
#

LOG_DIR="/home/ranhaber/cat_ball_tracker/logs"
PID_FILE="$LOG_DIR/.journal_pid"

if [ -f "$PID_FILE" ]; then
    JOURNAL_PID=$(cat "$PID_FILE")
    if kill -0 "$JOURNAL_PID" 2>/dev/null; then
        echo "Stopping journal logger (PID: $JOURNAL_PID)"
        kill "$JOURNAL_PID"
        rm "$PID_FILE"
    fi
fi
