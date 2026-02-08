"""
Cat Dome - Flask Web Server with MJPEG Streaming
Provides web interface for detection and tracking
"""

import time
import threading
import os
import logging
from datetime import datetime
import cv2
from flask import Flask, Response, render_template, jsonify, request

import config

# Suppress Flask/Werkzeug access logs (the GET /api/status messages)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)  # Only show warnings and errors, not INFO


def get_system_info():
    """Get RAM usage, CPU usage, and CPU temperature for Raspberry Pi"""
    info = {
        "ram_used_mb": None,
        "ram_total_mb": None,
        "ram_percent": None,
        "cpu_percent": None,
        "cpu_temp": None
    }
    
    try:
        # Get memory info from /proc/meminfo
        with open('/proc/meminfo', 'r') as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    value = int(parts[1])  # Value in kB
                    meminfo[key] = value
            
            total_kb = meminfo.get('MemTotal', 0)
            available_kb = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
            used_kb = total_kb - available_kb
            
            info["ram_total_mb"] = round(total_kb / 1024)
            info["ram_used_mb"] = round(used_kb / 1024)
            if total_kb > 0:
                info["ram_percent"] = round((used_kb / total_kb) * 100, 1)
    except Exception:
        pass
    
    try:
        # Get CPU usage from /proc/stat (average across all cores)
        with open('/proc/stat', 'r') as f:
            line = f.readline()  # First line is total CPU
            if line.startswith('cpu '):
                parts = line.split()
                # user, nice, system, idle, iowait, irq, softirq
                if len(parts) >= 5:
                    idle = int(parts[4])
                    total = sum(int(x) for x in parts[1:8] if x.isdigit())
                    
                    # Store for delta calculation
                    if not hasattr(get_system_info, '_last_cpu'):
                        get_system_info._last_cpu = (idle, total)
                        info["cpu_percent"] = 0
                    else:
                        last_idle, last_total = get_system_info._last_cpu
                        idle_delta = idle - last_idle
                        total_delta = total - last_total
                        
                        if total_delta > 0:
                            cpu_used = 100.0 * (1.0 - idle_delta / total_delta)
                            info["cpu_percent"] = round(cpu_used, 1)
                        
                        get_system_info._last_cpu = (idle, total)
    except Exception:
        pass
    
    try:
        # Get CPU temperature from Raspberry Pi thermal zone
        temp_path = '/sys/class/thermal/thermal_zone0/temp'
        if os.path.exists(temp_path):
            with open(temp_path, 'r') as f:
                temp_millicelsius = int(f.read().strip())
                info["cpu_temp"] = round(temp_millicelsius / 1000, 1)
    except Exception:
        pass
    
    return info
from camera.camera_handler import CameraHandler, FileCameraHandler
from detection.detector import TFLiteDetector
from detection.tracker import CentroidTracker
from detection.perimeter import PerimeterManager
from detection.motion_detector import MotionDetector
import settings

# Try to import calibration, but it's optional
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


