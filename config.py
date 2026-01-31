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
LABELS_FILENAME = "labelmap.txt"

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
PERIMETER_COLOR = (255, 200, 0)  # Light blue
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

# ============================================================================
# WEB SERVER SETTINGS
# ============================================================================
HOST = "0.0.0.0"    # Listen on all interfaces
PORT = 5000
DEBUG = True        # Enable detailed performance logging

# MJPEG streaming quality (0-100)
JPEG_QUALITY = 70

# ============================================================================
# PERFORMANCE SETTINGS (for RPi Zero 2W optimization)
# ============================================================================
# Skip frames for detection (1 = process every frame, 2 = every other, etc.)
DETECTION_FRAME_SKIP = 2

# Use threading for camera capture
USE_THREADED_CAPTURE = True

# Number of threads for TFLite inference
TFLITE_NUM_THREADS = 4  # Use all 4 cores of RPi Zero 2W

# OPTIMIZATION J: Enable GPU acceleration (OpenCL/UMat) if available
# Set to True to attempt GPU-accelerated operations
# Falls back to CPU if GPU not available
USE_GPU_ACCELERATION = True

# ============================================================================
# PERFORMANCE PROFILES - 3 Hard-coded profiles for 2304×1296 capture
# Optimized for Raspberry Pi Camera Module 3 WIDE (120° FOV)
# ============================================================================
PERFORMANCE_PROFILES = {
    "balanced": {
        "name": "Balanced",
        "description": "Recommended: Best trade-off between speed and quality",
        "jpeg_quality": 65,
        "motion_crop_size": (400, 400),
        "motion_scale": 0.30,
        "motion_threshold": 18,
        "motion_min_area": 80,
        "tflite_threads": 3,
        "estimated_fps": "5-7 FPS",
        "estimated_ram": "220MB",
        "estimated_cpu": "65%",
        "detection_range": "0-12m"
    },
    "performance": {
        "name": "Performance (13m)",
        "description": "Optimized for 13m max distance detection",
        "jpeg_quality": 60,
        "motion_crop_size": (420, 420),
        "motion_scale": 0.35,
        "motion_threshold": 18,
        "motion_min_area": 50,
        "tflite_threads": 3,
        "estimated_fps": "4-6 FPS",
        "estimated_ram": "220MB",
        "estimated_cpu": "60%",
        "detection_range": "0-13m"
    },
    "quality": {
        "name": "Quality",
        "description": "Best accuracy for close-range detailed detection",
        "jpeg_quality": 75,
        "motion_crop_size": (480, 480),
        "motion_scale": 0.35,
        "motion_threshold": 15,
        "motion_min_area": 80,
        "tflite_threads": 4,
        "estimated_fps": "3-5 FPS",
        "estimated_ram": "240MB",
        "estimated_cpu": "75%",
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

# Available streaming resolution options (width, height) - for web viewing
# Users can select this to balance bandwidth vs quality
STREAM_RESOLUTION_OPTIONS = [
    (480, 270),     # Ultra Low - for slow connections
    (640, 360),     # Low - mobile-friendly
    (960, 540),     # Medium (default) - good balance
    (1280, 720),    # High - HD quality
    (1920, 1080),   # Ultra High - maximum quality
]

# Available frame rate options
FRAMERATE_OPTIONS = [5, 10, 15, 20, 30]

# Available frame skip options (1 = process every frame)
FRAME_SKIP_OPTIONS = [1, 2, 3, 4, 5]

# Default performance settings
DEFAULT_RESOLUTION = (2304, 1296)   # 2x binned mode for 13m detection
DEFAULT_STREAM_RESOLUTION = (960, 540)  # Medium stream quality
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

# Crop size for AI detection when motion detected
# Use fixed 300x300 crop (no scaling) for better small object detection
MOTION_CROP_SIZE = (300, 300)      # Fixed crop size matching AI input (no scaling!)
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
# Sync FRAME_WIDTH/HEIGHT with DEFAULT_RESOLUTION
# ============================================================================
FRAME_WIDTH = DEFAULT_RESOLUTION[0]
FRAME_HEIGHT = DEFAULT_RESOLUTION[1]
STREAM_WIDTH = DEFAULT_STREAM_RESOLUTION[0]
STREAM_HEIGHT = DEFAULT_STREAM_RESOLUTION[1]