"""
Cat Dome — Flask Web Server with MJPEG Streaming and Detection Pipeline.

This file contains:
- VideoProcessor: Core video processing class (camera → detection → tracking → streaming)
- create_app(): Flask application factory with Blueprint route registration
- run_server(): Entry point that starts everything

Routes are organized in separate Blueprint files:
- routes_streaming.py  — /, /video_feed, /api/snapshot
- routes_status.py     — /api/status, /api/mode
- routes_perimeter.py  — /api/perimeter, /api/topdown
- routes_performance.py — /api/performance/*
- routes_calibration.py — /api/calibration/*, /api/lens_calibration/*
- routes_video.py      — /api/video/*, /api/motion/*
- routes_dev.py        — /api/dev/*
"""

import time
import threading
import queue
import os
import logging
from datetime import datetime
import cv2
import numpy as np
from flask import Flask

import config
import settings
from processing.async_log import log as plog
from processing.memory import get_system_info, get_ram_stats, reclaim_memory
from processing.inject_cat import InjectCat

# Fast JPEG encoding via libjpeg-turbo (NEON SIMD on ARM) — ~50-70% faster than cv2.imencode
try:
    import simplejpeg
    _HAS_SIMPLEJPEG = True
    print("[INIT] simplejpeg available — using libjpeg-turbo for JPEG encoding")
except ImportError:
    _HAS_SIMPLEJPEG = False
    print("[INIT] simplejpeg not installed — using cv2.imencode (pip install simplejpeg for faster JPEG)")

# Suppress Flask/Werkzeug access logs (the GET /api/status messages)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

# Zero-copy DMA buffer access for Phase 2 pipelining
try:
    from picamera2.request import MappedArray
    _HAS_MAPPED_ARRAY = True
except ImportError:
    _HAS_MAPPED_ARRAY = False
    MappedArray = None

from camera.camera_handler import CameraHandler, FileCameraHandler
from detection.detector import TFLiteDetector
from detection.tracker import CentroidTracker
from detection.perimeter import PerimeterManager
from detection.motion_detector import MotionDetector

# Optional calibration imports
try:
    from detection.calibration import CameraCalibration
    CALIBRATION_AVAILABLE = True
except ImportError:
    CALIBRATION_AVAILABLE = False
    CameraCalibration = None

try:
    from detection.lens_calibration import LensCalibration
    LENS_CALIBRATION_AVAILABLE = True
except ImportError:
    LENS_CALIBRATION_AVAILABLE = False
    LensCalibration = None


# =============================================================================
# VideoProcessor — Core Detection & Tracking Pipeline
# =============================================================================

