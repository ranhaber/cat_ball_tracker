"""
Flask Web Server with MJPEG Streaming
Provides web interface for cat/ball detection and tracking
"""

import time
import threading
import os
import cv2
from flask import Flask, Response, render_template, jsonify, request

import config


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
from detection.calibration import CameraCalibration


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
        
        self.running = False
        self.frame_count = 0
        self.fps = 0.0
        self._fps_start = time.time()
        self._fps_count = 0
        
        self.current_frame = None
        self.frame_lock = threading.Lock()
        
        # Performance settings (user-adjustable)
        self.current_resolution = config.DEFAULT_RESOLUTION
        self.current_framerate = config.DEFAULT_FRAMERATE
        self.current_frame_skip = config.DEFAULT_FRAME_SKIP
        
        # Store last detections with world coordinates for API
        self.last_detections_with_world = []
        
    def start(self):
        """Initialize and start all components"""
        print("Initializing video processor...")
        
        # Initialize components
        self.camera = CameraHandler()
        self.detector = TFLiteDetector()
        self.tracker = CentroidTracker()
        self.perimeter = PerimeterManager()
        self.calibration = CameraCalibration()
        
        # Start camera
        self.camera.start()
        
        # Start processing thread
        self.running = True
        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()
        
        print("Video processor started")
        
    def stop(self):
        """Stop all components"""
        self.running = False
        if self.camera:
            self.camera.stop()
        print("Video processor stopped")
        
    def _process_loop(self):
        """Main processing loop"""
        skip_counter = 0
        last_detections = []
        
        while self.running:
            try:
                # Get frame from camera
                frame = self.camera.get_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue
                    
                # Run detection periodically (skip frames for performance)
                skip_counter += 1
                if skip_counter >= self.current_frame_skip:
                    skip_counter = 0
                    
                    # Detect objects
                    detections = self.detector.detect(frame)
                    
                    # Filter by perimeter
                    detections = self.perimeter.filter_detections(detections)
                    
                    last_detections = detections
                    
                    # Compute world coordinates for each detection
                    self.last_detections_with_world = []
                    for det in detections:
                        x1, y1, x2, y2, conf, class_id = det
                        world_pos = None
                        if self.calibration and self.calibration.is_calibrated:
                            world_pos = self.calibration.bbox_to_world(x1, y1, x2, y2)
                        self.last_detections_with_world.append({
                            "bbox": [x1, y1, x2, y2],
                            "confidence": round(conf, 2),
                            "class_id": class_id,
                            "world_position": world_pos
                        })
                    
                # Update tracker with latest detections
                tracked_objects = self.tracker.update(last_detections)
                
                # Draw annotations
                annotated = frame.copy()
                
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
                time.sleep(0.1)
                
    def _draw_status(self, frame):
        """Draw status information on frame"""
        status_text = f"Mode: {self.detector.get_detection_mode().upper()} | FPS: {self.fps:.1f}"
        
        # Draw background
        (text_w, text_h), _ = cv2.getTextSize(
            status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
        )
        cv2.rectangle(
            frame,
            (5, 5),
            (text_w + 15, text_h + 15),
            (0, 0, 0),
            -1
        )
        
        # Draw text
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
            (10, text_h + 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
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
            
    def get_detection_mode(self):
        """Get current detection mode"""
        if self.detector:
            return self.detector.get_detection_mode()
        return config.DEFAULT_DETECTION_MODE
        
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
            
    def get_status(self):
        """Get current system status"""
        system_info = get_system_info()
        return {
            "fps": round(self.fps, 1),
            "frame_count": self.frame_count,
            "detection_mode": self.get_detection_mode(),
            "object_count": self.tracker.get_object_count() if self.tracker else 0,
            "perimeter_points": len(self.get_perimeter()),
            "resolution": list(self.current_resolution),
            "framerate": self.current_framerate,
            "frame_skip": self.current_frame_skip,
            "is_calibrated": self.calibration.is_calibrated if self.calibration else False,
            "detections": self.last_detections_with_world,
            "ram_used_mb": system_info["ram_used_mb"],
            "ram_total_mb": system_info["ram_total_mb"],
            "ram_percent": system_info["ram_percent"],
            "cpu_temp": system_info["cpu_temp"]
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
        
        # Restart camera with new settings
        if self.camera:
            self.camera.stop()
            self.camera = CameraHandler(width=width, height=height, fps=self.current_framerate)
            self.camera.start()
            
            # Update perimeter to new resolution
            if self.perimeter:
                self.perimeter.set_resolution(width, height)
        
        print(f"Resolution changed to: {width}x{height}")
        return True
    
    def set_framerate(self, fps):
        """Set camera framerate (requires camera restart)"""
        if fps not in config.FRAMERATE_OPTIONS:
            return False
        
        self.current_framerate = fps
        
        # Restart camera with new settings
        if self.camera:
            self.camera.stop()
            width, height = self.current_resolution
            self.camera = CameraHandler(width=width, height=height, fps=fps)
            self.camera.start()
        
        print(f"Framerate changed to: {fps} fps")
        return True
    
    def set_frame_skip(self, skip):
        """Set detection frame skip (no restart needed)"""
        if skip not in config.FRAME_SKIP_OPTIONS:
            return False
        
        self.current_frame_skip = skip
        print(f"Frame skip changed to: {skip}")
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
        """Get current perimeter points"""
        return jsonify({"points": video_processor.get_perimeter()})
        
    @app.route('/api/perimeter', methods=['POST'])
    def set_perimeter():
        """Set perimeter points"""
        data = request.get_json()
        points = data.get('points', [])
        
        if len(points) < 3:
            return jsonify({"error": "Need at least 3 points"}), 400
            
        success = video_processor.set_perimeter(points)
        return jsonify({"success": success, "points": video_processor.get_perimeter()})
        
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
    
    # =========================================================================
    # Calibration API Endpoints
    # =========================================================================
    
    @app.route('/api/calibration', methods=['GET'])
    def get_calibration():
        """Get current calibration status and points"""
        return jsonify(video_processor.get_calibration())
    
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
        return jsonify({"success": True, "calibration": video_processor.get_calibration()})
    
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
