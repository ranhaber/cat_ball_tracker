"""
Motion Detector
Lightweight motion detection for triggering AI detection only when needed.
Optimized for low memory usage on RPi Zero 2W.
"""

import cv2
import numpy as np
from collections import deque
import threading

import config


class MotionDetector:
    """
    Detects motion by comparing consecutive frames.
    Returns regions of interest where motion occurred.
    """
    
    def __init__(self, 
                 detection_scale=0.25,
                 motion_threshold=25,
                 min_area=500,
                 blur_size=21,
                 history_frames=3):
        """
        Initialize motion detector.
        
        Args:
            detection_scale: Scale factor for motion detection (lower = faster, less memory)
            motion_threshold: Pixel difference threshold to consider as motion
            min_area: Minimum contour area to consider as motion
            blur_size: Gaussian blur kernel size (must be odd)
            history_frames: Number of frames to average for background
        """
        self.detection_scale = detection_scale
        self.motion_threshold = motion_threshold
        self.min_area = min_area
        self.blur_size = blur_size
        self.history_frames = history_frames
        
        # Frame history for background averaging
        self.frame_history = deque(maxlen=history_frames)
        self.background = None
        self.last_frame_size = None  # Track resolution changes
        
        # Thread safety for parameter updates
        self._lock = threading.Lock()
        
        # OPTIMIZATION J: Check if GPU acceleration available
        self.use_gpu = getattr(config, 'USE_GPU_ACCELERATION', False) and self._check_gpu_available()
        
        # Motion state
        self.motion_detected = False
        self.motion_regions = []
        self.motion_frame_count = 0
        self.cooldown_frames = 0
        
        # Settings
        self.cooldown_after_motion = 10  # Keep detecting for N frames after motion stops
    
    def _check_gpu_available(self):
        """Check if GPU/OpenCL acceleration is available"""
        try:
            # Test UMat creation
            test = cv2.UMat(np.zeros((10, 10), dtype=np.uint8))
            return cv2.ocl.haveOpenCL()
        except Exception:
            return False
        
    def reset(self):
        """Reset motion detector state"""
        self.frame_history.clear()
        self.background = None
        self.last_frame_size = None
        self.motion_detected = False
        self.motion_regions = []
        self.motion_frame_count = 0
        self.cooldown_frames = 0
    
    def update_parameters(self, detection_scale=None, motion_threshold=None, min_area=None):
        """
        Update detection parameters and reset history if scale changes.
        Thread-safe parameter updates.
        
        Args:
            detection_scale: New scale factor (will reset history)
            motion_threshold: New threshold value
            min_area: New minimum area
        """
        with self._lock:
            scale_changed = False
            
            if detection_scale is not None and detection_scale != self.detection_scale:
                self.detection_scale = detection_scale
                scale_changed = True
            
            if motion_threshold is not None:
                self.motion_threshold = motion_threshold
            
            if min_area is not None:
                self.min_area = min_area
            
            # Clear history if scale changed (frame sizes will be different)
            if scale_changed:
                print(f"Motion detector: Scale changed to {self.detection_scale}, clearing history")
                self.frame_history.clear()
                self.background = None
                self.last_frame_size = None
        
    def detect(self, frame):
        """
        Detect motion in frame.
        
        Args:
            frame: BGR image (full resolution)
            
        Returns:
            dict with:
                - motion_detected: bool
                - regions: list of (x, y, w, h) bounding boxes in original resolution
                - combined_region: single (x, y, w, h) encompassing all motion, or None
                - motion_mask: binary mask at detection scale (for debugging)
        """
        with self._lock:
            h, w = frame.shape[:2]
            
            # Downscale for motion detection (saves memory)
            small_w = int(w * self.detection_scale)
            small_h = int(h * self.detection_scale)
            current_scaled_size = (small_w, small_h)
            
            # Reset history if scaled resolution changed (e.g., detection_scale changed)
            if self.last_frame_size is not None and self.last_frame_size != current_scaled_size:
                print(f"Motion detector: Scaled size changed from {self.last_frame_size} to {current_scaled_size}, resetting history")
                self.frame_history.clear()
                self.background = None
            self.last_frame_size = current_scaled_size
            
            # OPTIMIZATION J: Use GPU acceleration if available
            if self.use_gpu:
                # Upload to GPU
                frame_gpu = cv2.UMat(frame)
                small_frame_gpu = cv2.resize(frame_gpu, (small_w, small_h), interpolation=cv2.INTER_AREA)
                gray_gpu = cv2.cvtColor(small_frame_gpu, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray_gpu, (self.blur_size, self.blur_size), 0).get()
            else:
                # CPU path (original)
                small_frame = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (self.blur_size, self.blur_size), 0)
            
            # Build background model
            self.frame_history.append(gray.astype(np.float32))
            
            if len(self.frame_history) < self.history_frames:
                # Not enough history yet
                return {
                    "motion_detected": False,
                    "regions": [],
                    "combined_region": None,
                    "motion_mask": None
                }
            
            # Average background
            self.background = np.mean(list(self.frame_history), axis=0).astype(np.uint8)
            
            # Compute absolute difference
            frame_delta = cv2.absdiff(self.background, gray)
            
            # Threshold to binary
            _, thresh = cv2.threshold(frame_delta, self.motion_threshold, 255, cv2.THRESH_BINARY)
            
            # Dilate to fill gaps
            thresh = cv2.dilate(thresh, None, iterations=2)
            
            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter by area and get bounding boxes
            motion_regions = []
            scale_x = w / small_w
            scale_y = h / small_h
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self.min_area * (self.detection_scale ** 2):
                    continue
                    
                # Get bounding box and scale to original resolution
                x, y, cw, ch = cv2.boundingRect(contour)
                x = int(x * scale_x)
                y = int(y * scale_y)
                cw = int(cw * scale_x)
                ch = int(ch * scale_y)
                
                # Add padding (20%)
                pad_x = int(cw * 0.2)
                pad_y = int(ch * 0.2)
                x = max(0, x - pad_x)
                y = max(0, y - pad_y)
                cw = min(w - x, cw + 2 * pad_x)
                ch = min(h - y, ch + 2 * pad_y)
                
                motion_regions.append((x, y, cw, ch))
            
            # Combine overlapping regions
            motion_regions = self._merge_overlapping_regions(motion_regions)
            
            # Update motion state
            if motion_regions:
                self.motion_detected = True
                self.motion_regions = motion_regions
                self.motion_frame_count += 1
                self.cooldown_frames = self.cooldown_after_motion
            else:
                if self.cooldown_frames > 0:
                    self.cooldown_frames -= 1
                    # Keep previous regions during cooldown
                else:
                    self.motion_detected = False
                    self.motion_regions = []
                    self.motion_frame_count = 0
            
            # Compute combined region
            combined_region = None
            if self.motion_regions:
                min_x = min(r[0] for r in self.motion_regions)
                min_y = min(r[1] for r in self.motion_regions)
                max_x = max(r[0] + r[2] for r in self.motion_regions)
                max_y = max(r[1] + r[3] for r in self.motion_regions)
                combined_region = (min_x, min_y, max_x - min_x, max_y - min_y)
            
            return {
                "motion_detected": self.motion_detected or self.cooldown_frames > 0,
                "regions": self.motion_regions,
                "combined_region": combined_region,
                "motion_mask": thresh
            }
    
    def _merge_overlapping_regions(self, regions, overlap_thresh=0.3):
        """Merge overlapping bounding boxes"""
        if len(regions) <= 1:
            return regions
        
        # Convert to list for modification
        regions = list(regions)
        merged = True
        
        while merged:
            merged = False
            new_regions = []
            used = set()
            
            for i, r1 in enumerate(regions):
                if i in used:
                    continue
                    
                x1, y1, w1, h1 = r1
                
                for j, r2 in enumerate(regions[i+1:], i+1):
                    if j in used:
                        continue
                        
                    x2, y2, w2, h2 = r2
                    
                    # Check overlap
                    overlap_x = max(0, min(x1+w1, x2+w2) - max(x1, x2))
                    overlap_y = max(0, min(y1+h1, y2+h2) - max(y1, y2))
                    overlap_area = overlap_x * overlap_y
                    
                    min_area = min(w1*h1, w2*h2)
                    
                    if overlap_area > overlap_thresh * min_area:
                        # Merge regions
                        new_x = min(x1, x2)
                        new_y = min(y1, y2)
                        new_w = max(x1+w1, x2+w2) - new_x
                        new_h = max(y1+h1, y2+h2) - new_y
                        
                        r1 = (new_x, new_y, new_w, new_h)
                        used.add(j)
                        merged = True
                
                new_regions.append(r1)
                used.add(i)
            
            regions = new_regions
        
        return regions
    
    def get_fixed_crop_region(self, frame_shape, crop_size=(300, 300)):
        """
        Get a fixed-size crop region centered on motion (NO SCALING needed).
        This preserves object pixel size for better small object detection.
        
        Args:
            frame_shape: (height, width) of original frame
            crop_size: Fixed (width, height) for crop - should match AI input size
            
        Returns:
            (x, y, w, h) crop region, or None if no motion
        """
        if not self.motion_regions:
            return None
            
        h, w = frame_shape[:2]
        crop_w, crop_h = crop_size
        
        # Get center of all motion regions
        min_x = min(r[0] for r in self.motion_regions)
        min_y = min(r[1] for r in self.motion_regions)
        max_x = max(r[0] + r[2] for r in self.motion_regions)
        max_y = max(r[1] + r[3] for r in self.motion_regions)
        
        # Center of motion
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        
        # Center the fixed crop on motion center
        crop_x = cx - crop_w // 2
        crop_y = cy - crop_h // 2
        
        # Clamp to frame bounds
        crop_x = max(0, min(crop_x, w - crop_w))
        crop_y = max(0, min(crop_y, h - crop_h))
        
        # Handle edge case where frame is smaller than crop
        crop_w = min(crop_w, w)
        crop_h = min(crop_h, h)
        
        return (crop_x, crop_y, crop_w, crop_h)
    
    def get_crop_region(self, frame_shape, min_size=(640, 480)):
        """
        Get the best crop region for AI detection (legacy - variable size).
        
        Args:
            frame_shape: (height, width) of original frame
            min_size: Minimum (width, height) for crop
            
        Returns:
            (x, y, w, h) crop region, or None if no motion
        """
        if not self.motion_regions:
            return None
            
        h, w = frame_shape[:2]
        min_w, min_h = min_size
        
        # Get combined region
        min_x = min(r[0] for r in self.motion_regions)
        min_y = min(r[1] for r in self.motion_regions)
        max_x = max(r[0] + r[2] for r in self.motion_regions)
        max_y = max(r[1] + r[3] for r in self.motion_regions)
        
        # Center of motion
        cx = (min_x + max_x) // 2
        cy = (min_y + max_y) // 2
        
        # Expand to minimum size
        crop_w = max(max_x - min_x, min_w)
        crop_h = max(max_y - min_y, min_h)
        
        # Center crop on motion
        crop_x = cx - crop_w // 2
        crop_y = cy - crop_h // 2
        
        # Clamp to frame bounds
        crop_x = max(0, min(crop_x, w - crop_w))
        crop_y = max(0, min(crop_y, h - crop_h))
        crop_w = min(crop_w, w - crop_x)
        crop_h = min(crop_h, h - crop_y)
        
        return (crop_x, crop_y, crop_w, crop_h)
    
    def draw_motion(self, frame, regions=None, color=(0, 255, 255), thickness=2):
        """
        Draw motion regions on frame for debugging.
        
        Args:
            frame: Image to draw on
            regions: Optional list of regions to draw (if None, uses self.motion_regions)
            color: BGR color for rectangles
            thickness: Line thickness
        """
        regions_to_draw = regions if regions is not None else self.motion_regions
        
        for x, y, w, h in regions_to_draw:
            cv2.rectangle(frame, (x, y), (x+w, y+h), color, thickness)
            
        # Draw "MOTION" indicator only if there are regions
        if regions_to_draw:
            cv2.putText(
                frame,
                "MOTION",
                (10, frame.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2
            )
            
        return frame
