"""
Perimeter Manager
Handles user-defined detection zones/regions of interest
"""

import cv2
import numpy as np
import json
import os

import config


class PerimeterManager:
    """
    Manages user-defined perimeter/region of interest.
    Only objects within the perimeter are tracked.
    """
    
    def __init__(self, perimeter_file="perimeter.json"):
        """
        Initialize perimeter manager.
        
        Args:
            perimeter_file: JSON file to save/load perimeter points
        """
        self.perimeter_file = os.path.join(config.BASE_DIR, perimeter_file)
        self.points = []
        self.polygon = None
        # Resolution the perimeter was defined at
        self.saved_resolution = (config.FRAME_WIDTH, config.FRAME_HEIGHT)
        
        # Load saved perimeter or use default
        if os.path.exists(self.perimeter_file):
            self.load()
        else:
            self.set_points(config.DEFAULT_PERIMETER)
            
    def set_points(self, points, resolution=None):
        """
        Set perimeter points.
        
        Args:
            points: List of (x, y) tuples defining the polygon
            resolution: (width, height) the points are defined at
        """
        if len(points) < 3:
            print("Warning: Perimeter needs at least 3 points")
            return False
        
        self.points = [tuple(p) for p in points]
        self.polygon = np.array(self.points, dtype=np.int32)
        
        if resolution:
            self.saved_resolution = tuple(resolution)
        
        self.save()
        return True
        
    def get_points(self):
        """Get current perimeter points"""
        return self.points.copy()
        
    def clear(self):
        """Clear perimeter and reset to default"""
        self.set_points(config.DEFAULT_PERIMETER)
    
    def set_resolution(self, new_width, new_height):
        """
        Scale perimeter points to new resolution.
        
        Args:
            new_width: New frame width
            new_height: New frame height
        """
        if not self.points or len(self.points) < 3:
            return
        
        # Get current resolution from config
        old_width = config.FRAME_WIDTH
        old_height = config.FRAME_HEIGHT
        
        # Scale points proportionally
        scale_x = new_width / old_width
        scale_y = new_height / old_height
        
        scaled_points = [
            (int(x * scale_x), int(y * scale_y)) 
            for x, y in self.points
        ]
        
        self.set_points(scaled_points)
        print(f"Perimeter scaled from {old_width}x{old_height} to {new_width}x{new_height}")
        
    def get_scaled_polygon(self, frame_width, frame_height):
        """
        Get polygon scaled to a specific resolution.
        
        Args:
            frame_width: Target frame width
            frame_height: Target frame height
            
        Returns:
            Scaled polygon as numpy array, or None if no valid polygon
        """
        if self.polygon is None or len(self.polygon) < 3:
            return None
        
        saved_w, saved_h = self.saved_resolution
        
        if frame_width == saved_w and frame_height == saved_h:
            return self.polygon
        
        scale_x = frame_width / saved_w
        scale_y = frame_height / saved_h
        scaled_points = [(int(x * scale_x), int(y * scale_y)) for x, y in self.points]
        return np.array(scaled_points, dtype=np.int32)
    
    def is_inside(self, point, frame_resolution=None):
        """
        Check if a point is inside the perimeter.
        
        Args:
            point: (x, y) tuple
            frame_resolution: (width, height) of the frame the point is from
            
        Returns:
            True if point is inside perimeter
        """
        if self.polygon is None or len(self.polygon) < 3:
            return True  # No valid perimeter, accept all
        
        # Get polygon scaled to frame resolution if provided
        if frame_resolution:
            polygon = self.get_scaled_polygon(frame_resolution[0], frame_resolution[1])
        else:
            polygon = self.polygon
        
        if polygon is None:
            return True
            
        result = cv2.pointPolygonTest(polygon, point, False)
        return result >= 0  # >= 0 means inside or on edge
        
    def is_bbox_inside(self, bbox, mode="center", frame_resolution=None):
        """
        Check if a bounding box is inside the perimeter.
        
        Args:
            bbox: (x1, y1, x2, y2) bounding box
            mode: "center" - check if center is inside
                  "any" - check if any corner is inside
                  "all" - check if all corners are inside
            frame_resolution: (width, height) of the frame
                  
        Returns:
            True if bbox satisfies the condition
        """
        x1, y1, x2, y2 = bbox
        
        if mode == "center":
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            return self.is_inside((cx, cy), frame_resolution)
            
        elif mode == "any":
            corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            return any(self.is_inside(c, frame_resolution) for c in corners)
            
        elif mode == "all":
            corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            return all(self.is_inside(c, frame_resolution) for c in corners)
            
        return True
        
    def filter_detections(self, detections, mode="center", frame_resolution=None):
        """
        Filter detections to only those inside perimeter.
        
        Args:
            detections: List of (x1, y1, x2, y2, confidence, class_id)
            mode: How to check if detection is inside
            frame_resolution: (width, height) of the frame
            
        Returns:
            Filtered list of detections
        """
        if len(self.points) < 3:
            return detections  # No valid perimeter
            
        return [det for det in detections if self.is_bbox_inside(det[:4], mode, frame_resolution)]
        
    def draw(self, frame, filled=False, alpha=0.3):
        """
        Draw perimeter on frame.
        
        Args:
            frame: BGR image to draw on
            filled: If True, fill the polygon with semi-transparent color
            alpha: Transparency for filled mode
            
        Returns:
            Frame with perimeter drawn
        """
        if self.polygon is None or len(self.polygon) < 3:
            return frame
        
        # Get frame dimensions
        frame_h, frame_w = frame.shape[:2]
        saved_w, saved_h = self.saved_resolution
        
        # Scale polygon if frame resolution differs from saved resolution
        if frame_w != saved_w or frame_h != saved_h:
            scale_x = frame_w / saved_w
            scale_y = frame_h / saved_h
            scaled_points = [(int(x * scale_x), int(y * scale_y)) for x, y in self.points]
            draw_polygon = np.array(scaled_points, dtype=np.int32)
        else:
            draw_polygon = self.polygon
            scaled_points = self.points
            
        if filled:
            # Create overlay for semi-transparent fill
            overlay = frame.copy()
            cv2.fillPoly(overlay, [draw_polygon], config.PERIMETER_COLOR)
            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
            
        # Draw polygon outline
        cv2.polylines(
            frame, 
            [draw_polygon], 
            isClosed=True, 
            color=config.PERIMETER_COLOR, 
            thickness=config.PERIMETER_THICKNESS
        )
        
        # Draw corner points
        for point in scaled_points:
            cv2.circle(frame, point, 5, config.PERIMETER_COLOR, -1)
            
        return frame
        
    def save(self):
        """Save perimeter to JSON file with resolution info"""
        try:
            data = {
                "points": self.points,
                "resolution": list(self.saved_resolution)
            }
            with open(self.perimeter_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving perimeter: {e}")
    
    def set_saved_resolution(self, width, height):
        """Set the resolution the perimeter was defined at"""
        self.saved_resolution = (width, height)
            
    def load(self):
        """Load perimeter from JSON file"""
        try:
            with open(self.perimeter_file, 'r') as f:
                data = json.load(f)
            
            # Load saved resolution if available
            if "resolution" in data:
                self.saved_resolution = tuple(data["resolution"])
            
            self.points = [tuple(p) for p in data.get("points", config.DEFAULT_PERIMETER)]
            self.polygon = np.array(self.points, dtype=np.int32) if len(self.points) >= 3 else None
            
        except Exception as e:
            print(f"Error loading perimeter: {e}")
            self.set_points(config.DEFAULT_PERIMETER)
            
    def to_json(self):
        """Convert perimeter to JSON-serializable format"""
        return {"points": self.points}
        
    @classmethod
    def from_json(cls, data):
        """Create perimeter manager from JSON data"""
        manager = cls()
        manager.set_points(data.get("points", config.DEFAULT_PERIMETER))
        return manager
