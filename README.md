# Cat Dome - Detection & Tracking System

A real-time cat and ball detection system for Raspberry Pi Zero 2W with Camera Module 3. Features motion-first detection for efficiency, a web interface for live streaming, and zone-based tracking.

**Version:** 1.8.1

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RPi Zero 2W System                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Camera     │───▶│   Motion     │───▶│  Detection   │                   │
│  │  Module 3    │    │  Detector    │    │   (TFLite)   │                   │
│  │  (IMX708)    │    │ (Low memory) │    │ MobileNetSSD │                   │
│  │  picamera2   │    │              │    │              │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│         │                   │                   │                           │
│         │                   │                   ▼                           │
│         │                   │          ┌──────────────┐                     │
│         │                   │          │   Tracker    │                     │
│         │                   │          │  (Centroid)  │                     │
│         │                   │          │ + Perimeter  │                     │
│         │                   │          └──────────────┘                     │
│         ▼                   ▼                   │                           │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │              Frame Processor                        │                    │
│  │  - Motion detection (runs first, saves CPU)         │                    │
│  │  - AI detection only when motion detected           │                    │
│  │  - Draw perimeter and detection boxes               │                    │
│  │  - Overlay FPS, RAM, CPU temp status                │                    │
│  └─────────────────────────────────────────────────────┘                    │
│                            │                                                │
│                            ▼                                                │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │              Flask Web Server                       │                    │
│  │  - MJPEG video streaming                            │                    │
│  │  - REST API for control                             │                    │
│  │  - Settings persistence (JSON)                      │                    │
│  └─────────────────────────────────────────────────────┘                    │
│                            │                                                │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │
                             ▼ (HTTP)
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Web Browser (Client)                                │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Tab 1: 📹 Video Stream                             │                    │
│  │  - Live MJPEG feed with detection overlays          │                    │
│  │  - Motion status indicator                          │                    │
│  │  - RAM/CPU temp display                             │                    │
│  │  - Show motion regions checkbox                     │                    │
│  └─────────────────────────────────────────────────────┘                    │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Tab 2: ⚙️ Settings                                 │                    │
│  │  - Detection mode toggle (Cat / Ball)               │                    │
│  │  - Camera resolution selector                       │                    │
│  │  - Frame skip (performance tuning)                  │                    │
│  │  - System status (FPS, RAM, CPU temp)               │                    │
│  └─────────────────────────────────────────────────────┘                    │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Tab 3: 📍 Zone                                     │                    │
│  │  - Detection zone editor (click on camera frame)    │                    │
│  │  - Distance calibration (line-based)                │                    │
│  └─────────────────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

- **🐱 Cat & Ball Detection** - TensorFlow Lite MobileNet SSD
- **🎯 Motion-First Detection** - AI only runs when motion detected (saves ~30% CPU/memory)
- **🎯 Fixed 300x300 Crop** - No-scale AI input preserves object pixel size for better detection
- **⏱️ Temporal Confirmation** - Require detection in N consecutive frames (reduces false positives)
- **🔢 Object Tracking** - Consistent IDs across frames using centroid tracking
- **📍 Detection Zones** - Draw perimeter on camera snapshot to limit detection area
- **🗺️ Top-Down View** - Bird's eye view of detection zone with tracked objects (perspective transform)
- **📏 4-Point Calibration** - Define real-world X,Y coordinates for perspective mapping
- **⚡ Performance Controls** - Resolution, frame skip, threshold, and confirmation adjustment
- **💾 Settings Persistence** - All settings saved and restored on reboot
- **📊 System Monitoring** - RAM usage and CPU temperature display
- **📱 Responsive Web UI** - Works on desktop and mobile browsers

---

## 📁 Project Structure

```
cat_ball_tracker/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration settings
├── main.py                      # Application entry point (v1.5.0)
├── settings.py                  # Settings persistence
├── cat_dome.service             # Systemd service file
│
├── camera/
│   ├── __init__.py
│   └── camera_handler.py        # RPi Camera Module 3 interface
│
├── detection/
│   ├── __init__.py
│   ├── detector.py              # TensorFlow Lite detector
│   ├── tracker.py               # Centroid-based tracking
│   ├── perimeter.py             # Detection zone management
│   ├── motion_detector.py       # Lightweight motion detection
│   └── calibration.py           # Distance calibration
│
├── web/
│   ├── __init__.py
│   ├── app.py                   # Flask server & video processor
│   ├── templates/
│   │   └── index.html           # Web interface (3 tabs)
│   └── static/
│       ├── css/style.css
│       └── js/app.js
│
└── models/
    └── (downloaded on first run)
```

