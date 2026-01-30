"""
Cat Dome - Flask Web Server with MJPEG Streaming
Provides web interface for detection and tracking
"""

import time
import threading
import os
import logging
import cv2
from flask import Flask, Response, render_template, jsonify, request

import config

# Suppress Flask/Werkzeug access logs (the GET /api/status messages)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)  # Only show warnings and errors, not INFO


def get_system_info():
    """Get RAM usage and CPU temperature for Raspberry Pi"""
    info = {
        "ram_used_mb": None,
        "ram_total_mb": None,
        "ram_percent": None,
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
        # Get CPU temperature from Raspberry Pi thermal zone
        temp_path = '/sys/class/thermal/thermal_zone0/temp'
        if os.path.exists(temp_path):
            with open(temp_path, 'r') as f:
                temp_millicelsius = int(f.read().strip())
                info["cpu_temp"] = round(temp_millicelsius / 1000, 1)
    except Exception:
        pass
    
    return info
from camera.camera_handler import CameraHandler
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
        self.motion_detector = None
        
        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self._fps_start = time.time()
        self._fps_count = 0
        
        self.current_frame = None
        self.frame_lock = threading.Lock()
        
        # Load saved settings (or defaults)
        saved = settings.load_settings()
        
        # Performance settings (user-adjustable)
        self.current_resolution = tuple(saved.get("resolution", config.DEFAULT_RESOLUTION))
        self.current_framerate = saved.get("framerate", config.DEFAULT_FRAMERATE)
        self.current_frame_skip = saved.get("frame_skip", config.DEFAULT_FRAME_SKIP)
        
        # Motion-first detection mode (saves memory, better for distance)
        self.motion_first_enabled = saved.get("motion_first_enabled", True)
        self.show_motion_regions = saved.get("show_motion_regions", False)
        
        # Detection mode and threshold will be set on detector after it's created
        self._saved_detection_mode = saved.get("detection_mode", config.DEFAULT_DETECTION_MODE)
        self._saved_threshold = saved.get("detection_threshold", config.DETECTION_THRESHOLD)
        
        # Motion detection stats
        self.motion_detected = False
        self.ai_detections_count = 0
        
        # Temporal confirmation - require detection in N consecutive frames
        self.confirm_frames = saved.get("confirm_frames", getattr(config, 'DETECTION_CONFIRM_FRAMES', 1))
        self.detection_history = []  # List of recent detection counts
        
        # Store last detections with world coordinates for API
        self.last_detections_with_world = []
        
        print(f"Loaded settings: {self.current_resolution[0]}x{self.current_resolution[1]}, motion-first={self.motion_first_enabled}")
        
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
        
        # Set saved detection mode and threshold
        if hasattr(self, '_saved_detection_mode'):
            self.detector.set_detection_mode(self._saved_detection_mode)
        if hasattr(self, '_saved_threshold'):
            self.detector.set_threshold(self._saved_threshold)
        
        # Start camera
        self.camera.start()
        
        # Start processing thread
        self.running = True
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()
        
        mode_str = "MOTION-FIRST" if self.motion_first_enabled else "ALWAYS-ON"
        print(f"Video processor started (Detection mode: {mode_str})")
        
    def stop(self):
        """Stop all components"""
        self.running = False
        if self.camera:
            self.camera.stop()
        print("Video processor stopped")
        
    def _process_loop(self):
        """Main processing loop with motion-first detection"""
        skip_counter = 0
        last_detections = []
        
        while self.running:
            try:
                # Get frame from camera
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue
                
                frame_h, frame_w = frame.shape[:2]
                run_ai_detection = False
                crop_region = None
                motion_regions_in_perimeter = []
                
                # Run detection periodically (skip frames for performance)
                skip_counter += 1
                if skip_counter >= self.current_frame_skip:
                    skip_counter = 0
                    
                    if self.motion_first_enabled:
                        # Motion-first mode: only run AI when motion detected
                        motion_result = self.motion_detector.detect(frame)
                        
                        # Debug: log raw motion detection
                        if motion_result["motion_detected"]:
                            print(f"[DEBUG] Motion detected: {len(motion_result['regions'])} regions")
                        
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
                            
                            print(f"[DEBUG] Perimeter has {perimeter_points} points, {len(motion_regions_in_perimeter)}/{len(motion_result['regions'])} regions inside")
                            self.motion_detected = len(motion_regions_in_perimeter) > 0
                        else:
                            self.motion_detected = False
                        
                        if self.motion_detected:
                            # Get fixed 300x300 crop centered on motion (no scaling!)
                            # This preserves object pixel size for better detection
                            crop_size = getattr(config, 'MOTION_CROP_SIZE', (300, 300))
                            crop_region = self.motion_detector.get_fixed_crop_region(
                                frame.shape, 
                                crop_size=crop_size
                            )
                            run_ai_detection = True
                    else:
                        # Always-on mode: run AI on every frame
                        run_ai_detection = True
                        self.motion_detected = True
                    
                    if run_ai_detection:
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
                        
                        # Debug: log detections
                        if raw_count > 0:
                            confirmed_str = f", Confirmed: {len(detections) > 0}" if self.confirm_frames > 1 else ""
                            print(f"[DEBUG] Raw detections: {raw_count}, After perimeter filter: {len(detections)}{confirmed_str}")
                        
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
                    
                # Update tracker with latest detections
                tracked_objects = self.tracker.update(last_detections)
                
                # Draw annotations
                annotated = frame.copy()
                
                # Draw motion regions if enabled (only those inside perimeter)
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
                
                # Update current frame
                with self.frame_lock:
                    self.current_frame = annotated.copy()
                    
                # Update FPS
                self._update_fps()
                self.frame_count += 1
                
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
        
    def _update_fps(self):
        """Update FPS calculation"""
        self._fps_count += 1
        elapsed = time.time() - self._fps_start
        
        if elapsed >= 1.0:
            self.fps = self._fps_count / elapsed
            self._fps_count = 0
            self._fps_start = time.time()
            
    def get_frame_jpeg(self):
        """Get current frame as JPEG bytes"""
        with self.frame_lock:
            if self.current_frame is None:
                return None
            frame = self.current_frame.copy()
            
        # Encode as JPEG
        ret, jpeg = cv2.imencode(
            '.jpg', 
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY]
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
        system_info = get_system_info()
        
        is_calibrated = False
        if self.calibration and hasattr(self.calibration, 'is_calibrated'):
            is_calibrated = self.calibration.is_calibrated
        
        return {
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
            "cpu_temp": system_info["cpu_temp"],
            # Motion detection status
            "motion_first_enabled": self.motion_first_enabled,
            "motion_detected": self.motion_detected,
            "show_motion_regions": self.show_motion_regions,
            "ai_detections_count": self.ai_detections_count
        }
    
    # =========================================================================
    # Calibration Methods
    # =========================================================================
    
    def get_calibration(self):
        """Get current calibration status and points"""
        if self.calibration:
            return self.calibration.to_json()
        return {"is_calibrated": False, "points": [], "world_bounds": config.DEFAULT_WORLD_BOUNDS}
    
    def set_calibration(self, points):
        """Set calibration points"""
        if self.calibration:
            return self.calibration.set_calibration_points(points)
        return False
    
    def clear_calibration(self):
        """Clear calibration"""
        if self.calibration:
            self.calibration.clear()
    
    def pixel_to_world(self, pixel_x, pixel_y):
        """Convert pixel coordinates to world coordinates"""
        if self.calibration and self.calibration.is_calibrated:
            return self.calibration.pixel_to_world(pixel_x, pixel_y)
        return None
    
    def get_performance_settings(self):
        """Get current performance settings and available options"""
        return {
            "current": {
                "resolution": list(self.current_resolution),
                "framerate": self.current_framerate,
                "frame_skip": self.current_frame_skip
            },
            "options": {
                "resolutions": [list(r) for r in config.RESOLUTION_OPTIONS],
                "framerates": config.FRAMERATE_OPTIONS,
                "frame_skips": config.FRAME_SKIP_OPTIONS
            }
        }
    
    def set_resolution(self, width, height):
        """Set camera resolution (requires camera restart)"""
        new_res = (width, height)
        if new_res not in config.RESOLUTION_OPTIONS:
            return False
        
        self.current_resolution = new_res
        settings.update_setting("resolution", list(new_res))
        print(f"[SETTING] Resolution changed to: {width}x{height}")
        
        # Restart camera with new settings
        if self.camera:
            self.camera.stop()
            self.camera = CameraHandler(width=width, height=height, fps=self.current_framerate)
            self.camera.start()
            
            # Update perimeter to new resolution
            if self.perimeter:
                self.perimeter.set_resolution(width, height)
            
            # Reset motion detector for new resolution
            if self.motion_detector:
                self.motion_detector.reset()
        
        print(f"Resolution changed to: {width}x{height}")
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
            return False
        
        self.current_frame_skip = skip
        settings.update_setting("frame_skip", skip)
        print(f"[SETTING] Frame skip changed to: {skip}")
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
        
    @app.route('/video_feed')
    def video_feed():
        """MJPEG video stream endpoint"""
        # Check if requesting a single snapshot
        if request.args.get('snapshot'):
            jpeg = video_processor.get_frame_jpeg()
            if jpeg:
                return Response(jpeg, mimetype='image/jpeg')
            return Response(status=503)
        
        # Otherwise stream continuously
        def generate():
            while True:
                jpeg = video_processor.get_frame_jpeg()
                if jpeg is not None:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                    )
                else:
                    time.sleep(0.05)
                    
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
        """Set perimeter points"""
        data = request.get_json()
        points = data.get('points', [])
        source_width = data.get('source_width')
        source_height = data.get('source_height')
        
        if len(points) < 3:
            return jsonify({"error": "Need at least 3 points"}), 400
        
        cam_width, cam_height = video_processor.current_resolution
        
        # If source dimensions provided and different from camera, scale the points
        if source_width and source_height and (source_width != cam_width or source_height != cam_height):
            scale_x = cam_width / source_width
            scale_y = cam_height / source_height
            
            scaled_points = []
            for p in points:
                x = int(p[0] * scale_x)
                y = int(p[1] * scale_y)
                scaled_points.append([x, y])
            
            print(f"Perimeter: scaled from {source_width}x{source_height} to {cam_width}x{cam_height}")
            print(f"  Original first point: {points[0]}, Scaled: {scaled_points[0]}")
        else:
            # Points already at camera resolution
            scaled_points = [[int(p[0]), int(p[1])] for p in points]
            print(f"Perimeter: saved at camera resolution {cam_width}x{cam_height}")
            print(f"  First point: {scaled_points[0]}")
        
        # Set perimeter with resolution info
        if video_processor.perimeter:
            video_processor.perimeter.set_saved_resolution(cam_width, cam_height)
        success = video_processor.set_perimeter(scaled_points)
        
        if success:
            print(f"[SETTING] Perimeter updated: {len(scaled_points)} points at {cam_width}x{cam_height}")
        
        return jsonify({
            "success": success, 
            "points": video_processor.get_perimeter(),
            "camera_resolution": [cam_width, cam_height],
            "source_resolution": [source_width, source_height] if source_width else None
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
        """Set camera resolution"""
        data = request.get_json()
        width = data.get('width')
        height = data.get('height')
        
        if not width or not height:
            return jsonify({"error": "Width and height required"}), 400
        
        success = video_processor.set_resolution(int(width), int(height))
        if success:
            return jsonify({"success": True, "resolution": [width, height]})
        return jsonify({"error": "Invalid resolution"}), 400
    
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
        """Set calibration points (4 points required)"""
        data = request.get_json()
        points = data.get('points', [])
        
        if len(points) != 4:
            return jsonify({"error": "Exactly 4 calibration points required"}), 400
        
        # Validate point format
        for i, p in enumerate(points):
            if "pixel" not in p or "world" not in p:
                return jsonify({"error": f"Point {i+1} missing 'pixel' or 'world' coordinates"}), 400
        
        success = video_processor.set_calibration(points)
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
            debug=config.DEBUG,
            threaded=True,
            use_reloader=False  # Disable reloader to avoid duplicate processes
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
