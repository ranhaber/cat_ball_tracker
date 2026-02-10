"""
Lens Distortion Calibration (Plumb-Line Method)

The user marks 3+ points on each of several straight lines visible in the
camera image.  The optimizer finds distortion coefficients (k1, k2, k3, p1, p2)
and the camera matrix (f, cx, cy) that make those points as collinear as
possible after undistortion.

Uses OpenCV's standard distortion model (polynomial in r) which is suitable for
rectilinear wide-angle lenses like the RPi Camera Module 3 Wide (120° diagonal FOV).
k1 is constrained negative for barrel distortion.

Results are saved to lens_calibration.json and loaded automatically on startup.
pixel_to_world() uses these to undistort points before the homography.
"""

import json
import os
import numpy as np
import cv2
from scipy.optimize import least_squares

import config


class LensCalibration:
    """Estimates and applies radial lens distortion correction."""

    DEFAULT_FILE = "lens_calibration.json"

    def __init__(self, calibration_file=None):
        self.calibration_file = os.path.join(
            config.BASE_DIR,
            calibration_file or self.DEFAULT_FILE,
        )
        # Distortion coefficients  (k1, k2, p1, p2, k3)
        self.dist_coeffs = None          # np.array shape (1,5)
        # Camera matrix (estimated: square pixels, principal point at centre)
        self.camera_matrix = None        # np.array shape (3,3)
        # The lines used for calibration (for display / recalibration)
        self.lines = []                  # list of lists of [x, y]
        # Image resolution at calibration time
        self.image_width = 0
        self.image_height = 0
        self.is_calibrated = False
        self.model_type = "fisheye"  # "fisheye" or "standard" (legacy)
        # Optimal camera matrix and crop ROI for undistortion
        self.optimal_camera_matrix = None
        self.undistort_roi = None
        # Quality stats (saved for display on reload)
        self.overall_before_mean_px = 0.0
        self.overall_after_mean_px = 0.0
        self.overall_improvement_pct = 0.0
        # Progress tracking (for UI polling during calibration)
        self.calibration_in_progress = False
        self.calibration_iteration = 0
        self.calibration_max_iterations = 2000

        if os.path.exists(self.calibration_file):
            self.load()
        # Also load lines file (may have lines without calibration yet)
        self.load_lines_file()

    # ------------------------------------------------------------------
    # Core: plumb-line optimisation
    # ------------------------------------------------------------------

    def calibrate(self, lines, image_width, image_height):
        """
        Run the plumb-line calibration using the OpenCV standard distortion model.

        Standard model: x_d = x(1 + k1·r² + k2·r⁴ + k3·r⁶) + tangential(p1,p2)
        Suitable for rectilinear wide-angle lenses (like RPi Camera Module 3 Wide).

        Optimises 8 parameters jointly using Trust Region Reflective:
          - f       (focal length in pixels, square pixels)
          - cx, cy  (principal point)
          - k1, k2, k3  (radial distortion, k1 constrained negative for barrel)
          - p1, p2  (tangential distortion, small bounds)

        Args:
            lines: list of lines, each line is a list of [x, y] pixel coords
                   (minimum 3 points per line, minimum 2 lines).
            image_width:  image width in pixels at calibration resolution.
            image_height: image height in pixels at calibration resolution.

        Returns:
            dict with calibration results or raises ValueError.
        """
        # Validate
        if len(lines) < 2:
            raise ValueError("Need at least 2 lines for calibration")
        for i, line in enumerate(lines):
            if len(line) < 3:
                raise ValueError(f"Line {i+1} needs at least 3 points (has {len(line)})")

        self.image_width = image_width
        self.image_height = image_height
        self.lines = [[[float(p[0]), float(p[1])] for p in line] for line in lines]

        cx0 = image_width / 2.0
        cy0 = image_height / 2.0

        # Initial focal length estimate from 102° horizontal FOV
        f0 = (image_width / 2.0) / np.tan(np.radians(102.0 / 2.0))

        # Flatten all points and build per-line index masks
        all_points = []
        line_masks = []
        idx = 0
        for line in self.lines:
            mask = []
            for pt in line:
                all_points.append(pt)
                mask.append(idx)
                idx += 1
            line_masks.append(mask)
        all_points = np.array(all_points, dtype=np.float64)

        def _undistort(params):
            """Undistort all points with rational model. Returns (N,2) array."""
            f, cx, cy, k1, k2, p1, p2, k3, k4, k5, k6 = params
            cam = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=np.float64)
            dist = np.array([[k1, k2, p1, p2, k3, k4, k5, k6]], dtype=np.float64)
            pts = all_points.reshape(-1, 1, 2)
            out = cv2.undistortPoints(pts, cam, dist, P=cam)
            return out.reshape(-1, 2), cam, dist

        def _line_distances(undist_pts, mask):
            """Signed distance of each point from the best-fit line (SVD)."""
            lpts = undist_pts[mask]
            A = np.column_stack([lpts, np.ones(len(lpts))])
            _, _, Vt = np.linalg.svd(A)
            abc = Vt[-1]
            norm = np.sqrt(abc[0]**2 + abc[1]**2)
            if norm < 1e-12:
                return np.zeros(len(lpts))
            return (A @ abc) / norm

        eval_count = [0]
        best_result = [None, np.inf]  # [params, cost]
        prev_cost = [np.inf]  # for tracking convergence direction

        def residuals(params):
            """Residual vector: signed distance-to-line for every point."""
            eval_count[0] += 1
            self.calibration_iteration = eval_count[0]
            try:
                undist_pts, _, _ = _undistort(params)
            except cv2.error:
                return np.full(len(all_points), 1e6)
            res = []
            for mask in line_masks:
                res.append(_line_distances(undist_pts, mask))
            r = np.concatenate(res)
            cost = float(np.sum(r**2))
            if cost < best_result[1]:
                best_result[0] = params.copy()
                best_result[1] = cost
            if eval_count[0] % 200 == 0:
                direction = "converging" if cost <= prev_cost[0] else "DIVERGING"
                print(f"[LENS] Iter {eval_count[0]}/{self.calibration_max_iterations} "
                      f"| cost={cost:.2f} (best={best_result[1]:.2f}) | {direction} "
                      f"| f={params[0]:.1f} cx={params[1]:.1f} cy={params[2]:.1f} "
                      f"| k1={params[3]:.6f} k2={params[4]:.6f} k3={params[7]:.6f} "
                      f"| k4={params[8]:.6f} k5={params[9]:.6f} k6={params[10]:.6f}",
                      flush=True)
                prev_cost[0] = cost
            return r

        # 11 parameters: f, cx, cy, k1, k2, p1, p2, k3, k4, k5, k6
        # Rational model: r_d = r*(1+k1*r²+k2*r⁴+k3*r⁶) / (1+k4*r²+k5*r⁴+k6*r⁶)
        # Better for wide-angle lenses (120° FOV) than standard polynomial.
        x0 = np.array([f0, cx0, cy0, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        lower = [200, cx0 - image_width * 0.2, cy0 - image_height * 0.2,
                 -5.0, -5.0, -0.1, -0.1, -5.0, -5.0, -5.0, -5.0]
        upper = [3000, cx0 + image_width * 0.2, cy0 + image_height * 0.2,
                 5.0, 5.0, 0.1, 0.1, 5.0, 5.0, 5.0, 5.0]

        # Scale max iterations with number of lines (more data = may need more iterations)
        self.calibration_max_iterations = max(5000, len(self.lines) * 500)
        self.calibration_iteration = 0
        self.calibration_in_progress = True
        print(f"[LENS] Starting optimizer: {len(self.lines)} lines, "
              f"{sum(len(l) for l in self.lines)} points, {image_width}x{image_height}, "
              f"max_nfev={self.calibration_max_iterations}")
        print(f"[LENS] Initial: f={f0:.1f}, cx={cx0:.1f}, cy={cy0:.1f}")
        try:
            result = least_squares(residuals, x0, method='trf',
                                   bounds=(lower, upper),
                                   max_nfev=self.calibration_max_iterations,
                                   xtol=1e-12, ftol=1e-12)
        finally:
            self.calibration_in_progress = False
        # Use best result found (in case optimizer overshot)
        if best_result[0] is not None and best_result[1] < result.cost:
            f_opt, cx_opt, cy_opt, k1, k2, p1, p2, k3, k4, k5, k6 = best_result[0]
        else:
            f_opt, cx_opt, cy_opt, k1, k2, p1, p2, k3, k4, k5, k6 = result.x
        print(f"[LENS] Optimizer done: {eval_count[0]} evaluations, cost={result.cost:.4f}")

        self.camera_matrix = np.array([
            [f_opt,  0, cx_opt],
            [    0, f_opt, cy_opt],
            [    0,  0,  1]
        ], dtype=np.float64)
        # Rational dist_coeffs: [k1, k2, p1, p2, k3, k4, k5, k6]
        self.dist_coeffs = np.array([[k1, k2, p1, p2, k3, k4, k5, k6]], dtype=np.float64)
        self.is_calibrated = True
        self.model_type = "rational"
        self._compute_optimal_matrix()

        # ---- Compute before/after stats ----
        line_errors = []
        raw_pts = all_points  # before = raw pixels
        best_params = best_result[0] if best_result[0] is not None and best_result[1] < result.cost else result.x
        undist, _, _ = _undistort(best_params)  # after = undistorted

        total_before = 0.0
        total_after = 0.0
        total_points = 0

        for li, mask in enumerate(line_masks):
            n_pts = len(mask)
            dist_before = np.abs(_line_distances(raw_pts, mask))
            dist_after = np.abs(_line_distances(undist, mask))

            mean_before = float(np.mean(dist_before))
            mean_after = float(np.mean(dist_after))
            improvement = round((1.0 - mean_after / mean_before) * 100, 1) if mean_before > 1e-6 else 100.0

            total_before += np.sum(dist_before)
            total_after += np.sum(dist_after)
            total_points += n_pts

            line_errors.append({
                "line": li + 1,
                "points": n_pts,
                "before_mean_px": round(mean_before, 2),
                "after_mean_px": round(mean_after, 2),
                "after_max_px": round(float(np.max(dist_after)), 2),
                "improvement_pct": improvement,
            })

        overall_before = total_before / total_points if total_points > 0 else 0
        overall_after = total_after / total_points if total_points > 0 else 0
        overall_improvement = round((1.0 - overall_after / overall_before) * 100, 1) if overall_before > 1e-6 else 100.0

        self.overall_before_mean_px = round(overall_before, 2)
        self.overall_after_mean_px = round(overall_after, 2)
        self.overall_improvement_pct = overall_improvement
        self.save()

        print(f"[LENS] Calibration done (rational 11-param): f={f_opt:.1f}, "
              f"cx={cx_opt:.1f}, cy={cy_opt:.1f}, "
              f"k1={k1:.6f}, k2={k2:.6f}, k3={k3:.6f}, "
              f"k4={k4:.6f}, k5={k5:.6f}, k6={k6:.6f}, "
              f"p1={p1:.6f}, p2={p2:.6f}")
        print(f"[LENS] Overall: before={overall_before:.2f}px, after={overall_after:.2f}px, "
              f"improvement={overall_improvement}%")

        return {
            "model": "rational",
            "k1": round(k1, 8),
            "k2": round(k2, 8),
            "k3": round(k3, 8),
            "k4": round(k4, 8),
            "k5": round(k5, 8),
            "k6": round(k6, 8),
            "p1": round(p1, 8),
            "p2": round(p2, 8),
            "fx": round(f_opt, 2),
            "fy": round(f_opt, 2),
            "cx": round(cx_opt, 2),
            "cy": round(cy_opt, 2),
            "line_errors": line_errors,
            "overall_before_mean_px": round(overall_before, 2),
            "overall_after_mean_px": round(overall_after, 2),
            "overall_improvement_pct": overall_improvement,
        }

    # ------------------------------------------------------------------
    # Apply: undistort a single pixel coordinate
    # ------------------------------------------------------------------

    def _compute_optimal_matrix(self):
        """Compute optimal camera matrix that balances FOV retention vs black borders."""
        if self.camera_matrix is not None and self.image_width > 0 and self.image_height > 0:
            self.optimal_camera_matrix, self.undistort_roi = cv2.getOptimalNewCameraMatrix(
                self.camera_matrix, self.dist_coeffs,
                (self.image_width, self.image_height),
                alpha=1.0,  # 1.0 = retain all source pixels (may have black corners)
                newImgSize=(self.image_width, self.image_height))
            rx, ry, rw, rh = self.undistort_roi
            print(f"[LENS] Optimal camera matrix computed (alpha=1.0, crop ROI={rx},{ry},{rw}x{rh})")
        else:
            self.optimal_camera_matrix = self.camera_matrix
            self.undistort_roi = (0, 0, self.image_width, self.image_height)
    
    def undistort_point(self, px, py):
        """Undistort a single pixel coordinate. Returns (ux, uy).
        Uses optimal camera matrix and subtracts ROI offset so coordinates
        match the cropped undistorted frame."""
        if not self.is_calibrated:
            return (px, py)
        P = self.optimal_camera_matrix if self.optimal_camera_matrix is not None else self.camera_matrix
        pt = np.array([[[px, py]]], dtype=np.float64)
        out = cv2.undistortPoints(pt, self.camera_matrix, self.dist_coeffs, P=P)
        ux, uy = float(out[0, 0, 0]), float(out[0, 0, 1])
        # Subtract ROI offset to match cropped frame coordinates
        if self.undistort_roi:
            ux -= self.undistort_roi[0]
            uy -= self.undistort_roi[1]
        return (ux, uy)
    
    def redistort_point(self, ux, uy):
        """Convert undistorted+cropped pixel back to raw (distorted) pixel.
        Inverse of undistort_point(). Returns (raw_x, raw_y)."""
        if not self.is_calibrated:
            return (ux, uy)
        
        # Step 1: Add ROI offset to get undistorted (full image) coords
        if self.undistort_roi:
            ux_full = ux + self.undistort_roi[0]
            uy_full = uy + self.undistort_roi[1]
        else:
            ux_full, uy_full = ux, uy
        
        # Step 2: Convert from pixel to normalized coords using optimal camera matrix
        P = self.optimal_camera_matrix if self.optimal_camera_matrix is not None else self.camera_matrix
        fx, fy = P[0, 0], P[1, 1]
        cx, cy = P[0, 2], P[1, 2]
        xn = (ux_full - cx) / fx
        yn = (uy_full - cy) / fy
        
        # Step 3: Apply distortion model (rational) to get distorted normalized coords
        r2 = xn * xn + yn * yn
        dc = self.dist_coeffs.flatten()
        k1, k2 = dc[0], dc[1]
        p1 = dc[2] if len(dc) > 2 else 0
        p2 = dc[3] if len(dc) > 3 else 0
        k3 = dc[4] if len(dc) > 4 else 0
        k4 = dc[5] if len(dc) > 5 else 0
        k5 = dc[6] if len(dc) > 6 else 0
        k6 = dc[7] if len(dc) > 7 else 0
        
        # Rational model: numerator / denominator
        numer = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2
        denom = 1.0 + k4 * r2 + k5 * r2 * r2 + k6 * r2 * r2 * r2
        radial = numer / denom if abs(denom) > 1e-10 else numer
        xd = xn * radial + 2 * p1 * xn * yn + p2 * (r2 + 2 * xn * xn)
        yd = yn * radial + p1 * (r2 + 2 * yn * yn) + 2 * p2 * xn * yn
        
        # Step 4: Convert back to raw pixel coords using original camera matrix
        fx_orig, fy_orig = self.camera_matrix[0, 0], self.camera_matrix[1, 1]
        cx_orig, cy_orig = self.camera_matrix[0, 2], self.camera_matrix[1, 2]
        raw_x = xd * fx_orig + cx_orig
        raw_y = yd * fy_orig + cy_orig
        
        return (float(raw_x), float(raw_y))
    
    def undistort_frame(self, frame):
        """Undistort an entire image frame and crop to clean rectangle.
        No black borders — edges are cropped to the valid region."""
        if not self.is_calibrated:
            return frame
        new_cam = self.optimal_camera_matrix if self.optimal_camera_matrix is not None else self.camera_matrix
        undistorted = cv2.undistort(frame, self.camera_matrix, self.dist_coeffs, None, new_cam)
        # Crop to ROI (remove any remaining black borders)
        if self.undistort_roi:
            rx, ry, rw, rh = self.undistort_roi
            if rw > 0 and rh > 0:
                undistorted = undistorted[ry:ry+rh, rx:rx+rw]
        return undistorted

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        # Rational dist_coeffs: [k1, k2, p1, p2, k3, k4, k5, k6]
        dc = self.dist_coeffs.flatten()
        data = {
            "model_type": self.model_type,
            "k1": float(dc[0]),
            "k2": float(dc[1]),
            "p1": float(dc[2]) if len(dc) > 2 else 0.0,
            "p2": float(dc[3]) if len(dc) > 3 else 0.0,
            "k3": float(dc[4]) if len(dc) > 4 else 0.0,
            "k4": float(dc[5]) if len(dc) > 5 else 0.0,
            "k5": float(dc[6]) if len(dc) > 6 else 0.0,
            "k6": float(dc[7]) if len(dc) > 7 else 0.0,
            "camera_matrix": self.camera_matrix.tolist(),
            "image_width": self.image_width,
            "image_height": self.image_height,
            "lines": self.lines,
            "is_calibrated": self.is_calibrated,
            "overall_before_mean_px": self.overall_before_mean_px,
            "overall_after_mean_px": self.overall_after_mean_px,
            "overall_improvement_pct": self.overall_improvement_pct,
        }
        with open(self.calibration_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"[LENS] Saved to {self.calibration_file}")

    def load(self):
        try:
            with open(self.calibration_file, 'r') as f:
                data = json.load(f)
            self.camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
            self.model_type = data.get("model_type", "rational")
            k1 = data.get("k1", 0)
            k2 = data.get("k2", 0)
            p1 = data.get("p1", 0)
            p2 = data.get("p2", 0)
            k3 = data.get("k3", 0)
            k4 = data.get("k4", 0)
            k5 = data.get("k5", 0)
            k6 = data.get("k6", 0)
            self.dist_coeffs = np.array([[k1, k2, p1, p2, k3, k4, k5, k6]], dtype=np.float64)
            self.image_width = data.get("image_width", 0)
            self.image_height = data.get("image_height", 0)
            self.lines = data.get("lines", [])
            self.is_calibrated = data.get("is_calibrated", False)
            self.overall_before_mean_px = data.get("overall_before_mean_px", 0.0)
            self.overall_after_mean_px = data.get("overall_after_mean_px", 0.0)
            self.overall_improvement_pct = data.get("overall_improvement_pct", 0.0)
            if self.is_calibrated:
                self._compute_optimal_matrix()
                f = self.camera_matrix[0, 0]
                print(f"[LENS] Loaded: f={f:.1f}, "
                      f"k1={k1:.6f}, k2={k2:.6f}, k3={k3:.6f}, "
                      f"k4={k4:.6f}, k5={k5:.6f}, k6={k6:.6f}, "
                      f"p1={p1:.6f}, p2={p2:.6f}, "
                      f"{self.image_width}x{self.image_height}")
        except Exception as e:
            print(f"[LENS] Error loading {self.calibration_file}: {e}")
            self.is_calibrated = False

    LINES_FILE = "lens_lines_data.json"

    def _lines_path(self):
        return os.path.join(config.BASE_DIR, self.LINES_FILE)

    def _save_lines_file(self):
        """Save current lines to the persistent lines file."""
        data = {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "lines": self.lines,
        }
        with open(self._lines_path(), 'w') as f:
            json.dump(data, f, indent=2)

    def load_lines_file(self):
        """Load lines from the persistent file. Returns line count or 0."""
        path = self._lines_path()
        if not os.path.exists(path):
            return 0
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self.lines = data.get("lines", [])
            self.image_width = data.get("image_width", self.image_width)
            self.image_height = data.get("image_height", self.image_height)
            if self.lines:
                print(f"[LENS] Loaded {len(self.lines)} lines from {self.LINES_FILE}")
            return len(self.lines)
        except Exception as e:
            print(f"[LENS] Error loading {self.LINES_FILE}: {e}")
            return 0

    def append_line(self, points, image_width=0, image_height=0):
        """Append a single line (list of [x,y]) and auto-save to file.
        Returns updated line count."""
        pts = [[float(p[0]), float(p[1])] for p in points]
        if len(pts) < 3:
            raise ValueError(f"Line needs at least 3 points (has {len(pts)})")
        if image_width > 0:
            self.image_width = image_width
        if image_height > 0:
            self.image_height = image_height
        self.lines.append(pts)
        self._save_lines_file()
        return len(self.lines)

    def delete_line(self, line_number):
        """Delete a specific line by number (1-based). Saves updated file."""
        idx = line_number - 1
        if idx < 0 or idx >= len(self.lines):
            raise ValueError(f"Line {line_number} does not exist (have {len(self.lines)} lines)")
        removed = self.lines.pop(idx)
        self._save_lines_file()
        print(f"[LENS] Deleted line {line_number} ({len(removed)} points). {len(self.lines)} lines remaining.")
        return len(self.lines)

    def delete_lines(self, line_numbers):
        """Delete multiple lines by number (1-based). Saves updated file."""
        # Sort descending so indices don't shift during removal
        for num in sorted(line_numbers, reverse=True):
            idx = num - 1
            if 0 <= idx < len(self.lines):
                removed = self.lines.pop(idx)
                print(f"[LENS] Deleted line {num} ({len(removed)} points)")
        self._save_lines_file()
        print(f"[LENS] {len(self.lines)} lines remaining.")
        return len(self.lines)

    def recover_lines_from_calibration(self):
        """Recover lines from lens_calibration.json if lines file was accidentally deleted.
        Reads directly from the file on disk, not from memory."""
        if not os.path.exists(self.calibration_file):
            return 0
        try:
            with open(self.calibration_file, 'r') as f:
                data = json.load(f)
            lines = data.get("lines", [])
            if lines and len(lines) > 0:
                self.lines = lines
                self.image_width = data.get("image_width", self.image_width)
                self.image_height = data.get("image_height", self.image_height)
                self._save_lines_file()
                print(f"[LENS] Recovered {len(self.lines)} lines from {self.calibration_file}")
                return len(self.lines)
        except Exception as e:
            print(f"[LENS] Recovery error: {e}")
        return 0

    def clear_lines(self):
        """Delete all lines and remove the lines file."""
        self.lines = []
        path = self._lines_path()
        if os.path.exists(path):
            os.remove(path)
            print(f"[LENS] Deleted {self.LINES_FILE}")

    def analyze_lines(self):
        """Analyze all lines and score them for calibration quality.
        
        Lines are scored by:
        - Distance from image center (edge/corner lines are more informative)
        - Length in pixels (longer lines reveal more distortion)
        - Number of points (more points = more data)
        - Curvature (deviation from straight = visible distortion signal)
        
        Returns list of per-line stats sorted by score (best first).
        """
        if not self.lines or not self.image_width or not self.image_height:
            return []
        
        cx = self.image_width / 2.0
        cy = self.image_height / 2.0
        max_r = np.sqrt(cx * cx + cy * cy)  # corner distance
        
        results = []
        for li, line in enumerate(self.lines):
            pts = np.array(line, dtype=np.float64)
            n = len(pts)
            
            # Centroid of the line
            centroid_x = np.mean(pts[:, 0])
            centroid_y = np.mean(pts[:, 1])
            
            # Average distance of points from image center (0 = center, 1 = corner)
            dists_from_center = np.sqrt((pts[:, 0] - cx)**2 + (pts[:, 1] - cy)**2)
            avg_dist_from_center = float(np.mean(dists_from_center))
            norm_dist = avg_dist_from_center / max_r  # 0-1
            
            # Max distance from center (any point reaching the edge is valuable)
            max_dist_from_center = float(np.max(dists_from_center))
            norm_max_dist = max_dist_from_center / max_r
            
            # Length of line (distance from first to last point)
            length_px = float(np.sqrt((pts[-1, 0] - pts[0, 0])**2 + (pts[-1, 1] - pts[0, 1])**2))
            norm_length = length_px / max_r  # normalize by max possible
            
            # Curvature: max deviation from the straight line fit
            A = np.column_stack([pts, np.ones(n)])
            _, _, Vt = np.linalg.svd(A)
            abc = Vt[-1]
            norm_abc = np.sqrt(abc[0]**2 + abc[1]**2)
            if norm_abc > 1e-12:
                distances = np.abs(A @ abc) / norm_abc
                max_deviation = float(np.max(distances))
                mean_deviation = float(np.mean(distances))
            else:
                max_deviation = 0.0
                mean_deviation = 0.0
            
            # Region classification
            rel_x = centroid_x / self.image_width
            rel_y = centroid_y / self.image_height
            if rel_x < 0.25:
                region_h = "left"
            elif rel_x > 0.75:
                region_h = "right"
            else:
                region_h = "center"
            if rel_y < 0.25:
                region_t = "top"
            elif rel_y > 0.75:
                region_t = "bottom"
            else:
                region_t = "middle"
            region = f"{region_t}-{region_h}"
            
            # Angle of line (0=horizontal, 90=vertical)
            dx = pts[-1, 0] - pts[0, 0]
            dy = pts[-1, 1] - pts[0, 1]
            angle = float(np.degrees(np.arctan2(abs(dy), abs(dx))))
            
            # Score: higher = more useful for calibration
            # Edge/corner lines with high curvature and length are best
            score = (norm_max_dist * 3.0 +     # reaching the edge is very valuable
                     norm_dist * 2.0 +          # being far from center is valuable
                     norm_length * 2.0 +        # longer lines are better
                     min(max_deviation / 5.0, 1.0) * 2.0 +  # visible curvature
                     min(n / 10.0, 1.0) * 1.0)  # more points helps
            
            results.append({
                "line": li + 1,
                "points": n,
                "region": region,
                "angle_deg": round(angle, 1),
                "length_px": round(length_px, 0),
                "avg_dist_from_center": round(avg_dist_from_center, 0),
                "max_dist_from_center": round(max_dist_from_center, 0),
                "curvature_max_px": round(max_deviation, 2),
                "curvature_mean_px": round(mean_deviation, 2),
                "score": round(score, 2),
            })
        
        # Sort by score (best first)
        results.sort(key=lambda x: x["score"], reverse=True)
        
        # Region coverage summary
        regions = set(r["region"] for r in results)
        angles = [r["angle_deg"] for r in results]
        has_horizontal = any(a < 30 for a in angles)
        has_vertical = any(a > 60 for a in angles)
        has_diagonal = any(30 <= a <= 60 for a in angles)
        
        return {
            "lines": results,
            "summary": {
                "total_lines": len(results),
                "total_points": sum(r["points"] for r in results),
                "regions_covered": sorted(list(regions)),
                "has_horizontal": has_horizontal,
                "has_vertical": has_vertical,
                "has_diagonal": has_diagonal,
                "avg_score": round(np.mean([r["score"] for r in results]), 2),
                "best_score": results[0]["score"] if results else 0,
                "worst_score": results[-1]["score"] if results else 0,
            }
        }

    def export_lines(self):
        """Export lines/points data as a dict (for download)."""
        return {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "lines": self.lines,
            "num_lines": len(self.lines),
            "total_points": sum(len(l) for l in self.lines),
        }

    def import_lines(self, data):
        """Import lines/points data from a dict. Replaces current lines and saves to file."""
        lines = data.get("lines", [])
        if not lines:
            raise ValueError("No lines found in file")
        for i, line in enumerate(lines):
            if len(line) < 3:
                raise ValueError(f"Line {i+1} has only {len(line)} points (need 3+)")
        self.lines = [[[float(p[0]), float(p[1])] for p in line] for line in lines]
        self.image_width = data.get("image_width", 0)
        self.image_height = data.get("image_height", 0)
        self._save_lines_file()
        return {
            "lines": self.lines,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "num_lines": len(self.lines),
            "total_points": sum(len(l) for l in self.lines),
        }

    def clear(self):
        """Remove calibration and delete both calibration and lines files."""
        self.dist_coeffs = None
        self.camera_matrix = None
        self.is_calibrated = False
        if os.path.exists(self.calibration_file):
            os.remove(self.calibration_file)
        self.clear_lines()
        print("[LENS] Calibration and lines cleared")

    def get_progress(self):
        """Return current calibration progress (for polling during calibration)."""
        return {
            "in_progress": self.calibration_in_progress,
            "iteration": self.calibration_iteration,
            "max_iterations": self.calibration_max_iterations,
        }

    def get_status(self):
        """Return calibration status for the UI."""
        if not self.is_calibrated:
            return {"is_calibrated": False}
        dc = self.dist_coeffs.flatten()
        return {
            "is_calibrated": True,
            "model": self.model_type,
            "k1": round(float(dc[0]), 8),
            "k2": round(float(dc[1]), 8),
            "p1": round(float(dc[2]), 8) if len(dc) > 2 else 0,
            "p2": round(float(dc[3]), 8) if len(dc) > 3 else 0,
            "k3": round(float(dc[4]), 8) if len(dc) > 4 else 0,
            "fx": round(float(self.camera_matrix[0, 0]), 2),
            "fy": round(float(self.camera_matrix[1, 1]), 2),
            "cx": round(float(self.camera_matrix[0, 2]), 2),
            "cy": round(float(self.camera_matrix[1, 2]), 2),
            "image_width": self.image_width,
            "image_height": self.image_height,
            "num_lines": len(self.lines),
            "total_points": sum(len(l) for l in self.lines),
            "overall_before_mean_px": self.overall_before_mean_px,
            "overall_after_mean_px": self.overall_after_mean_px,
            "overall_improvement_pct": self.overall_improvement_pct,
        }
