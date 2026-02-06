# Cloudflared Low-RAM Configuration (Raspberry Pi)

Use this config to reduce cloudflared memory usage while keeping your tunnel and Zero Trust working.

## 1. Update tunnel config on the Pi

SSH into your Pi and edit the config:

```bash
sudo nano /etc/cloudflared/config.yml
```

**Replace the contents with** (use your real tunnel ID and credentials path):

```yaml
tunnel: 3221f10f-dfb2-4812-8e8a-6aaf33da6b45
credentials-file: /etc/cloudflared/3221f10f-dfb2-4812-8e8a-6aaf33da6b45.json

# --- Low-RAM options ---
protocol: http2
loglevel: warn

ingress:
  - hostname: catdome.habertech.org
    service: http://localhost:5000
  - service: http_status:404
```

**What this does:**
- `protocol: http2` – Use HTTP/2 instead of QUIC (less RAM, no UDP buffers).
- `loglevel: warn` – Fewer log messages, less buffering.

Save and exit (Ctrl+X, Y, Enter).

## 2. Disable metrics and pass protocol via systemd (optional, saves more RAM)

Create a drop-in override so the service does not start the metrics server and uses your config:

```bash
sudo mkdir -p /etc/systemd/system/cloudflared.service.d
sudo nano /etc/systemd/system/cloudflared.service.d/override.conf
```

Paste:

```ini
[Service]
# Disable metrics server to save RAM
Environment="TUNNEL_METRICS="
# Optional: reduce Go GC memory (default 100, lower = less RAM, more GC)
Environment="GOGC=50"
```

Save and exit, then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart cloudflared
sudo systemctl status cloudflared
```

## 3. Verify

- In browser: https://catdome.habertech.org (should still work with Zero Trust).
- Check RAM: `free -h` before/after, or `ps -o rss= -p $(pgrep cloudflared)` (RSS in KB).

## 4. If something breaks

Revert config to only tunnel + ingress (remove `protocol` and `loglevel`), and remove the override:

```bash
sudo rm /etc/systemd/system/cloudflared.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart cloudflared
```

## Summary of changes

| Change            | Effect                          |
|-------------------|---------------------------------|
| `protocol: http2` | Less RAM vs QUIC, no UDP buffers |
| `loglevel: warn`  | Less log I/O and buffering      |
| `TUNNEL_METRICS=` | No metrics server               |
| `GOGC=50`         | Lower heap target, more GC       |
