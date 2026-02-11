# Cat Dome - Detection & Tracking System

A real-time cat and ball detection system for Raspberry Pi Zero 2W with Camera Module 3. Features motion-first detection for efficiency, a web interface for live streaming, and zone-based tracking.

**Version:** 3.8.1

**For agents and developers:** See **[AGENTS.md](AGENTS.md)** for project guidelines, concurrency rules, and where to find things. Use it as the single entry point before diving into code or other docs.

---

## 🎯 Core Requirement

The system must identify and track a cat that enters the Detection Zone and continue tracking until the cat leaves the zone. Maximum detection and tracking range: **13 meters**. TFLite AI must remain active as long as a cat is detected — it does not unload while a cat is present.

---

## 🏗️ System Architecture

Detection and tracking work **independently of the web UI** — the system runs headless via systemd.

```
┌─────────────────────────────────────────────────────────────────────┐
│  RPi Zero 2W (416MB RAM, 4-core ARM Cortex-A53)                     │
│                                                                     │
│  Thread: CatDome-Proc (processing loop, always running)             │
│  ┌───────────┐    ┌──────────────┐    ┌──────────────────┐         │
│  │  Camera   │───▶│   Motion     │───▶│  TFLite AI       │         │
│  │ Module 3  │    │  Detector    │    │  (load on motion, │         │
│  │ 2304×1296 │    │ (every 2nd   │    │   active while   │         │
│  │ 2 buffers │    │  frame)      │    │   cat in zone,   │         │
│  │           │    │              │    │   unload 10s     │         │
│  │           │    │              │    │   after leaves)  │         │
│  └───────────┘    └──────────────┘    └──────────────────┘         │
│       │                 │                    │                       │
│       │                 │                    ▼                       │
│       │                 │           ┌──────────────┐                │
│       │                 │           │   Tracker    │                │
│       │                 │           │  (only when  │                │
│       │                 │           │  detections) │                │
│       │                 │           └──────────────┘                │
│       │                 │                    │                       │
│       ▼                 ▼                    ▼                       │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Lens Calibration (rational k1-k6, 94% improvement) │            │
│  │  → undistort detection pixel → homography → world xy │            │
│  └─────────────────────────────────────────────────────┘            │
│       │                                                             │
│       ▼ (only if stream clients connected)                          │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Frame Annotation (skip when nobody watches)         │            │
│  │  - Draw perimeter, boxes, FPS overlay                │            │
│  │  - Store frame for MJPEG streaming                   │            │
│  └─────────────────────────────────────────────────────┘            │
│                                                                     │
│  Thread: CatDome-Main (Flask web server)                            │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Flask Web Server                                    │            │
│  │  - MJPEG streaming (rate-limited ~10fps)             │            │
│  │  - REST API (status, calibration, settings)          │            │
│  │  - Lens-corrected snapshots for calibration          │            │
│  └─────────────────────────────────────────────────────┘            │
│                                                                     │
│  CPU optimization:                                                  │
│  - OpenCV: 1 thread idle, 4 when tracking                           │
│  - TFLite: 0 threads idle, 3 when detecting                        │
│  - MJPEG: rate-limited, skipped when no clients                     │
│  - Idle CPU: ~50% (was 92% before optimization)                     │
└─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼ (HTTP, optional)
┌─────────────────────────────────────────────────────────────────────┐
│  Web Browser (monitoring only — NOT required for detection)         │
│  ┌─────────────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ Tab 1: Video Stream │ │ Tab 2: Settng│ │ Tab 3: Zone          │ │
│  │ - Start/Stop button │ │ - Mode/FPS   │ │ - Detection Zone     │ │
│  │ - Live MJPEG feed   │ │ - Profiles   │ │ - Perspective Cal    │ │
│  │ - Top-Down View     │ │ - Motion     │ │ - Lens Calibration   │ │
│  └─────────────────────┘ └──────────────┘ └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

- **🐱 Cat & Ball Detection** - TensorFlow Lite MobileNet SSD (loaded on demand, unloaded after 10s idle)
- **🎯 Motion-First Detection** - AI only runs when motion detected inside the detection zone
- **🎯 Fixed 300x300 Crop** - No-scale AI input preserves object pixel size for better detection
- **⏱️ Temporal Confirmation** - Require detection in N consecutive frames (reduces false positives)
- **🔢 Object Tracking** - Consistent IDs across frames using centroid tracking (only runs with detections)
- **📍 Detection Zones** - Draw perimeter on lens-corrected camera snapshot
- **🗺️ Top-Down View** - Bird's eye view with tracked objects (1-4% world-coordinate accuracy)
- **📏 Multi-Rectangle Calibration** - Multiple rectangles with known dimensions; global findHomography
- **🔭 Lens Calibration** - Rational distortion model (k1-k6); 94.4% improvement, 0.8px residual
- **⚡ Smart Idle Mode** - Skip frame annotation when nobody watches; TFLite/OpenCV threads only active when needed
- **💾 Settings Persistence** - All settings saved and restored on reboot
- **📊 System Monitoring** - FPS, RAM, CPU temp, motion status, AI runs counter
- **📱 Responsive Web UI** - Works on desktop and mobile; Start/Stop Stream button

---

## 🔄 Detection Phase State Machine

The processing loop uses a 4-phase state machine to manage TFLite and CPU:

```
PHASE 1: IDLE                          PHASE 2: ACQUISITION
+----------------------------+         +----------------------------+
| Motion detection only      |         | TFLite loads, runs every   |
| (Detection Zone only)      | motion  | frame, searching for cat   |
| TFLite: NOT loaded         |-------->| TFLite: LOADED             |
| CPU: ~30%  RAM: ~75%       |in zone  | CPU: ~80%  RAM: ~87%       |
+----------------------------+         +-------------+--------------+
       ^                                      cat found |    no motion
       |                                               v    for 10s -> IDLE
       | no detection          PHASE 3: TRACKING       |
       | for 30s              +----------------------------+
       +----------------------| Cat confirmed              |
       |                      | TFLite every 3rd frame     |
       |                      | Motion crop for AI         |
       |                      | CPU: ~60%  RAM: ~87%       |
       |                      +-------------+--------------+
       |                           motion stops |
       |                                       v
       | no detection          PHASE 4: WATCH MODE
       | for 30s              +----------------------------+
       +----------------------| No motion, cat still there |
                              | TFLite every 2nd frame     |
                              | Full frame scan (no crop)  |
                              | Cat moves -> TRACKING      |
                              | CPU: ~50%  RAM: ~87%       |
                              +----------------------------+
