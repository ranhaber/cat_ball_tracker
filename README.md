# Cat Dome - Detection & Tracking System

A real-time cat and ball detection system for Raspberry Pi Zero 2W with Camera Module 3. Features motion-first detection for efficiency, a web interface for live streaming, and zone-based tracking.

**Version:** 3.2.1

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
- **📏 Multi-Rectangle Calibration** - Add one or more rectangles with known dimensions anywhere in the frame; least-squares best-fit homography
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
├── main.py                      # Application entry point (v2.4.1)
├── settings.py                  # Settings persistence
├── cat_dome.service             # Systemd service file
├── start_Cat_Dome.sh            # Startup wrapper with logging
├── install_rpi.sh               # RPi installation script
├── setup_car_dome.sh            # Full setup script (systemd, venv, model)
├── test_installation.py         # Dependency verification tests
├── test_lens_calibration.py     # Lens calibration unit tests
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
│   ├── calibration.py           # Perspective calibration (4+ points)
│   └── lens_calibration.py      # Plumb-line lens distortion correction
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
├── docs/
│   └── cloudflared-low-ram-config.md  # Cloudflare Tunnel RAM optimization
│
├── scripts/
│   └── README_LOGGING.md        # Logging system documentation
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
sudo journalctl -u cat_dome -f
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
- Enables higher resolutions (up to 2304x1296)
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

The system can show a **bird's eye view** of your detection zone with tracked objects, using perspective transformation (homography).

### Why Calibration Matters

The camera sees the world in **perspective** — far objects look smaller, parallel lines converge. Calibration teaches the system the real-world scale so it can:
- Show a correct **top-down view** of your space
- Measure real-world **distances** between detected objects
- Display accurate **side lengths** on the zone polygon

With a 120° wide-angle lens, there is also **barrel distortion** (straight lines curve at the edges). The system corrects this via **lens calibration** (separate step) before computing the perspective transform.

### Calibration: Step by Step

Add one or more **rectangles** with known dimensions at different positions across the camera view. Each rectangle is defined by clicking its 4 corners and entering its width and height.

**For each rectangle:**
1. Go to **Zone** tab → **Perspective Calibration**
2. Click **Load Camera Frame**
3. Click the **4 corners** of a rectangle on the image (clockwise or counterclockwise)
4. Enter the **width** (meters) and **height** (meters)
5. Optionally enter the **diagonal** (1→3) if the shape is not a perfect rectangle
6. Click **"Add Rectangle"**
7. Repeat for more rectangles at different positions
8. Click **"Save Calibration"** when done

### How It Works

- **Rectangle 1**: World coordinates computed exactly at origin using SSS triangles / rectangle geometry → preliminary homography
- **Rectangles 2+**: 4 pixel corners projected through the preliminary homography → accurate world positions
- **All points combined**: `findHomography` (least-squares best-fit) → final homography

| Rectangles | Total Points | Accuracy |
|------------|-------------|----------|
| **1 rectangle** | 4 | Exact `getPerspectiveTransform` — good near the rectangle |
| **2 rectangles** | 8 | `findHomography` — better across a wider area |
| **3+ rectangles** | 12+ | Best overall — covers center + edges of the frame |

### Example: 3-Rectangle Calibration (Full-Frame Coverage)

The goal is to track cat/ball x,y position accurately across the **entire** 120° camera frame.

```
Camera view (120° wide-angle, looking down at the floor):
┌─────────────────────────────────────────────────────┐
│                                                     │
│   ┌─Rect 1──┐                                      │
│   │ A large │          ┌─Rect 2──┐                  │
│   │ area in │          │ Near    │                  │
│   │ center  │          │ right   │                  │
│   │ 3×2m    │          │ edge    │                  │
│   └─────────┘          │ 0.6×0.6m│                  │
│                        └─────────┘                  │
│         ┌─Rect 3──┐                                 │
│         │ Far end │                                 │
│         │ 0.5×0.4m│                                 │
│         └─────────┘                                 │
│                                                     │
└─────────────────────────────────────────────────────┘

Rectangle 1 (center, large):
  Click 4 corners → Width: 3.00m, Height: 2.00m → Add Rectangle

Rectangle 2 (right edge):
  Click 4 corners → Width: 0.60m, Height: 0.60m → Add Rectangle

Rectangle 3 (far end):
  Click 4 corners → Width: 0.50m, Height: 0.40m → Add Rectangle

→ Save Calibration (12 points total, best-fit homography)
```

