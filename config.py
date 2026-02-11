"""
Configuration settings for Cat Dome
Optimized for Raspberry Pi Zero 2W
"""

import os

# ============================================================================
# PATHS
# ============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

# TFLite model settings
MODEL_URL = "https://storage.googleapis.com/download.tensorflow.org/models/tflite/coco_ssd_mobilenet_v1_1.0_quant_2018_06_29.zip"
MODEL_FILENAME = "detect.tflite"

# ============================================================================
# DETECTION SETTINGS
# ============================================================================
# Confidence threshold for detections (0.0 - 1.0)
# Lower = more detections but more false positives
# Higher = fewer detections but more accurate
# 0.3 recommended for small objects like tennis balls
DETECTION_THRESHOLD = 0.3

# Default detection mode: "cat" or "ball"
DEFAULT_DETECTION_MODE = "cat"

# COCO class IDs
# Cat = 17, Sports Ball = 37 (0-indexed: 16, 36)
COCO_CLASSES = {
    "cat": 17,      # COCO class ID for cat
    "ball": 37      # COCO class ID for sports ball
}

# Class names for display
CLASS_NAMES = {
    17: "Cat",
    37: "Ball"
}

# ============================================================================
# CAMERA SETTINGS
# ============================================================================
# Frame dimensions - derived from DEFAULT_RESOLUTION (set below)
# These are updated after DEFAULT_RESOLUTION is defined
FRAME_WIDTH = 2304  # Updated below
FRAME_HEIGHT = 1296  # Updated below

# Streaming dimensions (for MJPEG web stream only)
# Capture resolution can be higher for better detection
STREAM_WIDTH = 960  # Updated below
STREAM_HEIGHT = 540  # Updated below

# Target FPS (actual FPS limited by detection speed)
TARGET_FPS = 15

# Autofocus: Camera Module 3 has hardware PDAF. For a ceiling-mounted camera at a
# fixed height watching a known room, manual focus eliminates AF hunting/blur during
# fast cat movement and saves CPU.
# AfMode: 0=Manual (recommended), 1=Auto (trigger once), 2=Continuous (default if unset)
# LensPosition: diopters (1/distance_in_meters). 0.0=infinity, 0.5=2m, 1.0=1m
AF_MODE = 0          # Manual — no autofocus hunting
LENS_POSITION = 0.0  # Infinity — best depth of field for 0-13m range. Tune if needed.

# Camera warmup time in seconds
CAMERA_WARMUP = 2.0

# ============================================================================
# TRACKING SETTINGS
# ============================================================================
# Maximum distance (pixels) to associate detection with existing track
MAX_TRACKING_DISTANCE = 50

# Number of frames to keep a track alive without detection
MAX_DISAPPEARED_FRAMES = 30

# ============================================================================
# PERIMETER SETTINGS
# ============================================================================
# Default perimeter (full frame) - list of (x, y) points
# Will be overwritten by user-defined perimeter
DEFAULT_PERIMETER = [
    (0, 0),
    (FRAME_WIDTH, 0),
    (FRAME_WIDTH, FRAME_HEIGHT),
    (0, FRAME_HEIGHT)
]

# Perimeter line color (BGR)
PERIMETER_COLOR = (255, 200, 0)  # Cyan/teal (BGR)
PERIMETER_THICKNESS = 2

# ============================================================================
# VISUALIZATION SETTINGS
# ============================================================================
# Bounding box colors (BGR format for OpenCV)
BOX_COLOR_CAT = (0, 255, 0)      # Green for cats
BOX_COLOR_BALL = (0, 165, 255)   # Orange for balls
BOX_THICKNESS = 2

# Text settings
FONT_SCALE = 0.6
FONT_THICKNESS = 2
TEXT_COLOR = (255, 255, 255)     # White
TEXT_BG_COLOR = (0, 0, 0)        # Black background

# Status overlay (stream / get_frame_jpeg)
STATUS_BOX_PADDING = 5
STATUS_BOX_MIN_WIDTH = 250
STATUS_TEXT_PADDING = 15
STATUS_BOX_HEIGHT_EXTRA = 55
STATUS_FONT_SCALE_MAIN = 0.6
STATUS_FONT_SCALE_SUB = 0.5
STATUS_FONT_THICKNESS_MAIN = 2
STATUS_FONT_THICKNESS_SUB = 1
STATUS_TIMESTAMP_MARGIN = 10

# ============================================================================
# WEB SERVER SETTINGS
# ============================================================================
HOST = "0.0.0.0"    # Listen on all interfaces
PORT = 5000
DEBUG = True        # Enable detailed performance logging

# MJPEG streaming quality (0-100)
JPEG_QUALITY = 70

