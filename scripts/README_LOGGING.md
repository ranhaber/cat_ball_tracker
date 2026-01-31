# Automatic Journal Logging Setup

This directory contains scripts for automatically logging systemd journals to dated files.

## How It Works

- Each time the service starts, a new log file is created: `logs/journal_YYYYMMDD_HHMMSS.log`
- A symlink `logs/latest.log` always points to the most recent log
- Logs older than 7 days are automatically deleted
- Journal logging runs in the background and captures all service output

## Installation

### Option 1: Systemd Service (Recommended)

1. Copy the service files:
```bash
cd ~/cat_ball_tracker
sudo cp scripts/cat_ball_tracker_logging.service /etc/systemd/system/
sudo systemctl daemon-reload
```

2. Enable the logging service:
```bash
sudo systemctl enable cat_ball_tracker_logging.service
sudo systemctl start cat_ball_tracker_logging.service
```

3. Restart the main service to start logging:
```bash
sudo systemctl restart cat_ball_tracker
```

### Option 2: Manual Script Execution

Run the logging script manually after service starts:
```bash
cd ~/cat_ball_tracker
./scripts/start_with_logging.sh &
```

## Viewing Logs

### View latest log:
```bash
tail -f ~/cat_ball_tracker/logs/latest.log
```

### List all logs:
```bash
ls -lh ~/cat_ball_tracker/logs/
```

### View specific log:
```bash
cat ~/cat_ball_tracker/logs/journal_20260131_120000.log
```

### Search logs:
```bash
grep "ERROR" ~/cat_ball_tracker/logs/latest.log
grep "Profile" ~/cat_ball_tracker/logs/*.log
```

## Log Management

### Change retention period:

Edit `start_with_logging.sh` and change:
```bash
find "$LOG_DIR" -name "journal_*.log" -type f -mtime +7 -delete
```
Change `+7` to desired days.

### Manually clean old logs:
```bash
find ~/cat_ball_tracker/logs -name "journal_*.log" -mtime +7 -delete
```

### Disable logging:
```bash
sudo systemctl stop cat_ball_tracker_logging.service
sudo systemctl disable cat_ball_tracker_logging.service
```

## Log Location

All logs are stored in: `~/cat_ball_tracker/logs/`

Format: `journal_YYYYMMDD_HHMMSS.log`

Example: `journal_20260131_143052.log` (Started on 2026-01-31 at 14:30:52)
