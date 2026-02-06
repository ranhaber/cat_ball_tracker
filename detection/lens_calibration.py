"""
Lens Distortion Calibration (Plumb-Line Method)

The user marks 3+ points on each of several straight lines visible in the
camera image.  The optimizer finds radial distortion coefficients (k1, k2)
that make those points as collinear as possible after undistortion.

Results are saved to lens_calibration.json and loaded automatically on startup.
pixel_to_world() uses these to undistort points before the homography.
"""

import json
import os
import numpy as np
import cv2
from scipy.optimize import minimize

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

        if os.path.exists(self.calibration_file):
            self.load()

    # ------------------------------------------------------------------
    # Core: plumb-line optimisation
    # ------------------------------------------------------------------

    def calibrate(self, lines, image_width, image_height):
        """
        Run the plumb-line calibration.

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

        cx = image_width / 2.0
        cy = image_height / 2.0
        # Estimate focal length from 102° horizontal FOV:
        #   FOV = 2 * atan(w/2 / fx)  =>  fx = (w/2) / tan(FOV/2)
        # For RPi Camera Module 3 Wide: ~102° horizontal
        fx = (image_width / 2.0) / np.tan(np.radians(102.0 / 2.0))
        fy = fx  # square pixels

        self.camera_matrix = np.array([
            [fx,  0, cx],
            [ 0, fy, cy],
            [ 0,  0,  1]
        ], dtype=np.float64)

        # Flatten all points for the optimizer
        all_points = []
        line_indices = []
        for li, line in enumerate(self.lines):
            for pt in line:
                all_points.append(pt)
                line_indices.append(li)
        all_points = np.array(all_points, dtype=np.float64)

        # Optimise k1, k2 (radial distortion)
        def cost(params):
            k1, k2 = params
            dist = np.array([[k1, k2, 0, 0, 0]], dtype=np.float64)
            pts = all_points.reshape(-1, 1, 2)
            undist = cv2.undistortPoints(pts, self.camera_matrix, dist,
                                        P=self.camera_matrix)
            undist = undist.reshape(-1, 2)
            total_err = 0.0
            for li in range(len(self.lines)):
                mask = [j for j, idx in enumerate(line_indices) if idx == li]
                if len(mask) < 3:
                    continue
                lpts = undist[mask]
                # Fit line (ax + by + c = 0) via SVD
                A = np.column_stack([lpts, np.ones(len(lpts))])
                _, _, Vt = np.linalg.svd(A)
                abc = Vt[-1]
                norm = np.sqrt(abc[0]**2 + abc[1]**2)
                if norm < 1e-12:
                    continue
                distances = np.abs(A @ abc) / norm
                total_err += np.sum(distances ** 2)
            return total_err

        result = minimize(cost, [0.0, 0.0], method='Nelder-Mead',
                          options={'maxiter': 5000, 'xatol': 1e-8, 'fatol': 1e-8})
        k1, k2 = result.x

        self.dist_coeffs = np.array([[k1, k2, 0, 0, 0]], dtype=np.float64)
        self.is_calibrated = True

        # Compute per-line residuals: BEFORE (no correction) and AFTER (with k1, k2)
        line_errors = []
        pts = all_points.reshape(-1, 1, 2)
        no_dist = np.array([[0, 0, 0, 0, 0]], dtype=np.float64)
        raw_pts = cv2.undistortPoints(pts, self.camera_matrix, no_dist,
                                      P=self.camera_matrix).reshape(-1, 2)
        undist = cv2.undistortPoints(pts, self.camera_matrix, self.dist_coeffs,
                                    P=self.camera_matrix).reshape(-1, 2)

        total_before = 0.0
        total_after = 0.0
        total_points = 0

        for li in range(len(self.lines)):
            mask = [j for j, idx in enumerate(line_indices) if idx == li]
            n_pts = len(mask)

            # Before (original pixels, no correction)
            rpts = raw_pts[mask]
            A_raw = np.column_stack([rpts, np.ones(n_pts)])
            _, _, Vt_raw = np.linalg.svd(A_raw)
            abc_raw = Vt_raw[-1]
            norm_raw = np.sqrt(abc_raw[0]**2 + abc_raw[1]**2)
            dist_before = np.abs(A_raw @ abc_raw) / norm_raw if norm_raw > 1e-12 else np.zeros(n_pts)

            # After (undistorted)
            lpts = undist[mask]
            A = np.column_stack([lpts, np.ones(n_pts)])
            _, _, Vt = np.linalg.svd(A)
            abc = Vt[-1]
            norm = np.sqrt(abc[0]**2 + abc[1]**2)
            dist_after = np.abs(A @ abc) / norm if norm > 1e-12 else np.zeros(n_pts)

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

        # Overall quality
        overall_before = total_before / total_points if total_points > 0 else 0
        overall_after = total_after / total_points if total_points > 0 else 0
        overall_improvement = round((1.0 - overall_after / overall_before) * 100, 1) if overall_before > 1e-6 else 100.0

        self.overall_before_mean_px = round(overall_before, 2)
        self.overall_after_mean_px = round(overall_after, 2)
        self.overall_improvement_pct = overall_improvement
        self.save()

        print(f"[LENS] Calibration done: k1={k1:.6f}, k2={k2:.6f}, "
              f"fx={fx:.1f}, fy={fy:.1f}, cx={cx:.1f}, cy={cy:.1f}")
        print(f"[LENS] Overall: before={overall_before:.2f}px, after={overall_after:.2f}px, "
              f"improvement={overall_improvement}%")

        return {
            "k1": round(k1, 8),
            "k2": round(k2, 8),
            "fx": round(fx, 2),
            "fy": round(fy, 2),
            "cx": round(cx, 2),
            "cy": round(cy, 2),
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
        data = {
            "k1": float(self.dist_coeffs[0, 0]),
            "k2": float(self.dist_coeffs[0, 1]),
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
            self.dist_coeffs = np.array([[k1, k2, 0, 0, 0]], dtype=np.float64)
            self.image_width = data.get("image_width", 0)
            self.image_height = data.get("image_height", 0)
            self.lines = data.get("lines", [])
            self.is_calibrated = data.get("is_calibrated", False)
            self.overall_before_mean_px = data.get("overall_before_mean_px", 0.0)
            self.overall_after_mean_px = data.get("overall_after_mean_px", 0.0)
            self.overall_improvement_pct = data.get("overall_improvement_pct", 0.0)
            if self.is_calibrated:
                print(f"[LENS] Loaded: k1={k1:.6f}, k2={k2:.6f}, "
                      f"{self.image_width}x{self.image_height}")
        except Exception as e:
            print(f"[LENS] Error loading {self.calibration_file}: {e}")
            self.is_calibrated = False

    def clear(self):
        """Remove calibration and delete file."""
        self.dist_coeffs = None
        self.camera_matrix = None
        self.lines = []
        self.is_calibrated = False
        if os.path.exists(self.calibration_file):
            os.remove(self.calibration_file)
        print("[LENS] Calibration cleared")

    def get_status(self):
        """Return calibration status for the UI."""
        if not self.is_calibrated:
            return {"is_calibrated": False}
        return {
            "is_calibrated": True,
            "k1": round(float(self.dist_coeffs[0, 0]), 8),
            "k2": round(float(self.dist_coeffs[0, 1]), 8),
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
