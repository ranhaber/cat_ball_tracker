# Cat/Ball Detection & Tracking System for Raspberry Pi Zero 2W

A real-time object detection and tracking system designed specifically for the Raspberry Pi Zero 2W with Camera Module 3. Features a web interface for live video streaming, real-world position tracking, and control.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RPi Zero 2W System                                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Camera     │───▶│  Detection   │───▶│   Tracker    │                   │
│  │  Module 3    │    │   (TFLite)   │    │  (Centroid)  │                   │
│  │              │    │              │    │              │                   │
│  │  picamera2   │    │ MobileNetSSD │    │  + Perimeter │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│         │                   │                   │                           │
│         ▼                   ▼                   ▼                           │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │              Frame Processor                        │                    │
│  │  - Overlay bounding boxes & tracking IDs            │                    │
│  │  - Draw perimeter boundaries                        │                    │
│  │  - Apply detection mode (cat/ball)                  │                    │
│  │  - Calculate real-world positions (calibration)     │                    │
│  └─────────────────────────────────────────────────────┘                    │
│                            │                                                │
│                            ▼                                                │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │              Flask Web Server                       │                    │
│  │  - MJPEG video streaming                            │                    │
│  │  - REST API for control                             │                    │
│  │  - Static file serving                              │                    │
│  └─────────────────────────────────────────────────────┘                    │
│                            │                                                │
└────────────────────────────┼────────────────────────────────────────────────┘
                             │
                             ▼ (HTTP)
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Web Browser (Client)                                │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Tab 1: Video Stream                                │                    │
│  │  - Live MJPEG feed with detection overlays          │                    │
│  │  - Perimeter visualization                          │                    │
│  │  - Object tracking IDs                              │                    │
│  └─────────────────────────────────────────────────────┘                    │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Tab 2: Position Map                                │                    │
│  │  - Top-down view with real-world coordinates        │                    │
│  │  - Object positions in meters                       │                    │
│  └─────────────────────────────────────────────────────┘                    │
│  ┌─────────────────────────────────────────────────────┐                    │
│  │  Tab 3: Control Panel                               │                    │
│  │  - Toggle: Cat / Ball detection mode                │                    │
│  │  - Perimeter drawing interface                      │                    │
│  │  - Camera calibration for real-world coordinates    │                    │
│  │  - Performance settings                             │                    │
│  │  - System status & FPS display                      │                    │
│  └─────────────────────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

- **🐱 Cat & Ball Detection** - TensorFlow Lite-powered object detection
- **🔢 Object Tracking** - Consistent IDs across frames using centroid tracking
- **📐 Camera Calibration** - Convert pixel positions to real-world meters
- **🗺️ Position Map** - Top-down view showing object positions in meters
- **🎯 Detection Zones** - Draw perimeter to limit detection area
- **⚡ Performance Controls** - Adjust resolution, FPS, and processing speed
- **📱 Responsive Web UI** - Works on desktop and mobile browsers
- **❓ Built-in Help** - In-app guide for calibration and usage

---

## 📁 Project Structure

```
cat_ball_tracker/
├── README.md                    # This file - Project documentation
├── requirements.txt             # Python dependencies
├── config.py                    # Configuration settings
├── main.py                      # Application entry point
├── setup_car_dome.sh            # Automated setup script for Raspberry Pi
│
├── camera/
│   ├── __init__.py
│   └── camera_handler.py        # RPi Camera Module 3 interface (picamera2)
│
├── detection/
│   ├── __init__.py
│   ├── detector.py              # TensorFlow Lite MobileNet SSD detector
│   ├── tracker.py               # Centroid-based object tracking
│   ├── perimeter.py             # User-defined ROI/perimeter management
│   └── calibration.py           # Camera calibration for real-world coordinates
│
├── web/
│   ├── __init__.py
│   ├── app.py                   # Flask web server & MJPEG streaming
│   ├── templates/
│   │   └── index.html           # Main web interface (tabbed UI)
│   └── static/
│       ├── css/
│       │   └── style.css        # UI styling
│       └── js/
│           └── app.js           # Frontend JavaScript
│
└── models/
    └── .gitkeep                 # Model files go here (downloaded on first run)
```

---

## 🚀 Quick Start (Raspberry Pi OS Bookworm)

### Automated Setup

```bash
# Copy setup script to your Pi and run it
chmod +x setup_car_dome.sh
./setup_car_dome.sh
```

The script will:
1. Update system packages
2. Install all dependencies
3. Create Python virtual environment
4. Install TFLite runtime
5. Download detection model
6. Create systemd service for auto-start

### Manual Installation

#### 1. System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y \
    python3-full \
    python3-pip \
    python3-venv \
    python3-opencv \
    python3-picamera2 \
    python3-flask \
    python3-numpy \
    python3-pil \
    libatlas-base-dev
