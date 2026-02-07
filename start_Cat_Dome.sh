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

# Start the application with gunicorn (production server, lower CPU than werkzeug)
# -w 1: single worker (camera can only be opened once)
# --threads 4: handle MJPEG stream + API requests concurrently
# --timeout 0: don't kill long-lived MJPEG connections
# Add timestamp to each line using awk with line buffering
cd /home/ranhaber/cat_ball_tracker
exec /home/ranhaber/cat_ball_tracker/venv/bin/gunicorn \
  -w 1 \
  --threads 4 \
  --timeout 0 \
  -b 0.0.0.0:5000 \
  --access-logfile - \
  --error-logfile - \
  'web.app:gunicorn_app' 2>&1 | \
  awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0; fflush(); }' | \
  tee -a "$LOG_FILE"
