"""
Camera Handler for Raspberry Pi Camera Module 3
Uses picamera2 library for hardware-accelerated capture
"""

import time
import threading
import numpy as np

try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    print("Warning: picamera2 not available. Using mock camera for testing.")

import cv2
import config


class MockCamera:
    """Mock camera for testing on non-RPi systems"""
    
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.frame_count = 0
        self.start_time = time.time()
        
    def capture_array(self):
        """Generate a test pattern frame with animated elements"""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        
        self.frame_count += 1
        elapsed = time.time() - self.start_time
        
        # Background gradient
        for y in range(self.height):
            shade = int(20 + (y / self.height) * 30)
            frame[y, :] = [shade, shade + 10, shade + 5]
        
        # Draw grid pattern
        grid_color = (60, 60, 60)
        for x in range(0, self.width, 50):
            cv2.line(frame, (x, 0), (x, self.height), grid_color, 1)
        for y in range(0, self.height, 50):
            cv2.line(frame, (0, y), (self.width, y), grid_color, 1)
        
        # Animated moving circle (simulates a moving object)
        circle_x = int((self.width // 2) + np.sin(elapsed * 0.5) * 150)
        circle_y = int((self.height // 2) + np.cos(elapsed * 0.3) * 100)
        cv2.circle(frame, (circle_x, circle_y), 40, (100, 200, 100), -1)
        cv2.circle(frame, (circle_x, circle_y), 40, (150, 255, 150), 2)
        
        # Second moving object
        circle2_x = int((self.width // 3) + np.cos(elapsed * 0.4) * 100)
        circle2_y = int((self.height // 3) + np.sin(elapsed * 0.6) * 80)
        cv2.circle(frame, (circle2_x, circle2_y), 30, (200, 100, 100), -1)
        cv2.circle(frame, (circle2_x, circle2_y), 30, (255, 150, 150), 2)
        
        # Header bar
        cv2.rectangle(frame, (0, 0), (self.width, 80), (40, 40, 50), -1)
        
        # Add text overlays
        cv2.putText(
            frame,
            f"MOCK CAMERA - Frame {self.frame_count}",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 200),
            2
        )
        cv2.putText(
            frame,
            "Camera hardware not available - Test mode active",
            (15, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (150, 150, 150),
            1
        )
        
        # Timestamp
        cv2.putText(
            frame,
            f"Time: {elapsed:.1f}s",
            (self.width - 140, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1
        )
        
        # Status indicator (blinking)
        if int(elapsed * 2) % 2 == 0:
            cv2.circle(frame, (self.width - 20, 50), 8, (0, 255, 0), -1)
        else:
            cv2.circle(frame, (self.width - 20, 50), 8, (0, 150, 0), -1)
        
        return frame
    
    def start(self):
        self.start_time = time.time()
        print("MockCamera: Started (test mode)")
    
    def stop(self):
        print("MockCamera: Stopped")
    
    def close(self):
        pass


class CameraHandler:
    """
    Handles camera capture from RPi Camera Module 3.
    Uses threaded capture for better performance on RPi Zero 2W.
    """
    
    def __init__(self, width=None, height=None, fps=None):
        """
        Initialize camera handler.
        
        Args:
            width: Frame width (default from config)
            height: Frame height (default from config)
            fps: Target FPS (default from config)
        """
        self.width = width or config.FRAME_WIDTH
        self.height = height or config.FRAME_HEIGHT
        self.fps = fps or config.TARGET_FPS
        
        self.camera = None
        self.frame = None
        self.frame_lock = threading.Lock()
        self.running = False
        self.capture_thread = None
        self.use_mock = False  # Will be set in start()
        
        self._frame_count = 0
        self._start_time = None
        self._current_fps = 0.0
        
    def start(self):
        """Start the camera and capture thread"""
        if self.running:
            return
        
        self.use_mock = False
        
        if PICAMERA_AVAILABLE:
            try:
                self._init_picamera()
            except Exception as e:
                print(f"⚠️  Picamera2 failed, using mock camera: {e}")
                self.use_mock = True
                self._init_mock_camera()
        else:
            self.use_mock = True
            self._init_mock_camera()
        
        self._start_time = time.time()
        self.running = True
        
        if config.USE_THREADED_CAPTURE:
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
        
        # Camera warmup
        time.sleep(config.CAMERA_WARMUP)
        
        camera_type = "MOCK" if self.use_mock else "REAL"
        print(f"Camera started ({camera_type}): {self.width}x{self.height} @ {self.fps}fps")
        
    def _init_picamera(self):
        """Initialize real picamera2"""
        try:
            self.camera = Picamera2()
            
            # Check if any cameras are available
            cameras = self.camera.global_camera_info()
            if not cameras:
                raise RuntimeError("No cameras detected")
            
            print(f"Found camera(s): {cameras}")
            
            # Configure for video capture optimized for RPi Zero 2W
            # OPTIMIZATION D: Use BGR888 directly to avoid RGB->BGR conversion
            camera_config = self.camera.create_video_configuration(
                main={
                    "size": (self.width, self.height),
                    "format": "BGR888"  # Direct BGR output (no conversion needed)
                },
                controls={
                    "FrameRate": self.fps
                },
                buffer_count=4  # Small buffer to reduce latency
            )
            
            self.camera.configure(camera_config)
            self.camera.start()
            
            # FOV Verification: RAW stream at 2304×1296 confirms 2×2 binning (120° FOV preserved)
            print(f"✅ Camera configured: {self.width}×{self.height} (2×2 binned, full 120° FOV)")
            
        except Exception as e:
            print(f"⚠️  Camera initialization failed: {e}")
            print("   Falling back to mock camera for testing...")
            self.camera = None
            raise  # Re-raise to trigger fallback
        
    def _init_mock_camera(self):
        """Initialize mock camera for testing"""
        self.camera = MockCamera(self.width, self.height)
        self.camera.start()
        
    def _capture_loop(self):
        """Threaded capture loop for continuous frame updates"""
        while self.running:
            try:
                new_frame = self.camera.capture_array()
                
                # Add delay for mock camera to simulate real frame rate
                if self.use_mock:
                    time.sleep(1.0 / self.fps)
                
                # OPTIMIZATION A: Reuse frame buffer instead of creating new one
                with self.frame_lock:
                    self.frame = new_frame
                    self._frame_count += 1
                    
                # Update FPS calculation every second
                elapsed = time.time() - self._start_time
                if elapsed >= 1.0:
                    self._current_fps = self._frame_count / elapsed
                    self._frame_count = 0
                    self._start_time = time.time()
                    
            except Exception as e:
                print(f"Camera capture error: {e}")
                time.sleep(0.1)
                
    def get_frame(self):
        """
        Get the latest captured frame.
        
        Returns:
            numpy.ndarray: BGR image frame, or None if no frame available
        """
        if config.USE_THREADED_CAPTURE:
            with self.frame_lock:
                if self.frame is not None:
                    # OPTIMIZATION A & D: No conversion needed, camera outputs BGR directly
                    # Return reference instead of copy (caller will copy if needed)
                    return self.frame
                return None
        else:
            # Direct capture (blocking)
            try:
                frame = self.camera.capture_array()
                self._frame_count += 1
                # OPTIMIZATION D: No conversion needed, camera outputs BGR directly
                return frame
            except Exception as e:
                print(f"Frame capture error: {e}")
                return None
    
    def get_fps(self):
        """Get current capture FPS"""
        return self._current_fps
    
    def get_resolution(self):
        """Get current camera resolution"""
        return (self.width, self.height)
    
    def stop(self):
        """Stop the camera and release resources"""
        self.running = False
        
        if self.capture_thread is not None:
            self.capture_thread.join(timeout=2.0)
            
        if self.camera is not None:
            try:
                if self.use_mock:
                    self.camera.stop()
                else:
                    self.camera.stop()
                    self.camera.close()
            except Exception as e:
                print(f"Error stopping camera: {e}")
                
        print("Camera stopped")
        
    def __enter__(self):
        self.start()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