**What to use as rectangles:** Floor tiles, a doormat, a piece of cardboard, tape marks, a book — anything with known width × height and right angles.

### Calibration Pipeline

The correct order matters:

```
Step 1: Lens Calibration (once per lens)
  Mark straight lines on raw image → rational model optimizer (k1-k6)
  → corrects barrel distortion (94% improvement, 0.8px residual)

Step 2: Perspective Calibration (redo if camera moves)
  Load Camera Frame → lens-corrected snapshot (straight lines visible)
  → click rectangle corners on corrected image
  → pixels are in undistorted space → findHomography → world coords
  → Detection Zone perimeter → redistorted to raw for streaming overlay

Step 3: Cat/Ball Tracking (automatic, every frame)
  Raw camera frame → detect object at raw pixel
  → undistort_point() → same space as calibration
  → apply homography → world (x,y) position
```

**Why this order matters:**
- Lens calibration makes the image "pinhole-like" — a single homography can then accurately map the entire flat ground plane
- Without lens correction, the 120° barrel distortion means no single homography can be accurate across the full frame
- The rational distortion model (k1-k6) achieves 0.8px residual, enabling **1-4% world-coordinate accuracy** across the full FOV

### Accuracy Achieved

| Test Area | Location | Error |
|-----------|----------|-------|
| 1.2×1.8m | center-right | **0.7-1.0%** |
| 1.32×0.65m | far left edge | **0.5-2.1%** |
| 0.63×0.48m | between rects | **1.6-3.9%** |
| 0.93×0.83m | upper-right | **1-6%** |

### Tips for Accurate X,Y Tracking

- **Do lens calibration first**: Use 6+ straight lines across the image (edges of tiles, walls, door frames). The rational model (k1-k6) needs good edge coverage
- **Place 3-4 rectangles** spread across the visible floor. More rectangles = more calibration points = better homography fit
- **Measure carefully**: Width and height define the real-world scale. Use a tape measure, not estimates
- **Rectangle 1 = origin (0,0)**: All world coordinates are relative to the first corner of rectangle 1
- **Verify**: Place a known-size object at different positions and check the top-down view dimensions
- The top-down view appears below the video stream once calibrated

---

## ⚡ Performance Settings

| Setting | Description | Recommended |
|---------|-------------|-------------|
| Resolution | Camera capture size | 2304x1296 |
| Frame Skip | Skip N frames between AI runs | 1-2 |
| Threshold | Detection confidence (10-90%) | 30% |
| Confirm Frames | Consecutive frames for detection | 1-2 |

Access in **Settings** tab.

**Memory Limits (RPi Zero 2W - 512MB RAM):**
- 640x480: ~150MB
- 2304x1296: ~190-210MB (default, dual-resolution system)
- Stream resolution is separate (640x360 default)

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
| `/api/calibration` | GET/POST/DELETE | Calibration (rectangles-based) |
| `/api/calibration/debug` | GET | Calibration diagnostics (pixels, world coords, side lengths) |
| `/api/snapshot?undistort=1` | GET | Lens-corrected snapshot |
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

# Camera (dual-resolution system)
DEFAULT_RESOLUTION = (2304, 1296)   # Capture resolution (13m detection range)
DEFAULT_STREAM_RESOLUTION = (640, 360)  # Stream resolution (saves RAM)
DEFAULT_FRAMERATE = 15
DEFAULT_FRAME_SKIP = 2

# Performance Profiles: balanced, performance (default), quality
DEFAULT_PERFORMANCE_PROFILE = "performance"

# Motion-First
MOTION_FIRST_ENABLED = True
MOTION_DETECTION_SCALE = 0.35
MOTION_CROP_SIZE = (400, 400)       # Fixed crop size for AI

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
| Memory usage | 170-190MB |
| Motion detection | <10ms |
| AI detection | 200-500ms (loaded on demand) |
| Idle CPU (browser open) | ~50% (was 92%) |
| Idle CPU (browser closed) | ~25% |
| TFLite threads | 0 when idle, 3 when tracking |
| Calibration accuracy | 1-4% across full 120° FOV |

---

## 📝 Version History