---

## 🚀 Quick Start

### Prerequisites

- Raspberry Pi Zero 2W
- Camera Module 3 (IMX708)
- Raspberry Pi OS Bookworm (64-bit)

### Installation

```bash
# Clone or copy the project
cd ~
git clone https://github.com/ranhaber/cat_ball_tracker.git cat_ball_tracker
cd cat_ball_tracker

# IMPORTANT: Set executable permissions for shell scripts
chmod +x start_Cat_Dome.sh

# Install system dependencies
sudo apt update
sudo apt install -y python3-full python3-pip python3-venv \
    python3-opencv python3-picamera2 python3-flask \
    python3-numpy python3-pil libopenblas-dev

# Create virtual environment
python3 -m venv venv --system-site-packages
source venv/bin/activate

# Install TFLite (optional - works without it in mock mode)
pip install tflite-runtime --extra-index-url https://www.piwheels.org/simple

# Run the application
python main.py
```

Open browser: `http://<raspberry-pi-ip>:5000`

### Auto-Start on Boot

```bash
# Ensure start_Cat_Dome.sh is executable
chmod +x start_Cat_Dome.sh

# Copy service file
sudo cp cat_dome.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable cat_dome
sudo systemctl start cat_dome

# Check status
sudo systemctl status cat_dome

# View logs
sudo journalctl -u cat_ball_tracker -f
```

---

## 🎯 Motion-First Detection

Cat Dome uses a two-stage detection approach to save resources:

1. **Motion Detection** (always running, low CPU)
   - Runs on 1/4 resolution
   - Compares consecutive frames
   - Detects areas with movement

2. **AI Detection** (only when motion detected)
   - TensorFlow Lite MobileNet SSD
   - **Fixed 300x300 crop** centered on motion (no scaling!)
   - Preserves object pixel size for better small object detection
   - Filters by cat or ball class

3. **Temporal Confirmation** (optional)
   - Require detection in N consecutive frames before confirming
   - Slider in Settings: 1 = instant (default), 2-5 = require multiple frames
   - Reduces false positives from single-frame noise

**Benefits:**
- ~30% less CPU usage during idle
- Enables higher resolutions (up to 1536x864)
- Better detection for small/distant objects (no scaling loss)
- Reduced false positives with temporal confirmation

---

## 📍 Detection Zone Setup

1. Go to **Zone** tab
2. Click **Load Camera Frame** - loads full-resolution snapshot
3. Click to add polygon points (minimum 3)
4. Click **Save Zone**
5. Only objects inside the zone will be detected

---

## 🗺️ Top-Down View & Perspective Calibration

The system can show a **bird's eye view** of your detection zone with tracked objects, using perspective transformation.

### 4-Point Calibration Setup

1. Go to **Zone** tab → **Perspective Calibration**
2. Click **Load Camera Frame**
3. Click **4 points** on the ground in the camera view
4. For each point, enter its real-world X,Y coordinates (in meters):
   - **X** = left-right position (0 = camera center, positive = right)
   - **Y** = near-far position (0 = camera position, positive = farther away)
5. Click **Save Calibration**

### Tips for Accurate Calibration

- Use markers on the ground (tape, cones, etc.) at known positions
- Points should form a quadrilateral covering your detection area
- More spread-out points = more accurate transformation
- The top-down view appears below the video stream once calibrated

---

## ⚡ Performance Settings

| Setting | Description | Recommended |
|---------|-------------|-------------|
| Resolution | Camera capture size | 1536x864 |
| Frame Skip | Skip N frames between AI runs | 1-2 |
| Threshold | Detection confidence (10-90%) | 30% |
| Confirm Frames | Consecutive frames for detection | 1-2 |

Access in **Settings** tab.

**Memory Limits (RPi Zero 2W - 512MB RAM):**
- 640x480: ~150MB
- 1536x864: ~250MB
- 1920x1080: May fail (too much RAM)

