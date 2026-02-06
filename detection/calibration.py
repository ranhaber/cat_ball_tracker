"""
Camera Calibration and Perspective Transform
Converts pixel coordinates to real-world coordinates (meters)
"""

import cv2
import numpy as np
import json
import os

import config


class CameraCalibration:
    """
    Handles perspective transformation from camera view to real-world coordinates.
    Uses 4 calibration points to compute a homography matrix.
    
    The ground plane is assumed to be flat, with objects always on the ground.
    """
    
    def __init__(self, calibration_file="calibration.json"):
        """
        Initialize calibration manager.
        
        Args:
            calibration_file: JSON file to save/load calibration data
        """
        self.calibration_file = os.path.join(config.BASE_DIR, calibration_file)
        
        # Calibration points: list of 4 points
        # Each point: {"pixel": [px, py], "world": [wx, wy]}
        self.calibration_points = []
        
        # Transformation matrix (3x3 homography)
        self.transform_matrix = None
        self.inverse_matrix = None
        
        # Calibration status
        self.is_calibrated = False
        
        # Real-world bounds (for mini-map scaling)
        self.world_bounds = {
            "min_x": 0, "max_x": 10,
            "min_y": 0, "max_y": 10
        }
        
        # Load saved calibration
        if os.path.exists(self.calibration_file):
            self.load()
    
    def set_calibration_points(self, points):
        """
        Set the 4 calibration points and compute transformation.
        
        Args:
            points: List of 4 dicts with "pixel" and "world" coordinates
                   [{"pixel": [px, py], "world": [wx, wy]}, ...]
        
        Returns:
            bool: True if calibration successful
        """
        if len(points) != 4:
            print(f"Error: Need exactly 4 calibration points, got {len(points)}")
            return False
        
        # Validate points
        for i, p in enumerate(points):
            if "pixel" not in p or "world" not in p:
                print(f"Error: Point {i} missing 'pixel' or 'world' key")
                return False
            if len(p["pixel"]) != 2 or len(p["world"]) != 2:
                print(f"Error: Point {i} has invalid coordinates")
                return False
        
        self.calibration_points = points
        
        # Compute transformation matrix
        success = self._compute_transform()
        
        if success:
            self._update_world_bounds()
            self.save()
            print("Calibration successful!")
        
        return success
    
    def set_calibration_from_side_lengths(self, points_pixel, side_lengths):
        """
        Set calibration from 4 pixel points and the length of each side in meters.
        First point = origin (0, 0). Right in image = +X, up in image = +Y.
        
        Args:
            points_pixel: List of 4 [x, y] pixel coordinates (same order as zone).
            side_lengths: List of 4 lengths in meters: [P0->P1, P1->P2, P2->P3, P3->P0].
        
        Returns:
            bool: True if calibration successful
        """
        if len(points_pixel) != 4 or len(side_lengths) != 4:
            print(f"Error: Need exactly 4 pixel points and 4 side lengths")
            return False
        
        # Build world coordinates: P0 = (0,0); right = +X, up = +Y (image y down => world y = -image_y for direction)
        world_pts = []
        world_pts.append([0.0, 0.0])  # First mark = origin
        
        for i in range(1, 4):
            px_prev = points_pixel[i - 1]
            px_curr = points_pixel[i]
            dx = px_curr[0] - px_prev[0]
            dy = px_curr[1] - px_prev[1]
            # In world: image right = +X, image up = +Y, so direction = (dx, -dy)
            len_pixel = (dx * dx + dy * dy) ** 0.5
            if len_pixel < 1e-6:
                print(f"Error: Points {i} and {i+1} are too close together")
                return False
            length_m = float(side_lengths[i - 1])
            wx = world_pts[i - 1][0] + length_m * (dx / len_pixel)
            wy = world_pts[i - 1][1] - length_m * (dy / len_pixel)  # -dy because image Y down
            world_pts.append([wx, wy])
        
        points = [
            {"pixel": list(points_pixel[i]), "world": world_pts[i]}
            for i in range(4)
        ]
        return self.set_calibration_points(points)
    
    def _compute_transform(self):
        """Compute the perspective transformation matrix."""
        try:
            # Extract pixel and world points
            pixel_pts = np.float32([p["pixel"] for p in self.calibration_points])
            world_pts = np.float32([p["world"] for p in self.calibration_points])
            
            # Compute homography: pixel -> world
            self.transform_matrix = cv2.getPerspectiveTransform(pixel_pts, world_pts)
            
            # Compute inverse: world -> pixel
            self.inverse_matrix = cv2.getPerspectiveTransform(world_pts, pixel_pts)
            
            self.is_calibrated = True
            return True
            
        except Exception as e:
            print(f"Error computing transform: {e}")
            self.is_calibrated = False
            return False
    
    def _update_world_bounds(self):
        """Update world bounds based on calibration points."""
        if not self.calibration_points:
            return
        
        world_x = [p["world"][0] for p in self.calibration_points]
        world_y = [p["world"][1] for p in self.calibration_points]
        
        # Add some padding
        padding = 1.0  # 1 meter padding
        self.world_bounds = {
            "min_x": min(world_x) - padding,
            "max_x": max(world_x) + padding,
            "min_y": min(world_y) - padding,
            "max_y": max(world_y) + padding
        }
    
    def pixel_to_world(self, pixel_x, pixel_y):
        """
        Convert pixel coordinates to real-world coordinates (meters).
        
        Args:
            pixel_x: X coordinate in pixels
            pixel_y: Y coordinate in pixels
            
        Returns:
            tuple: (world_x, world_y) in meters, or None if not calibrated
        """
        if not self.is_calibrated or self.transform_matrix is None:
            return None
        
        try:
            # Create point array for transformation
            point = np.float32([[[pixel_x, pixel_y]]])
            
            # Apply perspective transform
            transformed = cv2.perspectiveTransform(point, self.transform_matrix)
            
            world_x = float(transformed[0][0][0])
            world_y = float(transformed[0][0][1])
            
            return (world_x, world_y)
            
        except Exception as e:
            print(f"Error in pixel_to_world: {e}")
            return None
    
    def world_to_pixel(self, world_x, world_y):
        """
        Convert real-world coordinates to pixel coordinates.
        
        Args:
            world_x: X coordinate in meters
            world_y: Y coordinate in meters
            
        Returns:
            tuple: (pixel_x, pixel_y), or None if not calibrated
        """
        if not self.is_calibrated or self.inverse_matrix is None:
            return None
        
        try:
            point = np.float32([[[world_x, world_y]]])
            transformed = cv2.perspectiveTransform(point, self.inverse_matrix)
            
            pixel_x = int(transformed[0][0][0])
            pixel_y = int(transformed[0][0][1])
            
            return (pixel_x, pixel_y)
            
        except Exception as e:
            print(f"Error in world_to_pixel: {e}")
            return None
    
    def bbox_to_world(self, x1, y1, x2, y2):
        """
        Convert a bounding box to world coordinates.
        Uses the bottom-center of the box (where object touches ground).
        
        Args:
            x1, y1, x2, y2: Bounding box in pixels
            
        Returns:
            dict: {"center": (wx, wy), "bottom_center": (wx, wy)} or None
        """
        if not self.is_calibrated:
            return None
        
        # Bottom-center of bounding box (where object touches ground)
        bottom_center_x = (x1 + x2) / 2
        bottom_center_y = y2  # Bottom of box
        
        world_pos = self.pixel_to_world(bottom_center_x, bottom_center_y)
        
        if world_pos:
            return {
                "world_x": round(world_pos[0], 2),
                "world_y": round(world_pos[1], 2)
            }
        return None
    
    def get_world_bounds(self):
        """Get the world coordinate bounds for mini-map scaling."""
        return self.world_bounds.copy()
    
    def get_calibration_points(self):
        """Get current calibration points."""
        return self.calibration_points.copy()
    
    def get_side_lengths(self):
        """
        Get the length of each side in meters from current calibration.
        Returns [L01, L12, L23, L30] or empty list if not calibrated.
        """
        if not self.calibration_points or len(self.calibration_points) != 4:
            return []
        pts = [p["world"] for p in self.calibration_points]
        lengths = []
        for i in range(4):
            j = (i + 1) % 4
            dx = pts[j][0] - pts[i][0]
            dy = pts[j][1] - pts[i][1]
            lengths.append(round((dx * dx + dy * dy) ** 0.5, 3))
        return lengths
    
    def clear(self):
        """Clear calibration."""
        self.calibration_points = []
        self.transform_matrix = None
        self.inverse_matrix = None
        self.is_calibrated = False
        
        # Delete saved file
        if os.path.exists(self.calibration_file):
            os.remove(self.calibration_file)
        
        print("Calibration cleared")
    
    def save(self):
        """Save calibration to JSON file."""
        try:
            data = {
                "points": self.calibration_points,
                "world_bounds": self.world_bounds,
                "is_calibrated": self.is_calibrated
            }
            with open(self.calibration_file, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Calibration saved to {self.calibration_file}")
        except Exception as e:
            print(f"Error saving calibration: {e}")
    
    def load(self):
        """Load calibration from JSON file."""
        try:
            with open(self.calibration_file, 'r') as f:
                data = json.load(f)
            
            points = data.get("points", [])
            if len(points) == 4:
                self.calibration_points = points
                self._compute_transform()
                self.world_bounds = data.get("world_bounds", self.world_bounds)
                print(f"Calibration loaded from {self.calibration_file}")
            else:
                print("Invalid calibration file - need 4 points")
                
        except Exception as e:
            print(f"Error loading calibration: {e}")
    
    def draw_calibration_info(self, frame):
        """
        Draw calibration status on frame.
        
        Args:
            frame: BGR image to draw on
            
        Returns:
            Frame with calibration info
        """
        if self.is_calibrated:
            status_text = "CALIBRATED"
            color = (0, 255, 0)  # Green
        else:
            status_text = "NOT CALIBRATED"
            color = (0, 165, 255)  # Orange
        
        # Draw in bottom-left corner
        cv2.putText(
            frame,
            status_text,
            (10, frame.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1
        )
        
        # Draw calibration points if set
        for i, point in enumerate(self.calibration_points):
            px, py = int(point["pixel"][0]), int(point["pixel"][1])
            wx, wy = point["world"][0], point["world"][1]
            
            # Draw point
            cv2.circle(frame, (px, py), 8, (255, 0, 255), -1)
            cv2.circle(frame, (px, py), 8, (255, 255, 255), 2)
            
            # Draw label
            label = f"P{i+1}: ({wx:.1f}m, {wy:.1f}m)"
            cv2.putText(
                frame,
                label,
                (px + 10, py - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 0, 255),
                1
            )
        
        return frame
    
    def to_json(self):
        """Get calibration status as JSON-serializable dict."""
        return {
            "is_calibrated": self.is_calibrated,
            "points": self.calibration_points,
            "world_bounds": self.world_bounds
        }