```

**Key rules:**
- Motion detection only inside the Detection Zone (all phases)
- TFLite uses crop around motion area (ACQUISITION/TRACKING) or full frame (WATCH)
- Cat gone for 30 seconds -> TFLite unloads, memory reclaimed, back to IDLE
- Inject Cat test mode forces ACQUISITION phase on enable

### RAM usage by phase (code-derived estimate)

These numbers are **estimated from the code without running on the RPi**. They approximate **process RSS** (resident set size) in MB. System-wide percentages in the diagram above (~75% IDLE, ~87% ACQ/TRACK/WATCH) include kernel, GPU, and other processes.

| Phase | TFLite | Estimated process RAM (MB) | Notes |
|-------|--------|----------------------------|--------|
| **IDLE** | Not loaded | **~120–145** | Motion only; 1 OpenCV thread; no AI buffers |
| **ACQUISITION** | Loaded | **~145–175** | +TFLite model + interpreter + pre-alloc input (300×300×3); 4 OpenCV threads |
| **TRACKING** | Loaded | **~145–175** | Same as ACQUISITION (TFLite every 3rd frame) |
| **WATCH** | Loaded | **~145–175** | Same; TFLite every 2nd frame, full-frame scan |

**Component breakdown (approximate):**

| Component | Size (MB) | Source |
|-----------|-----------|--------|
| Python + Flask + OpenCV + app | ~50–70 | Baseline imports and app code |
| picamera2 (2 buffers @ 2304×1296×3) | ~18 | `config.DEFAULT_RESOLUTION`, 2 buffers |
| Current frame reference / snapshot | ~9 | One full frame at capture resolution |
| Motion detector | ~2–3 | 3× scaled frames (576×324 float32), _bg_sum, _bg_buffer, gray/delta/thresh |
| TFLite (when loaded) | ~18–28 | Model file ~6–7 MB; interpreter + allocated tensors typically 2–3× on load; pre-alloc input 0.27 MB |
| Stream (when clients > 0) | ~0.8–1 | stream_frame 640×360×3 + JPEG cache |
| Recording (when active) | ~1–3 | VideoWriter internal buffer |
| Misc (stacks, allocator, libs) | ~10–15 | Threads, OpenCV temporaries |

**Accuracy of this estimate:** **Medium (±15–25%)**. Exact buffer sizes (frame, motion, TFLite input) are known from code; TFLite and picamera2 in-process footprint depend on the runtime and driver and are not measured here. To get real numbers on the RPi: use the Developer tab (system info / process RSS) or `ps -o rss= -p $(pgrep -f "python.*main")` and divide by 1024 for MB.

### Logging (non-blocking)

Hot-path logging uses **async log** (`processing/async_log.py`) so the process loop never blocks on stdout/pipe/journal I/O. Messages are enqueued and written by a dedicated **CatDome-Log** thread. Use `plog(msg, *args)` in the process loop and detector/motion code; startup calls `setup_async_logging()` from `main.py`. This improves debugging: you can add more log lines without affecting loop timing or risking pipe back-pressure.

### Inject Cat stop — CPU spike and debug plan

**2. Why CPU can hit 100% when stopping Inject Cat**

- While Inject Cat is **on**, the loop runs `time.sleep(INJECT_MODE_SLEEP_SEC)` every iteration (rate-limited).
- When you turn Inject Cat **off**, that sleep is no longer run. The loop then runs as fast as the camera and motion path allow. If the camera returns frames very quickly (or with a mock camera returns immediately), the loop can **spin with no sleep** and use 100% of one core.
- Cleanup (motion reset, TFLite unload, `cv2.setNumThreads(1)`) runs at the **start of the next** process-loop iteration. If the loop is already spinning, you still get one iteration where cleanup runs; after that, if there is no other rate limit, the loop keeps spinning in IDLE (motion only) and CPU stays high.
- On a real RPi with picamera2, `get_request()` is blocking, so the loop is often rate-limited by the camera. On a dev machine with mock camera, `get_frame()` can return a frame every iteration and the only sleep is when no frame is ready (`time.sleep(0.01)`), so the loop can run at very high rate.

**3. Will prints to the log help?**

Yes. Logging **when** cleanup runs (e.g. `[INJECT CLEANUP] motion reset, TFLite unload, OpenCV threads=1`) and the current phase confirms that the process loop saw the flags and performed unload/setNumThreads. If you see that line and CPU is still high, the cause is the **tight loop** (no sleep). If you never see that line, cleanup is delayed or not run (e.g. loop stuck elsewhere).

**4. Will the change to async logging improve debugging?**

Yes. With async logging (`plog`), you can add more log lines in the hot path (e.g. every N iterations, or on phase/cleanup) without blocking the loop or causing journal/pipe back-pressure. So you can safely add diagnostics (cleanup, phase, loop rate) and see them in the journal without affecting the CPU or timing you are trying to observe.

**5. Plan to check the cause of the CPU problem**

| Step | Action | What to check |
|------|--------|----------------|
| 1 | Add a one-line diagnostic when inject cleanup runs | In `_process_loop`, right after `detector.unload_model()` and `cv2.setNumThreads(1)`, call `plog("[INJECT CLEANUP] motion reset, TFLite unload, OpenCV threads=1")`. Restart, turn Inject Cat on then off, watch journal. | If the line appears: cleanup ran. If CPU is still high, the loop is spinning (no sleep). If the line never appears: cleanup not run this iteration (loop stuck or flags not set). |
| 2 | Confirm phase after stop | Log phase once when entering the phase block after cleanup, e.g. `plog("[INJECT CLEANUP] phase after=%s", self._phase)`. | Phase should be IDLE. |
| 3 | (Optional) Measure loop rate | Every 100 iterations, log `plog("[LOOP] iter=%s rate=%.1f/s", self.frame_count, rate)`. | If rate is very high (e.g. hundreds per second) when not in inject mode, the loop is not rate-limited. |
| 4 | Add a small rate-limit when not in inject mode | After the main loop body (e.g. after the inject sleep block), when `inject_cat` is False, add `time.sleep(0.001)` or target 2× FPS. | Re-test: CPU should drop. Confirms cause was tight loop. |
| 5 | On RPi: check thread count | After repro, run `ps -eLf \| grep python` or use Developer tab (thread count). | If many threads and high CPU, TFLite or OpenCV might not have been reduced (unload/setNumThreads not run or delayed). |

---

## ⏱️ Frame-to-TFLite timeline

End-to-end sequence from retrieving a new frame until TFLite inference finishes (one iteration of the process loop when `skip_counter >= frame_skip` and phase runs AI).

```mermaid
sequenceDiagram
    participant Loop as Process loop
    participant Cam as Camera
    participant Motion as Motion detector
    participant Phase as Phase state
    participant Det as TFLite detector

    Note over Loop: skip_counter >= frame_skip
    Loop->>Loop: _update_fps(), frame_count++, now

    alt Phase == IDLE
        Loop->>Motion: detect(frame)
        Motion->>Motion: copy params (lock), resize, gray, background, contours
        Motion-->>Loop: motion_result
        Loop->>Loop: _filter_motion_to_perimeter()
        Note over Loop: if motion_detected → ACQUISITION
    end

    alt Phase == ACQUISITION or TRACKING or WATCH
        Loop->>Motion: detect(frame)
        Motion-->>Loop: motion_result
        Loop->>Loop: get crop_region (motion or inject)
    end

    alt run_ai_detection (ACQ: every frame; TRACK: every 3rd; WATCH: every 2nd)
        alt crop_region set
            Loop->>Loop: cropped_frame = frame[cy:cy+ch, cx:cx+cw]
            Loop->>Det: detect(cropped_frame)
        else no crop (e.g. WATCH)
            Loop->>Det: detect(frame)
        end
        Det->>Det: load model if None
        Det->>Det: resize, BGR→RGB (pre-alloc buf), set_tensor, invoke
        Det->>Det: get_tensor (boxes, classes, scores), filter by threshold/class
        Det-->>Loop: detections (pixel coords)
        Loop->>Loop: inject fallback (if inject_cat), perimeter filter, confirm, world coords
    end

    Loop->>Loop: tracker.update(), merge IDs, annotate, JPEG, current_frame, recording