```

#### 2. Python Environment

```bash
# Create virtual environment with system packages
python3 -m venv venv --system-site-packages
source venv/bin/activate

# Install TFLite (if available for your Python version)
pip install tflite-runtime --extra-index-url https://www.piwheels.org/simple

# Install gunicorn
pip install gunicorn
```

#### 3. Run the Application

```bash
source venv/bin/activate
python main.py
```

Open your browser: `http://<raspberry-pi-ip>:5000`

---

## 📐 Camera Calibration

Calibration converts pixel coordinates to real-world positions (meters).

### How to Calibrate

1. **Place 4 markers** in your yard at known positions
   - Use cones, tape, or any visible markers
   - Measure their positions from a reference point (0,0)

2. **Open the web interface** and go to **Control Panel → Camera Calibration**

3. **Click on each marker** in the video preview

4. **Enter the X,Y coordinates** in meters when prompted

5. Click **Save Calibration**

### Example Setup

```
Your yard (10m × 8m) with camera at bottom-left:

        (0,8)────────────(10,8)
          │                 │
          │     YARD        │
          │                 │
        (0,0)────────────(10,0)
            ↑ Camera here

Calibration Points:
  Point 1: Click bottom-left  → Enter (0, 0)
  Point 2: Click bottom-right → Enter (10, 0)
  Point 3: Click top-right    → Enter (10, 8)
  Point 4: Click top-left     → Enter (0, 8)
```

### After Calibration

- Go to the **Position Map** tab
- See detected objects displayed on a top-down map
- Object positions shown in meters from origin

---

## ⚡ Performance Optimization

The Pi Zero 2W has limited resources. Use these settings to optimize:

| Setting | Low CPU | Balanced | Best Quality |
|---------|---------|----------|--------------|
| Resolution | 320×240 | 480×360 | 640×480 |
| Frame Rate | 5 FPS | 10 FPS | 15 FPS |
| Frame Skip | 5 | 2-3 | 1 |

Access these settings in **Control Panel → Performance Settings**

---

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/video_feed` | GET | MJPEG video stream |
| `/api/status` | GET | System status (FPS, detections, etc.) |
| `/api/mode` | GET/POST | Detection mode (cat/ball) |
| `/api/perimeter` | GET/POST/DELETE | Detection zone management |
| `/api/calibration` | GET/POST/DELETE | Camera calibration |
| `/api/performance` | GET | Performance settings |
| `/api/performance/resolution` | POST | Set resolution |
| `/api/performance/framerate` | POST | Set frame rate |
| `/api/performance/frameskip` | POST | Set frame skip |

---

## ⚙️ Configuration

Edit `config.py` to customize:

```python
# Detection settings
DETECTION_THRESHOLD = 0.5      # Confidence threshold (0.0 - 1.0)
DEFAULT_DETECTION_MODE = "cat" # Default mode: "cat" or "ball"

# Camera settings
FRAME_WIDTH = 640              # Default resolution
FRAME_HEIGHT = 480
TARGET_FPS = 15

# Calibration
CAMERA_HEIGHT_METERS = 3.0     # Camera height (for reference)

# Server settings
HOST = "0.0.0.0"
PORT = 5000
```

---

## 📊 Performance Expectations

| Metric | Expected Value |
|--------|----------------|
| Detection FPS | 3-5 FPS (with TFLite) |
| Tracking overhead | <10ms |
| Streaming latency | ~100-200ms |
| Memory usage | ~300-400MB |

**Note**: Without TFLite, the system runs in mock mode for testing.

---

## 🛠️ Troubleshooting

### Camera not detected
```bash
libcamera-hello --list-cameras
```

### TFLite not installing
- Use Raspberry Pi OS Bookworm (Debian 12)
- Use Python 3.11 (not 3.13)
- The app works in mock mode without TFLite

### Low FPS
- Reduce resolution in Performance Settings
- Increase frame skip
- Close other applications

### Calibration not working
- Ensure 4 points are placed
- Points should be spread across the view
- Re-measure real-world distances if positions are wrong

---

## 🔄 Auto-Start on Boot

The setup script creates a systemd service:

```bash
# Enable auto-start
sudo systemctl enable cat-tracker

# Manual control
sudo systemctl start cat-tracker
sudo systemctl stop cat-tracker
sudo systemctl status cat-tracker

# View logs
journalctl -u cat-tracker -f
```

---

## 📝 License

MIT License - Feel free to use and modify for your projects.

---

## 🤝 Acknowledgments

- TensorFlow Lite team for edge-optimized models
- Raspberry Pi Foundation for picamera2
- COCO dataset for pre-trained object classes
- OpenCV for computer vision tools