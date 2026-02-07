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
    Uses one or more rectangles with known dimensions to compute a homography matrix.
    
    The ground plane is assumed to be flat, with objects always on the ground.
    """
    
    def __init__(self, calibration_file="calibration.json"):
        """
        Initialize calibration manager.
        
        Args:
            calibration_file: JSON file to save/load calibration data
        """
        self.calibration_file = os.path.join(config.BASE_DIR, calibration_file)
        
        # Calibration points: list of {pixel, world} dicts
        self.calibration_points = []
        
        # Transformation matrix (3x3 homography)
        self.transform_matrix = None
        self.inverse_matrix = None
        
        # Calibration status
        self.is_calibrated = False
        
        # Rectangle definitions (for multi-rectangle calibration)
        self.rectangles = []
        self.pixels_undistorted = True  # Whether pixel coords are in undistorted space
        
        # Per-rectangle local homographies (for weighted interpolation)
        self.rect_homographies = []  # [{H, center_px, world_pts}, ...]
        
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
        Set calibration points and compute transformation.
        
        Args:
            points: List of 4+ dicts with "pixel" and "world" coordinates
                   [{"pixel": [px, py], "world": [wx, wy]}, ...]
                   4 points: exact homography (getPerspectiveTransform)
                   5+ points: least-squares best-fit homography (findHomography)
        
        Returns:
            bool: True if calibration successful
        """
        if len(points) < 4:
            print(f"Error: Need at least 4 calibration points, got {len(points)}")
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
            print(f"Calibration successful! ({len(points)} points)")
        
        return success
    
    def _compute_rect_world_pts(self, points_pixel, side_lengths, diagonal=None):
        """
        Compute world coordinates for 4 pixel points given side lengths.
        Places P0 at origin, orients based on pixel directions.
        
        Args:
            points_pixel: List of 4 [x, y] pixel coordinates.
            side_lengths: List of 4 side lengths in meters.
            diagonal: Optional diagonal P0->P2 in meters.
            
        Returns:
            list of 4 [wx, wy] world coordinates, or None on error.
        """
        import math
        
        L01, L12, L23, L30 = [float(s) for s in side_lengths]
        
        # Pixel winding
        cross_px = ((points_pixel[1][0] - points_pixel[0][0]) *
                    (points_pixel[2][1] - points_pixel[1][1]) -
                    (points_pixel[1][1] - points_pixel[0][1]) *
                    (points_pixel[2][0] - points_pixel[1][0]))
        
        dx01 = float(points_pixel[1][0] - points_pixel[0][0])
        dy01 = float(points_pixel[1][1] - points_pixel[0][1])
        
        tol = 0.01  # 1 cm
        is_rect = abs(L01 - L23) < tol and abs(L12 - L30) < tol
        
        if is_rect:
            # ====== RECTANGLE: direct geometry (no SSS needed) ======
            # P0=(0,0), P1=(width,0), P2=(width,height), P3=(0,height)
            # Height sign determined by pixel winding direction.
            width = L01
            height = L12
            
            # CW in image (cross_px > 0, y-down) → P2 below P1 → world y negative
            if cross_px > 0:
                h_sign = -1.0
            else:
                h_sign = 1.0
            
            world_pts = [
                [0.0, 0.0],
                [width, 0.0],
                [width, h_sign * height],
                [0.0, h_sign * height]
            ]
            
            # Orient based on pixel direction of P0→P1
            if abs(dx01) < abs(dy01):
                # P0→P1 is mostly vertical → rotate 90°
                sy = -1.0 if dy01 >= 0 else 1.0
                world_pts = [[-sy * p[1], sy * p[0]] for p in world_pts]
            else:
                # P0→P1 is mostly horizontal → flip X if going left
                if dx01 < 0:
                    world_pts = [[-p[0], p[1]] for p in world_pts]
        
        elif diagonal is not None and float(diagonal) > 0:
            # ====== NON-RECTANGLE WITH DIAGONAL: SSS triangles ======
            d02 = float(diagonal)
            
            cos_a = (L01 * L01 + d02 * d02 - L12 * L12) / (2.0 * L01 * d02) if L01 > 0 and d02 > 0 else 0
            cos_a = max(-1.0, min(1.0, cos_a))
            sin_a = math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
            if cross_px > 0:
                p2y = -sin_a * d02
            else:
                p2y = sin_a * d02
            p2x = cos_a * d02
            
            d = math.sqrt(p2x * p2x + p2y * p2y)
            if d < 1e-10:
                return None
            aa = (L30 * L30 - L23 * L23 + d * d) / (2.0 * d)
            hh_sq = L30 * L30 - aa * aa
            if hh_sq < -1e-6:
                return None
            hh = math.sqrt(max(0.0, hh_sq))
            ux, uy = p2x / d, p2y / d
            p3_a = [aa * ux + hh * (-uy), aa * uy + hh * ux]
            p3_b = [aa * ux - hh * (-uy), aa * uy - hh * ux]
            
            # Pick P3 that is NOT degenerate (not same position as P0 or P1)
            dist_a_p1 = math.sqrt((p3_a[0] - L01)**2 + p3_a[1]**2)
            dist_b_p1 = math.sqrt((p3_b[0] - L01)**2 + p3_b[1]**2)
            if dist_a_p1 < 0.01:
                # p3_a is at P1 — degenerate, use p3_b
                p3 = p3_b
            elif dist_b_p1 < 0.01:
                # p3_b is at P1 — degenerate, use p3_a
                p3 = p3_a
            else:
                # Normal case: use winding check
                cross_a = (p2x - L01) * (p3_a[1] - p2y) - (p2y - 0) * (p3_a[0] - p2x)
                cross_01_12 = (L01 - 0) * (p2y - 0) - (0 - 0) * (p2x - L01)
                if cross_01_12 * cross_a >= 0:
                    p3 = p3_a
                else:
                    p3 = p3_b
            
            world_pts = [[0.0, 0.0], [L01, 0.0], [p2x, p2y], p3]
            
            if abs(dx01) < abs(dy01):
                sy = -1.0 if dy01 >= 0 else 1.0
                world_pts = [[-sy * p[1], sy * p[0]] for p in world_pts]
            else:
                if dx01 < 0:
                    world_pts = [[-p[0], p[1]] for p in world_pts]
        else:
            # Heuristic fallback
            world_pts = [[0.0, 0.0]]
            for i in range(1, 4):
                px_prev = points_pixel[i - 1]
                px_curr = points_pixel[i]
                ddx = float(px_curr[0] - px_prev[0])
                ddy = float(px_curr[1] - px_prev[1])
                length_px = math.sqrt(ddx * ddx + ddy * ddy)
                if length_px < 1e-6:
                    return None
                length_m = float(side_lengths[i - 1])
                wx = world_pts[i - 1][0] + length_m * (ddx / length_px)
                wy = world_pts[i - 1][1] - length_m * (ddy / length_px)
                world_pts.append([wx, wy])
        
        return world_pts
    
    def set_calibration_from_rectangles(self, rectangles):
        """
        Set calibration from one or more rectangles.
        
        Each rectangle's exact shape is computed independently from its side lengths
        (using SSS triangles / rectangle geometry). Rectangle 0 is placed at the origin.
        Rectangles 1+ are positioned using a preliminary homography from rect 0, but
        their SHAPE is preserved exactly (only position and orientation from H).
        
        Final homography computed from ALL points (findHomography).
        
        Args:
            rectangles: List of dicts, each with:
                - "pixels": [[x,y], [x,y], [x,y], [x,y]]
                - "side_lengths": [L01, L12, L23, L30]
                - "diagonal": optional float
                
        Returns:
            bool: True if calibration successful
        """
        import math
        
        if not rectangles or len(rectangles) < 1:
            print("Error: Need at least 1 rectangle")
            return False
        
        # Note: self.rectangles should be set by caller with original (display) pixels.
        if not self.rectangles:
            self.rectangles = rectangles
        
        # --- Rectangle 0: exact world coords at origin ---
        r0 = rectangles[0]
        world_pts_0 = self._compute_rect_world_pts(
            r0["pixels"], r0["side_lengths"], r0.get("diagonal"))
        if world_pts_0 is None:
            print("Error: Failed to compute world coords for rectangle 1")
            return False
        
        print(f"[CALIBRATION] Rect 1 world: {[f'({p[0]:.3f},{p[1]:.3f})' for p in world_pts_0]}")
        
        all_pixel_pts = list(r0["pixels"])
        all_world_pts = list(world_pts_0)
        
        if len(rectangles) > 1:
            # Compute preliminary homography from rectangle 0
            pixel_pts_0 = np.float32(r0["pixels"])
            world_pts_0_np = np.float32(world_pts_0)
            H_prelim = cv2.getPerspectiveTransform(pixel_pts_0, world_pts_0_np)
            
            for idx, rect in enumerate(rectangles[1:], start=2):
                # Step 1: Compute this rectangle's exact local shape
                local_world = self._compute_rect_world_pts(
                    rect["pixels"], rect["side_lengths"], rect.get("diagonal"))
                if local_world is None:
                    print(f"Error: Failed to compute world coords for rectangle {idx}")
                    return False
                
                # Step 2: Project this rectangle's pixel center through H_prelim
                # to get approximate world position
                px_center = np.mean([p[0] for p in rect["pixels"]])
                py_center = np.mean([p[1] for p in rect["pixels"]])
                pt_center = np.float32([[[px_center, py_center]]])
                proj_center = cv2.perspectiveTransform(pt_center, H_prelim)
                world_cx = float(proj_center[0][0][0])
                world_cy = float(proj_center[0][0][1])
                
                # Step 3: Get approximate orientation by projecting P0→P1 direction
                p0_proj = cv2.perspectiveTransform(
                    np.float32([[[rect["pixels"][0][0], rect["pixels"][0][1]]]]), H_prelim)
                p1_proj = cv2.perspectiveTransform(
                    np.float32([[[rect["pixels"][1][0], rect["pixels"][1][1]]]]), H_prelim)
                proj_dx = float(p1_proj[0][0][0] - p0_proj[0][0][0])
                proj_dy = float(p1_proj[0][0][1] - p0_proj[0][0][1])
                proj_angle = math.atan2(proj_dy, proj_dx)
                
                # Local shape P0→P1 angle
                local_dx = local_world[1][0] - local_world[0][0]
                local_dy = local_world[1][1] - local_world[0][1]
                local_angle = math.atan2(local_dy, local_dx)
                
                # Rotation needed to align local shape with projected orientation
                rot = proj_angle - local_angle
                cos_r = math.cos(rot)
                sin_r = math.sin(rot)
                
                # Step 4: Rotate local shape and translate to projected center
                local_cx = np.mean([p[0] for p in local_world])
                local_cy = np.mean([p[1] for p in local_world])
                
                placed_world = []
                for lp in local_world:
                    # Center, rotate, translate
                    dx = lp[0] - local_cx
                    dy = lp[1] - local_cy
                    rx = dx * cos_r - dy * sin_r
                    ry = dx * sin_r + dy * cos_r
                    placed_world.append([rx + world_cx, ry + world_cy])
                
                print(f"[CALIBRATION] Rect {idx} exact shape placed at ({world_cx:.3f},{world_cy:.3f}), "
                      f"rot={math.degrees(rot):.1f}°")
                print(f"[CALIBRATION]   world: {[f'({p[0]:.3f},{p[1]:.3f})' for p in placed_world]}")
                
                # Verify side lengths
                for i in range(4):
                    j = (i + 1) % 4
                    dx_s = placed_world[j][0] - placed_world[i][0]
                    dy_s = placed_world[j][1] - placed_world[i][1]
                    computed = math.sqrt(dx_s * dx_s + dy_s * dy_s)
                    expected = rect["side_lengths"][i]
                    print(f"[CALIBRATION]   side {i+1}→{(i+1)%4+1}: expected={expected:.3f}m, got={computed:.3f}m")
                
                all_pixel_pts.extend(rect["pixels"])
                all_world_pts.extend(placed_world)
        
        print(f"[CALIBRATION] Total: {len(all_pixel_pts)} points from {len(rectangles)} rectangle(s)")
        
        # --- Build per-rectangle local homographies for weighted interpolation ---
        self.rect_homographies = []
        for i in range(len(rectangles)):
            start = i * 4
            px_pts = np.float32(all_pixel_pts[start:start+4])
            wd_pts = np.float32(all_world_pts[start:start+4])
            H_local = cv2.getPerspectiveTransform(px_pts, wd_pts)
            center_px = [float(np.mean(px_pts[:, 0])), float(np.mean(px_pts[:, 1]))]
            self.rect_homographies.append({
                "H": H_local,
                "center_px": center_px,
                "world_pts": [list(w) for w in wd_pts],
            })
            print(f"[CALIBRATION] Rect {i+1} local H built, center=({center_px[0]:.0f},{center_px[1]:.0f})")
        
        # Build global calibration points and compute global homography (fallback + world_to_pixel)
        points = [
            {"pixel": list(all_pixel_pts[i]), "world": all_world_pts[i]}
            for i in range(len(all_pixel_pts))
        ]
        return self.set_calibration_points(points)
    
    def _compute_transform(self):
        """Compute the perspective transformation matrix.
        4 points: exact (getPerspectiveTransform).
        5+ points: least-squares best-fit (findHomography)."""
        try:
            # Extract pixel and world points
            pixel_pts = np.float32([p["pixel"] for p in self.calibration_points])
            world_pts = np.float32([p["world"] for p in self.calibration_points])
            
            if len(self.calibration_points) == 4:
                # Exact: 4 points determine the homography uniquely
                self.transform_matrix = cv2.getPerspectiveTransform(pixel_pts, world_pts)
                self.inverse_matrix = cv2.getPerspectiveTransform(world_pts, pixel_pts)
            else:
                # Least-squares: 5+ points, best-fit homography
                self.transform_matrix, _ = cv2.findHomography(pixel_pts, world_pts, method=0)
                self.inverse_matrix, _ = cv2.findHomography(world_pts, pixel_pts, method=0)
                if self.transform_matrix is None or self.inverse_matrix is None:
                    print("Error: findHomography failed")
                    self.is_calibrated = False
                    return False
                print(f"[CALIBRATION] findHomography with {len(self.calibration_points)} points")
            
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
        
        Uses the nearest rectangle's local homography (Voronoi regions).
        Each rectangle's homography is exact for its 4 corners, and accurate
        for nearby pixels. The nearest rectangle gives the best result because
        its homography captures the local perspective and distortion.
        
        Falls back to the global homography if no per-rectangle data.
        
        Args:
            pixel_x: X coordinate in pixels
            pixel_y: Y coordinate in pixels
            
        Returns:
            tuple: (world_x, world_y) in meters, or None if not calibrated
        """
        if not self.is_calibrated:
            return None
        
        try:
            point = np.float32([[[pixel_x, pixel_y]]])
            
            # Use nearest rectangle's homography
            if self.rect_homographies and len(self.rect_homographies) > 0:
                # Find the nearest rectangle by distance to center
                best_idx = 0
                best_dist = float('inf')
                for i, rh in enumerate(self.rect_homographies):
                    dx = pixel_x - rh["center_px"][0]
                    dy = pixel_y - rh["center_px"][1]
                    dist = dx * dx + dy * dy
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = i
                
                transformed = cv2.perspectiveTransform(point, self.rect_homographies[best_idx]["H"])
                return (float(transformed[0][0][0]), float(transformed[0][0][1]))
            
            # Fallback: global homography
            if self.transform_matrix is not None:
                transformed = cv2.perspectiveTransform(point, self.transform_matrix)
                return (float(transformed[0][0][0]), float(transformed[0][0][1]))
            
            return None
            
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
    
    def clear(self):
        """Clear calibration."""
        self.calibration_points = []
        self.transform_matrix = None
        self.inverse_matrix = None
        self.is_calibrated = False
        self.rectangles = []
        self.rect_homographies = []
        self.pixels_undistorted = True
        
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
                "is_calibrated": self.is_calibrated,
                "rectangles": self.rectangles,
                "pixels_undistorted": self.pixels_undistorted
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
            if len(points) >= 4:
                self.calibration_points = points
                self._compute_transform()
                self.world_bounds = data.get("world_bounds", self.world_bounds)
                self.rectangles = data.get("rectangles", [])
                self.pixels_undistorted = data.get("pixels_undistorted", True)
                
                # Rebuild per-rectangle local homographies from saved calibration points
                n_rects = len(self.rectangles)
                if n_rects > 0 and len(points) >= n_rects * 4:
                    self.rect_homographies = []
                    for i in range(n_rects):
                        start = i * 4
                        px_pts = np.float32([p["pixel"] for p in points[start:start+4]])
                        wd_pts = np.float32([p["world"] for p in points[start:start+4]])
                        H_local = cv2.getPerspectiveTransform(px_pts, wd_pts)
                        center_px = [float(np.mean(px_pts[:, 0])), float(np.mean(px_pts[:, 1]))]
                        self.rect_homographies.append({"H": H_local, "center_px": center_px})
                    print(f"  Rebuilt {len(self.rect_homographies)} local homographies")
                
                print(f"Calibration loaded from {self.calibration_file} ({len(points)} points, {n_rects} rects)")
            else:
                print(f"Invalid calibration file - need at least 4 points, got {len(points)}")
                
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
            "world_bounds": self.world_bounds,
            "rectangles": self.rectangles,
            "pixels_undistorted": self.pixels_undistorted
        }