```

**Step-by-step (same order as code):**

| Step | What happens |
|------|----------------|
| 1 | **Frame capture** — Real camera: `get_request()` then `req.make_array("main")` (blocking until frame ready), or `get_frame()` (last frame from capture thread). File: `file_camera.get_frame()`. |
| 2 | **Optional inject** — If `inject_cat`: `paste_on_frame(frame)` (move cat, paste, set bbox). If stream clients > 0: annotate copy, encode JPEG, set `_cached_jpeg` and `current_frame`. |
| 3 | **Frame-skip gate** — `skip_counter += 1`. Only when `skip_counter >= frame_skip`: reset counter, update FPS, enter phase block. Otherwise loop goes to next frame (no motion, no TFLite). |
| 4 | **Phase + motion** — According to `_phase`: **IDLE** → `motion_detector.detect(frame)` (resize, gray, running-sum background, diff, contours), filter to perimeter; transition to ACQUISITION if motion in zone. **ACQUISITION/TRACKING/WATCH** → same motion.detect(); then set `run_ai_detection` and `crop_region` (motion bbox or inject bbox; WATCH often has no crop). |
| 5 | **Crop (if any)** — If `crop_region`: `cropped_frame = frame[cy:cy+ch, cx:cx+cw]`. Else use full `frame`. |
| 6 | **TFLite** — `detector.detect(cropped_frame or frame)`: load model if not loaded; resize to input size; BGR→RGB into pre-alloc buffer; `set_tensor` → `invoke` → `get_tensor` (boxes, classes, scores); filter by threshold and target class; return list of `(x1, y1, x2, y2, conf, class_id)` in crop/frame pixel coords. |
| 7 | **Post-AI** — If crop: add (cx, cy) to detection coords. Inject fallback: if no TFLite detection near inject bbox, append inject bbox. Filter by perimeter; temporal confirmation; build `last_detections_with_world` (world xy from calibration). |
| 8 | **After TFLite** — Tracker merge IDs; annotate frame, pre-compute JPEG, set `current_frame`; recording if enabled; rate-limit sleep if inject mode. Loop continues to next frame. |

### Crop vs resize — where and why

We use **crop** (extract a rectangle, same resolution) and **resize** (change dimensions) in different places. Summary:

| Step | Operation | Input | Output | Purpose |
|------|------------|--------|--------|---------|
| **Motion detection** | **Resize** | Full frame (e.g. 2304×1296) | Small gray image (e.g. 576×324 @ scale 0.25) | Downscale so motion (diff, contours) is cheap; scale is `MOTION_DETECTION_SCALE` (0.25). No crop — whole frame is scaled. |
| **AI region (ACQ/TRACK)** | **Crop** | Full frame (2304×1296) | Rectangle at **same resolution** (e.g. 380×380 or 400×400 or 450×450 px) | Take only the region of interest (motion bbox or inject cat bbox) so TFLite sees a smaller area; size from profile `motion_crop_size`. No resize here — we slice `frame[cy:cy+ch, cx:cx+cw]`. |
| **TFLite detector** | **Resize** (or skip if crop already model size) | Cropped region **or** full frame | Model input size (e.g. 300×300 from model) | Model has fixed input shape; we resize whatever we pass to that size. If the crop is already 300×300, resize is skipped. So: 380×380 crop → 300×300, or 300×300 crop → no resize. |
| **Stream / JPEG** | **Resize** | Annotated frame at capture res (2304×1296) | Stream resolution (e.g. 1920×1080, 640×360) | Reduce size for MJPEG streaming and bandwidth. |
| **Inject cat asset** | **Resize** | Cat image (e.g. 400×218) | Paste size (perspective-based, e.g. 150 px wide) | Scale the pasted cat to the right size on the frame; not a frame crop/resize. |

**Flow in short:**

1. **Motion:** full frame → **resize** to ¼ resolution → motion result (regions in full-frame coords).
2. **Crop (if any):** full frame → **crop** to e.g. 380×380 window (same pixel density).
3. **TFLite:** crop or full frame → **resize** to model input (e.g. 300×300) if size differs → inference → detections in crop/frame coords.
4. **Stream:** full annotated frame → **resize** to stream resolution → encode JPEG.

So we **crop** once (to define the AI window) and **resize** in three separate places: motion (downscale), TFLite (to model input), and stream (to viewer resolution).

**Why not crop to the size TFLite needs?**

It would be more efficient. The TFLite model has a fixed input size (e.g. **300×300** for the COCO SSD MobileNet quant model). Today we crop a *larger* window (380×380, 400×400, or 450×450 from the performance profile), then resize that down to 300×300. So we do extra work: a bigger crop and a resize.

- **Current:** crop 380/400/450 px → resize to model input (300×300) → inference. More context per crop, but one extra resize and more pixels through the pipeline.
- **More efficient:** crop **300×300** (model input size) directly → feed to TFLite (no resize, or a no-op). Less memory, less CPU, same detection quality if the cat fits in the 300×300 window (centered on motion/inject).

The current 380/400/450 sizes are a profile choice to give the model slightly more “context” (larger field of view) at the cost of that resize. For maximum efficiency you could set the crop size to the model’s actual input dimensions (e.g. 300×300) so the detector receives an already-sized crop and can skip the resize step.

**1. Effect on detection and tracking to 13 m**

| Crop size | Effect |
|-----------|--------|
| **400×400 (Performance 13 m)** | Largest margin around the cat. At 13 m the cat is small (~60–120 px); a 400 px window gives room for centering error and keeps the whole cat inside the crop. Best robustness for long range. |
| **380×380 (Balanced)** | Slightly less margin; still good for 0–12 m. |
| **300×300 (model input)** | Tightest window. At 13 m the cat still fits if the crop is well centered on motion/inject, but there is **less margin**: if the motion bbox or centroid is off by ~50–80 px, the cat can be clipped at the edge and detection may fail. Tracking can then drop until the next good crop. So 300×300 is **riskier at 13 m**; fine for closer range or when motion centering is accurate. |

**Recommendation:** Keep **400×400 for the "Performance (13 m)" profile** so detection and tracking stay reliable to 13 m. Use 300×300 only for a "max efficiency" profile (e.g. indoor / shorter range) if you want to save CPU and a bit of RAM.

**2. RAM and CPU impact of switching to 300×300**

| Resource | Change when going 380/400/450 → 300×300 |
|----------|----------------------------------------|
| **RAM** | **Small:** The crop is a view into the frame (no extra full crop buffer). Skipping resize avoids OpenCV's internal temp buffers for the scale step (roughly **~100–400 KB** less per inference). The TFLite input buffer is already 300×300; no change there. |
| **CPU** | **Modest:** One fewer `cv2.resize()` per frame when AI runs. On RPi Zero 2W, resizing 400×400 → 300×300 is on the order of **~1–3 ms**. If TFLite inference is ~50–80 ms, that's about **2–5%** of the AI path. So a few percent less CPU when the phase is ACQUISITION/TRACKING and crop is used. |

So: **RAM saving is small (hundreds of KB), CPU saving is a few percent.** The main benefit of 300×300 is simpler pipeline and slightly lower latency; for 13 m, keeping 400×400 is the safer choice for detection and tracking.

---

## 📁 Project Structure

```
cat_ball_tracker/
├── main.py                      # Application entry point
├── config.py                    # Configuration settings & performance profiles
├── settings.py                  # User settings persistence (JSON)
├── requirements.txt             # Python dependencies
├── README.md                    # This file
│
├── camera/
│   ├── __init__.py
│   └── camera_handler.py        # RPi Camera Module 3 interface (pause/resume)
│
├── processing/
│   ├── async_log.py             # Non-blocking logging (queue + writer thread; hot path uses plog)
│   ├── inject_cat.py            # Inject Cat test mode (paste, vertex movement)
│   └── memory.py                # RAM stats, reclaim_memory (gc + malloc_trim)
│
├── detection/                   # Detection & calibration modules
│   ├── __init__.py
│   ├── detector.py              # TFLite MobileNet SSD (lazy load/unload)
│   ├── tracker.py               # Centroid-based object tracking
│   ├── perimeter.py             # Detection Zone polygon management
│   ├── motion_detector.py       # Lightweight motion detection
│   ├── calibration.py           # Multi-rectangle perspective calibration
│   └── lens_calibration.py      # Rational model (k1-k6) lens distortion
│
├── web/                         # Flask web server & API routes
│   ├── __init__.py
│   ├── app.py                   # VideoProcessor + Flask app factory
│   ├── routes_streaming.py      # /, /video_feed, /api/snapshot
│   ├── routes_status.py         # /api/status, /api/mode
│   ├── routes_perimeter.py      # /api/perimeter, /api/topdown
│   ├── routes_performance.py    # /api/performance/*
│   ├── routes_calibration.py    # /api/calibration/*, /api/lens_calibration/*
│   ├── routes_video.py          # /api/video/*, /api/motion/*
│   ├── routes_dev.py            # /api/dev/* (system info, inject cat, services)
│   ├── templates/
│   │   └── index.html           # Web interface (Video, Calibration, Developer)
│   └── static/
│       ├── css/style.css
│       └── js/app.js
│
├── tests/                       # Unit tests (run manually)
│   ├── __init__.py
│   ├── run_tests.py             # Test runner: python tests/run_tests.py [module]
│   ├── test_calibration.py      # Homography, world coords, rectangles
│   ├── test_perimeter.py        # Point-in-polygon, filter_detections
│   ├── test_tracker.py          # ID assignment, persistence, reset
│   ├── test_memory.py           # RAM stats, reclaim_memory
│   └── test_inject_cat.py       # Movement, vertex cycling, paste
│
├── models/
│   ├── .gitkeep
│   └── test_cat.png             # Cat image for inject test
│
├── docs/
│   ├── CODE_REVIEW.md            # Code review notes (clarity, config, guards)
│   ├── CODE_REVIEW_DEADLOCKS.md  # Locks, deadlock analysis, data races
│   └── cloudflared-low-ram-config.md
├── AGENTS.md                     # Project guidelines for agents/developers (read first)
│
├── cat_dome.service             # Systemd service file
├── start_Cat_Dome.sh            # Startup wrapper with logging
├── setup_car_dome.sh            # Full setup script (systemd, venv, model)
└── test_installation.py         # Dependency verification
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

