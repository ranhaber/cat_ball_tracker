"""
Inject Cat — test feature for validating the detection pipeline.

Pastes a cat image onto the real camera frame at a known position.
The cat walks vertex-to-vertex across the Detection Zone diagonals,
cycling through all vertices until the test is stopped.

This module is used by VideoProcessor and the /api/dev/inject_cat endpoint.
It does NOT load TFLite or modify the detection pipeline — it only
modifies the input frame. The real pipeline processes it as normal.

Usage:
    inject = InjectCat(perimeter, calibration, pixel_to_world_fn)
    inject.enable()
    frame = inject.paste_on_frame(frame)  # modifies frame in-place
    inject.disable()
"""

import os
import math
import cv2
import config


class InjectCat:
    """Manages the inject cat test feature.
    
    Attributes:
        active: Whether inject mode is currently enabled
        bbox: Current cat bounding box (x1, y1, x2, y2) or None
    """
    
    def __init__(self, perimeter, calibration, pixel_to_world_fn):
        """Initialize inject cat.
        
        Args:
            perimeter: PerimeterManager instance (for Detection Zone vertices)
            calibration: CameraCalibration instance (for perspective sizing)
            pixel_to_world_fn: Function(px, py) -> (wx, wy) for world coords
        """
        self.perimeter = perimeter
        self.calibration = calibration
        self.pixel_to_world = pixel_to_world_fn
        
        # State
        self.active = False
        self.bbox = None  # Current cat bounding box (x1, y1, x2, y2)
        
        # Cat image
        self._img = None          # Original pre-shrunk cat image (BGR+A)
        self._cached = None       # Resized BGR cat for paste
        self._cached_size = None  # Size the cache was built for
        self._cached_w = 0
        self._cached_h = 0
        
        # Movement
        self._x = 0.0             # Top-left X position
        self._y = 0.0             # Top-left Y position
        self._dx = 0.0            # Direction X (normalized)
        self._dy = 0.0            # Direction Y (normalized)
        self._speed = 2.0         # Pixels per frame
        self._initialized = False
        self._fixed_size = None   # Locked pixel size (no perspective drift)
        self._fallback_size = 150 # Fallback if no calibration
        
        # Vertex cycling
        self._vertex_idx = 0      # Current starting vertex
        self._target_x = 0.0     # Target vertex X
        self._target_y = 0.0     # Target vertex Y
        
        # Debug
        self._debug_count = 0
        
        # Load cat image at init
        self._load_image()
    
    def _load_image(self):
        """Load the test cat image. Pre-shrinks to max 400px wide."""
        cat_path = os.path.join(config.BASE_DIR, 'models', 'test_cat.png')
        if os.path.exists(cat_path):
            img = cv2.imread(cat_path, cv2.IMREAD_UNCHANGED)
            if img is not None:
                max_w = 400
                h_orig, w_orig = img.shape[:2]
                if w_orig > max_w:
                    scale = max_w / w_orig
                    new_w = max_w
                    new_h = max(10, int(h_orig * scale))
                    img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    print(f"[INJECT] Cat image pre-shrunk: {w_orig}x{h_orig} -> {new_w}x{new_h}")
                self._img = img
                print(f"[INJECT] Cat image loaded: {img.shape} ({img.nbytes // 1024}KB in RAM)")
            else:
                print(f"[INJECT] Failed to load cat image from {cat_path}")
        else:
            print(f"[INJECT] Cat image not found at {cat_path}")
    
    def enable(self):
        """Enable inject cat mode. Reloads image if previously freed."""
        self.active = True
        self._initialized = False
        self.bbox = None
        self._fixed_size = None
        self._vertex_idx = 0
        self._debug_count = 0
        if self._img is None:
            self._load_image()
        print("[INJECT] Cat injection enabled — pasting on real camera frames")
    
    def disable(self):
        """Disable inject cat mode and free resources."""
        self.active = False
        self.bbox = None
        self._initialized = False
        self._fixed_size = None
        
        # Free cached resized image
        self._cached = None
        self._cached_size = None
        self._cached_w = 0
        self._cached_h = 0
        
        # Free original image (reload on next enable)
        self._img = None
        
        print("[INJECT] Cat injection disabled, resources freed")
    
    def _get_perimeter_vertices(self, frame_w, frame_h):
        """Get Detection Zone vertices scaled to current frame resolution."""
        perim = self.perimeter.get_points() if self.perimeter else []
        if len(perim) < 3:
            return []
        saved_res = self.perimeter.saved_resolution if hasattr(self.perimeter, 'saved_resolution') else None
        pts = []
        for p in perim:
            px, py = float(p[0]), float(p[1])
            if saved_res and saved_res[0] > 0 and saved_res[1] > 0:
                px = px * frame_w / saved_res[0]
                py = py * frame_h / saved_res[1]
            pts.append((px, py))
        return pts
    
    def _get_perspective_size(self, px, py):
        """Get pixel size a 0.5m cat should be at position (px, py)."""
        if not (self.calibration and self.calibration.is_calibrated and 
                self.calibration.inverse_matrix is not None):
            return self._fallback_size
        
        try:
            world_pos = self.pixel_to_world(px, py)
            if world_pos is None:
                return self._fallback_size
            wx, wy = world_pos
            p1 = self.calibration.world_to_pixel(wx, wy)
            p2 = self.calibration.world_to_pixel(wx + 0.5, wy)
            if p1 and p2:
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                pixel_size = int(math.sqrt(dx * dx + dy * dy))
                return max(30, min(pixel_size, 400))
        except Exception:
            pass
        return self._fallback_size
    
    def _init_position(self, frame_w, frame_h):
        """Place cat at a vertex, heading towards the opposite diagonal vertex.
        Cycles through vertices sequentially on each call."""
        # Cat size offsets to convert bottom-center → top-left
        cat_h = self._cached_h if self._cached_h else 60
        cat_w_half = (self._cached_w // 2) if self._cached_w else 50
        
        pts = self._get_perimeter_vertices(frame_w, frame_h)
        if len(pts) >= 3:
            n = len(pts)
            start_idx = self._vertex_idx % n
            target_idx = (start_idx + n // 2) % n  # Opposite diagonal
            
            # Advance to next vertex for next respawn
            self._vertex_idx = (self._vertex_idx + 1) % n
            
            start_pt = pts[start_idx]
            target_pt = pts[target_idx]
            
            # Store target for arrival check
            self._target_x = target_pt[0]
            self._target_y = target_pt[1]
            
            # Push start 15% inward from vertex towards centroid
            cx = sum(p[0] for p in pts) / n
            cy = sum(p[1] for p in pts) / n
            sx = start_pt[0] + 0.15 * (cx - start_pt[0])
            sy = start_pt[1] + 0.15 * (cy - start_pt[1])
            
            # Position top-left so bottom-center is at start point
            self._x = float(sx - cat_w_half)
            self._y = float(sy - cat_h)
            
            # Direction towards target vertex
            dx = target_pt[0] - sx
            dy = target_pt[1] - sy
            length = math.sqrt(dx * dx + dy * dy)
            if length > 0:
                self._dx = dx / length
                self._dy = dy / length
            else:
                self._dx = 1.0
                self._dy = 0.0
            
            print(f"[INJECT] Vertex {start_idx+1}→{target_idx+1} (of {n}): "
                  f"start≈({sx:.0f},{sy:.0f}), target=({target_pt[0]:.0f},{target_pt[1]:.0f}), "
                  f"dist={length:.0f}px")
        else:
            # No perimeter — start at frame center
            self._x = float(frame_w // 2 - cat_w_half)
            self._y = float(frame_h // 2 - cat_h)
            self._dx = 1.0
            self._dy = 0.0
            self._target_x = float(frame_w - 100)
            self._target_y = float(frame_h // 2)
            print("[INJECT] No Detection Zone — starting at frame center")
        
        self._initialized = True
        self._fixed_size = None  # Recompute on first frame
    
    def paste_on_frame(self, frame):
        """Paste the cat image on the frame at the current position.
        
        Moves the cat each call. When it reaches the target vertex,
        respawns at the next vertex heading to its opposite.
        
        Args:
            frame: numpy array (H, W, 3) BGR — modified in-place
            
        Returns:
            The same frame array (modified in-place)
        """
        if self._img is None:
            return frame
        
        h, w = frame.shape[:2]
        
        # Initialize position on first call
        if not self._initialized:
            self._init_position(w, h)
        
        # Compute fixed size once per leg (no perspective drift)
        if self._fixed_size is None:
            raw_size = self._get_perspective_size(self._x, self._y)
            self._fixed_size = max(30, round(raw_size / 10) * 10)
            print(f"[INJECT] Fixed cat size: {self._fixed_size}px")
        cat_size = self._fixed_size
        
        # Cache resized cat image
        if self._cached_size != cat_size:
            cat_h_orig, cat_w_orig = self._img.shape[:2]
            scale = cat_size / cat_w_orig
            new_w = max(10, int(cat_w_orig * scale))
            new_h = max(10, int(cat_h_orig * scale))
            resized = cv2.resize(self._img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            self._cached = resized[:, :, :3] if resized.shape[2] >= 3 else resized
            self._cached_size = cat_size
            self._cached_w = new_w
            self._cached_h = new_h
        
        new_w = self._cached_w
        new_h = self._cached_h
        
        # Update position
        self._x += self._dx * self._speed
        self._y += self._dy * self._speed
        
        # Check arrival at target vertex (bottom-center)
        bcx = self._x + new_w // 2
        bcy = self._y + new_h
        target_dx = bcx - self._target_x
        target_dy = bcy - self._target_y
        dist = math.sqrt(target_dx * target_dx + target_dy * target_dy)
        
        # Also check out-of-frame safety
        out_of_frame = bcx < -50 or bcx > w + 50 or bcy < -50 or bcy > h + 50
        
        if dist < 25 or out_of_frame:
            reason = "out of frame" if out_of_frame else f"reached target (dist={dist:.0f}px)"
            print(f"[INJECT] Cat {reason}, moving to next vertex")
            self._initialized = False
            self.bbox = None
            self._init_position(w, h)
            return frame
        
        # Compute paste region (clamp to frame bounds)
        x = max(0, min(int(self._x), w - new_w))
        y = max(0, min(int(self._y), h - new_h))
        paste_w = min(new_w, w - x)
        paste_h = min(new_h, h - y)
        if paste_w <= 0 or paste_h <= 0:
            return frame
        
        # Fast paste — no alpha blending, just overwrite pixels
        frame[y:y+paste_h, x:x+paste_w] = self._cached[:paste_h, :paste_w]
        
        # Store bounding box for fallback detection injection
        self.bbox = (x, y, x + paste_w, y + paste_h)
        
        return frame
    
    def get_crop_region(self, frame_w, frame_h, crop_size=(380, 380)):
        """Get a crop region centered on the cat for TFLite inference.
        
        Returns (cx, cy, cw, ch) or None if no bbox.
        Same format as motion_detector.get_fixed_crop_region().
        """
        if not self.bbox:
            return None
        bx = self.bbox
        cat_cx = (bx[0] + bx[2]) // 2
        cat_cy = (bx[1] + bx[3]) // 2
        cw, ch = crop_size
        cx = max(0, min(cat_cx - cw // 2, frame_w - cw))
        cy = max(0, min(cat_cy - ch // 2, frame_h - ch))
        return (cx, cy, cw, ch)
    
    def get_debug_info(self):
        """Get debug info string for logging."""
        return (f"bbox={self.bbox}, "
                f"pos=({self._x:.0f},{self._y:.0f}), "
                f"initialized={self._initialized}")
