# Automatic Journal Logging

The Cat Ball Tracker automatically logs all output to dated files on each service start.

## How It Works

- Each time the service starts, a new log file is created: `logs/journal_YYYYMMDD_HHMMSS.log`
- A symlink `logs/latest.log` always points to the most recent log
- Logs older than 7 days are automatically deleted
- Logs go to BOTH journald AND dated files simultaneously

## Installation

Logging is built into the main service! Just deploy the updated service file:

```bash
cd ~/cat_ball_tracker
git pull

# Make the wrapper script executable
chmod +x start_Cat_Dome.sh

# Install/update the service file
sudo cp cat_dome.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart cat_dome
```

That's it! Logs will be automatically created in `~/cat_ball_tracker/logs/`

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

Edit `start_Cat_Dome.sh` and change:
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
