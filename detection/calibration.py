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
        
        # Original user-entered side lengths (preserved for UI)
        self.user_side_lengths = []
        
        # Rectangle definitions (for multi-rectangle calibration)
        self.rectangles = []
        
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
        
        # Determine diagonal
        if diagonal is not None and float(diagonal) > 0:
            d02 = float(diagonal)
        else:
            is_rect = abs(L01 - L23) < tol and abs(L12 - L30) < tol
            if is_rect:
                d02 = math.sqrt(L01 * L01 + L12 * L12)
            else:
                d02 = None
        
        if d02 is not None:
            # Exact SSS triangles
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
        
        Rectangle 0: world coords computed exactly at origin.
        Rectangles 1+: pixel points projected through preliminary homography
        from rectangle 0 to get world positions.
        Final homography computed from ALL points (findHomography).
        
        Args:
            rectangles: List of dicts, each with:
                - "pixels": [[x,y], [x,y], [x,y], [x,y]]
                - "side_lengths": [L01, L12, L23, L30]
                - "diagonal": optional float
                
        Returns:
            bool: True if calibration successful
        """
        if not rectangles or len(rectangles) < 1:
            print("Error: Need at least 1 rectangle")
            return False
        
        # Store rectangles for save/load
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
            
            # Project remaining rectangles through preliminary H
            for idx, rect in enumerate(rectangles[1:], start=2):
                for px_pt in rect["pixels"]:
                    pt = np.float32([[[px_pt[0], px_pt[1]]]])
                    projected = cv2.perspectiveTransform(pt, H_prelim)
                    wx = float(projected[0][0][0])
                    wy = float(projected[0][0][1])
                    all_pixel_pts.append(px_pt)
                    all_world_pts.append([wx, wy])
                
                print(f"[CALIBRATION] Rect {idx} projected through H_prelim")
        
        print(f"[CALIBRATION] Total: {len(all_pixel_pts)} points from {len(rectangles)} rectangle(s)")
        
        # Build calibration points and compute homography
        points = [
            {"pixel": list(all_pixel_pts[i]), "world": all_world_pts[i]}
            for i in range(len(all_pixel_pts))
        ]
        return self.set_calibration_points(points)
    
    def set_calibration_from_side_lengths(self, points_pixel, side_lengths, diagonal=None):
        """
        Set calibration from N pixel points and N side lengths, optionally a diagonal.
        First point = origin (0, 0).  World axes: right = +X, up = +Y.

        For 4 points with a diagonal: exact shape via SSS triangles.
        For 4 points without diagonal: rectangles detected; others use heuristic.
        For 5+ points: world coords built as a chain (each point from previous + side length).

        Args:
            points_pixel: List of N [x, y] pixel coordinates (minimum 4).
            side_lengths: List of N lengths in meters (sides in order, last closes the polygon).
            diagonal: Optional float -- length of diagonal P0->P2 in meters (4 points only).

        Returns:
            bool: True if calibration successful
        """
        import math

        n = len(points_pixel)
        if n < 4 or len(side_lengths) != n:
            print(f"Error: Need at least 4 points and matching side lengths (got {n} points, {len(side_lengths)} sides)")
            return False

        lengths = [float(s) for s in side_lengths]
        if any(l <= 0 for l in lengths):
            print("Error: All side lengths must be positive")
            return False

        # Store original user-entered side lengths for UI restoration
        self.user_side_lengths = lengths.copy()

        # Pixel winding: cross product of P0P1 x P1P2 in image coords (y down).
        cross_px = ((points_pixel[1][0] - points_pixel[0][0]) *
                    (points_pixel[2][1] - points_pixel[1][1]) -
                    (points_pixel[1][1] - points_pixel[0][1]) *
                    (points_pixel[2][0] - points_pixel[1][0]))

        # Pixel directions for orientation (only signs used, not magnitudes)
        dx01 = float(points_pixel[1][0] - points_pixel[0][0])
        dy01 = float(points_pixel[1][1] - points_pixel[0][1])

        if n == 4:
            # ====== 4-POINT CALIBRATION ======
            L01, L12, L23, L30 = lengths

            tol = 0.01  # 1 cm

            # --- Determine diagonal d02 (P0->P2 distance) ---
            if diagonal is not None and float(diagonal) > 0:
                d02 = float(diagonal)
                print(f"[CALIBRATION] Diagonal P0->P2 = {d02:.3f} m (user-provided)")
            else:
                # Check for rectangle (opposite sides equal)
                is_rect = abs(L01 - L23) < tol and abs(L12 - L30) < tol
                if is_rect:
                    # Rectangle diagonal from Pythagoras
                    d02 = math.sqrt(L01 * L01 + L12 * L12)
                    print(f"[CALIBRATION] Rectangle detected ({L01}x{L12} m), diagonal = {d02:.3f} m")
                else:
                    d02 = None
                    print(f"[CALIBRATION] General quad ({L01},{L12},{L23},{L30} m), no diagonal provided -- using heuristic")

            if d02 is not None:
                # ====== EXACT: two SSS triangles (P0-P1-P2) and (P0-P2-P3) ======
                # Place P0 = (0,0), P1 = (L01, 0).
                # Triangle P0-P1-P2: sides L01, L12, d02.
                # Use law of cosines to find P2.
                cos_a = (L01 * L01 + d02 * d02 - L12 * L12) / (2.0 * L01 * d02) if L01 > 0 and d02 > 0 else 0
                cos_a = max(-1.0, min(1.0, cos_a))
                sin_a = math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
                # P2 at distance d02 from P0, at angle a from X-axis.
                # Two solutions: sin_a or -sin_a.  Pick based on pixel winding.
                # In image CW (cross_px > 0) with y-down → world CCW with y-up → P2.y > 0.
                # In image CCW (cross_px < 0) → world CW with y-up → P2.y < 0.
                # Image CW (y-down) = visual CW; world y-up: visual CW = negative y.
                # So: image CW (cross_px > 0) → world P2.y < 0; image CCW → P2.y > 0.
                if cross_px > 0:
                    p2y = -sin_a * d02
                else:
                    p2y = sin_a * d02
                p2x = cos_a * d02

                # Triangle P0-P2-P3: sides d02, L23, L30.  P0=(0,0), P2=(p2x,p2y).
                # P3 at distance L30 from P0 and L23 from P2.  Two-circle intersection.
                d = math.sqrt(p2x * p2x + p2y * p2y)  # should equal d02
                if d < 1e-10:
                    print("Error: P2 coincides with P0")
                    return False
                aa = (L30 * L30 - L23 * L23 + d * d) / (2.0 * d)
                hh_sq = L30 * L30 - aa * aa
                if hh_sq < -1e-6:
                    print(f"Error: Side lengths + diagonal cannot form closed quad")
                    return False
                hh = math.sqrt(max(0.0, hh_sq))
                ux, uy = p2x / d, p2y / d
                p3_a = [aa * ux + hh * (-uy), aa * uy + hh * ux]
                p3_b = [aa * ux - hh * (-uy), aa * uy - hh * ux]
                # Pick the P3 that keeps the same winding as P0,P1,P2.
                cross_a = (p2x - L01) * (p3_a[1] - p2y) - (p2y - 0) * (p3_a[0] - p2x)
                cross_01_12 = (L01 - 0) * (p2y - 0) - (0 - 0) * (p2x - L01)
                if cross_01_12 * cross_a >= 0:
                    p3 = p3_a
                else:
                    p3 = p3_b

                world_pts = [[0.0, 0.0], [L01, 0.0], [p2x, p2y], p3]

                # Rotate so that image-right ≈ +X and image-up ≈ +Y.
                # The layout above has P0→P1 along +X.  Check if that matches image direction.
                if abs(dx01) < abs(dy01):
                    # P0→P1 is mostly vertical in image, but we placed it on X-axis.
                    # Rotate the world 90° so P0→P1 aligns with Y-axis instead.
                    sy = -1.0 if dy01 >= 0 else 1.0  # image down = -Y
                    world_pts = [[-sy * p[1], sy * p[0]] for p in world_pts]
                else:
                    # P0→P1 is mostly horizontal.  Flip X if it goes left in image.
                    if dx01 < 0:
                        world_pts = [[-p[0], p[1]] for p in world_pts]

                print(f"[CALIBRATION] World points (exact): "
                      f"{[f'({p[0]:.3f},{p[1]:.3f})' for p in world_pts]}")

            else:
                # ====== HEURISTIC: no diagonal, non-rectangle ======
                # Use pixel directions to approximate.  Less accurate for oblique views.
                world_pts = [[0.0, 0.0]]
                for i in range(1, 4):
                    px_prev = points_pixel[i - 1]
                    px_curr = points_pixel[i]
                    ddx = float(px_curr[0] - px_prev[0])
                    ddy = float(px_curr[1] - px_prev[1])
                    length_px = math.sqrt(ddx * ddx + ddy * ddy)
                    if length_px < 1e-6:
                        print(f"Error: Points {i} and {i+1} are too close together")
                        return False
                    length_m = float(side_lengths[i - 1])
                    wx = world_pts[i - 1][0] + length_m * (ddx / length_px)
                    wy = world_pts[i - 1][1] - length_m * (ddy / length_px)
                    world_pts.append([wx, wy])

                print(f"[CALIBRATION] World points (heuristic): "
                      f"{[f'({p[0]:.3f},{p[1]:.3f})' for p in world_pts]}")

        else:
            # ====== N-POINT (5+): 4-point bootstrap + homography projection ======
            # Step 1: Use the first 4 points + their side lengths to compute exact
            #         world coords via the 4-point method (rectangle/SSS/heuristic).
            # Step 2: Compute a preliminary homography from these 4 points.
            # Step 3: Project remaining pixel points through this homography to get
            #         accurate world coordinates (perspective-correct).
            # Step 4: Compute final homography with all N points for best accuracy.
            #
            # This avoids the chain method which uses pixel directions (perspective-
            # distorted) and produces parallelograms instead of rectangles.

            # --- Step 1: Compute world coords for first 4 points ---
            L01, L12, L23, L30 = lengths[0], lengths[1], lengths[2], lengths[3]
            tol = 0.01

            # Diagonal for first 4 points
            if diagonal is not None and float(diagonal) > 0:
                d02 = float(diagonal)
                print(f"[CALIBRATION] Diagonal P0->P2 = {d02:.3f} m (user-provided)")
            else:
                is_rect = abs(L01 - L23) < tol and abs(L12 - L30) < tol
                if is_rect:
                    d02 = math.sqrt(L01 * L01 + L12 * L12)
                    print(f"[CALIBRATION] First 4 pts: rectangle ({L01}x{L12} m)")
                else:
                    d02 = None
                    print(f"[CALIBRATION] First 4 pts: general quad, no diagonal -- heuristic")

            if d02 is not None:
                # Exact SSS triangles for first 4 points
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
                    print("Error: P2 coincides with P0")
                    return False
                aa = (L30 * L30 - L23 * L23 + d * d) / (2.0 * d)
                hh_sq = L30 * L30 - aa * aa
                if hh_sq < -1e-6:
                    print(f"Error: Side lengths + diagonal cannot form closed quad")
                    return False
                hh = math.sqrt(max(0.0, hh_sq))
                ux, uy = p2x / d, p2y / d
                p3_a = [aa * ux + hh * (-uy), aa * uy + hh * ux]
                p3_b = [aa * ux - hh * (-uy), aa * uy - hh * ux]
                cross_a = (p2x - L01) * (p3_a[1] - p2y) - (p2y - 0) * (p3_a[0] - p2x)
                cross_01_12 = (L01 - 0) * (p2y - 0) - (0 - 0) * (p2x - L01)
                if cross_01_12 * cross_a >= 0:
                    p3 = p3_a
                else:
                    p3 = p3_b

                world_pts_4 = [[0.0, 0.0], [L01, 0.0], [p2x, p2y], p3]

                if abs(dx01) < abs(dy01):
                    sy = -1.0 if dy01 >= 0 else 1.0
                    world_pts_4 = [[-sy * p[1], sy * p[0]] for p in world_pts_4]
                else:
                    if dx01 < 0:
                        world_pts_4 = [[-p[0], p[1]] for p in world_pts_4]
            else:
                # Heuristic for first 4 points
                world_pts_4 = [[0.0, 0.0]]
                for i in range(1, 4):
                    px_prev = points_pixel[i - 1]
                    px_curr = points_pixel[i]
                    ddx = float(px_curr[0] - px_prev[0])
                    ddy = float(px_curr[1] - px_prev[1])
                    length_px = math.sqrt(ddx * ddx + ddy * ddy)
                    if length_px < 1e-6:
                        print(f"Error: Points {i} and {i+1} are too close together")
                        return False
                    length_m = float(lengths[i - 1])
                    wx = world_pts_4[i - 1][0] + length_m * (ddx / length_px)
                    wy = world_pts_4[i - 1][1] - length_m * (ddy / length_px)
                    world_pts_4.append([wx, wy])

            print(f"[CALIBRATION] Bootstrap 4-point world: "
                  f"{[f'({p[0]:.3f},{p[1]:.3f})' for p in world_pts_4]}")

            # --- Step 2: Compute preliminary homography from first 4 points ---
            pixel_pts_4 = np.float32([points_pixel[i] for i in range(4)])
            world_pts_4_np = np.float32(world_pts_4)
            H_prelim = cv2.getPerspectiveTransform(pixel_pts_4, world_pts_4_np)

            # --- Step 3: Project remaining pixel points through preliminary H ---
            world_pts = list(world_pts_4)
            for i in range(4, n):
                px_pt = np.float32([[[points_pixel[i][0], points_pixel[i][1]]]])
                projected = cv2.perspectiveTransform(px_pt, H_prelim)
                wx = float(projected[0][0][0])
                wy = float(projected[0][0][1])
                world_pts.append([wx, wy])

            print(f"[CALIBRATION] {n}-point world coords (bootstrap): "
                  f"{[f'({p[0]:.3f},{p[1]:.3f})' for p in world_pts]}")

            # Log computed side lengths vs user's for verification
            for i in range(n):
                j = (i + 1) % n
                dx_s = world_pts[j][0] - world_pts[i][0]
                dy_s = world_pts[j][1] - world_pts[i][1]
                computed = math.sqrt(dx_s * dx_s + dy_s * dy_s)
                print(f"[CALIBRATION]   Side {i+1}→{j+1}: user={lengths[i]:.3f}m, computed={computed:.3f}m")

        points = [
            {"pixel": list(points_pixel[i]), "world": world_pts[i]}
            for i in range(n)
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
        Returns list of N lengths or empty list if not calibrated.
        """
        if not self.calibration_points or len(self.calibration_points) < 4:
            return []
        pts = [p["world"] for p in self.calibration_points]
        n = len(pts)
        lengths = []
        for i in range(n):
            j = (i + 1) % n
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
        self.user_side_lengths = []
        self.rectangles = []
        
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
                "user_side_lengths": self.user_side_lengths,
                "rectangles": self.rectangles
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
                self.user_side_lengths = data.get("user_side_lengths", [])
                self.rectangles = data.get("rectangles", [])
                print(f"Calibration loaded from {self.calibration_file} ({len(points)} points, {len(self.rectangles)} rects)")
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
            "user_side_lengths": self.user_side_lengths,
            "rectangles": self.rectangles
        }