### Where do application logs (prints) appear?

All application output goes to **stdout** (or via the async log writer to stdout), then through the wrapper script to **journald** and to `logs/latest.log`. You see:

- **Startup:** Banner, "Starting server", "Loaded settings", "[PROFILE] Applied...", "Initializing video processor", "Video processor started", "TFLite model ready", then **libcamera/picamera2** messages when the camera starts (those are from the library, not our code). Scroll **up** in the journal to see our startup lines; they appear just before the libcamera flood.
- **At runtime:** We only log on **events**: phase changes (`[PHASE] ...`), inject cleanup (`[INJECT CLEANUP]`), recording start/stop (`[REC]`), `[PERF]` when AI runs, and errors. In **IDLE** with no motion there are no phase changes, so the journal is quiet until something happens. That is expected.
- **To follow live:** `sudo journalctl -u cat_dome -f` or `tail -f ~/cat_ball_tracker/logs/latest.log`.

### Per-step performance log (bottleneck analysis)

Every phase-block iteration (every processed frame) a single line is written to the log:

`[PERF] cap=850ms motion=45ms crop=0.1 tflite=72 track=0.2 annot=12 phase=IDLE`

| Field | Meaning |
|-------|--------|
| **cap** | Time (ms) to get one raw frame from the camera (blocking). |
| **motion** | Time (ms) for motion detection (resize to ¼, background, contours). |
| **crop** | Time (ms) to slice the crop from the frame (crop only; `-` when no crop). |
| **tflite** | Time (ms) for TFLite to run on the 300×300 (or full frame); `-` when AI did not run this frame. |
| **track** | Time (ms) for tracker update + merge IDs. |
| **annot** | Time (ms) for draw + resize + JPEG encode (when stream has clients); `-` when no stream. |
| **phase** | IDLE / ACQUISITION / TRACKING / WATCH. |