---

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/video_feed` | GET | MJPEG stream |
| `/video_feed?snapshot=1` | GET | Single JPEG frame |
| `/api/status` | GET | System status |
| `/api/mode` | GET/POST | Detection mode (cat/ball) |
| `/api/perimeter` | GET/POST/DELETE | Detection zone |
| `/api/calibration` | GET/DELETE | Calibration status |
| `/api/calibration/lines` | GET/POST | Calibration lines |
| `/api/motion` | GET | Motion detection status |
| `/api/motion/toggle` | POST | Toggle motion-first mode |
| `/api/motion/show_regions` | POST | Toggle motion region display |
| `/api/performance` | GET | Performance settings |
| `/api/performance/resolution` | POST | Set resolution |
| `/api/performance/frameskip` | POST | Set frame skip |
| `/api/performance/threshold` | GET/POST | Detection threshold |
| `/api/performance/confirm_frames` | GET/POST | Temporal confirmation frames |
| `/api/topdown` | GET | Top-down view data (perimeter + objects in world coords) |

---

## ⚙️ Configuration

Edit `config.py`:

```python
# Detection
DETECTION_THRESHOLD = 0.3           # Confidence threshold (0.1 - 0.9)
DEFAULT_DETECTION_MODE = "cat"      # or "ball"
DETECTION_CONFIRM_FRAMES = 1        # Require N consecutive frames (1-5)

# Camera
DEFAULT_RESOLUTION = (1536, 864)
DEFAULT_FRAMERATE = 15
DEFAULT_FRAME_SKIP = 2

# Motion-First
MOTION_FIRST_ENABLED = True
MOTION_DETECTION_SCALE = 0.25
MOTION_CROP_SIZE = (300, 300)       # Fixed crop size (matches AI input)

# Server
HOST = "0.0.0.0"
PORT = 5000
```

---

## 🛠️ Troubleshooting

### Camera not detected
```bash
rpicam-hello --list-cameras
```

### Service not starting
```bash
sudo journalctl -u cat_ball_tracker -n 50
```

### "Cannot allocate memory"
- Reduce resolution to 1536x864 or lower
- Check RAM: `free -h`

### Perimeter in wrong position
- Delete `perimeter.json` and recreate
- Ensure snapshot resolution matches camera resolution

### TFLite not available
- System works in mock mode (random detections)
- Install from piwheels if Python version supported

### Service fails with "exit code 203/EXEC"
- The `start_Cat_Dome.sh` script is not executable
- Fix: `chmod +x ~/cat_ball_tracker/start_Cat_Dome.sh`
- Then restart: `sudo systemctl restart cat_dome`

---

## 📊 Expected Performance

| Metric | Value |
|--------|-------|
| FPS (with TFLite) | 3-8 FPS |
| FPS (mock mode) | 15+ FPS |
| Memory usage | 180-250MB |
| Motion detection | <10ms |
| AI detection | 200-500ms |

---

## 📝 Version History

- **v1.7.0** - Optimize Performance profile for 120° wide FOV camera: 0-8m reliable detection (based on 50cm cat body length)
- **v1.8.0** - Dual-resolution system: 2304×1296 capture for 13m detection, user-selectable stream resolution (960×540 default). Reduced to 3 optimized performance profiles.
- **v1.8.1** - Bugfix: Handle legacy settings gracefully (auto-upgrade from v1.7.0 "default" profile to "performance")
- **v1.6.6** - Rename systemd service from cat_ball_tracker to cat_dome for consistent branding
- **v1.6.5** - UI improvements: Refresh all settings after profile change, clarify profile-controlled vs independent settings
- **v1.6.4** - Add performance debugging (motion/AI/JPEG timing), profile persistence, show profile parameters in UI
- **v1.6.3** - Bugfix: Add thread safety to motion detector (prevents race condition crashes)
- **v1.6.2** - Bugfix: Fix motion detector crash on profile changes (frame size mismatch)
- **v1.6.1** - Bugfix: Fix camera attribute errors (is_running, get_resolution)
- **v1.6.0** - Performance profile system (4 user-selectable optimization presets: Default, Balanced, Performance, Quality)
- **v1.5.2** - Phase 1 optimizations: Memory management, GPU acceleration, color conversion optimization
- **v1.5.0** - Top-down view (bird's eye), 4-point perspective calibration
- **v1.4.0** - Fixed 300x300 crop (no scaling), temporal confirmation slider
- **v1.3.0** - Detection threshold slider, settings logging, UI improvements
- **v1.2.0** - Motion-first detection, zone editor with snapshots, settings persistence
- **v1.1.0** - RAM/CPU monitoring, resolution controls
- **v1.0.0** - Initial release

---

## 📝 License

MIT License - Feel free to use and modify.
