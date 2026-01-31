#!/bin/bash
#
# Wrapper script that starts the Cat Ball Tracker with automatic logging
# This script is called by systemd service
#

# Log directory
LOG_DIR="/home/ranhaber/cat_ball_tracker/logs"
mkdir -p "$LOG_DIR"

# Generate log filename with current timestamp
LOG_FILE="$LOG_DIR/journal_$(date +%Y%m%d_%H%M%S).log"

# Write startup marker
{
    echo "========================================"
    echo "Cat Ball Tracker Started"
    echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "========================================"
    echo ""
    echo "System Info:"
    echo "  Hostname: $(hostname)"
    echo "  Python: $(python3 --version 2>&1)"
    echo "  RAM Total: $(free -h | awk '/^Mem:/ {print $2}')"
    echo "  Disk Free: $(df -h /home | awk 'NR==2 {print $4}')"
    echo ""
    echo "========================================"
    echo ""
} > "$LOG_FILE"

# Create symlink to latest log
ln -sf "$LOG_FILE" "$LOG_DIR/latest.log"

# Keep old logs for 7 days, delete older
find "$LOG_DIR" -name "journal_*.log" -type f -mtime +7 -delete 2>/dev/null || true

# Start the application with output redirected to log file AND stdout (for systemd journal)
# Use -u flag to force unbuffered output so logs appear immediately
# Add timestamp to each line
cd /home/ranhaber/cat_ball_tracker
exec /home/ranhaber/cat_ball_tracker/venv/bin/python -u main.py 2>&1 | \
  while IFS= read -r line; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $line"
  done | tee -a "$LOG_FILE"
