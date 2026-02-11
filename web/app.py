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

# Suppress Flask/Werkzeug access logs (the GET /api/status messages)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

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
        self._last_motion_ms = None
        self._last_heartbeat_time = 0.0  # for periodic log so journal shows activity when idle
        
        # Frame storage for streaming
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self._stream_clients_lock = threading.Lock()
        self._stream_clients = 0  # Number of active MJPEG stream connections
        
        # Pre-computed JPEG cache (built in _process_loop, read by get_frame_jpeg)
        self._cached_jpeg = None        # JPEG bytes for MJPEG stream
        self._cached_jpeg_lock = threading.Lock()
        self._cached_capture_frame = None  # Raw frame for snapshot/recording
        
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
        self.recording_enabled = saved.get("recording_enabled", True)
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
        if self.video_source == "file" and self.video_file_path and os.path.isfile(self.video_file_path):
            self.file_camera = FileCameraHandler()
            try:
                self.file_camera.start(self.video_file_path)
            except Exception as e:
                print(f"File camera failed: {e}")
                self.file_camera = None
                self.video_source = "live"
        
        # Start processing thread
        self.running = True
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True, name="CatDome-Process")
        self.process_thread.start()
        
        mode_str = "MOTION-FIRST" if self.motion_first_enabled else "ALWAYS-ON"
        print(f"Video processor started (Detection mode: {mode_str})")
        
    def stop(self):
        """Stop all components"""
        self.running = False
        self._stop_recording()
        if self.file_camera:
            self.file_camera.stop()
            self.file_camera = None
        if self.camera:
            self.camera.stop()
        print("Video processor stopped")
        
    # =========================================================================
    # Main Processing Loop
    # =========================================================================
    
    def _process_loop(self):
        """Main processing loop — camera → motion → AI → tracking → annotation.
        
        Handles both normal operation and inject cat test mode.
        In inject mode, the cat image is pasted on the real camera frame,
        then the same pipeline processes it.
        """
        # Set OS thread name
        try:
            import ctypes
            libc = ctypes.CDLL('libc.so.6')
            PR_SET_NAME = 15  # Linux prctl constant for setting thread name
            libc.prctl(PR_SET_NAME, b'CatDome-Proc', 0, 0, 0)
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
                    if self.detector:
                        self.detector.unload_model()
                    cv2.setNumThreads(1)
                    plog("[INJECT CLEANUP] motion reset, TFLite unload, OpenCV threads=1, phase=%s", self._phase)
                
                # ── Frame capture ──
                t_capture_start = time.perf_counter()
                frame = None
                if self.video_source == "file" and self.file_camera and self.file_camera.running:
                    frame = self.file_camera.get_frame()
                    if frame is None:
                        time.sleep(0.05)
                        continue
                else:
                    request = self.camera.get_request()
                    if request is None:
                        frame = self.camera.get_frame()
                        if frame is None:
                            time.sleep(0.01)
                            continue
                    else:
                        with request as req:
                            frame = req.make_array("main")
                self._last_capture_ms = round((time.perf_counter() - t_capture_start) * 1000, 1)
                
                frame_h, frame_w = frame.shape[:2]
                tracked_objects = {}  # Used by phase block and by inject stream update below
                
                # ── Inject cat: paste cat on real camera frame ──
                if self.inject_cat and self.inject_cat_handler:
                    frame = self.inject_cat_handler.paste_on_frame(frame)
                    # Debug logging
                    if not hasattr(self, '_inject_debug_count'):
                        self._inject_debug_count = 0
                    self._inject_debug_count += 1
                    if self._inject_debug_count <= 5 or self._inject_debug_count % 50 == 0:
                        ram_info = get_ram_stats()
                        plog("[INJECT DEBUG] %s, clients=%s, RAM: %s",
                             self.inject_cat_handler.get_debug_info(), self.stream_clients, ram_info)
                    # Update stream every frame so the cat moves visibly (phase block only runs every frame_skip)
                    if self.stream_clients > 0:
                        stream_w, stream_h = self.current_stream_resolution
                        if stream_w != frame_w or stream_h != frame_h:
                            ann = cv2.resize(frame, (stream_w, stream_h), interpolation=cv2.INTER_AREA)
                        else:
                            ann = frame.copy()
                        # Draw perimeter (cached scaled)
                        perim_polygon, perim_pts = self._get_scaled_perimeter(stream_w, stream_h)
                        if perim_polygon is not None and len(perim_polygon) >= 3:
                            cv2.polylines(ann, [perim_polygon], True,
                                          config.PERIMETER_COLOR, config.PERIMETER_THICKNESS)
                        self._draw_status(ann)
                        ret, jpeg_buf = cv2.imencode('.jpg', ann, [cv2.IMWRITE_JPEG_QUALITY, self.current_jpeg_quality])
                        with self._cached_jpeg_lock:
                            self._cached_jpeg = jpeg_buf.tobytes() if ret else None
                        with self.frame_lock:
                            self.current_frame = frame
                
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
                        cap = self._last_capture_ms if self._last_capture_ms is not None else "--"
                        mot = self._last_motion_ms if self._last_motion_ms is not None else "--"
                        plog("[HEARTBEAT] FPS=%.1f phase=%s cap=%sms mot=%sms", self.fps, self._phase, cap, mot)
                    
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
                    
                    # When inject_cat, skip motion/AI/annotation so loop stays fast and cat keeps moving
                    if not self.inject_cat:
                        # ── PHASE: IDLE ──
                        # Motion detection only. TFLite not loaded. Low power.
                        if self._phase == "IDLE":
                            t_motion_start = time.perf_counter()
                            motion_result = self.motion_detector.detect(frame)
                            self._last_motion_ms = round((time.perf_counter() - t_motion_start) * 1000, 1)
                            motion_regions_in_perimeter = self._filter_motion_to_perimeter(
                                motion_result, frame_w, frame_h)
                            self.motion_detected = len(motion_regions_in_perimeter) > 0
                            
                            if self.motion_detected or self.inject_cat:
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
                            motion_result = self.motion_detector.detect(frame)
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
                                self.detector.unload_model()
                                cv2.setNumThreads(1)
                                reclaim_memory()
                                plog("[PHASE] ACQUISITION → IDLE (no motion for %ss)", self._acquisition_timeout)
                        
                        # ── PHASE: TRACKING ──
                        # Cat confirmed. TFLite every 3rd processed frame with motion crop.
                        elif self._phase == "TRACKING":
                            t_motion_start = time.perf_counter()
                            motion_result = self.motion_detector.detect(frame)
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
                                self.detector.unload_model()
                                cv2.setNumThreads(1)
                                reclaim_memory()
                                last_detections = []
                                self.last_detections_with_world = []
                                plog("[PHASE] TRACKING → IDLE (no detection for %ss)", self._detection_timeout)
                        
                        # ── PHASE: WATCH ──
                        # No motion but cat was recently detected. TFLite every 2nd frame.
                        elif self._phase == "WATCH":
                            t_motion_start = time.perf_counter()
                            motion_result = self.motion_detector.detect(frame)
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
                                self.detector.unload_model()
                                cv2.setNumThreads(1)
                                reclaim_memory()
                                last_detections = []
                                self.last_detections_with_world = []
                                plog("[PHASE] WATCH → IDLE (no detection for %ss)", self._detection_timeout)
                        
                        # ── AI DETECTION (shared by ACQUISITION, TRACKING, WATCH) ──
                        if run_ai_detection:
                            if crop_region:
                                cx, cy, cw, ch = crop_region
                                t0 = time.perf_counter()
                                cropped_frame = frame[cy:cy+ch, cx:cx+cw]
                                _perf_crop_ms = round((time.perf_counter() - t0) * 1000, 1)
                                t1 = time.perf_counter()
                                crop_detections = self.detector.detect(cropped_frame)
                                _perf_tflite_ms = round((time.perf_counter() - t1) * 1000, 1)
                                detections = []
                                for det in crop_detections:
                                    x1, y1, x2, y2, conf, class_id = det
                                    detections.append((x1 + cx, y1 + cy, x2 + cx, y2 + cy, conf, class_id))
                            else:
                                t1 = time.perf_counter()
                                detections = self.detector.detect(frame)
                                _perf_tflite_ms = round((time.perf_counter() - t1) * 1000, 1)
                            
                            # Grab TFLite sub-breakdown
                            _perf_tflite_detail = getattr(self.detector, '_last_perf', None)
                            
                            ai_time_ms = (_perf_crop_ms or 0) + (_perf_tflite_ms or 0)
                            
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
                            
                            # Resize FIRST, then draw on small frame
                            stream_w, stream_h = self.current_stream_resolution
                            capture_h, capture_w = frame.shape[:2]
                            t_rsz = time.perf_counter()
                            if stream_w != capture_w or stream_h != capture_h:
                                stream_frame = cv2.resize(frame, (stream_w, stream_h), interpolation=cv2.INTER_AREA)
                                sx = stream_w / capture_w
                                sy = stream_h / capture_h
                            else:
                                stream_frame = frame.copy()
                                sx = sy = 1.0
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
                            ret, jpeg_buf = cv2.imencode('.jpg', stream_frame,
                                                          [cv2.IMWRITE_JPEG_QUALITY, self.current_jpeg_quality])
                            with self._cached_jpeg_lock:
                                self._cached_jpeg = jpeg_buf.tobytes() if ret else None
                            _perf_jpeg_ms = round((time.perf_counter() - t_jpg) * 1000, 1)
                            _perf_annot_ms = round((time.perf_counter() - t_annot_start) * 1000, 1)
                        
                        # Store raw frame for snapshot and recording (no copy needed —
                        # frame is replaced by a new camera buffer on the next iteration)
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
                        cap = self._last_capture_ms if self._last_capture_ms is not None else 0
                        mot = self._last_motion_ms if self._last_motion_ms is not None else 0
                        getcrop_s = _perf_getcrop_ms if _perf_getcrop_ms is not None else "-"
                        crop_s = _perf_crop_ms if _perf_crop_ms is not None else "-"
                        # TFLite with sub-breakdown
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
                        plog("[PERF] cap=%.0fms mot=%.0fms gcrop=%s crop=%s tf=%s filt=%s world=%s trk=%s ann=%s ph=%s",
                             cap, mot, getcrop_s, crop_s, tflite_s, filt_s, world_s, track_s, annot_s, self._phase)
                    
                    # Rate-limit inject mode
                if self.inject_cat:
                    time.sleep(config.INJECT_MODE_SLEEP_SEC)
                else:
                    # Prevent tight loop when not in inject (avoids 100% CPU after stopping Inject Cat)
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
        ret, jpeg = cv2.imencode('.jpg', frame,
                                  [cv2.IMWRITE_JPEG_QUALITY, min(85, self.current_jpeg_quality + 15)])
        if ret:
            return jpeg.tobytes()
        return None
        
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
        print(f"[SETTING] Stream resolution changed to: {width}x{height}")
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
            self.motion_detector.update_parameters(
                detection_scale=profile["motion_scale"],
                motion_threshold=profile["motion_threshold"],
                min_area=profile["motion_min_area"])
        
        if self.detector and profile["tflite_threads"] != self.detector.num_threads:
            self.detector.num_threads = profile["tflite_threads"]
        
        self.current_motion_crop_size = profile["motion_crop_size"]
        self.current_profile = profile_name
        
        if save:
            settings.update_setting("performance_profile", profile_name)
        
        print(f"[PROFILE] Applied '{profile['name']}' profile")
        print(f"  - JPEG Quality: {profile['jpeg_quality']}%")
        print(f"  - AI Crop: {profile['motion_crop_size']}")
        print(f"  - Motion Scale: {profile['motion_scale']}")
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