class VideoProcessor:
    """
    Processes video frames with detection and tracking.
    Generates annotated frames for streaming.
    """
    
    def __init__(self):
        self.camera = None
        self.detector = None
        self.tracker = None
        self.perimeter = None
        self.calibration = None
        self.lens_calibration = None
        self.motion_detector = None
        
        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self._fps_start = time.time()
        self._fps_count = 0
        
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.stream_clients = 0  # Number of active MJPEG stream connections
        
        # Load saved settings (or defaults)
        saved = settings.load_settings()
        
        # Performance settings (user-adjustable)
        # Force capture resolution to 2304x1296 (v1.8.0+)
        self.current_resolution = config.DEFAULT_RESOLUTION  # Always use 2304x1296
        if tuple(saved.get("resolution", config.DEFAULT_RESOLUTION)) != config.DEFAULT_RESOLUTION:
            print(f"[INFO] Upgrading capture resolution from {saved.get('resolution')} to {config.DEFAULT_RESOLUTION}")
            settings.update_setting("resolution", list(config.DEFAULT_RESOLUTION))
        
        self.current_stream_resolution = tuple(saved.get("stream_resolution", config.DEFAULT_STREAM_RESOLUTION))
        self.current_framerate = saved.get("framerate", config.DEFAULT_FRAMERATE)
        self.current_frame_skip = saved.get("frame_skip", config.DEFAULT_FRAME_SKIP)
        
        # Motion-first detection mode (saves memory, better for distance)
        self.motion_first_enabled = saved.get("motion_first_enabled", True)
        self.show_motion_regions = saved.get("show_motion_regions", False)
        
        # Performance profile (Phase 2)
        saved_profile = saved.get("performance_profile", config.DEFAULT_PERFORMANCE_PROFILE)
        # Handle legacy profiles (e.g., "default" from v1.7.0)
        if saved_profile not in config.PERFORMANCE_PROFILES:
            print(f"[WARNING] Saved profile '{saved_profile}' not found. Using '{config.DEFAULT_PERFORMANCE_PROFILE}'")
            saved_profile = config.DEFAULT_PERFORMANCE_PROFILE
        self.current_profile = saved_profile
        self.current_jpeg_quality = config.JPEG_QUALITY  # Will be updated by profile
        
        # Video source and recording
        self.video_library_path = saved.get("video_library_path", getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos'))
        self.record_after_detection_sec = saved.get("record_after_detection_sec", getattr(config, 'RECORD_AFTER_DETECTION_SEC', 5))
        self.recording_enabled = saved.get("recording_enabled", True)
        self.video_source = saved.get("video_source", "live")
        self.video_file_path = saved.get("video_file_path")  # None or path
        self.file_camera = None  # FileCameraHandler, created when source is file
        # Recording state
        self._recording_writer = None
        self._recording_start_time = None
        self._recording_last_detection_time = None
        self._recording_filename = None
        
        # Detection mode and threshold will be set on detector after it's created
        self._saved_detection_mode = saved.get("detection_mode", config.DEFAULT_DETECTION_MODE)
        self._saved_threshold = saved.get("detection_threshold", config.DETECTION_THRESHOLD)
        
        # Motion detection stats
        self.motion_detected = False
        self.ai_detections_count = 0
        self._last_motion_time = 0  # Time of last motion detection
        self._tflite_idle_timeout = 10  # Seconds of no motion before unloading TFLite
        
        # Temporal confirmation - require detection in N consecutive frames
        self.confirm_frames = saved.get("confirm_frames", getattr(config, 'DETECTION_CONFIRM_FRAMES', 1))
        self.detection_history = []  # List of recent detection counts
        
        # Store last detections with world coordinates for API
        self.last_detections_with_world = []
        
        print(f"Loaded settings: Capture={self.current_resolution[0]}x{self.current_resolution[1]}, Stream={self.current_stream_resolution[0]}x{self.current_stream_resolution[1]}, motion-first={self.motion_first_enabled}, profile={self.current_profile}")
        
    def start(self):
        """Initialize and start all components"""
        print("Initializing video processor...")
        
        # Initialize components with saved resolution
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
        
        # Calibration is optional
        if CALIBRATION_AVAILABLE:
            self.calibration = CameraCalibration()
        else:
            self.calibration = None
        
        # Lens distortion calibration (optional)
        if LENS_CALIBRATION_AVAILABLE:
            self.lens_calibration = LensCalibration()
        else:
            self.lens_calibration = None
        
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
        
        # Start camera (or file source)
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
        
    def _process_loop(self):
        """Main processing loop with motion-first detection"""
        # Set OS thread name so it shows in top/htop
        try:
            import ctypes
            libc = ctypes.CDLL('libc.so.6')
            libc.prctl(15, b'CatDome-Proc', 0, 0, 0)
        except Exception:
            pass
        # Start with single-threaded OpenCV to avoid spin-wait threads when idle
        cv2.setNumThreads(1)
        skip_counter = 0
        last_detections = []
        
        while self.running:
            try:
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
                            # picamera2 "RGB888" format actually stores BGR bytes in memory
                            # (reversed naming convention), which is exactly what OpenCV needs
                            frame = req.make_array("main")
                
                frame_h, frame_w = frame.shape[:2]
                run_ai_detection = False
                crop_region = None
                motion_regions_in_perimeter = []
                
                # Run detection periodically (skip frames for performance)
                skip_counter += 1
                if skip_counter >= self.current_frame_skip:
                    skip_counter = 0
                    
                    # Update FPS only when we actually process a frame (not every loop iteration)
                    self._update_fps()
                    self.frame_count += 1
                    
                    if self.motion_first_enabled:
                        # Motion-first mode: only run AI when motion detected
                        motion_start = time.time()
                        motion_result = self.motion_detector.detect(frame)
                        motion_time_ms = (time.time() - motion_start) * 1000
                        
                        # Debug: log raw motion detection (only if config.DEBUG enabled)
                        if motion_result["motion_detected"] and config.DEBUG:
                            print(f"[DEBUG] Motion detected: {len(motion_result['regions'])} regions (took {motion_time_ms:.1f}ms)")
                        
                        # Filter motion regions to only those inside perimeter
                        motion_regions_in_perimeter = []
                        if motion_result["motion_detected"] and motion_result["regions"]:
                            frame_res = (frame_w, frame_h)
                            perimeter_points = len(self.perimeter.get_points()) if self.perimeter else 0
                            
                            for region in motion_result["regions"]:
                                rx, ry, rw, rh = region
                                # Check if center of motion region is inside perimeter
                                center_x = rx + rw // 2
                                center_y = ry + rh // 2
                                inside = self.perimeter.is_inside((center_x, center_y), frame_res)
                                if inside:
                                    motion_regions_in_perimeter.append(region)
                            
                            # Only log if config.DEBUG or if motion inside perimeter (interesting event)
                            if config.DEBUG or len(motion_regions_in_perimeter) > 0:
                                print(f"[DEBUG] Perimeter has {perimeter_points} points, {len(motion_regions_in_perimeter)}/{len(motion_result['regions'])} regions inside")
                            self.motion_detected = len(motion_regions_in_perimeter) > 0
                        else:
                            self.motion_detected = False
                        
                        if self.motion_detected:
                            self._last_motion_time = time.time()
                            # Enable multi-threaded OpenCV for faster processing during tracking
                            cv2.setNumThreads(4)
                            # Get fixed 300x300 crop centered on motion (no scaling!)
                            # This preserves object pixel size for better detection
                            crop_size = getattr(config, 'MOTION_CROP_SIZE', (300, 300))
                            crop_region = self.motion_detector.get_fixed_crop_region(
                                frame.shape, 
                                crop_size=crop_size
                            )
                            run_ai_detection = True
                        elif (self.detector.is_loaded() and 
                              time.time() - self._last_motion_time > self._tflite_idle_timeout):
                            # No motion for N seconds — unload TFLite and reduce OpenCV threads
                            self.detector.unload_model()
                            cv2.setNumThreads(1)  # Back to single-thread to stop spin-wait
                    else:
                        # Always-on mode: run AI on every frame
                        run_ai_detection = True
                        self.motion_detected = True
                    
                    if run_ai_detection:
                        ai_start = time.time()
                        if crop_region and self.motion_first_enabled:
                            # Crop frame to motion region for AI detection
                            cx, cy, cw, ch = crop_region
                            cropped_frame = frame[cy:cy+ch, cx:cx+cw]
                            
                            # Run detection on cropped frame
                            crop_detections = self.detector.detect(cropped_frame)
                            
                            # Scale detection coordinates back to original frame
                            detections = []
                            for det in crop_detections:
                                x1, y1, x2, y2, conf, class_id = det
                                # Offset by crop position
                                x1 += cx
                                y1 += cy
                                x2 += cx
                                y2 += cy
                                detections.append((x1, y1, x2, y2, conf, class_id))
                        else:
                            # Run detection on full frame
                            detections = self.detector.detect(frame)
                        
                        ai_time_ms = (time.time() - ai_start) * 1000
                        
                        # Filter by perimeter (pass frame resolution for scaling)
                        frame_res = (frame_w, frame_h)
                        raw_count = len(detections)
                        detections = self.perimeter.filter_detections(detections, frame_resolution=frame_res)
                        self.ai_detections_count += 1
                        
                        # Temporal confirmation - require detection in N consecutive frames
                        self.detection_history.append(len(detections) > 0)
                        if len(self.detection_history) > self.confirm_frames:
                            self.detection_history.pop(0)
                        
                        # Only confirm detections if detected in enough consecutive frames
                        if self.confirm_frames > 1:
                            confirmed = len(self.detection_history) >= self.confirm_frames and all(self.detection_history)
                            if not confirmed:
                                detections = []  # Not confirmed yet
                        
                        last_detections = detections
                        
                        # Debug: log detections with timing
                        if config.DEBUG or raw_count > 0:
                            confirmed_str = f", Confirmed: {len(detections) > 0}" if self.confirm_frames > 1 else ""
                            print(f"[PERF] AI inference: {ai_time_ms:.1f}ms | Raw detections: {raw_count}, After perimeter: {len(detections)}{confirmed_str}")
                        
                        # Compute world coordinates for each detection
                        self.last_detections_with_world = []
                        for det in detections:
                            x1, y1, x2, y2, conf, class_id = det
                            world_pos = None
                            if self.calibration and hasattr(self.calibration, 'is_calibrated') and self.calibration.is_calibrated:
                                world_pos = self.calibration.bbox_to_world(x1, y1, x2, y2)
                            self.last_detections_with_world.append({
                                "bbox": [x1, y1, x2, y2],
                                "confidence": round(conf, 2),
                                "class_id": class_id,
                                "world_position": world_pos
                            })
                    elif not self.motion_detected:
                        # No motion - clear detections after a while
                        if len(last_detections) > 0:
                            # Keep last detections for a few frames
                            pass
                    
                # Update tracker only when there are detections
                tracked_objects = self.tracker.update(last_detections) if last_detections else {}
                
                # Only annotate and store frame if someone is watching the stream
                if self.stream_clients > 0:
                    annotated = frame
                    
                    # Draw motion regions if enabled
                    if self.show_motion_regions and self.motion_first_enabled:
                        self.motion_detector.draw_motion(annotated, regions=motion_regions_in_perimeter)
                    
                    # Draw crop region if used
                    if crop_region and self.show_motion_regions:
                        cx, cy, cw, ch = crop_region
                        cv2.rectangle(annotated, (cx, cy), (cx+cw, cy+ch), (255, 0, 255), 2)
                    
                    # Draw perimeter
                    annotated = self.perimeter.draw(annotated)
                    
                    # Draw detections and tracking
                    annotated = self.detector.draw_detections(
                        annotated, 
                        last_detections,
                        tracked_objects
                    )
                    
                    # Draw FPS and status
                    self._draw_status(annotated)
                    
                    # Store for MJPEG streaming
                    with self.frame_lock:
                        self.current_frame = annotated
                else:
                    # No stream clients — store raw frame (for snapshots) without annotation
                    with self.frame_lock:
                        self.current_frame = frame
                
                # Recording on detection (live only, when enabled)
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
                
            except Exception as e:
                print(f"Processing error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
                
    def _draw_status(self, frame):
        """Draw status information on frame"""
        # Main status line
        mode_text = self.detector.get_detection_mode().upper()
        status_text = f"Mode: {mode_text} | FPS: {self.fps:.1f}"
        
        # Draw background
        (text_w, text_h), _ = cv2.getTextSize(
            status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
        )
        cv2.rectangle(
            frame,
            (5, 5),
            (max(text_w + 15, 250), text_h + 55),
            (0, 0, 0),
            -1
        )
        
        # Draw main status text
        cv2.putText(
            frame,
            status_text,
            (10, text_h + 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2
        )
        
        # Draw object count
        count_text = f"Objects: {self.tracker.get_object_count()}"
        cv2.putText(
            frame,
            count_text,
            (10, text_h + 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            1
        )
        
        # Draw motion status if motion-first mode
        if self.motion_first_enabled:
            motion_status = "MOTION" if self.motion_detected else "IDLE"
            motion_color = (0, 255, 255) if self.motion_detected else (128, 128, 128)
            cv2.putText(
                frame,
                f"Motion: {motion_status}",
                (10, text_h + 52),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                motion_color,
                1
            )
        
        # Draw timestamp in top-right corner (dd/mm/yyyy HH:MM:SS)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        (ts_w, ts_h), _ = cv2.getTextSize(timestamp, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ts_x = frame.shape[1] - ts_w - 10
        ts_y = ts_h + 10
        
        # Background for timestamp
        cv2.rectangle(frame, (ts_x - 5, 5), (frame.shape[1] - 5, ts_y + 5), (0, 0, 0), -1)
        cv2.putText(frame, timestamp, (ts_x, ts_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
    def _update_fps(self):
        """Update FPS calculation"""
        self._fps_count += 1
        elapsed = time.time() - self._fps_start
        
        if elapsed >= 1.0:
            self.fps = self._fps_count / elapsed
            self._fps_count = 0
            self._fps_start = time.time()
    
    def _start_recording(self):
        """Start writing a new clip (same resolution/FPS as live for later use as input)."""
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
            print(f"[REC] Started: {self._recording_filename}")
        except Exception as e:
            print(f"[REC] Start failed: {e}")
            self._recording_writer = None
    
    def _stop_recording(self):
        """Stop current clip and release writer."""
        if self._recording_writer is None:
            return
        try:
            self._recording_writer.release()
            print(f"[REC] Stopped: {self._recording_filename}")
        except Exception:
            pass
        self._recording_writer = None
        self._recording_filename = None
        self._recording_start_time = None
        self._recording_last_detection_time = None
            
    def get_frame_jpeg(self):
        """Get current frame as JPEG bytes"""
        # OPTIMIZATION A: Only copy when encoding (required by imencode)
        with self.frame_lock:
            if self.current_frame is None:
                return None
            # imencode doesn't modify the frame, but we copy for thread safety
            frame = self.current_frame.copy()
        
        # OPTIMIZATION B: Use profile-specific JPEG quality
        jpeg_quality = self.current_jpeg_quality
        
        # Scale down to stream resolution before encoding (saves bandwidth)
        stream_w, stream_h = self.current_stream_resolution
        capture_h, capture_w = frame.shape[:2]
        
        # Only scale if stream resolution is different from capture
        if stream_w != capture_w or stream_h != capture_h:
            frame = cv2.resize(frame, (stream_w, stream_h), interpolation=cv2.INTER_AREA)
        
        # Encode as JPEG with timing
        if config.DEBUG:
            encode_start = time.time()
            ret, jpeg = cv2.imencode(
                '.jpg', 
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            )
            encode_time_ms = (time.time() - encode_start) * 1000
            
            # Log encoding time periodically (every 50 frames)
            if not hasattr(self, '_encode_log_counter'):
                self._encode_log_counter = 0
            self._encode_log_counter += 1
            if self._encode_log_counter >= 50:
                print(f"[PERF] JPEG encoding: {encode_time_ms:.1f}ms @ Q{jpeg_quality} ({stream_w}x{stream_h})")
                self._encode_log_counter = 0
        else:
            ret, jpeg = cv2.imencode(
                '.jpg', 
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            )
        
        if ret:
            return jpeg.tobytes()
        return None
    
    def get_frame_jpeg_capture_resolution(self, undistort=False):
        """Get current frame as JPEG at capture resolution (no scaling).
        If undistort=True and lens calibration is available, applies lens correction first."""
        with self.frame_lock:
            if self.current_frame is None:
                return None
            frame = self.current_frame.copy()
        if undistort and self.lens_calibration and self.lens_calibration.is_calibrated:
            frame = self.lens_calibration.undistort_frame(frame)
        ret, jpeg = cv2.imencode(
            '.jpg',
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, min(85, self.current_jpeg_quality + 15)]
        )
        if ret:
            return jpeg.tobytes()
        return None
        
    def set_detection_mode(self, mode):
        """Set detection mode (cat or ball)"""
        if self.detector:
            self.detector.set_detection_mode(mode)
            self.tracker.reset()  # Reset tracking when mode changes
            settings.update_setting("detection_mode", mode)
            print(f"[SETTING] Detection mode changed to: {mode}")
            
    def get_detection_mode(self):
        """Get current detection mode"""
        if self.detector:
            return self.detector.get_detection_mode()
        return config.DEFAULT_DETECTION_MODE
    
    def set_detection_threshold(self, threshold):
        """Set detection confidence threshold"""
        if self.detector:
            self.detector.set_threshold(threshold)
            settings.update_setting("detection_threshold", threshold)
            print(f"[SETTING] Detection threshold changed to: {threshold:.0%}")
    
    def get_detection_threshold(self):
        """Get current detection threshold"""
        if self.detector:
            return self.detector.get_threshold()
        return config.DETECTION_THRESHOLD
    
    def set_confirm_frames(self, frames):
        """Set temporal confirmation frames (1 = instant, 2-5 = require N consecutive detections)"""
        self.confirm_frames = max(1, min(5, int(frames)))
        self.detection_history = []  # Reset history when changing
        settings.update_setting("confirm_frames", self.confirm_frames)
        print(f"[SETTING] Confirmation frames changed to: {self.confirm_frames}")
        
    def set_perimeter(self, points):
        """Set perimeter points"""
        if self.perimeter:
            return self.perimeter.set_points(points)
        return False
        
    def get_perimeter(self):
        """Get perimeter points"""
        if self.perimeter:
            return self.perimeter.get_points()
        return []
        
    def clear_perimeter(self):
        """Reset perimeter to default"""
        if self.perimeter:
            self.perimeter.clear()
            print("[SETTING] Perimeter cleared")
            
    def get_status(self):
        """Get current system status"""
        import main as main_module
        system_info = get_system_info()
        
        is_calibrated = False
        if self.calibration and hasattr(self.calibration, 'is_calibrated'):
            is_calibrated = self.calibration.is_calibrated
        
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
            # Motion detection status
            "motion_first_enabled": self.motion_first_enabled,
            "motion_detected": self.motion_detected,
            "show_motion_regions": self.show_motion_regions,
            "ai_detections_count": self.ai_detections_count,
            # Performance profile
            "performance_profile": self.current_profile
        }
    
    # =========================================================================
    # Calibration Methods
    # =========================================================================
    
    def get_calibration(self):
        """Get current calibration status and points"""
        if self.calibration:
            return self.calibration.to_json()
        return {"is_calibrated": False, "points": [], "world_bounds": config.DEFAULT_WORLD_BOUNDS, "rectangles": []}
    
    def _undistort_pixels(self, points_pixel):
        """Undistort pixel coordinates if lens calibration is available.
        This ensures the homography is computed in undistorted pixel space."""
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
            # Undistort pixel coordinates so homography is in undistorted space
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
        """Clear calibration"""
        if self.calibration:
            self.calibration.clear()
    
    def pixel_to_world(self, pixel_x, pixel_y, already_undistorted=False):
        """Convert pixel coordinates to world coordinates.
        If already_undistorted=False (default), applies lens undistortion first.
        Set already_undistorted=True for pixels from lens-corrected snapshots
        (calibration rectangles, detection zone perimeter)."""
        if self.calibration and self.calibration.is_calibrated:
            ux, uy = pixel_x, pixel_y
            if not already_undistorted and self.lens_calibration and self.lens_calibration.is_calibrated:
                ux, uy = self.lens_calibration.undistort_point(pixel_x, pixel_y)
            return self.calibration.pixel_to_world(ux, uy)
        return None
    
    def get_topdown_data(self):
        """
        Get top-down (bird's eye) view data for the UI.
        Transforms perimeter and tracked objects to world coordinates.
        """
        is_calibrated = self.calibration and self.calibration.is_calibrated
        
        result = {
            "is_calibrated": is_calibrated,
            "world_bounds": self.calibration.get_world_bounds() if is_calibrated else None,
            "perimeter_world": [],
            "objects": []
        }
        
        if not is_calibrated:
            return result
        
        # Transform perimeter points to world coordinates via the homography.
        # The homography is accurate because calibration world coords are now a proper
        # axis-aligned rectangle (not distorted by pixel directions).
        perimeter_points = self.get_perimeter()
        if perimeter_points:
            frame_res = None
            if self.camera and self.camera.running:
                frame_res = self.camera.get_resolution()
            
            # Debug: log resolution info on first call
            if not hasattr(self, '_topdown_debug_done'):
                saved_res = self.perimeter.saved_resolution if hasattr(self.perimeter, 'saved_resolution') else 'N/A'
                print(f"[TOPDOWN DEBUG] frame_res={frame_res}, perimeter saved_res={saved_res}, "
                      f"perimeter points={len(perimeter_points)}, "
                      f"lens_cal={'ON' if self.lens_calibration and self.lens_calibration.is_calibrated else 'OFF'}")
                print(f"[TOPDOWN DEBUG] calibration points={len(self.calibration.calibration_points)}, "
                      f"rectangles={len(self.calibration.rectangles)}")
                # Log first few calibration points
                for i, cp in enumerate(self.calibration.calibration_points[:4]):
                    print(f"[TOPDOWN DEBUG]   cal point {i}: pixel={cp['pixel']}, world={cp['world']}")
                self._topdown_debug_done = True
            
            for idx, point in enumerate(perimeter_points):
                px, py = float(point[0]), float(point[1])
                # Perimeter pixels are in raw camera space (redistorted at save time).
                # pixel_to_world undistorts them to match the calibration space.
                world_pos = self.pixel_to_world(px, py, already_undistorted=False)
                if world_pos:
                    result["perimeter_world"].append({
                        "x": round(world_pos[0], 2),
                        "y": round(world_pos[1], 2)
                    })
        
        # Get tracked objects with world coordinates
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
    
    def get_performance_settings(self):
        """Get current performance settings and available options"""
        return {
            "current": {
                "resolution": list(self.current_resolution),
                "stream_resolution": list(self.current_stream_resolution),
                "framerate": self.current_framerate,
                "frame_skip": self.current_frame_skip
            },
            "options": {
                "resolutions": [list(config.CAPTURE_RESOLUTION)],  # Fixed capture resolution
                "stream_resolutions": [list(r) for r in config.STREAM_RESOLUTION_OPTIONS],
                "framerates": config.FRAMERATE_OPTIONS,
                "frame_skips": config.FRAME_SKIP_OPTIONS
            }
        }
    
    def set_resolution(self, width, height):
        """Set camera resolution (now fixed at 2304x1296 for optimal 13m detection)"""
        # Capture resolution is fixed - use set_stream_resolution() instead
        print(f"[WARNING] Capture resolution is fixed at 2304x1296")
        return False
    
    def set_stream_resolution(self, width, height):
        """Set streaming resolution (no camera restart needed)"""
        new_res = (width, height)
        if new_res not in config.STREAM_RESOLUTION_OPTIONS:
            return False
        
        self.current_stream_resolution = new_res
        settings.update_setting("stream_resolution", list(new_res))
        print(f"[SETTING] Stream resolution changed to: {width}x{height}")
        
        return True
    
    def set_framerate(self, fps):
        """Set camera framerate (requires camera restart)"""
        if fps not in config.FRAMERATE_OPTIONS:
            return False
        
        self.current_framerate = fps
        settings.update_setting("framerate", fps)
        
        # Restart camera with new settings
        if self.camera:
            self.camera.stop()
            width, height = self.current_resolution
            self.camera = CameraHandler(width=width, height=height, fps=fps)
            self.camera.start()
        
        print(f"[SETTING] Framerate changed to: {fps} fps")
        return True
    
    def set_frame_skip(self, skip):
        """Set detection frame skip (no restart needed)"""
        if skip not in config.FRAME_SKIP_OPTIONS:
            print(f"[SETTING] Invalid frame skip: {skip}, must be one of {config.FRAME_SKIP_OPTIONS}")
            return False
        
        self.current_frame_skip = skip
        settings.update_setting("frame_skip", skip)
        return True
    
    # =========================================================================
    # Performance Profile Management (Phase 2)
    # =========================================================================
    
    def get_performance_profiles(self):
        """Get all available performance profiles with metadata"""
        return {
            "profiles": config.PERFORMANCE_PROFILES,
            "current": self.current_profile
        }
    
    def get_current_profile(self):
        """Get current active performance profile"""
        return {
            "profile": self.current_profile,
            "settings": config.PERFORMANCE_PROFILES.get(self.current_profile, {})
        }
    
    def set_performance_profile(self, profile_name):
        """
        Switch to a different performance profile.
        Applies all settings from the profile immediately.
        
        Args:
            profile_name: One of "default", "balanced", "performance", "quality"
            
        Returns:
            bool: True if successful, False if invalid profile
        """
        if profile_name not in config.PERFORMANCE_PROFILES:
            print(f"[ERROR] Invalid profile: {profile_name}")
            return False
        
        return self._apply_performance_profile(profile_name, save=True)
    
    def _apply_performance_profile(self, profile_name, save=True):
        """Internal method to apply profile settings"""
        # Handle legacy/invalid profile names (e.g., "default" from v1.7.0)
        if profile_name not in config.PERFORMANCE_PROFILES:
            print(f"[WARNING] Profile '{profile_name}' not found. Using default: '{config.DEFAULT_PERFORMANCE_PROFILE}'")
            profile_name = config.DEFAULT_PERFORMANCE_PROFILE
            # Update saved settings to valid profile
            if save:
                settings.update_setting("performance_profile", profile_name)
        
        profile = config.PERFORMANCE_PROFILES[profile_name]
        
        # Update JPEG quality
        self.current_jpeg_quality = profile["jpeg_quality"]
        
        # Update motion detection settings (safely handles history reset)
        if self.motion_detector:
            self.motion_detector.update_parameters(
                detection_scale=profile["motion_scale"],
                motion_threshold=profile["motion_threshold"],
                min_area=profile["motion_min_area"]
            )
        
        # Update TFLite thread count (requires model reload if changed)
        if self.detector and profile["tflite_threads"] != self.detector.num_threads:
            self.detector.num_threads = profile["tflite_threads"]
            # Note: Thread count change requires interpreter recreation
            # This happens automatically on next model load
        
        # Update crop size (used in motion-first detection)
        config.MOTION_CROP_SIZE = profile["motion_crop_size"]
        
        # Update current profile
        self.current_profile = profile_name
        
        # Save to persistent settings
        if save:
            settings.update_setting("performance_profile", profile_name)
        
        print(f"[PROFILE] Applied '{profile['name']}' profile")
        print(f"  - JPEG Quality: {profile['jpeg_quality']}%")
        print(f"  - AI Crop: {profile['motion_crop_size']}")
        print(f"  - Motion Scale: {profile['motion_scale']}")
        print(f"  - TFLite Threads: {profile['tflite_threads']}")
        
        return True


# Global video processor instance
video_processor = VideoProcessor()


def create_app():
    """Create and configure Flask application"""
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )
    
    @app.route('/')
    def index():
        """Serve main page"""
        return render_template('index.html')
        
    @app.route('/api/snapshot')
    def snapshot_capture_resolution():
        """Single snapshot at capture resolution. If undistort=1 and lens cal available, applies correction."""
        undistort = request.args.get('undistort', '0') == '1'
        jpeg = video_processor.get_frame_jpeg_capture_resolution(undistort=undistort)
        if jpeg:
            return Response(jpeg, mimetype='image/jpeg')
        return Response(status=503)
    
    @app.route('/video_feed')
    def video_feed():
        """MJPEG video stream endpoint"""
        # Check if requesting a single snapshot (stream resolution)
        if request.args.get('snapshot'):
            jpeg = video_processor.get_frame_jpeg()
            if jpeg:
                return Response(jpeg, mimetype='image/jpeg')
            return Response(status=503)
        
        # Otherwise stream continuously (rate-limited to save CPU)
        def generate():
            video_processor.stream_clients += 1
            print(f"[STREAM] Client connected ({video_processor.stream_clients} active)")
            try:
                while True:
                    jpeg = video_processor.get_frame_jpeg()
                    if jpeg is not None:
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                        )
                    # Limit stream to ~10 FPS max — saves CPU on JPEG encoding
                    time.sleep(0.1)
            finally:
                video_processor.stream_clients = max(0, video_processor.stream_clients - 1)
                print(f"[STREAM] Client disconnected ({video_processor.stream_clients} active)")
                    
        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
        
    @app.route('/api/status')
    def get_status():
        """Get current system status"""
        return jsonify(video_processor.get_status())
        
    @app.route('/api/mode', methods=['GET'])
    def get_mode():
        """Get current detection mode"""
        return jsonify({"mode": video_processor.get_detection_mode()})
        
    @app.route('/api/mode', methods=['POST'])
    def set_mode():
        """Set detection mode"""
        data = request.get_json()
        mode = data.get('mode', 'cat')
        
        if mode not in ['cat', 'ball']:
            return jsonify({"error": "Invalid mode. Use 'cat' or 'ball'"}), 400
            
        video_processor.set_detection_mode(mode)
        return jsonify({"mode": mode, "success": True})
        
    @app.route('/api/perimeter', methods=['GET'])
    def get_perimeter():
        """Get current perimeter points with resolution info"""
        return jsonify({
            "points": video_processor.get_perimeter(),
            "resolution": list(video_processor.current_resolution)
        })
        
    @app.route('/api/perimeter', methods=['POST'])
    def set_perimeter():
        """Set perimeter points.
        Points are clicked on the undistorted+cropped snapshot.
        They are converted to raw camera pixel space for:
        - Streaming overlay (draw_perimeter on raw frame)
        - Detection filtering (is_inside check on raw detection pixels)
        The top-down view re-undistorts them via pixel_to_world."""
        data = request.get_json()
        points = data.get('points', [])
        
        if len(points) < 3:
            return jsonify({"error": "Need at least 3 points"}), 400
        
        # Convert from undistorted+cropped space to raw camera space
        raw_points = video_processor._redistort_pixels(points)
        
        cam_width, cam_height = video_processor.current_resolution
        if video_processor.perimeter:
            video_processor.perimeter.set_saved_resolution(cam_width, cam_height)
        success = video_processor.set_perimeter(raw_points)
        
        if success:
            print(f"[SETTING] Perimeter: {len(raw_points)} points redistorted to raw {cam_width}x{cam_height}")
            print(f"  Undistorted first: {points[0]}, Raw: {raw_points[0]}")
        
        return jsonify({
            "success": success, 
            "points": video_processor.get_perimeter(),
            "camera_resolution": [cam_width, cam_height]
        })
        
    @app.route('/api/perimeter', methods=['DELETE'])
    def clear_perimeter():
        """Reset perimeter to default"""
        video_processor.clear_perimeter()
        return jsonify({"success": True, "points": video_processor.get_perimeter()})
    
    @app.route('/api/performance', methods=['GET'])
    def get_performance():
        """Get current performance settings and available options"""
        return jsonify(video_processor.get_performance_settings())
    
    @app.route('/api/performance/resolution', methods=['POST'])
    def set_resolution():
        """Set camera resolution (capture resolution - fixed at 2304x1296)"""
        # Note: Capture resolution is now fixed at 2304x1296 for optimal 13m detection
        return jsonify({"error": "Capture resolution is fixed at 2304x1296"}), 400
    
    @app.route('/api/performance/stream_resolution', methods=['POST'])
    def set_stream_resolution():
        """Set streaming resolution (for web viewing)"""
        data = request.get_json()
        width = data.get('width')
        height = data.get('height')
        
        if not width or not height:
            return jsonify({"error": "Width and height required"}), 400
        
        success = video_processor.set_stream_resolution(int(width), int(height))
        if success:
            return jsonify({"success": True, "stream_resolution": [width, height]})
        return jsonify({"error": "Invalid stream resolution"}), 400
    
    @app.route('/api/performance/framerate', methods=['POST'])
    def set_framerate():
        """Set camera framerate"""
        data = request.get_json()
        fps = data.get('fps')
        
        if fps is None:
            return jsonify({"error": "FPS value required"}), 400
        
        success = video_processor.set_framerate(int(fps))
        if success:
            return jsonify({"success": True, "framerate": fps})
        return jsonify({"error": "Invalid framerate"}), 400
    
    @app.route('/api/performance/frameskip', methods=['POST'])
    def set_frameskip():
        """Set detection frame skip"""
        data = request.get_json()
        skip = data.get('skip')
        
        if skip is None:
            return jsonify({"error": "Skip value required"}), 400
        
        success = video_processor.set_frame_skip(int(skip))
        if success:
            return jsonify({"success": True, "frame_skip": skip})
        return jsonify({"error": "Invalid frame skip value"}), 400
    
    @app.route('/api/performance/threshold', methods=['GET'])
    def get_threshold():
        """Get current detection threshold"""
        return jsonify({
            "threshold": video_processor.get_detection_threshold()
        })
    
    @app.route('/api/performance/threshold', methods=['POST'])
    def set_threshold():
        """Set detection confidence threshold"""
        data = request.get_json()
        threshold = data.get('threshold')
        
        if threshold is None:
            return jsonify({"error": "Threshold value required"}), 400
        
        threshold = float(threshold)
        if threshold < 0.1 or threshold > 0.9:
            return jsonify({"error": "Threshold must be between 0.1 and 0.9"}), 400
        
        video_processor.set_detection_threshold(threshold)
        return jsonify({"success": True, "threshold": threshold})
    
    @app.route('/api/performance/confirm_frames', methods=['GET'])
    def get_confirm_frames():
        """Get current confirmation frames setting"""
        return jsonify({"confirm_frames": video_processor.confirm_frames})
    
    @app.route('/api/performance/confirm_frames', methods=['POST'])
    def set_confirm_frames():
        """Set detection confirmation frames (temporal confirmation)"""
        data = request.get_json()
        frames = data.get('frames')
        
        if frames is None:
            return jsonify({"error": "Frames value required"}), 400
        
        frames = int(frames)
        if frames < 1 or frames > 5:
            return jsonify({"error": "Frames must be between 1 and 5"}), 400
        
        video_processor.set_confirm_frames(frames)
        return jsonify({"success": True, "confirm_frames": frames})
    
    # =========================================================================
    # Video Source & Recording API
    # =========================================================================
    
    @app.route('/api/video/source', methods=['GET'])
    def get_video_source():
        """Get current video source and file path"""
        return jsonify({
            "video_source": video_processor.video_source,
            "video_file_path": video_processor.video_file_path,
            "video_library_path": video_processor.video_library_path,
            "recording_enabled": video_processor.recording_enabled,
            "record_after_detection_sec": video_processor.record_after_detection_sec,
        })
    
    @app.route('/api/video/source', methods=['POST'])
    def set_video_source():
        """Set video source: live or file. For file, provide video_file_path."""
        data = request.get_json() or {}
        source = data.get("video_source", "live")
        path = data.get("video_file_path")
        if source not in ("live", "file"):
            return jsonify({"error": "video_source must be 'live' or 'file'"}), 400
        if source == "file" and (not path or not os.path.isfile(path)):
            return jsonify({"error": "Valid video_file_path required for file source"}), 400
        video_processor.video_source = source
        video_processor.video_file_path = path if source == "file" else None
        settings.update_setting("video_source", video_processor.video_source)
        settings.update_setting("video_file_path", video_processor.video_file_path)
        if source == "file" and path:
            if video_processor.file_camera:
                video_processor.file_camera.stop()
            video_processor.file_camera = FileCameraHandler()
            try:
                video_processor.file_camera.start(path)
            except Exception as e:
                video_processor.file_camera = None
                video_processor.video_source = "live"
                return jsonify({"error": str(e)}), 400
        else:
            if video_processor.file_camera:
                video_processor.file_camera.stop()
                video_processor.file_camera = None
        return jsonify({"success": True, "video_source": video_processor.video_source, "video_file_path": video_processor.video_file_path})
    
    @app.route('/api/video/library', methods=['GET'])
    def get_video_library():
        """List video files in library dir (or optional path query param)."""
        path = request.args.get("path") or video_processor.video_library_path or getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos')
        if not os.path.isdir(path):
            return jsonify({"path": path, "files": [], "error": "Directory not found"})
        try:
            names = sorted([f for f in os.listdir(path) if f.lower().endswith(('.mp4', '.avi', '.mkv', '.mov'))])
            files = [{"name": n, "path": os.path.join(path, n)} for n in names]
            return jsonify({"path": path, "files": files})
        except Exception as e:
            return jsonify({"path": path, "files": [], "error": str(e)})
    
    @app.route('/api/video/recording', methods=['GET'])
    def get_recording_settings():
        return jsonify({
            "recording_enabled": video_processor.recording_enabled,
            "record_after_detection_sec": video_processor.record_after_detection_sec,
            "video_library_path": video_processor.video_library_path,
        })
    
    @app.route('/api/video/recording', methods=['POST'])
    def set_recording_settings():
        data = request.get_json() or {}
        if "recording_enabled" in data:
            video_processor.recording_enabled = bool(data["recording_enabled"])
            settings.update_setting("recording_enabled", video_processor.recording_enabled)
        if "record_after_detection_sec" in data:
            sec = int(data["record_after_detection_sec"])
            if 1 <= sec <= 60:
                video_processor.record_after_detection_sec = sec
                settings.update_setting("record_after_detection_sec", sec)
        if "video_library_path" in data:
            p = (data.get("video_library_path") or "").strip()
            video_processor.video_library_path = p or getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos')
            os.makedirs(video_processor.video_library_path, exist_ok=True)
            settings.update_setting("video_library_path", video_processor.video_library_path)
        return jsonify({"success": True, "recording_enabled": video_processor.recording_enabled, "record_after_detection_sec": video_processor.record_after_detection_sec, "video_library_path": video_processor.video_library_path})
    
    # =========================================================================
    # Motion Detection API Endpoints
    # =========================================================================
    
    @app.route('/api/motion', methods=['GET'])
    def get_motion_settings():
        """Get motion detection settings"""
        return jsonify({
            "motion_first_enabled": video_processor.motion_first_enabled,
            "show_motion_regions": video_processor.show_motion_regions,
            "motion_detected": video_processor.motion_detected,
            "ai_detections_count": video_processor.ai_detections_count
        })
    
    @app.route('/api/motion/toggle', methods=['POST'])
    def toggle_motion_first():
        """Toggle motion-first detection mode"""
        data = request.get_json() or {}
        enabled = data.get('enabled')
        
        if enabled is None:
            # Toggle if no value provided
            video_processor.motion_first_enabled = not video_processor.motion_first_enabled
        else:
            video_processor.motion_first_enabled = bool(enabled)
        
        # Save setting
        settings.update_setting("motion_first_enabled", video_processor.motion_first_enabled)
        
        # Reset motion detector when toggling
        if video_processor.motion_detector:
            video_processor.motion_detector.reset()
        
        return jsonify({
            "success": True,
            "motion_first_enabled": video_processor.motion_first_enabled
        })
    
    @app.route('/api/motion/show_regions', methods=['POST'])
    def toggle_show_motion_regions():
        """Toggle showing motion regions on video"""
        data = request.get_json() or {}
        show = data.get('show')
        
        if show is None:
            video_processor.show_motion_regions = not video_processor.show_motion_regions
        else:
            video_processor.show_motion_regions = bool(show)
        
        # Save setting
        settings.update_setting("show_motion_regions", video_processor.show_motion_regions)
        print(f"[SETTING] Show motion regions: {video_processor.show_motion_regions}")
        
        return jsonify({
            "success": True,
            "show_motion_regions": video_processor.show_motion_regions
        })
    
    # =========================================================================
    # Calibration API Endpoints
    # =========================================================================
    
    @app.route('/api/calibration', methods=['GET'])
    def get_calibration():
        """Get current calibration status and points"""
        calib = video_processor.get_calibration()
        # Also include saved lines
        saved = settings.load_settings()
        calib["lines"] = saved.get("calibration_lines", [])
        return jsonify(calib)
    
    @app.route('/api/calibration', methods=['POST'])
    def set_calibration():
        """Set calibration from one or more rectangles."""
        data = request.get_json()
        rectangles = data.get('rectangles', [])
        
        if not rectangles:
            return jsonify({"error": "Need at least 1 rectangle"}), 400
        
        for i, rect in enumerate(rectangles):
            if not rect.get("pixels") or len(rect["pixels"]) != 4:
                return jsonify({"error": f"Rectangle {i+1} needs exactly 4 pixel points"}), 400
            if not rect.get("side_lengths") or len(rect["side_lengths"]) != 4:
                return jsonify({"error": f"Rectangle {i+1} needs exactly 4 side lengths"}), 400
            try:
                rect["side_lengths"] = [float(x) for x in rect["side_lengths"]]
                rect["pixels"] = [[float(p[0]), float(p[1])] for p in rect["pixels"]]
            except (TypeError, ValueError, IndexError):
                return jsonify({"error": f"Rectangle {i+1} has invalid data"}), 400
            if rect.get("diagonal") is not None:
                try:
                    rect["diagonal"] = float(rect["diagonal"])
                except (TypeError, ValueError):
                    rect["diagonal"] = None
        
        success = video_processor.set_calibration_from_rectangles(rectangles)
        
        if success:
            return jsonify({
                "success": True,
                "calibration": video_processor.get_calibration()
            })
        return jsonify({"error": "Calibration failed"}), 400
    
    @app.route('/api/calibration', methods=['DELETE'])
    def clear_calibration():
        """Clear calibration"""
        video_processor.clear_calibration()
        # Also clear saved calibration lines
        settings.update_setting("calibration_lines", [])
        print("[SETTING] Calibration cleared")
        return jsonify({"success": True, "calibration": video_processor.get_calibration()})
    
    @app.route('/api/calibration/debug', methods=['GET'])
    def calibration_debug():
        """Diagnostic: compare calibration rectangles, perimeter, and world coords."""
        import math
        debug = {
            "lens_calibration": "ON" if video_processor.lens_calibration and video_processor.lens_calibration.is_calibrated else "OFF",
            "is_calibrated": video_processor.calibration.is_calibrated if video_processor.calibration else False,
        }
        
        # Camera resolution
        frame_res = None
        if video_processor.camera and video_processor.camera.running:
            frame_res = video_processor.camera.get_resolution()
        debug["camera_resolution"] = list(frame_res) if frame_res else None
        
        # Perimeter info
        perim_saved_res = None
        if hasattr(video_processor.perimeter, 'saved_resolution'):
            perim_saved_res = list(video_processor.perimeter.saved_resolution)
        debug["perimeter_saved_resolution"] = perim_saved_res
        
        # Calibration rectangles (original pixels)
        rects = video_processor.calibration.rectangles if video_processor.calibration else []
        debug["rectangles"] = []
        for i, rect in enumerate(rects):
            debug["rectangles"].append({
                "index": i + 1,
                "pixels": rect.get("pixels", []),
                "side_lengths": rect.get("side_lengths", []),
                "diagonal": rect.get("diagonal"),
            })
        
        # Calibration points (pixel + world, as used by homography)
        cal_pts = video_processor.calibration.calibration_points if video_processor.calibration else []
        debug["calibration_points"] = []
        for i, cp in enumerate(cal_pts):
            debug["calibration_points"].append({
                "index": i,
                "pixel": [round(cp["pixel"][0], 1), round(cp["pixel"][1], 1)],
                "world": [round(cp["world"][0], 4), round(cp["world"][1], 4)],
            })
        
        # Perimeter points and their world transformations
        perim_points = video_processor.get_perimeter()
        debug["perimeter_points"] = []
        if perim_points and video_processor.calibration and video_processor.calibration.is_calibrated:
            for i, point in enumerate(perim_points):
                px, py = float(point[0]), float(point[1])
                
                # Perimeter pixels are in raw camera space (redistorted at save).
                world_pos = video_processor.pixel_to_world(px, py, already_undistorted=False)
                
                debug["perimeter_points"].append({
                    "index": i,
                    "pixel": [round(px, 1), round(py, 1)],
                    "world": [round(world_pos[0], 4), round(world_pos[1], 4)] if world_pos else None,
                    "note": "already undistorted (clicked on corrected image)"
                })
            
            # Compute side lengths in top-down view
            world_pts = [p["world"] for p in debug["perimeter_points"] if p["world"]]
            n = len(world_pts)
            sides = []
            for i in range(n):
                j = (i + 1) % n
                dx = world_pts[j][0] - world_pts[i][0]
                dy = world_pts[j][1] - world_pts[i][1]
                sides.append(round(math.sqrt(dx*dx + dy*dy), 4))
            debug["topdown_side_lengths"] = sides
        
        return jsonify(debug)
    
    @app.route('/api/calibration/lines', methods=['GET'])
    def get_calibration_lines():
        """Get saved calibration lines"""
        saved = settings.load_settings()
        lines = saved.get("calibration_lines", [])
        return jsonify({"lines": lines, "is_calibrated": len(lines) > 0})
    
    @app.route('/api/calibration/lines', methods=['POST'])
    def save_calibration_lines():
        """Save calibration lines"""
        data = request.get_json()
        lines = data.get('lines', [])
        settings.update_setting("calibration_lines", lines)
        print(f"[SETTING] Calibration lines updated: {len(lines)} lines defined")
        return jsonify({"success": True, "lines": lines, "is_calibrated": len(lines) > 0})
    
    @app.route('/api/calibration/convert', methods=['POST'])
    def convert_coordinates():
        """Convert pixel coordinates to world coordinates"""
        data = request.get_json()
        pixel_x = data.get('x')
        pixel_y = data.get('y')
        
        if pixel_x is None or pixel_y is None:
            return jsonify({"error": "x and y coordinates required"}), 400
        
        world_pos = video_processor.pixel_to_world(float(pixel_x), float(pixel_y))
        
        if world_pos:
            return jsonify({
                "pixel": {"x": pixel_x, "y": pixel_y},
                "world": {"x": round(world_pos[0], 2), "y": round(world_pos[1], 2)}
            })
        return jsonify({"error": "Not calibrated or conversion failed"}), 400
    
    # =========================================================================
    # Top-Down View (Bird's Eye)
    # =========================================================================
    
    @app.route('/api/topdown', methods=['GET'])
    def get_topdown_view():
        """
        Get top-down (bird's eye) view data including:
        - Perimeter polygon in world coordinates
        - Tracked objects in world coordinates
        - World bounds for scaling
        """
        data = video_processor.get_topdown_data()
        return jsonify(data)
    
    # =========================================================================
    # Lens Calibration API Endpoints
    # =========================================================================
    
    @app.route('/api/lens_calibration', methods=['GET'])
    def get_lens_calibration():
        """Get lens calibration status and parameters."""
        if video_processor.lens_calibration:
            return jsonify(video_processor.lens_calibration.get_status())
        return jsonify({"is_calibrated": False})
    
    @app.route('/api/lens_calibration', methods=['POST'])
    def set_lens_calibration():
        """Run lens calibration from plumb lines.
        Body: { lines: [[[x,y],[x,y],[x,y],...], ...], image_width: W, image_height: H }
        """
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        lines = data.get('lines', [])
        image_width = data.get('image_width', 0)
        image_height = data.get('image_height', 0)
        if not lines or not image_width or not image_height:
            return jsonify({"error": "Missing lines, image_width, or image_height"}), 400
        try:
            result = video_processor.lens_calibration.calibrate(lines, image_width, image_height)
            return jsonify({"success": True, "calibration": result})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            print(f"[LENS] Calibration error: {e}")
            return jsonify({"error": f"Calibration failed: {e}"}), 500
    
    @app.route('/api/lens_calibration/analyze', methods=['GET'])
    def analyze_lens_lines():
        """Analyze all lines and return per-line quality scores."""
        if not video_processor.lens_calibration or not video_processor.lens_calibration.lines:
            return jsonify({"error": "No lines data available"}), 404
        result = video_processor.lens_calibration.analyze_lines()
        return jsonify(result)
    
    @app.route('/api/lens_calibration/progress', methods=['GET'])
    def get_lens_progress():
        """Poll calibration progress during optimization."""
        if video_processor.lens_calibration:
            return jsonify(video_processor.lens_calibration.get_progress())
        return jsonify({"in_progress": False, "iteration": 0, "max_iterations": 0})
    
    @app.route('/api/lens_calibration', methods=['DELETE'])
    def clear_lens_calibration():
        """Clear lens calibration and delete saved file."""
        if video_processor.lens_calibration:
            video_processor.lens_calibration.clear()
        return jsonify({"success": True})
    
    @app.route('/api/lens_calibration/lines', methods=['GET'])
    def export_lens_lines():
        """Export lines/points data as JSON (download or page-load)."""
        if not video_processor.lens_calibration or not video_processor.lens_calibration.lines:
            return jsonify({"lines": [], "num_lines": 0, "total_points": 0,
                            "image_width": 0, "image_height": 0})
        data = video_processor.lens_calibration.export_lines()
        return jsonify(data)
    
    @app.route('/api/lens_calibration/lines', methods=['POST'])
    def import_lens_lines():
        """Import lines/points data from JSON (upload). Replaces all lines."""
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        try:
            result = video_processor.lens_calibration.import_lines(data)
            return jsonify({"success": True, **result})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    
    @app.route('/api/lens_calibration/lines', methods=['DELETE'])
    def clear_lens_lines():
        """Delete all lines (but keep calibration result if any)."""
        if video_processor.lens_calibration:
            video_processor.lens_calibration.clear_lines()
        return jsonify({"success": True})
    
    @app.route('/api/lens_calibration/lines/recover', methods=['POST'])
    def recover_lens_lines():
        """Recover lines from lens_calibration.json after accidental deletion."""
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        count = video_processor.lens_calibration.recover_lines_from_calibration()
        if count > 0:
            return jsonify({"success": True, "recovered_lines": count})
        return jsonify({"error": "No lines found in calibration data to recover"}), 404
    
    @app.route('/api/lens_calibration/lines/delete', methods=['POST'])
    def delete_lens_lines():
        """Delete specific lines by number (1-based).
        Body: { line: 1 } or { lines: [1, 2] }
        """
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        line_numbers = data.get('lines', [])
        single = data.get('line', None)
        if single is not None:
            line_numbers = [int(single)]
        if not line_numbers:
            return jsonify({"error": "Specify 'line' (number) or 'lines' (array of numbers)"}), 400
        try:
            remaining = video_processor.lens_calibration.delete_lines([int(n) for n in line_numbers])
            return jsonify({"success": True, "remaining_lines": remaining})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    
    @app.route('/api/lens_calibration/lines/append', methods=['POST'])
    def append_lens_line():
        """Append a single line. Auto-saves to file."""
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        points = data.get('points', [])
        image_width = data.get('image_width', 0)
        image_height = data.get('image_height', 0)
        try:
            count = video_processor.lens_calibration.append_line(points, image_width, image_height)
            return jsonify({"success": True, "num_lines": count})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    
    # =========================================================================
    # Performance Profile API Endpoints (Phase 2)
    # =========================================================================
    
    @app.route('/api/performance/profiles', methods=['GET'])
    def get_profiles():
        """Get all available performance profiles"""
        return jsonify(video_processor.get_performance_profiles())
    
    @app.route('/api/performance/profile', methods=['GET'])
    def get_current_profile():
        """Get current active performance profile"""
        return jsonify(video_processor.get_current_profile())
    
    @app.route('/api/performance/profile', methods=['POST'])
    def set_profile():
        """Set active performance profile"""
        data = request.get_json()
        profile_name = data.get('profile')
        
        if not profile_name:
            return jsonify({"error": "Profile name required"}), 400
        
        success = video_processor.set_performance_profile(profile_name)
        if success:
            return jsonify({
                "success": True,
                "profile": profile_name,
                "settings": config.PERFORMANCE_PROFILES.get(profile_name, {})
            })
        return jsonify({"error": "Invalid profile name"}), 400
        
    return app


def run_server():
    """Run the web server"""
    # Start video processor
    video_processor.start()
    
    try:
        # Create and run Flask app
        app = create_app()
        app.run(
            host=config.HOST,
            port=config.PORT,
            debug=False,  # Always False in production — debug mode adds CPU overhead
            threaded=True,
            use_reloader=False
        )
    finally:
        video_processor.stop()


if __name__ == '__main__':
    run_server()

# Resolution options for 12MP camera
RESOLUTIONS = {
    "320x240": (320, 240),
    "640x480": (640, 480),
    "800x600": (800, 600),
    "1280x720": (1280, 720),
    "1920x1080": (1920, 1080),
    "2592x1944": (2592, 1944),
    "4056x3040": (4056, 3040),
}