Use this to find the bottleneck: e.g. high **cap** → camera; high **motion** → motion scale/resolution; high **tflite** → model/threads; high **annot** → stream resolution or JPEG quality.

### Low FPS (how to find the cause)

The **displayed FPS** is processed frames per second (how often the phase block runs). Expected range is **3–7 FPS** depending on profile (see § Expected FPS from the code).

1. **Check FPS diagnostics in the API**  
   Open `GET /api/status` (or the status payload used by the web UI). It includes:
   - **`capture_ms`** — time in ms to get one frame from the camera (blocking).
   - **`motion_ms`** — time in ms for the last motion detection run (resize, background, contours).

   **How to interpret:**
   - **High `capture_ms`** (e.g. 500–1000 ms) → **camera is the bottleneck.** Check Settings → Framerate (try 15); ensure the camera pipeline isn’t throttled; on RPi check `rpicam-hello` and exposure.
   - **High `motion_ms`** (e.g. 200–500 ms) → **motion detection is the bottleneck.** Try a lower motion scale in the profile or a lower resolution if available.
   - **Both low** but FPS still low → check **frame_skip** (Settings): if it’s 4 or 5, displayed FPS = (loop rate) / frame_skip. Try frame_skip 1 or 2.
   - **RAM / swap** — if the system is swapping (`free -h`), both capture and motion can slow down; reduce load or add RAM.