class VideoProcessor:
    """
    Processes video frames with detection and tracking.
    Generates annotated frames for streaming.
    
    Core requirement: Identify and track a cat that enters the Detection Zone
    and continue tracking until the cat leaves. Max range: 13m.
    TFLite AI stays active while a cat is detected.
    """
    
    def __init__(self):
        # Components (initialized in start())
        self.camera = None
        self.detector = None
        self.tracker = None
        self.perimeter = None
        self.calibration = None
        self.lens_calibration = None
        self.motion_detector = None
        
        # Processing state
        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self._fps_start = time.time()
        self._fps_count = 0
        # FPS diagnostics: last capture and motion duration (ms) to find bottleneck
        self._last_capture_ms = None
        self._last_queue_wait_ms = None  # How long processing thread waited for next frame
        self._last_motion_ms = None
        self._last_heartbeat_time = 0.0  # for periodic log so journal shows activity when idle
        
        # Callback-driven capture with ring buffer (Stage 3)
        self._frame_ready = threading.Event()
        self._ring_main = [None, None, None]      # Pre-allocated in start()
        self._ring_lores_y = [None, None, None]
        self._ring_lores_bgr = [None, None, None]
        self._ring_lores_bgr_valid = [False, False, False]  # Whether BGR was computed for this slot
        self._ring_last_written = -1  # Slot index [0-2] of last completed write (-1 = none)
        self._ring_copy_ms = 0.0   # Last DMA→ring memcpy time (ms)
        
        # Async AI thread (Stage 4)
        self._ai_request_queue = None
        self._ai_result_queue = None
        self._ai_thread = None
        
        # Frame storage for streaming
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self._stream_clients_lock = threading.Lock()
        self._stream_clients = 0  # Number of active MJPEG stream connections
        
        # Pre-computed JPEG cache (built in _process_loop, read by get_frame_jpeg)
        self._cached_jpeg = None        # JPEG bytes for MJPEG stream
        self._cached_jpeg_lock = threading.Lock()
        self._cached_capture_frame = None  # Raw frame for snapshot/recording
        
        # H.264 WebSocket streaming state
        self._h264_clients = 0
        self._h264_clients_lock = threading.Lock()
        self._overlay_data = None       # Latest overlay JSON dict for H.264 Canvas
        self._overlay_data_lock = threading.Lock()
        
        # Load saved settings (or defaults)
        saved = settings.load_settings()
        
        # Performance settings
        self.current_resolution = config.DEFAULT_RESOLUTION  # Fixed at 2304x1296
        if tuple(saved.get("resolution", config.DEFAULT_RESOLUTION)) != config.DEFAULT_RESOLUTION:
            print(f"[INFO] Upgrading capture resolution from {saved.get('resolution')} to {config.DEFAULT_RESOLUTION}")
            settings.update_setting("resolution", list(config.DEFAULT_RESOLUTION))
        
        self.current_stream_resolution = tuple(saved.get("stream_resolution", config.DEFAULT_STREAM_RESOLUTION))
        self._scaled_perimeter_cache = None  # (stream_w, stream_h, np.array) — pre-computed for draw
        self.current_framerate = saved.get("framerate", config.DEFAULT_FRAMERATE)
        self.current_frame_skip = saved.get("frame_skip", config.DEFAULT_FRAME_SKIP)
        
        # ISP lores stream state (set in start() after camera init)
        self._using_lores = False
        self._lores_resolution = getattr(config, 'LORES_RESOLUTION', (960, 540))
        self._pending_lores_reconfigure = None  # (w, h) tuple set by set_stream_resolution, executed by process loop
        
        # Motion-first detection mode
        self.motion_first_enabled = saved.get("motion_first_enabled", True)
        self.show_motion_regions = saved.get("show_motion_regions", False)
        
        # Performance profile
        saved_profile = saved.get("performance_profile", config.DEFAULT_PERFORMANCE_PROFILE)
        if saved_profile not in config.PERFORMANCE_PROFILES:
            print(f"[WARNING] Saved profile '{saved_profile}' not found. Using '{config.DEFAULT_PERFORMANCE_PROFILE}'")
            saved_profile = config.DEFAULT_PERFORMANCE_PROFILE
        self.current_profile = saved_profile
        self.current_jpeg_quality = config.JPEG_QUALITY
        self.current_motion_crop_size = config.PERFORMANCE_PROFILES[saved_profile]["motion_crop_size"]
        
        # Video source and recording
        self.video_library_path = saved.get("video_library_path", getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos'))
        self.record_after_detection_sec = saved.get("record_after_detection_sec", getattr(config, 'RECORD_AFTER_DETECTION_SEC', 5))
        self.recording_enabled = saved.get("recording_enabled", False)
        self.video_source = saved.get("video_source", "live")
        self.video_file_path = saved.get("video_file_path")
        self.file_camera = None
        self._recording_writer = None
        self._recording_start_time = None
        self._recording_last_detection_time = None
        self._recording_filename = None
        
        # Detection mode and threshold
        self._saved_detection_mode = saved.get("detection_mode", config.DEFAULT_DETECTION_MODE)
        self._saved_threshold = saved.get("detection_threshold", config.DETECTION_THRESHOLD)
        
        # Phase state machine: IDLE → ACQUISITION → TRACKING → WATCH → IDLE
        # See README.md for detailed phase diagram
        self._phase = "IDLE"
        self._last_detection_time = 0    # Time of last successful cat detection
        self._last_motion_time = 0       # Time of last motion in Detection Zone
        self._phase_frame_counter = 0    # Frames since entering current phase
        self._detection_timeout = config.PHASE_DETECTION_TIMEOUT
        self._acquisition_timeout = config.PHASE_ACQUISITION_TIMEOUT
        
        # Motion detection stats (exposed to API)
        self.motion_detected = False
        self.ai_detections_count = 0
        
        # Inject Cat test mode (uses InjectCat class from processing/inject_cat.py)
        self.inject_cat = False
        self.inject_cat_handler = None  # Created in start() after perimeter/calibration init
        self._request_motion_reset_after_inject = False  # Process loop performs reset (avoids cross-thread race)
        self._request_unload_after_inject = False        # Process loop performs unload (avoids deadlock with detect())
        
        # Temporal confirmation
        self.confirm_frames = saved.get("confirm_frames", getattr(config, 'DETECTION_CONFIRM_FRAMES', 1))
        self.detection_history = []
        
        # Last detections with world coordinates for API
        self.last_detections_with_world = []
        
        print(f"Loaded settings: Capture={self.current_resolution[0]}x{self.current_resolution[1]}, "
              f"Stream={self.current_stream_resolution[0]}x{self.current_stream_resolution[1]}, "
              f"motion-first={self.motion_first_enabled}, profile={self.current_profile}")
    
    @property
    def stream_clients(self):
        """Thread-safe access to stream client count."""
        with self._stream_clients_lock:
            return self._stream_clients
    
    @stream_clients.setter
    def stream_clients(self, value):
        with self._stream_clients_lock:
            self._stream_clients = max(0, value)
    
    def increment_stream_clients(self):
        """Thread-safe increment of stream client count (e.g. new MJPEG viewer)."""
        with self._stream_clients_lock:
            self._stream_clients += 1
            return self._stream_clients
    
    def decrement_stream_clients(self):
        """Thread-safe decrement of stream client count (e.g. viewer disconnected)."""
        with self._stream_clients_lock:
            self._stream_clients = max(0, self._stream_clients - 1)
            return self._stream_clients
    
    # =========================================================================
    # H.264 WebSocket Streaming
    # =========================================================================
    
    def increment_h264_clients(self):
        """Thread-safe increment. Starts H.264 encoder on first client."""
        with self._h264_clients_lock:
            self._h264_clients += 1
            n = self._h264_clients
        if n == 1 and self.camera:
            self.camera.start_h264_encoder()
        return n
    
    def decrement_h264_clients(self):
        """Thread-safe decrement. Stops H.264 encoder when last client leaves."""
        with self._h264_clients_lock:
            self._h264_clients = max(0, self._h264_clients - 1)
            n = self._h264_clients
        if n == 0 and self.camera:
            self.camera.stop_h264_encoder()
        return n
    
    @property
    def h264_clients(self):
        with self._h264_clients_lock:
            return self._h264_clients
    
    def get_h264_frame(self, timeout=1.0):
        """Get next H.264 encoded frame from hardware encoder."""
        if self.camera:
            return self.camera.get_h264_frame(timeout)
        return None
    
    def get_overlay_data(self):
        """Get latest overlay data for H.264 Canvas rendering."""
        with self._overlay_data_lock:
            return self._overlay_data
    
    def _update_overlay_data(self, last_detections, motion_regions_in_perimeter,
                             crop_region, tracked_objects):
        """Package current detection state as JSON-serializable dict for Canvas overlay."""
        capture_w, capture_h = self.current_resolution
        
        detections_list = []
        for det in last_detections:
            x1, y1, x2, y2, conf, class_id = det
            entry = {
                "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                "conf": round(float(conf), 2),
                "class": config.CLASS_NAMES.get(class_id, f"Class {class_id}"),
            }
            # Match track ID if available
            if tracked_objects:
                cx_det, cy_det = (x1 + x2) // 2, (y1 + y2) // 2
                for obj_id, centroid in tracked_objects.items():
                    if abs(int(centroid[0]) - cx_det) < 20 and abs(int(centroid[1]) - cy_det) < 20:
                        entry["track_id"] = obj_id
                        break
            detections_list.append(entry)
        
        # Get perimeter points in capture coords
        perim_points = []
        if self.perimeter and hasattr(self.perimeter, 'get_points'):
            raw = self.perimeter.get_points()
            if raw:
                perim_points = [[int(p[0]), int(p[1])] for p in raw]
        
        # Include inject cat bbox for H.264 overlay when inject test is active
        inject_bbox = None
        if self.inject_cat and self.inject_cat_handler and self.inject_cat_handler.bbox:
            b = self.inject_cat_handler.bbox
            inject_bbox = [int(b[0]), int(b[1]), int(b[2]), int(b[3])]
        
        overlay = {
            "phase": self._phase,
            "fps": round(self.fps, 1),
            "mode": self.detector.get_detection_mode() if self.detector else "cat",
            "objects": self.tracker.get_object_count() if self.tracker else 0,
            "detections": detections_list,
            "motion_regions": [[int(x), int(y), int(w), int(h)]
                               for x, y, w, h in motion_regions_in_perimeter] if self.show_motion_regions else [],
            "crop_region": [int(v) for v in crop_region] if crop_region and self.show_motion_regions else None,
            "perimeter": perim_points,
            "capture_res": [capture_w, capture_h],
            "inject_cat_bbox": inject_bbox,
        }
        
        with self._overlay_data_lock:
            self._overlay_data = overlay
    
    # =========================================================================
    # ISP Lores Stream Helpers
    # =========================================================================
    
    def _lores_motion_scale(self, profile_scale):
        """Adjust motion detection scale for lores input frame.
        
        Performance profiles define motion_scale for the full capture resolution
        (e.g. 0.30 × 2304 = 691px wide). When passing the smaller lores frame,
        we scale up so the final detection resolution matches the profile's intent.
        """
        if not self._using_lores:
            return profile_scale
        main_w = self.current_resolution[0]
        lores_w = self._lores_resolution[0]
        return min(1.0, profile_scale * main_w / lores_w)
    
    def _scale_motion_to_main(self, motion_result, frame_w, frame_h):
        """Scale motion detection regions from lores coordinates to main frame coordinates.
        
        Motion regions must be in main-frame coords for perimeter filtering and AI crop.
        """
        if not self._using_lores:
            return motion_result
        lores_w, lores_h = self._lores_resolution
        sx = frame_w / lores_w
        sy = frame_h / lores_h
        
        if motion_result["regions"]:
            scaled = []
            for rx, ry, rw, rh in motion_result["regions"]:
                scaled.append((int(rx * sx), int(ry * sy), int(rw * sx), int(rh * sy)))
            motion_result["regions"] = scaled
            # Update detector's internal state so get_fixed_crop_region() uses main coords
            self.motion_detector.motion_regions = scaled
        
        if motion_result["combined_region"]:
            cx, cy, cw, ch = motion_result["combined_region"]
            motion_result["combined_region"] = (int(cx * sx), int(cy * sy), int(cw * sx), int(ch * sy))
        
        return motion_result
    
    def _encode_jpeg(self, frame, quality):
        """Encode frame to JPEG bytes using simplejpeg (libjpeg-turbo) or cv2 fallback."""
        if _HAS_SIMPLEJPEG:
            try:
                return simplejpeg.encode_jpeg(frame, quality=quality, colorspace='BGR')
            except Exception:
                pass
        ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ret else None
    
    def _resize_for_stream(self, frame, frame_lores, stream_w, stream_h):
        """Get a stream-sized frame, preferring lores to avoid expensive main resize.
        
        Returns (stream_frame, sx, sy) where sx/sy map main-frame coords to stream coords.
        """
        capture_h, capture_w = frame.shape[:2]
        
        # If lores available and stream fits within lores, resize from lores (very fast)
        if frame_lores is not None:
            lores_h, lores_w = frame_lores.shape[:2]
            if stream_w <= lores_w and stream_h <= lores_h:
                if stream_w == lores_w and stream_h == lores_h:
                    stream_frame = frame_lores.copy()
                else:
                    stream_frame = cv2.resize(frame_lores, (stream_w, stream_h),
                                              interpolation=cv2.INTER_LINEAR)
                # Scale factors: main coords → stream coords (for annotation drawing)
                sx = stream_w / capture_w
                sy = stream_h / capture_h
                return stream_frame, sx, sy
        
        # Fallback: resize from main (for stream resolutions larger than lores)
        if stream_w != capture_w or stream_h != capture_h:
            stream_frame = cv2.resize(frame, (stream_w, stream_h),
                                      interpolation=cv2.INTER_LINEAR)
            sx = stream_w / capture_w
            sy = stream_h / capture_h
        else:
            stream_frame = frame.copy()
            sx = sy = 1.0
        return stream_frame, sx, sy
        
    def start(self):
        """Initialize and start all components"""
        print("Initializing video processor...")
        
        # Initialize components
        width, height = self.current_resolution
        self.camera = CameraHandler(width=width, height=height, fps=self.current_framerate)
        self.detector = TFLiteDetector()
        self.tracker = CentroidTracker()
        self.perimeter = PerimeterManager()
        self.motion_detector = MotionDetector(
            detection_scale=getattr(config, 'MOTION_DETECTION_SCALE', 0.25),
            motion_threshold=getattr(config, 'MOTION_THRESHOLD', 25),
            min_area=getattr(config, 'MOTION_MIN_AREA', 500),
            history_frames=getattr(config, 'MOTION_HISTORY_FRAMES', 3)
        )
        
        # Calibration (optional)
        if CALIBRATION_AVAILABLE:
            self.calibration = CameraCalibration()
        if LENS_CALIBRATION_AVAILABLE:
            self.lens_calibration = LensCalibration()
        
        # Inject cat handler (needs perimeter + calibration)
        self.inject_cat_handler = InjectCat(
            self.perimeter, self.calibration, self.pixel_to_world)
        
        # Set saved detection mode and threshold
        if hasattr(self, '_saved_detection_mode'):
            self.detector.set_detection_mode(self._saved_detection_mode)
        if hasattr(self, '_saved_threshold'):
            self.detector.set_threshold(self._saved_threshold)
        
        # Apply saved performance profile
        self._apply_performance_profile(self.current_profile, save=False)
        
        # Ensure video library directory exists
        lib_path = self.video_library_path or getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos')
        os.makedirs(lib_path, exist_ok=True)
        
        # Start camera
        self.camera.start()
        
        # Configure ISP lores stream state
        if self.camera.has_lores:
            self._using_lores = True
            self._lores_resolution = self.camera.lores_size
            # Re-apply motion scale for lores input
            if self.motion_detector:
                profile = config.PERFORMANCE_PROFILES.get(self.current_profile, {})
                adjusted_scale = self._lores_motion_scale(profile.get("motion_scale", 0.25))
                self.motion_detector.update_parameters(detection_scale=adjusted_scale)
            print(f"[LORES] ISP lores active: {self._lores_resolution[0]}×{self._lores_resolution[1]} "
                  f"(motion+stream resize eliminated)")
        else:
            self._using_lores = False
            print("[LORES] ISP lores not available — using main-frame resize (slower)")
        
        if self.video_source == "file" and self.video_file_path and os.path.isfile(self.video_file_path):
            self.file_camera = FileCameraHandler()
            try:
                self.file_camera.start(self.video_file_path)
            except Exception as e:
                print(f"File camera failed: {e}")
                self.file_camera = None
                self.video_source = "live"
        
        # Pre-allocate ring buffer (3 slots, zero alloc per frame)
        h, w = self.current_resolution[1], self.current_resolution[0]
        for i in range(3):
            self._ring_main[i] = np.empty((h, w, 3), dtype=np.uint8)
        lores_bytes = 0
        if self._using_lores:
            lh, lw = self._lores_resolution[1], self._lores_resolution[0]
            for i in range(3):
                self._ring_lores_y[i] = np.empty((lh, lw), dtype=np.uint8)
                self._ring_lores_bgr[i] = np.empty((lh, lw, 3), dtype=np.uint8)
            lores_bytes = lh * lw + lh * lw * 3
        ring_mb = 3 * (h * w * 3 + lores_bytes) / 1024 / 1024
        plog("[RING] Pre-allocated 3-slot ring buffer (%.1fMB)", ring_mb)
        
        # Start processing
        self.running = True
        
        use_callback = (self.video_source != "file" and not self.camera.use_mock
                        and _HAS_MAPPED_ARRAY)
        
        if use_callback:
            self.camera.camera.post_callback = self._frame_callback
            self._capture_thread = None
            plog("[CAPTURE] Callback-driven (no capture thread)")
        else:
            self._capture_thread = threading.Thread(
                target=self._file_capture_loop, daemon=True, name="CatDome-Cap")
            self._capture_thread.start()
            plog("[CAPTURE] File/mock fallback thread")
        
        # AI thread (async TFLite on cores 1-3)
        self._ai_request_queue = queue.Queue(maxsize=1)
        self._ai_result_queue = queue.Queue(maxsize=1)
        threading.stack_size(256 * 1024)
        self._ai_thread = threading.Thread(target=self._ai_loop, daemon=True, name="CatDome-AI")
        self._ai_thread.start()
        threading.stack_size(0)
        
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True, name="CatDome-Process")
        self.process_thread.start()
        
        mode_str = "MOTION-FIRST" if self.motion_first_enabled else "ALWAYS-ON"
        print(f"Video processor started (Detection mode: {mode_str})")
        
    def stop(self):
        """Stop all components"""
        self.running = False
        self._frame_ready.set()  # Unblock process thread if waiting
        self._stop_recording()
        # Wait for AI thread
        if self._ai_thread and self._ai_thread.is_alive():
            self._ai_thread.join(timeout=3.0)
            plog("[AI] Thread joined")
        # Wait for capture thread (only exists for file/mock camera)
        if hasattr(self, '_capture_thread') and self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)
        if self.file_camera:
            self.file_camera.stop()
            self.file_camera = None
        if self.camera:
            # Clear callback before stopping to avoid callback during shutdown
            if hasattr(self.camera, 'camera') and self.camera.camera:
                self.camera.camera.post_callback = None
            self.camera.stop()
        print("Video processor stopped")
        
    # =========================================================================
    # Camera Callback (Stage 2: callback-driven, no capture thread)
    # =========================================================================
    
    def _frame_callback(self, request):
        """Called by picamera2's camera thread when a frame is ready.
        
        Copies frame data into pre-allocated ring buffer slot and signals
        the processing thread.  Runs in picamera2's internal thread —
        must be fast (<20ms).  Zero per-frame allocation.
        """
        if not self.running:
            return
        
        t0 = time.perf_counter()
        
        try:
            wi = (self._ring_last_written + 1) % 3
            
            # Copy main frame into pre-allocated ring slot (no alloc)
            with MappedArray(request, "main", write=False) as m:
                np.copyto(self._ring_main[wi], m.array)
            
            # Copy lores into pre-allocated ring slot
            self._ring_lores_bgr_valid[wi] = False
            if self._using_lores:
                with MappedArray(request, "lores", write=False) as m:
                    lores_raw = m.array
                    lores_h_px = self._lores_resolution[1]
                    np.copyto(self._ring_lores_y[wi], lores_raw[:lores_h_px, :])
                    if self.stream_clients > 0:
                        cv2.cvtColor(lores_raw, cv2.COLOR_YUV2BGR_I420,
                                     dst=self._ring_lores_bgr[wi])
                        self._ring_lores_bgr_valid[wi] = True
            
            self._ring_copy_ms = round((time.perf_counter() - t0) * 1000, 1)
            self._ring_last_written = wi  # Publish completed slot
            self._frame_ready.set()
            
        except Exception as e:
            if not getattr(self, '_cb_error_logged', False):
                plog("[CALLBACK] Error: %s", e)
                self._cb_error_logged = True
    
    def _file_capture_loop(self):
        """Fallback capture loop for file/mock camera (no picamera2 callback).
        Only used when video_source='file' or mock camera.
        """
        try:
            import ctypes
            libc = ctypes.CDLL('libc.so.6')
            libc.prctl(15, b'CatDome-Cap', 0, 0, 0)
        except Exception:
            pass
        
        while self.running:
            try:
                t0 = time.perf_counter()
                
                if self.video_source == "file" and self.file_camera and self.file_camera.running:
                    frame = self.file_camera.get_frame()
                    if frame is None:
                        time.sleep(0.05)
                        continue
                else:
                    frame = self.camera.get_frame()
                    if frame is None:
                        time.sleep(0.01)
                        continue
                
                wi = (self._ring_last_written + 1) % 3
                
                # Copy into ring buffer (resize if shape mismatch)
                ring_shape = self._ring_main[wi].shape
                if frame.shape != ring_shape:
                    frame = cv2.resize(frame, (ring_shape[1], ring_shape[0]))
                np.copyto(self._ring_main[wi], frame)
                self._ring_lores_bgr_valid[wi] = False
                if self._using_lores:
                    cv2.resize(frame, self._lores_resolution,
                               interpolation=cv2.INTER_LINEAR,
                               dst=self._ring_lores_bgr[wi])
                    cv2.cvtColor(self._ring_lores_bgr[wi], cv2.COLOR_BGR2GRAY,
                                 dst=self._ring_lores_y[wi])
                    self._ring_lores_bgr_valid[wi] = True
                
                self._ring_copy_ms = round((time.perf_counter() - t0) * 1000, 1)
                self._ring_last_written = wi  # Publish completed slot
                self._frame_ready.set()
                
            except Exception as e:
                plog("[FILE_CAPTURE] Error: %s", e)
                time.sleep(0.1)
    
    # =========================================================================
    # Async AI Thread (Stage 4)
    # =========================================================================
    
    def _submit_ai(self, frame, crop_region):
        """Submit an AI request to the async AI thread (non-blocking).
        
        Copies the crop (or center crop for WATCH) into a pre-allocated buffer
        and puts the request on the queue.  Drops if AI is busy (queue full).
        """
        try:
            if crop_region:
                cx, cy, cw, ch = crop_region
                crop = frame[cy:cy+ch, cx:cx+cw].copy()
            else:
                # WATCH phase: center crop (saves RAM vs full frame copy)
                fh, fw = frame.shape[:2]
                cs = min(fw, fh, self.current_motion_crop_size)
                cx = (fw - cs) // 2
                cy = (fh - cs) // 2
                crop = frame[cy:cy+cs, cx:cx+cs].copy()
                crop_region = (cx, cy, cs, cs)
            self._ai_request_queue.put_nowait((crop, crop_region))
        except queue.Full:
            pass  # AI busy — skip this frame
    
    def _ai_loop(self):
        """Async AI inference thread — runs TFLite on cores 1-3.
        
        Blocks on _ai_request_queue, runs detect(), puts result on
        _ai_result_queue.  Handles model load/unload lifecycle.
        """
        # Set OS thread name
        try:
            import ctypes
            libc = ctypes.CDLL('libc.so.6')
            libc.prctl(15, b'CatDome-AI', 0, 0, 0)
        except Exception:
            pass
        
        # Pin to cores 1-3 (leave core 0 for camera + process)
        if getattr(config, 'THREAD_AFFINITY_ENABLED', False):
            try:
                os.sched_setaffinity(0, {1, 2, 3})
            except Exception:
                pass
        
        _idle_since = time.perf_counter()
        _AI_IDLE_UNLOAD_SEC = 3.0
        
        while self.running:
            try:
                try:
                    crop, crop_region = self._ai_request_queue.get(timeout=0.5)
                except queue.Empty:
                    # Unload model if idle long enough and phase is IDLE
                    if (self._phase == "IDLE" and self.detector and
                            time.perf_counter() - _idle_since > _AI_IDLE_UNLOAD_SEC):
                        if self.detector.interpreter is not None:
                            self.detector.unload_model()
                            reclaim_memory()
                            plog("[AI] Model unloaded (idle %.0fs)", _AI_IDLE_UNLOAD_SEC)
                    continue
                
                _idle_since = time.perf_counter()
                
                t1 = time.perf_counter()
                crop_detections = self.detector.detect(crop)
                tflite_ms = round((time.perf_counter() - t1) * 1000, 1)
                tflite_detail = getattr(self.detector, '_last_perf', None)
                
                # Remap crop coordinates to full frame
                cx, cy, cw, ch = crop_region
                detections = []
                for det in crop_detections:
                    x1, y1, x2, y2, conf, class_id = det
                    detections.append((x1 + cx, y1 + cy, x2 + cx, y2 + cy, conf, class_id))
                
                # Put result (drop old if unconsumed)
                try:
                    self._ai_result_queue.get_nowait()
                except queue.Empty:
                    pass
                self._ai_result_queue.put((detections, crop_region, tflite_ms, tflite_detail))
                
            except Exception as e:
                plog("[AI] Error: %s", e)
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
        
        # Cleanup on exit
        if self.detector and self.detector.interpreter is not None:
            self.detector.unload_model()
            plog("[AI] Thread exiting, model unloaded")
    
    # =========================================================================
    # Main Processing Loop
    # =========================================================================
    
    def _process_loop(self):
        """Main processing loop — motion → AI submit → tracking → annotation.
        
        Frames arrive from the ring buffer via _frame_ready event.
        AI detection is async — submitted to _ai_loop, results fetched
        non-blocking.  Handles both normal operation and inject cat test mode.
        """
        # Set OS thread name
        try:
            import ctypes
            libc = ctypes.CDLL('libc.so.6')
            libc.prctl(15, b'CatDome-Proc', 0, 0, 0)
        except Exception:
            pass
        
        # Optional: pin to Core 0 for cache locality
        if getattr(config, 'THREAD_AFFINITY_ENABLED', False):
            try:
                os.sched_setaffinity(0, {getattr(config, 'PROCESS_THREAD_CORE', 0)})
            except Exception:
                pass
        
        cv2.setNumThreads(1)  # Single-threaded OpenCV when idle
        skip_counter = 0
        last_detections = []
        
        while self.running:
            try:
                # ── Pending cleanup after inject stop (done here to avoid calling from Flask during detect()) ──
                if getattr(self, '_request_motion_reset_after_inject', False):
                    self._request_motion_reset_after_inject = False
                    if self.motion_detector:
                        self.motion_detector.reset()
                if getattr(self, '_request_unload_after_inject', False):
                    self._request_unload_after_inject = False
                    # AI thread owns model lifecycle — just reset OpenCV threads
                    cv2.setNumThreads(1)
                    plog("[INJECT CLEANUP] motion reset, OpenCV threads=1, phase=%s", self._phase)
                
                # ── Pending lores reconfigure ──
                if self._pending_lores_reconfigure is not None:
                    new_lores_w, new_lores_h = self._pending_lores_reconfigure
                    self._pending_lores_reconfigure = None
                    if self.camera.reconfigure_lores(new_lores_w, new_lores_h):
                        old_lores = self._lores_resolution
                        self._lores_resolution = (new_lores_w, new_lores_h)
                        self._using_lores = True
                        # Re-allocate ring buffer lores arrays for new resolution
                        for i in range(3):
                            self._ring_lores_y[i] = np.empty((new_lores_h, new_lores_w), dtype=np.uint8)
                            self._ring_lores_bgr[i] = np.empty((new_lores_h, new_lores_w, 3), dtype=np.uint8)
                            self._ring_lores_bgr_valid[i] = False
                        plog("[RING] Lores re-allocated for %s×%s", new_lores_w, new_lores_h)
                        profile = config.PERFORMANCE_PROFILES.get(self.current_profile, {})
                        adjusted_scale = self._lores_motion_scale(profile.get("motion_scale", 0.25))
                        self.motion_detector.update_parameters(detection_scale=adjusted_scale)
                        plog("[LORES] Reconfigured %s×%s → %s×%s, motion_scale=%.2f",
                             old_lores[0], old_lores[1], new_lores_w, new_lores_h, adjusted_scale)
                
                # ── Frame from ring buffer (filled by camera callback) ──
                t_qw = time.perf_counter()
                self._frame_ready.wait(timeout=0.5)
                self._frame_ready.clear()
                if not self.running:
                    break
                
                # Read from ring buffer (no lock needed — single writer, single reader)
                ri = self._ring_last_written
                if ri < 0:
                    continue  # No frame written yet
                frame = self._ring_main[ri]
                frame_lores = self._ring_lores_bgr[ri] if self._ring_lores_bgr_valid[ri] else None
                frame_lores_y = self._ring_lores_y[ri] if self._using_lores else None
                _lores_y_only = (self._using_lores and not self._ring_lores_bgr_valid[ri])
                copy_ms = self._ring_copy_ms
                
                if frame is None:
                    continue
                self._last_queue_wait_ms = round((time.perf_counter() - t_qw) * 1000, 1)
                self._last_capture_ms = copy_ms
                
                frame_h, frame_w = frame.shape[:2]
                tracked_objects = {}
                
                # ── Inject cat: simulate a camera frame that contains a moving cat ──
                if self.inject_cat and self.inject_cat_handler:
                    frame = self.inject_cat_handler.paste_on_frame(frame)
                    # Re-derive lores from main so motion detection sees the cat
                    if self._using_lores:
                        frame_lores = cv2.resize(frame, self._lores_resolution,
                                                 interpolation=cv2.INTER_LINEAR)
                        frame_lores_y = None
                        _lores_y_only = False
                
                # ══════════════════════════════════════════════════════════
                # PHASE STATE MACHINE: IDLE → ACQUISITION → TRACKING → WATCH
                # ══════════════════════════════════════════════════════════
                run_ai_detection = False
                crop_region = None
                motion_regions_in_perimeter = []
                
                skip_counter += 1
                if skip_counter >= self.current_frame_skip:
                    skip_counter = 0
                    self._update_fps()
                    self.frame_count += 1
                    self._phase_frame_counter += 1
                    now = time.time()
                    # Periodic heartbeat so journal shows activity when idle (no phase changes)
                    if now - self._last_heartbeat_time >= 30.0:
                        self._last_heartbeat_time = now
                        cpy = self._last_capture_ms if self._last_capture_ms is not None else "--"
                        mot = self._last_motion_ms if self._last_motion_ms is not None else "--"
                        plog("[HEARTBEAT] FPS=%.1f phase=%s cpy=%sms mot=%sms", self.fps, self._phase, cpy, mot)
                    
                    # Per-step timings for bottleneck analysis (logged every phase-block iteration)
                    _perf_crop_ms = None
                    _perf_tflite_ms = None
                    _perf_tflite_detail = None  # sub-breakdown from detector
                    _perf_track_ms = None
                    _perf_annot_ms = None
                    _perf_resize_ms = None
                    _perf_jpeg_ms = None
                    _perf_getcrop_ms = None  # time to compute crop region
                    _perf_filter_ms = None   # perimeter filter + temporal confirm
                    _perf_world_ms = None    # world coord computation
                    
                    # When inject_cat is active, skip IDLE and force straight to ACQUISITION
                    # (first inject frame has no motion history yet; subsequent frames will
                    # have natural motion from the cat moving across the scene)
                    if self.inject_cat and self._phase == "IDLE":
                        self._phase = "ACQUISITION"
                        self._phase_frame_counter = 0
                        self._last_motion_time = now
                        cv2.setNumThreads(4)
                        plog("[PHASE] IDLE → ACQUISITION (inject cat)")
                    
                    # ── PHASE: IDLE ──
                    # Motion detection only. TFLite not loaded. Low power.
                    if self._phase == "IDLE":
                        t_motion_start = time.perf_counter()
                        if frame_lores_y is not None:
                            motion_result = self.motion_detector.detect(frame_lores_y, gray_input=True)
                        else:
                            motion_input = frame_lores if frame_lores is not None else frame
                            motion_result = self.motion_detector.detect(motion_input)
                        self._scale_motion_to_main(motion_result, frame_w, frame_h)
                        self._last_motion_ms = round((time.perf_counter() - t_motion_start) * 1000, 1)
                        motion_regions_in_perimeter = self._filter_motion_to_perimeter(
                            motion_result, frame_w, frame_h)
                        self.motion_detected = len(motion_regions_in_perimeter) > 0
                        
                        if self.motion_detected:
                            # Transition → ACQUISITION
                            self._phase = "ACQUISITION"
                            self._phase_frame_counter = 0
                            self._last_motion_time = now
                            cv2.setNumThreads(4)
                            plog("[PHASE] IDLE → ACQUISITION (motion in Detection Zone)")
                    
                    # ── PHASE: ACQUISITION ──
                    # TFLite runs every frame, searching for cat.
                    elif self._phase == "ACQUISITION":
                        t_motion_start = time.perf_counter()
                        if frame_lores_y is not None:
                            motion_result = self.motion_detector.detect(frame_lores_y, gray_input=True)
                        else:
                            motion_input = frame_lores if frame_lores is not None else frame
                            motion_result = self.motion_detector.detect(motion_input)
                        self._scale_motion_to_main(motion_result, frame_w, frame_h)
                        self._last_motion_ms = round((time.perf_counter() - t_motion_start) * 1000, 1)
                        t_filt_motion = time.perf_counter()
                        motion_regions_in_perimeter = self._filter_motion_to_perimeter(
                            motion_result, frame_w, frame_h)
                        self.motion_detected = len(motion_regions_in_perimeter) > 0
                        if self.motion_detected:
                            self._last_motion_time = now
                        
                        # AI runs every frame during acquisition
                        run_ai_detection = True
                        t_getcrop = time.perf_counter()
                        crop_size = self.current_motion_crop_size
                        if self.inject_cat and self.inject_cat_handler:
                            crop_region = self.inject_cat_handler.get_crop_region(
                                frame_w, frame_h, crop_size)
                        elif motion_regions_in_perimeter:
                            crop_region = self.motion_detector.get_fixed_crop_region(
                                frame.shape, crop_size=crop_size)
                        _perf_getcrop_ms = round((time.perf_counter() - t_getcrop) * 1000, 1)
                        
                        # Timeout: no motion for 10s → back to IDLE
                        if not self.inject_cat and (now - self._last_motion_time > self._acquisition_timeout):
                            self._phase = "IDLE"
                            self._phase_frame_counter = 0
                            cv2.setNumThreads(1)
                            plog("[PHASE] ACQUISITION → IDLE (no motion for %ss)", self._acquisition_timeout)
                    
                    # ── PHASE: TRACKING ──
                    # Cat confirmed. TFLite every 3rd processed frame with motion crop.
                    elif self._phase == "TRACKING":
                        t_motion_start = time.perf_counter()
                        if frame_lores_y is not None:
                            motion_result = self.motion_detector.detect(frame_lores_y, gray_input=True)
                        else:
                            motion_input = frame_lores if frame_lores is not None else frame
                            motion_result = self.motion_detector.detect(motion_input)
                        self._scale_motion_to_main(motion_result, frame_w, frame_h)
                        self._last_motion_ms = round((time.perf_counter() - t_motion_start) * 1000, 1)
                        motion_regions_in_perimeter = self._filter_motion_to_perimeter(
                            motion_result, frame_w, frame_h)
                        self.motion_detected = len(motion_regions_in_perimeter) > 0
                        if self.motion_detected:
                            self._last_motion_time = now
                        
                        if self._phase_frame_counter % config.PHASE_TRACKING_AI_INTERVAL == 0:
                            run_ai_detection = True
                            crop_size = self.current_motion_crop_size
                            if self.inject_cat and self.inject_cat_handler:
                                crop_region = self.inject_cat_handler.get_crop_region(
                                    frame_w, frame_h, crop_size)
                            elif motion_regions_in_perimeter:
                                crop_region = self.motion_detector.get_fixed_crop_region(
                                    frame.shape, crop_size=crop_size)
                        
                        # Motion stopped → WATCH
                        if not self.motion_detected and not self.inject_cat:
                            self._phase = "WATCH"
                            self._phase_frame_counter = 0
                            plog("[PHASE] TRACKING → WATCH (motion stopped, watching for cat)")
                        
                        # No detection for 30s → IDLE
                        if now - self._last_detection_time > self._detection_timeout:
                            self._phase = "IDLE"
                            self._phase_frame_counter = 0
                            cv2.setNumThreads(1)
                            last_detections = []
                            self.last_detections_with_world = []
                            plog("[PHASE] TRACKING → IDLE (no detection for %ss)", self._detection_timeout)
                    
                    # ── PHASE: WATCH ──
                    # No motion but cat was recently detected. TFLite every 2nd frame.
                    elif self._phase == "WATCH":
                        t_motion_start = time.perf_counter()
                        if frame_lores_y is not None:
                            motion_result = self.motion_detector.detect(frame_lores_y, gray_input=True)
                        else:
                            motion_input = frame_lores if frame_lores is not None else frame
                            motion_result = self.motion_detector.detect(motion_input)
                        self._scale_motion_to_main(motion_result, frame_w, frame_h)
                        self._last_motion_ms = round((time.perf_counter() - t_motion_start) * 1000, 1)
                        motion_regions_in_perimeter = self._filter_motion_to_perimeter(
                            motion_result, frame_w, frame_h)
                        self.motion_detected = len(motion_regions_in_perimeter) > 0
                        
                        # Cat moved again → back to TRACKING
                        if self.motion_detected:
                            self._last_motion_time = now
                            self._phase = "TRACKING"
                            self._phase_frame_counter = 0
                            plog("[PHASE] WATCH → TRACKING (motion resumed)")
                        
                        if self._phase_frame_counter % config.PHASE_WATCH_AI_INTERVAL == 0:
                            run_ai_detection = True
                            # No crop in WATCH — scan wider area
                        
                        # No detection for 30s → IDLE
                        if now - self._last_detection_time > self._detection_timeout:
                            self._phase = "IDLE"
                            self._phase_frame_counter = 0
                            cv2.setNumThreads(1)
                            last_detections = []
                            self.last_detections_with_world = []
                            plog("[PHASE] WATCH → IDLE (no detection for %ss)", self._detection_timeout)
                    
                    # ── ASYNC AI: submit request (non-blocking) ──
                    if run_ai_detection:
                        t0 = time.perf_counter()
                        self._submit_ai(frame, crop_region)
                        _perf_crop_ms = round((time.perf_counter() - t0) * 1000, 1)
                    
                    # ── ASYNC AI: fetch result (non-blocking, 1-frame latency) ──
                    try:
                        ai_result = self._ai_result_queue.get_nowait()
                        detections, _ai_crop_region, _perf_tflite_ms, _perf_tflite_detail = ai_result
                        
                        # Inject Cat fallback: if TFLite didn't detect the pasted cat
                        if self.inject_cat and self.inject_cat_handler and self.inject_cat_handler.bbox:
                            bbox = self.inject_cat_handler.bbox
                            cat_class_id = config.COCO_CLASSES.get('cat', 17)
                            proximity = config.INJECT_BBOX_PROXIMITY_PX
                            tflite_found = any(
                                abs((d[0]+d[2])/2 - (bbox[0]+bbox[2])/2) < proximity and
                                abs((d[1]+d[3])/2 - (bbox[1]+bbox[3])/2) < proximity
                                for d in detections
                            )
                            if not tflite_found:
                                detections.append((bbox[0], bbox[1], bbox[2], bbox[3],
                                                   config.INJECT_FALLBACK_CONFIDENCE, cat_class_id))
                        
                        # Filter by perimeter + temporal confirmation
                        t_filter = time.perf_counter()
                        frame_res = (frame_w, frame_h)
                        raw_count = len(detections)
                        detections = self.perimeter.filter_detections(detections, frame_resolution=frame_res)
                        self.ai_detections_count += 1
                        
                        # Temporal confirmation
                        self.detection_history.append(len(detections) > 0)
                        if len(self.detection_history) > self.confirm_frames:
                            self.detection_history.pop(0)
                        if self.confirm_frames > 1:
                            confirmed = len(self.detection_history) >= self.confirm_frames and all(self.detection_history)
                            if not confirmed:
                                detections = []
                        _perf_filter_ms = round((time.perf_counter() - t_filter) * 1000, 1)
                        
                        last_detections = detections
                        
                        # Phase transitions based on detection results
                        if len(detections) > 0:
                            self._last_detection_time = now
                            # ACQUISITION → TRACKING (cat found!)
                            if self._phase == "ACQUISITION":
                                self._phase = "TRACKING"
                                self._phase_frame_counter = 0
                                plog("[PHASE] ACQUISITION → TRACKING (cat detected!)")
                        
                        # Compute world coordinates
                        t_world = time.perf_counter()
                        self.last_detections_with_world = []
                        for det in detections:
                            x1, y1, x2, y2, conf, class_id = det
                            world_pos = None
                            if self.calibration and self.calibration.is_calibrated:
                                bcx = (x1 + x2) / 2
                                bcy = y2  # bottom-center
                                wp = self.pixel_to_world(bcx, bcy, already_undistorted=False)
                                if wp:
                                    world_pos = {"world_x": round(wp[0], 2), "world_y": round(wp[1], 2)}
                            is_injected = (self.inject_cat and
                                          conf == config.INJECT_FALLBACK_CONFIDENCE and 
                                          self.inject_cat_handler and self.inject_cat_handler.bbox and
                                          abs(x1 - self.inject_cat_handler.bbox[0]) < 5)
                            self.last_detections_with_world.append({
                                "bbox": [x1, y1, x2, y2],
                                "confidence": round(conf, 2),
                                "class_id": class_id,
                                "world_position": world_pos,
                                "injected": is_injected
                            })
                        _perf_world_ms = round((time.perf_counter() - t_world) * 1000, 1)
                    except queue.Empty:
                        pass  # No AI result yet — use last_detections from previous frame
                    
                    # ── Tracking ──
                    t_track_start = time.perf_counter()
                    tracked_objects = self.tracker.update(last_detections) if last_detections else {}
                    # Merge tracker IDs into last_detections_with_world
                    if tracked_objects and self.last_detections_with_world:
                        tracked_bboxes = self.tracker.get_bboxes()  # {id: (x1,y1,x2,y2)}
                        for det in self.last_detections_with_world:
                            db = det["bbox"]  # [x1, y1, x2, y2]
                            det_cx = (db[0] + db[2]) / 2
                            det_cy = (db[1] + db[3]) / 2
                            best_id = None
                            best_dist = float('inf')
                            for tid, tb in tracked_bboxes.items():
                                tb_cx = (tb[0] + tb[2]) / 2
                                tb_cy = (tb[1] + tb[3]) / 2
                                d = abs(det_cx - tb_cx) + abs(det_cy - tb_cy)
                                if d < best_dist:
                                    best_dist = d
                                    best_id = tid
                            if best_id is not None and best_dist < 50:
                                det["track_id"] = best_id
                    _perf_track_ms = round((time.perf_counter() - t_track_start) * 1000, 1)
                    
                    # ── Annotation, JPEG pre-compute & frame storage ──
                    annotated = frame  # Always defined (used by recording below)
                    if self.stream_clients > 0:
                        t_annot_start = time.perf_counter()
                        
                        # Resize from lores (fast) or main (fallback), then draw on small frame
                        stream_w, stream_h = self.current_stream_resolution
                        t_rsz = time.perf_counter()
                        stream_frame, sx, sy = self._resize_for_stream(
                            frame, frame_lores, stream_w, stream_h)
                        _perf_resize_ms = round((time.perf_counter() - t_rsz) * 1000, 1)
                        
                        # Draw motion regions (scaled to stream res)
                        if self.show_motion_regions and self.motion_first_enabled and motion_regions_in_perimeter:
                            for mx, my, mw, mh in motion_regions_in_perimeter:
                                cv2.rectangle(stream_frame,
                                              (int(mx * sx), int(my * sy)),
                                              (int((mx + mw) * sx), int((my + mh) * sy)),
                                              (0, 255, 255), 2)
                            cv2.putText(stream_frame, "MOTION",
                                        (10, stream_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        
                        # Draw crop region (scaled)
                        if crop_region and self.show_motion_regions:
                            rcx, rcy, rcw, rch = crop_region
                            cv2.rectangle(stream_frame,
                                          (int(rcx * sx), int(rcy * sy)),
                                          (int((rcx + rcw) * sx), int((rcy + rch) * sy)),
                                          (255, 0, 255), 2)
                        
                        # Draw perimeter (pre-computed scaled cache)
                        perim_polygon, perim_pts = self._get_scaled_perimeter(stream_w, stream_h)
                        if perim_polygon is not None and len(perim_polygon) >= 3:
                            cv2.polylines(stream_frame, [perim_polygon], True,
                                          config.PERIMETER_COLOR, config.PERIMETER_THICKNESS)
                            for pt in perim_pts:
                                cv2.circle(stream_frame, pt, 3, config.PERIMETER_COLOR, -1)
                        
                        # Draw detections (scaled to stream res)
                        if last_detections:
                            box_color = config.BOX_COLOR_CAT if self.detector.detection_mode == "cat" else config.BOX_COLOR_BALL
                            for det in last_detections:
                                x1, y1, x2, y2, conf, class_id = det
                                sx1, sy1 = int(x1 * sx), int(y1 * sy)
                                sx2, sy2 = int(x2 * sx), int(y2 * sy)
                                cv2.rectangle(stream_frame, (sx1, sy1), (sx2, sy2), box_color, config.BOX_THICKNESS)
                                class_name = config.CLASS_NAMES.get(class_id, f"Class {class_id}")
                                label = f"{class_name}: {conf:.2f}"
                                if tracked_objects:
                                    cx_det, cy_det = (sx1 + sx2) // 2, (sy1 + sy2) // 2
                                    for obj_id, centroid in tracked_objects.items():
                                        if abs(int(centroid[0] * sx) - cx_det) < 20 and abs(int(centroid[1] * sy) - cy_det) < 20:
                                            label = f"ID:{obj_id} {label}"
                                            break
                                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX,
                                                               config.FONT_SCALE, config.FONT_THICKNESS)
                                cv2.rectangle(stream_frame, (sx1, sy1 - th - 10), (sx1 + tw + 5, sy1),
                                              config.TEXT_BG_COLOR, -1)
                                cv2.putText(stream_frame, label, (sx1 + 2, sy1 - 5),
                                            cv2.FONT_HERSHEY_SIMPLEX, config.FONT_SCALE,
                                            config.TEXT_COLOR, config.FONT_THICKNESS)
                        
                        self._draw_status(stream_frame)
                        t_jpg = time.perf_counter()
                        with self._cached_jpeg_lock:
                            self._cached_jpeg = self._encode_jpeg(stream_frame, self.current_jpeg_quality)
                        _perf_jpeg_ms = round((time.perf_counter() - t_jpg) * 1000, 1)
                        _perf_annot_ms = round((time.perf_counter() - t_annot_start) * 1000, 1)
                    
                    # Update overlay data for H.264 Canvas streaming (always, even without clients —
                    # data is tiny and read by WebSocket route when clients connect)
                    self._update_overlay_data(last_detections, motion_regions_in_perimeter,
                                              crop_region, tracked_objects)
                    
                    # Store raw frame for snapshot and recording
                    # With zero-copy, frame is a DMA view that becomes invalid after release
                    with self.frame_lock:
                        self.current_frame = frame
                    
                    # ── Recording ──
                    if self.video_source == "live" and self.recording_enabled:
                        target_class = config.COCO_CLASSES.get(self.get_detection_mode(), 17)
                        has_target = any(d[5] == target_class for d in last_detections)
                        now = time.time()
                        if has_target:
                            if self._recording_writer is None:
                                self._start_recording()
                            if self._recording_writer is not None:
                                self._recording_writer.write(annotated)
                                self._recording_last_detection_time = now
                        else:
                            if self._recording_writer is not None and (now - self._recording_last_detection_time) >= self.record_after_detection_sec:
                                self._stop_recording()
                    
                    # Per-step timings to log every phase-block iteration (bottleneck analysis)
                    # cpy = callback copy time (DMA→ring buffer memcpy, ~17ms)
                    # qw = event wait (how long process thread waited for next frame)
                    # sub = AI submit time (crop copy + queue put, non-blocking)
                    # tf = TFLite invoke time (from async AI result, 1-frame latency)
                    # filt/world = only present when AI result was fetched this frame
                    cpy = self._last_capture_ms if self._last_capture_ms is not None else 0
                    qw = self._last_queue_wait_ms if self._last_queue_wait_ms is not None else 0
                    mot = self._last_motion_ms if self._last_motion_ms is not None else 0
                    getcrop_s = _perf_getcrop_ms if _perf_getcrop_ms is not None else "-"
                    sub_s = _perf_crop_ms if _perf_crop_ms is not None else "-"
                    # TFLite with sub-breakdown (async — from AI thread result)
                    if _perf_tflite_ms is not None and _perf_tflite_detail:
                        d = _perf_tflite_detail
                        tflite_s = "%.0f(ld=%s pre=%s inv=%s post=%s)" % (
                            _perf_tflite_ms, d.get("load", "-"), d.get("pre", "-"),
                            d.get("invoke", "-"), d.get("post", "-"))
                    elif _perf_tflite_ms is not None:
                        tflite_s = str(_perf_tflite_ms)
                    else:
                        tflite_s = "-"
                    filt_s = _perf_filter_ms if _perf_filter_ms is not None else "-"
                    world_s = _perf_world_ms if _perf_world_ms is not None else "-"
                    track_s = _perf_track_ms if _perf_track_ms is not None else "-"
                    if _perf_annot_ms is not None:
                        rsz_s = _perf_resize_ms if _perf_resize_ms is not None else "-"
                        jpg_s = _perf_jpeg_ms if _perf_jpeg_ms is not None else "-"
                        annot_s = "%.0f(rsz=%s jpg=%s)" % (_perf_annot_ms, rsz_s, jpg_s)
                    else:
                        annot_s = "-"
                    plog("[PERF] cpy=%.0fms qw=%.0fms mot=%.0fms gcrop=%s sub=%s tf=%s filt=%s world=%s trk=%s ann=%s ph=%s",
                         cpy, qw, mot, getcrop_s, sub_s, tflite_s, filt_s, world_s, track_s, annot_s, self._phase)
                    
                    # Rate-limit inject mode
                if self.inject_cat:
                    time.sleep(config.INJECT_MODE_SLEEP_SEC)
                else:
                    time.sleep(0.001)
                
            except Exception as e:
                plog("Processing error: %s", e)
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
                
    # =========================================================================
    # Frame Annotation & FPS
    # =========================================================================
    
    def _draw_status(self, frame):
        """Draw status overlay (mode, FPS, object count, phase, timestamp)."""
        pad = config.STATUS_BOX_PADDING
        min_w = config.STATUS_BOX_MIN_WIDTH
        text_pad = config.STATUS_TEXT_PADDING
        extra_h = config.STATUS_BOX_HEIGHT_EXTRA
        fs_main = config.STATUS_FONT_SCALE_MAIN
        fs_sub = config.STATUS_FONT_SCALE_SUB
        thick_main = config.STATUS_FONT_THICKNESS_MAIN
        thick_sub = config.STATUS_FONT_THICKNESS_SUB
        ts_margin = config.STATUS_TIMESTAMP_MARGIN

        mode_text = self.detector.get_detection_mode().upper()
        status_text = f"Mode: {mode_text} | FPS: {self.fps:.1f}"
        (text_w, text_h), _ = cv2.getTextSize(status_text, cv2.FONT_HERSHEY_SIMPLEX, fs_main, thick_main)
        cv2.rectangle(frame, (pad, pad), (max(text_w + text_pad, min_w), text_h + extra_h), (0, 0, 0), -1)
        cv2.putText(frame, status_text, (pad + 5, text_h + 10), cv2.FONT_HERSHEY_SIMPLEX, fs_main, (0, 255, 0), thick_main)

        count_text = f"Objects: {self.tracker.get_object_count()}"
        cv2.putText(frame, count_text, (pad + 5, text_h + 32), cv2.FONT_HERSHEY_SIMPLEX, fs_sub, (255, 255, 0), thick_sub)

        phase_colors = {
            "IDLE": (128, 128, 128),
            "ACQUISITION": (0, 255, 255),
            "TRACKING": (0, 255, 0),
            "WATCH": (0, 165, 255)
        }
        phase_color = phase_colors.get(self._phase, (255, 255, 255))
        cv2.putText(frame, f"Phase: {self._phase}", (pad + 5, text_h + 52),
                    cv2.FONT_HERSHEY_SIMPLEX, fs_sub, phase_color, thick_sub)

        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        (ts_w, ts_h), _ = cv2.getTextSize(timestamp, cv2.FONT_HERSHEY_SIMPLEX, fs_sub, thick_sub)
        ts_x = frame.shape[1] - ts_w - ts_margin
        ts_y = ts_h + pad
        cv2.rectangle(frame, (ts_x - pad, pad), (frame.shape[1] - pad, ts_y + pad), (0, 0, 0), -1)
        cv2.putText(frame, timestamp, (ts_x, ts_y), cv2.FONT_HERSHEY_SIMPLEX, fs_sub, (255, 255, 255), thick_sub)
        
    def _filter_motion_to_perimeter(self, motion_result, frame_w, frame_h):
        """Filter motion regions to only those inside the Detection Zone.
        
        Args:
            motion_result: Dict from motion_detector.detect() with 'motion_detected' and 'regions'
            frame_w: Frame width in pixels
            frame_h: Frame height in pixels
            
        Returns:
            List of (x, y, w, h) regions that are inside the Detection Zone
        """
        regions_in_perimeter = []
        if motion_result["motion_detected"] and motion_result["regions"]:
            frame_res = (frame_w, frame_h)
            for region in motion_result["regions"]:
                rx, ry, rw, rh = region
                center_x = rx + rw // 2
                center_y = ry + rh // 2
                if self.perimeter.is_inside((center_x, center_y), frame_res):
                    regions_in_perimeter.append(region)
        return regions_in_perimeter
    
    def _update_fps(self):
        """Update FPS calculation"""
        self._fps_count += 1
        elapsed = time.time() - self._fps_start
        if elapsed >= 1.0:
            self.fps = self._fps_count / elapsed
            self._fps_count = 0
            self._fps_start = time.time()
    
    # =========================================================================
    # Recording
    # =========================================================================
    
    def _start_recording(self):
        """Start writing a new video clip."""
        lib = self.video_library_path or getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos')
        os.makedirs(lib, exist_ok=True)
        obj_name = self.get_detection_mode()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._recording_filename = os.path.join(lib, f"{obj_name}_{ts}.mp4")
        w, h = self.current_resolution
        fps = self.current_framerate
        for fourcc_name in (getattr(config, 'RECORDING_FOURCC', 'avc1'), 'mp4v', 'X264'):
            fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
            self._recording_writer = cv2.VideoWriter(self._recording_filename, fourcc, fps, (w, h))
            if self._recording_writer is not None and self._recording_writer.isOpened():
                break
            if self._recording_writer is not None:
                self._recording_writer.release()
            self._recording_writer = None
        try:
            if self._recording_writer is None:
                return
            self._recording_start_time = time.time()
            self._recording_last_detection_time = time.time()
            plog("[REC] Started: %s", self._recording_filename)
        except Exception as e:
            plog("[REC] Start failed: %s", e)
            self._recording_writer = None
    
    def _stop_recording(self):
        """Stop current clip and release writer."""
        if self._recording_writer is None:
            return
        try:
            self._recording_writer.release()
            plog("[REC] Stopped: %s", self._recording_filename)
        except Exception:
            pass
        self._recording_writer = None
        self._recording_filename = None
        self._recording_start_time = None
        self._recording_last_detection_time = None
            
    # =========================================================================
    # Frame JPEG Encoding
    # =========================================================================
    
    def get_frame_jpeg(self):
        """Get pre-computed JPEG bytes at stream resolution.
        
        The JPEG is built in _process_loop (resize + overlay + encode)
        so this method is zero-copy — just returns cached bytes.
        """
        with self._cached_jpeg_lock:
            return self._cached_jpeg
    
    def get_frame_jpeg_capture_resolution(self, undistort=False):
        """Get current frame as JPEG at capture resolution.
        If undistort=True and lens calibration available, applies correction."""
        with self.frame_lock:
            if self.current_frame is None:
                return None
            frame = self.current_frame.copy()
        if undistort and self.lens_calibration and self.lens_calibration.is_calibrated:
            frame = self.lens_calibration.undistort_frame(frame)
        return self._encode_jpeg(frame, min(85, self.current_jpeg_quality + 15))
        
    # =========================================================================
    # Detection & Tracking Settings
    # =========================================================================
    
    def set_detection_mode(self, mode):
        if self.detector:
            self.detector.set_detection_mode(mode)
            self.tracker.reset()
            settings.update_setting("detection_mode", mode)
            print(f"[SETTING] Detection mode changed to: {mode}")
            
    def get_detection_mode(self):
        if self.detector:
            return self.detector.get_detection_mode()
        return config.DEFAULT_DETECTION_MODE
    
    def set_detection_threshold(self, threshold):
        if self.detector:
            self.detector.set_threshold(threshold)
            settings.update_setting("detection_threshold", threshold)
            print(f"[SETTING] Detection threshold changed to: {threshold:.0%}")
    
    def get_detection_threshold(self):
        if self.detector:
            return self.detector.get_threshold()
        return config.DETECTION_THRESHOLD
    
    def set_confirm_frames(self, frames):
        self.confirm_frames = max(1, min(5, int(frames)))
        self.detection_history = []
        settings.update_setting("confirm_frames", self.confirm_frames)
        print(f"[SETTING] Confirmation frames changed to: {self.confirm_frames}")
        
    def set_perimeter(self, points):
        if self.perimeter:
            result = self.perimeter.set_points(points)
            self._scaled_perimeter_cache = None  # invalidate
            return result
        return False
        
    def get_perimeter(self):
        if self.perimeter:
            return self.perimeter.get_points()
        return []
        
    def clear_perimeter(self):
        if self.perimeter:
            self.perimeter.clear()
            self._scaled_perimeter_cache = None  # invalidate
            print("[SETTING] Perimeter cleared")
    
    def _get_scaled_perimeter(self, stream_w, stream_h):
        """Return pre-computed perimeter polygon and points scaled for stream resolution.
        Cached — only recomputed when perimeter or stream resolution changes."""
        cache = self._scaled_perimeter_cache
        if cache is not None and cache[0] == stream_w and cache[1] == stream_h:
            return cache[2], cache[3]  # (polygon_np, points_list)
        # Compute
        if not self.perimeter or self.perimeter.polygon is None or len(self.perimeter.polygon) < 3:
            self._scaled_perimeter_cache = (stream_w, stream_h, None, [])
            return None, []
        saved_w, saved_h = self.perimeter.saved_resolution
        scale_x = stream_w / saved_w
        scale_y = stream_h / saved_h
        scaled_pts = [(int(x * scale_x), int(y * scale_y)) for x, y in self.perimeter.points]
        polygon = np.array(scaled_pts, dtype=np.int32)
        self._scaled_perimeter_cache = (stream_w, stream_h, polygon, scaled_pts)
        return polygon, scaled_pts
            
    def get_status(self):
        """Get current system status"""
        import main as main_module
        system_info = get_system_info()
        is_calibrated = self.calibration and hasattr(self.calibration, 'is_calibrated') and self.calibration.is_calibrated
        return {
            "version": getattr(main_module, "__version__", "?"),
            "fps": round(self.fps, 1),
            "frame_count": self.frame_count,
            "detection_mode": self.get_detection_mode(),
            "detection_threshold": self.get_detection_threshold(),
            "confirm_frames": self.confirm_frames,
            "object_count": self.tracker.get_object_count() if self.tracker else 0,
            "perimeter_points": len(self.get_perimeter()),
            "resolution": list(self.current_resolution),
            "framerate": self.current_framerate,
            "frame_skip": self.current_frame_skip,
            "is_calibrated": is_calibrated,
            "detections": self.last_detections_with_world,
            "ram_used_mb": system_info["ram_used_mb"],
            "ram_total_mb": system_info["ram_total_mb"],
            "ram_percent": system_info["ram_percent"],
            "cpu_percent": system_info["cpu_percent"],
            "cpu_temp": system_info["cpu_temp"],
            "motion_first_enabled": self.motion_first_enabled,
            "motion_detected": self.motion_detected,
            "show_motion_regions": self.show_motion_regions,
            "ai_detections_count": self.ai_detections_count,
            "performance_profile": self.current_profile,
            "phase": self._phase,
            "capture_ms": self._last_capture_ms,
            "motion_ms": self._last_motion_ms
        }
    
    # =========================================================================
    # Calibration Methods (preserved exactly — same work order and data format)
    # =========================================================================
    
    def get_calibration(self):
        if self.calibration:
            return self.calibration.to_json()
        return {"is_calibrated": False, "points": [], "world_bounds": config.DEFAULT_WORLD_BOUNDS, "rectangles": []}
    
    def _undistort_pixels(self, points_pixel):
        """Undistort pixel coordinates if lens calibration available."""
        if self.lens_calibration and self.lens_calibration.is_calibrated:
            undistorted = []
            for p in points_pixel:
                ux, uy = self.lens_calibration.undistort_point(float(p[0]), float(p[1]))
                undistorted.append([ux, uy])
            return undistorted
        return points_pixel

    def _redistort_pixels(self, points_pixel):
        """Convert undistorted+cropped pixels back to raw (distorted) pixels."""
        if self.lens_calibration and self.lens_calibration.is_calibrated:
            raw = []
            for p in points_pixel:
                rx, ry = self.lens_calibration.redistort_point(float(p[0]), float(p[1]))
                raw.append([int(round(rx)), int(round(ry))])
            return raw
        return [[int(p[0]), int(p[1])] for p in points_pixel]
    
    def set_calibration(self, points):
        """Set calibration points (undistorts pixels if lens calibration available)"""
        if self.calibration:
            if self.lens_calibration and self.lens_calibration.is_calibrated:
                for p in points:
                    ux, uy = self.lens_calibration.undistort_point(float(p["pixel"][0]), float(p["pixel"][1]))
                    p["pixel"] = [ux, uy]
            return self.calibration.set_calibration_points(points)
        return False

    def set_calibration_from_rectangles(self, rectangles):
        """Set calibration from multiple rectangles.
        Pixels are in undistorted+cropped space (user clicks on corrected snapshot)."""
        if self.calibration:
            self.calibration.rectangles = rectangles
            return self.calibration.set_calibration_from_rectangles(rectangles)
        return False
    
    def clear_calibration(self):
        if self.calibration:
            self.calibration.clear()
    
    def pixel_to_world(self, pixel_x, pixel_y, already_undistorted=False):
        """Convert pixel coordinates to world coordinates.
        If already_undistorted=False (default), applies lens undistortion first."""
        if self.calibration and self.calibration.is_calibrated:
            ux, uy = pixel_x, pixel_y
            if not already_undistorted and self.lens_calibration and self.lens_calibration.is_calibrated:
                ux, uy = self.lens_calibration.undistort_point(pixel_x, pixel_y)
            return self.calibration.pixel_to_world(ux, uy)
        return None
    
    def get_topdown_data(self):
        """Get top-down view data (perimeter + tracked objects in world coordinates)."""
        is_calibrated = self.calibration and self.calibration.is_calibrated
        result = {
            "is_calibrated": is_calibrated,
            "world_bounds": self.calibration.get_world_bounds() if is_calibrated else None,
            "perimeter_world": [],
            "objects": []
        }
        if not is_calibrated:
            return result
        
        perimeter_points = self.get_perimeter()
        if perimeter_points:
            frame_res = None
            if self.camera and self.camera.running:
                frame_res = self.camera.get_resolution()
            
            if not hasattr(self, '_topdown_debug_done'):
                saved_res = self.perimeter.saved_resolution if hasattr(self.perimeter, 'saved_resolution') else 'N/A'
                print(f"[TOPDOWN DEBUG] frame_res={frame_res}, perimeter saved_res={saved_res}, "
                      f"perimeter points={len(perimeter_points)}, "
                      f"lens_cal={'ON' if self.lens_calibration and self.lens_calibration.is_calibrated else 'OFF'}")
                print(f"[TOPDOWN DEBUG] calibration points={len(self.calibration.calibration_points)}, "
                      f"rectangles={len(self.calibration.rectangles)}")
                for i, cp in enumerate(self.calibration.calibration_points[:4]):
                    print(f"[TOPDOWN DEBUG]   cal point {i}: pixel={cp['pixel']}, world={cp['world']}")
                self._topdown_debug_done = True
            
            for idx, point in enumerate(perimeter_points):
                px, py = float(point[0]), float(point[1])
                world_pos = self.pixel_to_world(px, py, already_undistorted=False)
                if world_pos:
                    result["perimeter_world"].append({"x": round(world_pos[0], 2), "y": round(world_pos[1], 2)})
        
        for det in self.last_detections_with_world:
            wp = det.get("world_position")
            if wp:
                result["objects"].append({
                    "id": det.get("track_id", 0),
                    "class": det.get("class_id", 0),
                    "confidence": det.get("confidence", 0),
                    "world_x": wp.get("world_x", 0),
                    "world_y": wp.get("world_y", 0)
                })
        return result
    
    # =========================================================================
    # Performance Profile Management
    # =========================================================================
    
    def get_performance_settings(self):
        return {
            "current": {
                "resolution": list(self.current_resolution),
                "stream_resolution": list(self.current_stream_resolution),
                "framerate": self.current_framerate,
                "frame_skip": self.current_frame_skip
            },
            "options": {
                "resolutions": [list(config.CAPTURE_RESOLUTION)],
                "stream_resolutions": [list(r) for r in config.STREAM_RESOLUTION_OPTIONS],
                "framerates": config.FRAMERATE_OPTIONS,
                "frame_skips": config.FRAME_SKIP_OPTIONS
            }
        }
    
    def set_resolution(self, width, height):
        print(f"[WARNING] Capture resolution is fixed at 2304x1296")
        return False
    
    def set_stream_resolution(self, width, height):
        new_res = (width, height)
        if new_res not in config.STREAM_RESOLUTION_OPTIONS:
            return False
        self.current_stream_resolution = new_res
        self._scaled_perimeter_cache = None  # invalidate
        settings.update_setting("stream_resolution", list(new_res))
        
        if self._using_lores:
            # Compute the lores size needed: at least stream_res, at least config minimum
            min_lores_w = max(width, config.LORES_RESOLUTION[0])
            min_lores_h = max(height, config.LORES_RESOLUTION[1])
            lores_w, lores_h = self._lores_resolution
            
            if min_lores_w != lores_w or min_lores_h != lores_h:
                # Lores needs reconfiguration — schedule for processing thread
                # (camera operations must happen on the thread that captures frames)
                self._pending_lores_reconfigure = (min_lores_w, min_lores_h)
                print(f"[SETTING] Stream resolution -> {width}x{height} "
                      f"(lores reconfigure {lores_w}x{lores_h} -> {min_lores_w}x{min_lores_h} pending)")
            else:
                src = "no resize" if (width == lores_w and height == lores_h) else f"lores {lores_w}x{lores_h}"
                print(f"[SETTING] Stream resolution -> {width}x{height} ({src})")
        else:
            print(f"[SETTING] Stream resolution -> {width}x{height} (resize from main)")
        return True
    
    def set_framerate(self, fps):
        if fps not in config.FRAMERATE_OPTIONS:
            return False
        self.current_framerate = fps
        settings.update_setting("framerate", fps)
        if self.camera:
            self.camera.stop()
            width, height = self.current_resolution
            self.camera = CameraHandler(width=width, height=height, fps=fps)
            self.camera.start()
        print(f"[SETTING] Framerate changed to: {fps} fps")
        return True
    
    def set_frame_skip(self, skip):
        if skip not in config.FRAME_SKIP_OPTIONS:
            return False
        self.current_frame_skip = skip
        settings.update_setting("frame_skip", skip)
        return True
    
    def get_performance_profiles(self):
        return {"profiles": config.PERFORMANCE_PROFILES, "current": self.current_profile}
    
    def get_current_profile(self):
        return {"profile": self.current_profile, "settings": config.PERFORMANCE_PROFILES.get(self.current_profile, {})}
    
    def set_performance_profile(self, profile_name):
        if profile_name not in config.PERFORMANCE_PROFILES:
            print(f"[ERROR] Invalid profile: {profile_name}")
            return False
        return self._apply_performance_profile(profile_name, save=True)
    
    def _apply_performance_profile(self, profile_name, save=True):
        if profile_name not in config.PERFORMANCE_PROFILES:
            print(f"[WARNING] Profile '{profile_name}' not found. Using default.")
            profile_name = config.DEFAULT_PERFORMANCE_PROFILE
            if save:
                settings.update_setting("performance_profile", profile_name)
        
        profile = config.PERFORMANCE_PROFILES[profile_name]
        self.current_jpeg_quality = profile["jpeg_quality"]
        
        if self.motion_detector:
            # Adjust motion scale for lores input (profile scale is for full capture resolution)
            adjusted_scale = self._lores_motion_scale(profile["motion_scale"])
            self.motion_detector.update_parameters(
                detection_scale=adjusted_scale,
                motion_threshold=profile["motion_threshold"],
                min_area=profile["motion_min_area"])
        
        if self.detector and profile["tflite_threads"] != self.detector.num_threads:
            self.detector.num_threads = profile["tflite_threads"]
        
        self.current_motion_crop_size = profile["motion_crop_size"]
        self.current_profile = profile_name
        
        if save:
            settings.update_setting("performance_profile", profile_name)
        
        lores_info = f" (adjusted for lores: {self._lores_motion_scale(profile['motion_scale']):.2f})" if self._using_lores else ""
        print(f"[PROFILE] Applied '{profile['name']}' profile")
        print(f"  - JPEG Quality: {profile['jpeg_quality']}%")
        print(f"  - AI Crop: {profile['motion_crop_size']}")
        print(f"  - Motion Scale: {profile['motion_scale']}{lores_info}")
        print(f"  - TFLite Threads: {profile['tflite_threads']}")
        return True


# =============================================================================
# Global Video Processor Instance
# =============================================================================

video_processor = VideoProcessor()


# =============================================================================
# Flask Application Factory
# =============================================================================

def create_app():
    """Create and configure Flask application with Blueprint routes."""
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )
    
    # Register route blueprints
    from web.routes_streaming import streaming_bp, init_streaming_routes
    from web.routes_status import status_bp, init_status_routes
    from web.routes_perimeter import perimeter_bp, init_perimeter_routes
    from web.routes_performance import performance_bp, init_performance_routes
    from web.routes_calibration import calibration_bp, init_calibration_routes
    from web.routes_video import video_bp, init_video_routes
    from web.routes_dev import dev_bp, init_dev_routes
    from web.routes_h264 import init_h264_routes
    
    # Initialize routes with video processor reference
    init_streaming_routes(video_processor)
    init_status_routes(video_processor)
    init_perimeter_routes(video_processor)
    init_performance_routes(video_processor)
    init_calibration_routes(video_processor)
    init_video_routes(video_processor)
    init_dev_routes(video_processor)
    
    # Register blueprints
    app.register_blueprint(streaming_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(perimeter_bp)
    app.register_blueprint(performance_bp)
    app.register_blueprint(calibration_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(dev_bp)
    
    # H.264 WebSocket route (registered on app, not as blueprint — flask-sock requirement)
    if getattr(config, 'H264_ENABLED', False):
        init_h264_routes(app, video_processor)
        
    return app


def run_server():
    """Run the web server"""
    video_processor.start()
    try:
        app = create_app()
        app.run(
            host=config.HOST,
            port=config.PORT,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    finally:
        video_processor.stop()


if __name__ == '__main__':
    run_server()
