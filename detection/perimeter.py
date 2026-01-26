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
        
        # Load saved perimeter or use default
        if os.path.exists(self.perimeter_file):
            self.load()
        else:
            self.set_points(config.DEFAULT_PERIMETER)
            
    def set_points(self, points):
        """
        Set perimeter points.
        
        Args:
            points: List of (x, y) tuples defining the polygon
        """
        if len(points) < 3:
            print("Warning: Perimeter needs at least 3 points")
            return False
            
        self.points = [tuple(p) for p in points]
        self.polygon = np.array(self.points, dtype=np.int32)
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
        
    def is_inside(self, point):
        """
        Check if a point is inside the perimeter.
        
        Args:
            point: (x, y) tuple
            
        Returns:
            True if point is inside perimeter
        """
        if self.polygon is None or len(self.polygon) < 3:
            return True  # No valid perimeter, accept all
            
        result = cv2.pointPolygonTest(self.polygon, point, False)
        return result >= 0  # >= 0 means inside or on edge
        
    def is_bbox_inside(self, bbox, mode="center"):
        """
        Check if a bounding box is inside the perimeter.
        
        Args:
            bbox: (x1, y1, x2, y2) bounding box
            mode: "center" - check if center is inside
                  "any" - check if any corner is inside
                  "all" - check if all corners are inside
                  
        Returns:
            True if bbox satisfies the condition
        """
        x1, y1, x2, y2 = bbox
        
        if mode == "center":
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            return self.is_inside((cx, cy))
            
        elif mode == "any":
            corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            return any(self.is_inside(c) for c in corners)
            
        elif mode == "all":
            corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            return all(self.is_inside(c) for c in corners)
            
        return True
        
    def filter_detections(self, detections, mode="center"):
        """
        Filter detections to only those inside perimeter.
        
        Args:
            detections: List of (x1, y1, x2, y2, confidence, class_id)
            mode: How to check if detection is inside
            
        Returns:
            Filtered list of detections
        """
        if len(self.points) < 3:
            return detections  # No valid perimeter
            
        return [det for det in detections if self.is_bbox_inside(det[:4], mode)]
        
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
            
        if filled:
            # Create overlay for semi-transparent fill
            overlay = frame.copy()
            cv2.fillPoly(overlay, [self.polygon], config.PERIMETER_COLOR)
            frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)
            
        # Draw polygon outline
        cv2.polylines(
            frame, 
            [self.polygon], 
            isClosed=True, 
            color=config.PERIMETER_COLOR, 
            thickness=config.PERIMETER_THICKNESS
        )
        
        # Draw corner points
        for point in self.points:
            cv2.circle(frame, point, 5, config.PERIMETER_COLOR, -1)
            
        return frame
        
    def save(self):
        """Save perimeter to JSON file"""
        try:
            data = {"points": self.points}
            with open(self.perimeter_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving perimeter: {e}")
            
    def load(self):
        """Load perimeter from JSON file"""
        try:
            with open(self.perimeter_file, 'r') as f:
                data = json.load(f)
            self.set_points(data.get("points", config.DEFAULT_PERIMETER))
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