- **v3.2.1** - Smart idle mode: skip frame annotation when no stream clients connected; tracker only runs with actual detections; stream client counter tracks MJPEG connections; Start/Stop Stream button on Video tab with auto-reconnect fix
- **v3.2.0** - CPU optimization: TFLite lazy load/unload (load on motion, destroy after 10s idle — eliminates spin-wait threads); dynamic OpenCV thread count (1 when idle, 4 when tracking); MJPEG stream rate-limited to ~10 FPS; Flask debug=False; JS polling reduced (status 3s, topdown 2s); thread names visible in top/htop. Idle CPU reduced from 92% to ~50%
- **v3.1.0** - Rational distortion model (k1-k6): upgrade from standard polynomial (3 radial coeffs) to rational model (6 radial + 2 tangential = 11 params). Residual error dropped from 2.63px to 0.80px (94.4% improvement). World-coordinate accuracy improved from 3-8% to 1-4% across the full 120° FOV
- **v3.0.1** - Revert joint optimization (changed lens params mid-session breaking UI consistency); fix alpha=1.0 for undistorted snapshots
- **v3.0.0** - Joint distortion+homography optimization (experimental, reverted in v3.0.1)
- **v2.8.x** - Fix perimeter coordinate pipeline: redistort perimeter points to raw for streaming overlay; fix top-down view crash (undefined variable); use global findHomography instead of nearest-rectangle
- **v2.7.x** - Undistorted snapshots for calibration/zone editors; full pipeline: lens cal → corrected snapshot → click → homography; fix camera color swap; optimal camera matrix for FOV retention
- **v2.6.x** - Regional calibration with per-rectangle homographies; fix square degenerate P3; nearest-rectangle Voronoi approach
- **v2.5.x** - Multi-rectangle calibration system; exact rectangle geometry; remove legacy side-lengths code
- **v2.5.3** - Fix multi-rectangle calibration accuracy: each rectangle's exact shape computed independently (SSS/rectangle geometry); preliminary homography used only for position and orientation, not shape; fixes severe distortion when rectangles are spread across 120° wide-angle frame; added /api/calibration/debug endpoint
- **v2.5.2** - Fix: preserve original rectangle pixel positions after save (lens undistortion was shifting displayed rectangles on canvas); undistort copies for homography, keep originals for UI
- **v2.5.1** - Clean up: update README for multi-rectangle calibration with 3-rectangle example; remove all legacy side-lengths references; update API docs
- **v2.5.0** - Multi-rectangle calibration: add one or more rectangles with known dimensions at different positions across the frame; first rectangle establishes the coordinate system, additional rectangles are projected through the preliminary homography; all points combined for best-fit homography; new UI with "Add Rectangle" workflow, rectangle list with delete, visual overlay per rectangle; replaces single-polygon approach; removes legacy N-point side-lengths code
- **v2.4.2** - Fix N-point calibration accuracy: 4-point bootstrap + homography projection (replaces pixel-direction chain that caused parallelogram distortion); fix top-down tracked objects (world_position key mismatch); polygon outline on calibration canvas; auto-clear old points on new clicks
- **v2.4.1** - Fix: preserve user-entered side lengths (no longer replaced by recomputed values); persist original side lengths in calibration file; fix N-point side length restore on page reload; closure error diagnostic logging
- **v2.4.0** - Multi-point calibration: 4+ points with N side lengths; 5+ points use findHomography (least-squares best-fit); dynamic side length inputs in UI; better accuracy across entire image
- **v2.3.3** - Fix: top-down view and calibration now consistently undistort pixels; homography computed in undistorted space; zone pixels undistorted before homography
- **v2.3.2** - Lens Calibration: reverted to standard polynomial model (rectilinear lens, not fisheye); k1 negative for barrel; 8-param (f,cx,cy,k1,k2,k3,p1,p2) with bounds; convergence logging; test verified 98.2% improvement
- **v2.3.1** - Lens Calibration: add parameter bounds (Trust Region optimizer) to prevent divergence; f=200-3000, cx/cy ±20%, k1-k4 ±1
- **v2.3.0** - Lens Calibration: switched to OpenCV FISHEYE model (angle-based θ_d = θ(1+k1θ²+k2θ⁴+k3θ⁶+k4θ⁸)) for accurate wide-angle 120° FOV correction; 7 params (f, cx, cy, k1-k4); backward compatible with legacy standard model
- **v2.2.6** - Lens Calibration: Delete Line button (by number) in UI, Analyze Lines button, line recovery from calibration file, delete lines API
- **v2.2.5** - Lens Calibration: line analysis endpoint (per-line scoring by region, curvature, length, distance from center); live progress polling; duplicate function fix
- **v2.2.4** - Lens Calibration: live progress polling (iteration X/20000 on button and status); full precision optimizer (xtol=1e-14); progress API endpoint
- **v2.2.3** - Lens Calibration UI redesign: Load Frame (no side effects), Add Line (memory), Save Lines (to file), Calibrate, Export/Import, Clear; saved vs unsaved visual distinction
- **v2.2.2** - Lens Calibration: auto-save lines to persistent file on each "New Line" (append-only); auto-load saved lines on startup; separate lines file from calibration result
- **v2.2.1** - Lens Calibration: upgraded to 8-param model (f, cx, cy, k1, k2, k3, p1, p2) with Levenberg-Marquardt; export/import lines as JSON; target 6 lines with progress bar
- **v2.2.0** - Lens Calibration: plumb-line method for radial distortion correction (k1, k2). Mark 3+ points on 6 straight lines in the image; optimizer finds distortion; before/after improvement stats; saved to lens_calibration.json; undistort applied to all pixel-to-world conversions
- **v2.1.0** - Calibration: optional diagonal (P1→P3) for exact shape of any quadrilateral (SSS triangles); rectangles auto-detected; proper axis-aligned world layout; homography now accurate for all ground-plane pixels
- **v2.0.9** - Top-down view: show side length of each polygon edge near center of side (m/cm)
- **v2.0.8** - Top-down view: show all Detection Zone polygon points (labels); 1m margin on x-y bounds
- **v2.0.7** - Top-down view: (0,0) and axes drawn at first Detection Zone polygon point so they match
- **v2.0.6** - Top-down view: draw X and Y axes through origin and label (0,0) so zone aligns with first point at 0,0
- **v2.0.5** - Calibration: use all 4 side lengths (two-circle for P3) so top-down view is a proper rectangle and Side 4 stays as entered
- **v2.0.4** - Detection Zone Clear Points: force canvas reset and clear perimeter on server (DELETE) so polygon stays erased
- **v2.0.3** - Detection Zone: fix Clear Points (polygon fully erased); show coordinate system (0,0 at first point, +X right, +Y up) and polygon
- **v2.0.2** - Calibration: enter side lengths (meters) instead of X,Y; Zone: first mark = origin (0,0), right = +X, up = +Y
- **v2.0.1** - Zone/Calibration snapshot uses full capture resolution (no stream downscale) for accurate overlay
- **v2.0.0** - Recording on detection + video file input: record clips when cat/ball detected (stop N sec after last detection), save to configurable library path; Video tab: source Live camera vs From file, file picker from library or custom path; same resolution/FPS as live for later use as input
- **v1.9.4** - PROPER FIX: Use captured_request() context manager (blocking/interrupt-driven, zero CPU waste)
- **v1.9.3** - CRITICAL FIX: Use picamera2 callbacks instead of polling (proper event-driven architecture) [PARTIAL - main loop still polling]
- **v1.9.2** - MAJOR CPU OPTIMIZATION: Use event-driven camera capture (blocking capture_request instead of polling) [FAILED - known issue]
- **v1.9.1** - Clean up: Remove verbose diagnostic logging (keep FPS fix from v1.9.0)
- **v1.9.0** - CRITICAL FIX: Fix FPS calculation bug (was counting loop iterations instead of actual processed frames)
- **v1.8.9** - Fix diagnostic logging output buffering (add flush=True to all diagnostic prints)
- **v1.8.8** - Add extensive diagnostic logging for FPS calculation, camera initialization, and settings changes
- **v1.8.7** - Fix web UI profile labels to match actual config values (CPU, RAM, JPEG quality, crop sizes)
- **v1.8.6** - Memory optimization: Reduce RAM usage to prevent swapping, lower default stream resolution to 640x360, tune all performance profiles
- **v1.8.5** - UI improvements: Move status (FPS/RAM/CPU) above video, add responsive design for mobile/tablet screens
- **v1.8.4** - Correct detection range descriptions: Balanced (0-12m), Performance (0-13m), Quality (0-12m high detail)
- **v1.8.3** - Fix camera initialization hang (removed blocking metadata capture, simplified diagnostics)
- **v1.8.2** - Add sensor mode diagnostics to verify full FOV (2304×1296 uses 2×2 binning, not crop - preserves 120° FOV)
- **v1.8.1** - Bugfix: Handle legacy settings gracefully (auto-upgrade from v1.7.0 "default" profile to "performance")
- **v1.8.0** - Dual-resolution system: 2304×1296 capture for 13m detection, user-selectable stream resolution (960×540 default). Reduced to 3 optimized performance profiles.
- **v1.7.0** - Optimize Performance profile for 120° wide FOV camera: 0-8m reliable detection (based on 50cm cat body length)
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
