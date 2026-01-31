#!/bin/bash
#
# Start script that captures journal logs to dated files
# This script is called by systemd on service start
#

# Log directory
LOG_DIR="/home/ranhaber/cat_ball_tracker/logs"
mkdir -p "$LOG_DIR"

# Generate log filename with current timestamp
LOG_FILE="$LOG_DIR/journal_$(date +%Y%m%d_%H%M%S).log"

# Write startup marker
echo "========================================" >> "$LOG_FILE"
echo "Cat Ball Tracker Started" >> "$LOG_FILE"
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Log system info
echo "System Info:" >> "$LOG_FILE"
echo "  Hostname: $(hostname)" >> "$LOG_FILE"
echo "  Python: $(python3 --version)" >> "$LOG_FILE"
echo "  RAM Total: $(free -h | awk '/^Mem:/ {print $2}')" >> "$LOG_FILE"
echo "  Disk Free: $(df -h /home | awk 'NR==2 {print $4}')" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Create symlink to latest log
ln -sf "$LOG_FILE" "$LOG_DIR/latest.log"

# First, dump all logs from current boot for this service
echo "Capturing existing session logs..." >> "$LOG_FILE"
journalctl -u cat_ball_tracker --boot --no-pager >> "$LOG_FILE" 2>&1

echo "" >> "$LOG_FILE"
echo "========== Live Logging Started at $(date '+%Y-%m-%d %H:%M:%S') ==========" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# Now start following new logs in background
journalctl -u cat_ball_tracker -f --no-pager --since "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE" 2>&1 &
JOURNAL_PID=$!

# Save PID for cleanup
echo $JOURNAL_PID > "$LOG_DIR/.journal_pid"

# Keep old logs for 7 days, delete older
find "$LOG_DIR" -name "journal_*.log" -type f -mtime +7 -delete

echo "Logging to: $LOG_FILE"
echo "Latest log link: $LOG_DIR/latest.log"
