"""
Lens Distortion Calibration (Plumb-Line Method)

The user marks 3+ points on each of several straight lines visible in the
camera image.  The optimizer finds distortion coefficients (k1, k2, k3, p1, p2)
and the focal length that make those points as collinear as possible after
undistortion.

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
        Run the plumb-line calibration.

        Optimises 8 parameters jointly using Levenberg-Marquardt:
          - f       (focal length in pixels, square pixels)
          - cx, cy  (principal point, initialised at image centre)
          - k1, k2, k3  (radial distortion)
          - p1, p2  (tangential distortion)

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
        line_masks = []  # list of lists of indices into all_points
        idx = 0
        for line in self.lines:
            mask = []
            for pt in line:
                all_points.append(pt)
                mask.append(idx)
                idx += 1
            line_masks.append(mask)
        all_points = np.array(all_points, dtype=np.float64)
        n_lines = len(self.lines)

        def _undistort(params):
            """Undistort all points with given params. Returns (N,2) array."""
            f, cx, cy, k1, k2, k3, p1, p2 = params
            cam = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=np.float64)
            dist = np.array([[k1, k2, p1, p2, k3]], dtype=np.float64)
            pts = all_points.reshape(-1, 1, 2)
            out = cv2.undistortPoints(pts, cam, dist, P=cam)
            return out.reshape(-1, 2), cam, dist

        def _line_distances(undist_pts, mask):
            """Distance of each point from the best-fit line (SVD)."""
            lpts = undist_pts[mask]
            A = np.column_stack([lpts, np.ones(len(lpts))])
            _, _, Vt = np.linalg.svd(A)
            abc = Vt[-1]
            norm = np.sqrt(abc[0]**2 + abc[1]**2)
            if norm < 1e-12:
                return np.zeros(len(lpts))
            return (A @ abc) / norm   # signed distances (better for least_squares)

        eval_count = [0]  # mutable counter for closure

        def residuals(params):
            """Residual vector: signed distance-to-line for every point."""
            eval_count[0] += 1
            self.calibration_iteration = eval_count[0]
            if eval_count[0] % 100 == 0:
                print(f"[LENS] Iteration {eval_count[0]}/{self.calibration_max_iterations}", flush=True)
            undist_pts, _, _ = _undistort(params)
            res = []
            for mask in line_masks:
                res.append(_line_distances(undist_pts, mask))
            return np.concatenate(res)

        # 8-parameter optimisation: f, cx, cy, k1, k2, k3, p1, p2
        # Tolerances tuned for Pi Zero 2W: accurate enough without taking minutes
        x0 = np.array([f0, cx0, cy0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.calibration_max_iterations = 20000
        self.calibration_iteration = 0
        self.calibration_in_progress = True
        print(f"[LENS] Starting optimizer: {len(self.lines)} lines, "
              f"{sum(len(l) for l in self.lines)} points, {image_width}x{image_height}")
        try:
            result = least_squares(residuals, x0, method='lm',
                                   max_nfev=20000, xtol=1e-14, ftol=1e-14)
        finally:
            self.calibration_in_progress = False
        f_opt, cx_opt, cy_opt, k1, k2, k3, p1, p2 = result.x
        print(f"[LENS] Optimizer done: {eval_count[0]} evaluations, cost={result.cost:.4f}")

        self.camera_matrix = np.array([
            [f_opt,  0, cx_opt],
            [    0, f_opt, cy_opt],
            [    0,  0,  1]
        ], dtype=np.float64)
        self.dist_coeffs = np.array([[k1, k2, p1, p2, k3]], dtype=np.float64)
        self.is_calibrated = True

        # ---- Compute before/after stats ----
        line_errors = []
        # "Before" = original pixels (no correction)
        raw_pts = all_points  # no distortion applied = raw pixels
        # "After" = undistorted with optimised params
        undist, _, _ = _undistort(result.x)

        total_before = 0.0
        total_after = 0.0
        total_points = 0

        for li, mask in enumerate(line_masks):
            n_pts = len(mask)

            # Before
            dist_before = np.abs(_line_distances(raw_pts, mask))
            # After
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

        print(f"[LENS] Calibration done (8-param): f={f_opt:.1f}, "
              f"cx={cx_opt:.1f}, cy={cy_opt:.1f}, "
              f"k1={k1:.6f}, k2={k2:.6f}, k3={k3:.6f}, "
              f"p1={p1:.6f}, p2={p2:.6f}")
        print(f"[LENS] Overall: before={overall_before:.2f}px, after={overall_after:.2f}px, "
              f"improvement={overall_improvement}%")

        return {
            "k1": round(k1, 8),
            "k2": round(k2, 8),
            "k3": round(k3, 8),
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

    def undistort_point(self, px, py):
        """Undistort a single pixel coordinate.  Returns (ux, uy)."""
        if not self.is_calibrated:
            return (px, py)
        pt = np.array([[[px, py]]], dtype=np.float64)
        out = cv2.undistortPoints(pt, self.camera_matrix, self.dist_coeffs,
                                  P=self.camera_matrix)
        return (float(out[0, 0, 0]), float(out[0, 0, 1]))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        # dist_coeffs layout: [k1, k2, p1, p2, k3]
        dc = self.dist_coeffs[0]
        data = {
            "k1": float(dc[0]),
            "k2": float(dc[1]),
            "p1": float(dc[2]),
            "p2": float(dc[3]),
            "k3": float(dc[4]),
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
            k1 = data.get("k1", 0)
            k2 = data.get("k2", 0)
            p1 = data.get("p1", 0)
            p2 = data.get("p2", 0)
            k3 = data.get("k3", 0)
            self.dist_coeffs = np.array([[k1, k2, p1, p2, k3]], dtype=np.float64)
            self.image_width = data.get("image_width", 0)
            self.image_height = data.get("image_height", 0)
            self.lines = data.get("lines", [])
            self.is_calibrated = data.get("is_calibrated", False)
            self.overall_before_mean_px = data.get("overall_before_mean_px", 0.0)
            self.overall_after_mean_px = data.get("overall_after_mean_px", 0.0)
            self.overall_improvement_pct = data.get("overall_improvement_pct", 0.0)
            if self.is_calibrated:
                f = self.camera_matrix[0, 0]
                print(f"[LENS] Loaded: f={f:.1f}, k1={k1:.6f}, k2={k2:.6f}, "
                      f"k3={k3:.6f}, p1={p1:.6f}, p2={p2:.6f}, "
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

    def clear_lines(self):
        """Delete all lines and remove the lines file."""
        self.lines = []
        path = self._lines_path()
        if os.path.exists(path):
            os.remove(path)
            print(f"[LENS] Deleted {self.LINES_FILE}")

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
        dc = self.dist_coeffs[0]
        return {
            "is_calibrated": True,
            "k1": round(float(dc[0]), 8),
            "k2": round(float(dc[1]), 8),
            "p1": round(float(dc[2]), 8),
            "p2": round(float(dc[3]), 8),
            "k3": round(float(dc[4]), 8),
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