# H.264 hardware streaming (v3.10.0+)
# The Pi's VideoCore has a dedicated H.264 encoder — zero CPU cost.
# H.264 is streamed via WebSocket + jMuxer in the browser (GPU-decoded).
# MJPEG /video_feed is kept as fallback for snapshots and simple clients.
H264_QP = 24           # Quantization parameter (lower = higher quality/bitrate). 20-30 is typical.
H264_ENABLED = True    # Enable H.264 WebSocket streaming (disable to save ~3MB RAM from encoder)

# ============================================================================
# PERFORMANCE SETTINGS (for RPi Zero 2W optimization)
# ============================================================================
# Skip frames for detection (1 = process every frame, 2 = every other, etc.)
DETECTION_FRAME_SKIP = 2

# Use threading for camera capture
USE_THREADED_CAPTURE = True

# Number of threads for TFLite inference
# Reduced from 4 to 3 to leave one core for system tasks
# This improves overall responsiveness and reduces memory pressure
TFLITE_NUM_THREADS = 3  # Use 3 of 4 cores (leave 1 for system)

# OPTIMIZATION J: Enable GPU acceleration (OpenCL/UMat) if available
# Set to True to attempt GPU-accelerated operations
# Falls back to CPU if GPU not available
USE_GPU_ACCELERATION = True

# ============================================================================
# PHASE STATE MACHINE CONSTANTS
# ============================================================================
PHASE_DETECTION_TIMEOUT = 30      # Seconds with no detection → back to IDLE
PHASE_ACQUISITION_TIMEOUT = 10    # Seconds with no motion in ACQUISITION → back to IDLE
PHASE_TRACKING_AI_INTERVAL = 3    # Run TFLite every Nth processed frame in TRACKING
PHASE_WATCH_AI_INTERVAL = 2       # Run TFLite every Nth processed frame in WATCH
INJECT_FALLBACK_CONFIDENCE = 0.95 # Confidence for injected fake detections
INJECT_BBOX_PROXIMITY_PX = 100    # Pixel threshold for matching TFLite detection to injected cat
INJECT_MODE_SLEEP_SEC = 0.15      # Rate-limit sleep per frame in inject mode

# ============================================================================
# PERFORMANCE PROFILES - 3 Hard-coded profiles for 2304×1296 capture
# Optimized for Raspberry Pi Camera Module 3 WIDE (120° FOV)
# ============================================================================
PERFORMANCE_PROFILES = {
    "balanced": {
        "name": "Balanced",
        "description": "Recommended: Best trade-off between speed and quality",
        "jpeg_quality": 60,  # Reduced from 65 to save memory
        "motion_crop_size": (380, 380),  # Reduced from 400 to save RAM
        "motion_scale": 0.30,
        "motion_threshold": 25,
        "motion_min_area": 80,
        "tflite_threads": 3,
        "estimated_fps": "5-7 FPS",
        "estimated_ram": "190MB",  # Updated estimate
        "estimated_cpu": "55-60%",  # Updated estimate
        "detection_range": "0-12m"
    },
    "performance": {
        "name": "Performance (13m)",
        "description": "Optimized for 13m max distance detection",
        "jpeg_quality": 55,  # Reduced from 60 to save memory
        "motion_crop_size": (400, 400),  # Reduced from 420 to save RAM
        "motion_scale": 0.35,
        "motion_threshold": 25,
        "motion_min_area": 50,
        "tflite_threads": 3,
        "estimated_fps": "4-6 FPS",
        "estimated_ram": "200MB",  # Updated estimate
        "estimated_cpu": "55-65%",  # Updated estimate
        "detection_range": "0-13m"
    },
    "quality": {
        "name": "Quality",
        "description": "Best accuracy for close-range detailed detection",
        "jpeg_quality": 70,  # Reduced from 75 to save memory
        "motion_crop_size": (450, 450),  # Reduced from 480 to save RAM
        "motion_scale": 0.35,
        "motion_threshold": 18,
        "motion_min_area": 80,
        "tflite_threads": 3,  # Reduced from 4 to leave headroom
        "estimated_fps": "3-5 FPS",
        "estimated_ram": "210MB",  # Updated estimate
        "estimated_cpu": "65-70%",  # Updated estimate
        "detection_range": "0-12m (high detail)"
    }
}

# Default active profile
DEFAULT_PERFORMANCE_PROFILE = "performance"

# ============================================================================
# PERFORMANCE OPTIONS (user-selectable via web UI)
# ============================================================================
# Available capture resolution options (width, height) - for detection
# Fixed to 2304×1296 (2x binned mode) - optimal for 13m cat detection
CAPTURE_RESOLUTION = (2304, 1296)  # Native 2x mode, best balance