2. **Quick checks**
   - Settings → **Framerate**: 15 (or 10) is typical; 5 or 1 will cap FPS.
   - Settings → **Frame skip**: 1 or 2; higher values reduce displayed FPS.
   - In IDLE, the loop does: capture → (every `frame_skip` iterations) motion → sleep(0.001). So per “processed” frame, cost ≈ capture + motion; if capture is ~800 ms you get ~1.2 FPS.

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
| Memory (RSS) | ~177 MB (2 camera buffers) |
| Memory (swap) | ~27 MB |
| Motion detection | <15ms |
| AI detection | 200-500ms (loaded on demand) |
| Idle CPU (browser open, stream on) | ~50% (was 92%) |
| Idle CPU (browser open, stream off) | ~35% |
| Idle CPU (no browser) | ~25% |
| TFLite threads | 0 when idle, 3 when tracking |
| OpenCV threads | 1 when idle, 4 when tracking |
| Calibration accuracy | 1-4% across full 120° FOV |
| Lens correction | 94.4% improvement, 0.8px residual |

---

## 📝 Version History

- **v3.8.1** - Annotation optimization: resize raw frame to stream resolution first, then draw all annotations (perimeter, detections, motion, crop) on the small frame. Pre-computed scaled perimeter cache (invalidated on perimeter/stream-res change). Saves ~30-80ms per frame on RPi Zero 2W. Stop Stream button already skips entire annotation path (250ms saving).
- **v3.8.0** - Non-blocking async logging (queue + writer thread, plog); per-step performance log every processed frame ([PERF] cap/motion/crop/tflite/track/annot); FPS diagnostics in status API and UI (Cap/Mot ms); heartbeat log every 30s; Inject Cat stop CPU fix (rate-limit sleep); AGENTS.md and README updated for architectural changes.
- **v3.7.1** - Minor fixes.
- **v3.7.0** - Real-time performance optimizations: pre-compute JPEG in process loop (zero-copy streaming), running-sum background model in motion detector (eliminates np.mean alloc), pre-allocated TFLite input buffer, narrowed motion detector lock (5-15ms -> <0.1ms), removed debug allocations from hot path, skip unused motion_mask allocation.
- **v3.6.3** - Fix top-down view: merge tracker IDs into world-coordinate detections so red dots show stable track IDs and update with tracking.
- **v3.6.2** - Code review: fix current_frame when no stream clients; move motion crop size to VideoProcessor (no config mutation); Inject Cat API returns 503 if processor not started; status overlay uses config constants; MOTION_CROP_SIZE comment updated.
- **v3.6.1** - Draw status overlay after resize for readable text at any stream resolution. Fix indentation bug in TRACKING phase crop region.
- **v3.6.0** - Phase state machine (IDLE/ACQUISITION/TRACKING/WATCH): TFLite stays active while cat is in Detection Zone. Removed RAM safety valve. Motion detection only inside Detection Zone. Cat gone for 30s -> IDLE.
- **v3.5.0** - Modular refactoring: split 2500-line app.py into processing/ module + Flask Blueprint routes + unit tests. Added processing/memory.py (RAM stats, gc+malloc_trim reclaim), processing/inject_cat.py (InjectCat class). 7 route Blueprint files. Core requirement documented: track cat until it leaves Detection Zone (max 13m).
- **v3.4.0** - Inject Cat test mode: overlay a real cat photo on camera frames to test the full pipeline (motion → TFLite → tracking → world position → top-down view). Cat walks vertex-to-vertex across Detection Zone. Toggle from Developer tab.
- **v3.3.1** - Developer tab: add swap activity monitoring (swap in/out since boot, swappiness value); setup script adds rpi-connect-lite installation, sudoers for web UI service control, swappiness=10
- **v3.3.0** - Developer tab: system info (RAM, swap, CPU temp, uptime, disk, process RSS/swap/threads), RPi Connect toggle (start/stop from web UI), color-coded indicators
- **v3.2.2** - Reduce camera buffers from 4 to 2 (saves ~18 MB RAM); update README architecture diagram with current design
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
