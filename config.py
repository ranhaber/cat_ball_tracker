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
FRAME_WIDTH = 1536  # Updated below
FRAME_HEIGHT = 864  # Updated below

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
DEBUG = False       # Set True only for development (not on RPi)

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

# ============================================================================
# PERFORMANCE OPTIONS (user-selectable via web UI)
# ============================================================================
# Available resolution options (width, height)
# Matches IMX708 (Camera Module 3) capabilities: 4608x2592 max
RESOLUTION_OPTIONS = [
    (320, 240),     # Fastest - for testing/low bandwidth
    (640, 480),     # Default - good balance for RPi Zero 2W
    (800, 600),     # Medium
    (1280, 720),    # HD 720p
    (1536, 864),    # Native mode 1
    (1920, 1080),   # Full HD 1080p
    (2304, 1296),   # Native mode 2
    (2592, 1944),   # 5MP equivalent
    (4056, 3040),   # 12MP
    (4608, 2592),   # Max resolution (native)
]

# Available frame rate options
FRAMERATE_OPTIONS = [5, 10, 15, 20, 30]

# Available frame skip options (1 = process every frame)
FRAME_SKIP_OPTIONS = [1, 2, 3, 4, 5]

# Default performance settings
DEFAULT_RESOLUTION = (1536, 864)  # Higher res for better distance detection
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
MOTION_THRESHOLD = 25            # Pixel difference threshold
MOTION_MIN_AREA = 500            # Minimum contour area for motion
MOTION_HISTORY_FRAMES = 3        # Frames to average for background

# Crop size for AI detection when motion detected
MOTION_CROP_MIN_SIZE = (640, 480)  # Minimum crop size for AI detection

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