# ISP lores (low-resolution) stream — hardware-downscaled by the camera ISP at zero CPU cost.
# Used for motion detection and stream frame generation instead of resizing the full 9MB main frame.
# Must be <= main resolution in both dimensions. 960×540 covers the 3 most common stream options.
# Stream resolutions larger than this fall back to resizing from main.
LORES_RESOLUTION = (960, 540)

# Available streaming resolution options (width, height) - for web viewing
# Users can select this to balance bandwidth vs quality
STREAM_RESOLUTION_OPTIONS = [
    (480, 270),     # Ultra Low - for slow connections
    (640, 360),     # Low - mobile-friendly (RECOMMENDED for RPi Zero 2W)
    (960, 540),     # Medium - good balance (matches lores — zero resize)
    (1280, 720),    # High - HD quality (resizes from main — slower)
    (1920, 1080),   # Ultra High - maximum quality (not recommended)
]

# Available frame rate options
FRAMERATE_OPTIONS = [5, 10, 15, 20, 30]

# Available frame skip options (1 = process every frame)
FRAME_SKIP_OPTIONS = [1, 2, 3, 4, 5]

# Default performance settings
DEFAULT_RESOLUTION = (2304, 1296)   # 2x binned mode for 13m detection
# Changed to 640x360 to reduce memory pressure on RPi Zero 2W
DEFAULT_STREAM_RESOLUTION = (640, 360)  # Low stream quality - saves RAM
DEFAULT_FRAMERATE = 15
DEFAULT_FRAME_SKIP = 2

# ============================================================================
# MOTION-FIRST DETECTION (saves memory, better for distance detection)
# ============================================================================
# Enable motion-first mode: only run AI when motion detected
MOTION_FIRST_ENABLED = True

# Show motion detection regions on video (for debugging)
SHOW_MOTION_REGIONS = False

# Motion detection settings
MOTION_DETECTION_SCALE = 0.25    # Scale for motion detection (0.25 = 1/4 resolution)
MOTION_THRESHOLD = 15            # Pixel difference threshold (lower = more sensitive)
MOTION_MIN_AREA = 100            # Minimum contour area for motion (lower = smaller objects)
MOTION_HISTORY_FRAMES = 3        # Frames to average for background

# Crop size for AI detection when motion detected.
# Default before any performance profile is applied; profiles override at runtime
# via VideoProcessor.current_motion_crop_size (380/400/450 per profile).
# Using the model's input size (e.g. 300×300 for COCO SSD quant) avoids resize in detector.
MOTION_CROP_SIZE = (300, 300)
MOTION_CROP_MIN_SIZE = (640, 480)  # Legacy - not used with fixed crop

# Temporal confirmation - require detection in N consecutive frames
# 1 = instant (current behavior), 2-3 = more reliable, fewer false positives
DETECTION_CONFIRM_FRAMES = 1

# ============================================================================
# CALIBRATION SETTINGS (for real-world coordinates)
# ============================================================================
# Camera height in meters (for reference, not used in calculations)
CAMERA_HEIGHT_METERS = 3.0

# Default world bounds for mini-map (meters)
DEFAULT_WORLD_BOUNDS = {
    "min_x": 0,
    "max_x": 10,
    "min_y": 0,
    "max_y": 10
}

# Mini-map display settings
MINIMAP_WIDTH = 200   # pixels
MINIMAP_HEIGHT = 200  # pixels
MINIMAP_BG_COLOR = (30, 30, 30)
MINIMAP_GRID_COLOR = (60, 60, 60)
MINIMAP_POINT_COLOR_CAT = (0, 255, 0)    # Green
MINIMAP_POINT_COLOR_BALL = (0, 165, 255)  # Orange

# ============================================================================
# RECORDING (on detection)
# ============================================================================
# Directory for saved clips (created if missing)
VIDEO_LIBRARY_PATH = "/home/ranhaber/cat_dome_videos"
# Stop recording this many seconds after last detection of cat/ball
RECORD_AFTER_DETECTION_SEC = 5
# Recording format: H.264 in MP4 (good compression, same quality)
RECORDING_FOURCC = "avc1"  # H.264 for MP4

# ============================================================================
# Sync FRAME_WIDTH/HEIGHT with DEFAULT_RESOLUTION
# ============================================================================
FRAME_WIDTH = DEFAULT_RESOLUTION[0]
FRAME_HEIGHT = DEFAULT_RESOLUTION[1]
STREAM_WIDTH = DEFAULT_STREAM_RESOLUTION[0]
STREAM_HEIGHT = DEFAULT_STREAM_RESOLUTION[1]
