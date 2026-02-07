#!/usr/bin/env python3
"""
Test for the plumb-line fisheye lens calibration optimizer.

Approach:
1. Define KNOWN fisheye distortion parameters (ground truth)
2. Create straight lines in undistorted space
3. DISTORT the points using the known parameters (simulate what the camera does)
4. Feed the distorted points to our optimizer
5. Verify: does the optimizer recover the original parameters?
6. Verify: after undistortion with recovered params, are lines straight again?

If this passes, the optimizer is correct.
"""

import numpy as np
import cv2
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fisheye_distort_points(points, camera_matrix, dist_coeffs):
    """
    Apply fisheye distortion to undistorted points.
    This simulates what the camera lens does to straight lines.
    
    points: (N, 2) array of undistorted pixel coordinates
    camera_matrix: 3x3 intrinsic matrix
    dist_coeffs: (4,1) fisheye distortion coefficients
    
    Returns: (N, 2) array of distorted pixel coordinates
    """
    fx = camera_matrix[0, 0]
    fy = camera_matrix[1, 1]
    cx = camera_matrix[0, 2]
    cy = camera_matrix[1, 2]
    k1, k2, k3, k4 = dist_coeffs.flatten()
    
    distorted = []
    for pt in points:
        # Pixel to normalized coordinates
        x = (pt[0] - cx) / fx
        y = (pt[1] - cy) / fy
        
        # Radius and angle
        r = np.sqrt(x * x + y * y)
        theta = np.arctan(r)  # angle from optical axis
        
        # Apply fisheye distortion: theta_d = theta * (1 + k1*theta^2 + k2*theta^4 + ...)
        theta2 = theta * theta
        theta_d = theta * (1 + k1 * theta2 + k2 * theta2**2 + k3 * theta2**3 + k4 * theta2**4)
        
        # Scale factor
        if r < 1e-12:
            scale = 1.0
        else:
            scale = theta_d / r
        
        # Distorted normalized coordinates
        xd = x * scale
        yd = y * scale
        
        # Back to pixel coordinates
        u = fx * xd + cx
        v = fy * yd + cy
        distorted.append([u, v])
    
    return np.array(distorted, dtype=np.float64)


def max_line_deviation(points):
    """Compute max deviation from best-fit line (SVD)."""
    A = np.column_stack([points, np.ones(len(points))])
    _, _, Vt = np.linalg.svd(A)
    abc = Vt[-1]
    norm = np.sqrt(abc[0]**2 + abc[1]**2)
    if norm < 1e-12:
        return 0.0
    distances = np.abs(A @ abc) / norm
    return float(np.max(distances))


def test_optimizer():
    """
    Test the fisheye plumb-line optimizer with synthetic data.
    """
    print("=" * 70)
    print("TEST: Fisheye Plumb-Line Optimizer Verification")
    print("=" * 70)
    
    # ---- Ground truth parameters ----
    image_width = 2304
    image_height = 1296
    
    # Realistic values for RPi Camera Module 3 Wide
    f_true = 850.0
    cx_true = 1152.0  # image center
    cy_true = 648.0
    k1_true = -0.05
    k2_true = 0.01
    k3_true = -0.002
    k4_true = 0.0003
    
    cam_true = np.array([[f_true, 0, cx_true],
                          [0, f_true, cy_true],
                          [0, 0, 1]], dtype=np.float64)
    dist_true = np.array([[k1_true], [k2_true], [k3_true], [k4_true]], dtype=np.float64)
    
    print(f"\nGround truth:")
    print(f"  f={f_true}, cx={cx_true}, cy={cy_true}")
    print(f"  k1={k1_true}, k2={k2_true}, k3={k3_true}, k4={k4_true}")
    
    # ---- Create straight lines in undistorted space ----
    lines_undistorted = []
    
    # Horizontal lines at different y positions
    for y in [100, 300, 500, 648, 800, 1000, 1196]:
        pts = [[x, y] for x in range(50, 2260, 100)]
        lines_undistorted.append(np.array(pts, dtype=np.float64))
    
    # Vertical lines at different x positions
    for x in [100, 400, 700, 1152, 1500, 1800, 2100]:
        pts = [[x, y] for y in range(50, 1250, 80)]
        lines_undistorted.append(np.array(pts, dtype=np.float64))
    
    # Diagonal lines
    for offset in [-300, 0, 300]:
        pts = [[200 + i * 80, 100 + i * 50 + offset] for i in range(25)
               if 0 <= 100 + i * 50 + offset <= 1296]
        if len(pts) >= 3:
            lines_undistorted.append(np.array(pts, dtype=np.float64))
    
    print(f"\nGenerated {len(lines_undistorted)} straight lines "
          f"({sum(len(l) for l in lines_undistorted)} points)")
    
    # ---- Verify lines ARE straight before distortion ----
    print("\nBefore distortion (should be ~0 px deviation):")
    for i, line in enumerate(lines_undistorted):
        dev = max_line_deviation(line)
        print(f"  Line {i+1}: max deviation = {dev:.4f} px")
        assert dev < 0.01, f"Line {i+1} not straight before distortion!"
    
    # ---- Apply fisheye distortion (simulate camera) ----
    lines_distorted = []
    for line in lines_undistorted:
        distorted = fisheye_distort_points(line, cam_true, dist_true)
        lines_distorted.append(distorted.tolist())
    
    print("\nAfter distortion (should show curvature):")
    for i, line in enumerate(lines_distorted):
        dev = max_line_deviation(np.array(line))
        print(f"  Line {i+1}: max deviation = {dev:.2f} px")
    
    total_distortion = sum(max_line_deviation(np.array(l)) for l in lines_distorted)
    assert total_distortion > 10, "Distortion too small -- test isn't meaningful"
    print(f"  Total distortion: {total_distortion:.2f} px")
    
    # ---- Run our optimizer on the distorted points ----
    print("\n" + "-" * 70)
    print("Running optimizer...")
    print("-" * 70)
    
    from detection.lens_calibration import LensCalibration
    
    cal = LensCalibration.__new__(LensCalibration)
    cal.dist_coeffs = None
    cal.camera_matrix = None
    cal.lines = []
    cal.image_width = 0
    cal.image_height = 0
    cal.is_calibrated = False
    cal.model_type = "fisheye"
    cal.overall_before_mean_px = 0.0
    cal.overall_after_mean_px = 0.0
    cal.overall_improvement_pct = 0.0
    cal.calibration_in_progress = False
    cal.calibration_iteration = 0
    cal.calibration_max_iterations = 20000
    cal.calibration_file = "/dev/null"  # don't save during test
    
    # Override save to avoid file I/O
    cal.save = lambda: None
    
    result = cal.calibrate(lines_distorted, image_width, image_height)
    
    # ---- Check results ----
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    f_opt = result["fx"]
    cx_opt = result["cx"]
    cy_opt = result["cy"]
    k1_opt = result["k1"]
    k2_opt = result["k2"]
    k3_opt = result["k3"]
    k4_opt = result["k4"]
    
    print(f"\n{'Parameter':<10} {'True':>12} {'Recovered':>12} {'Error':>12} {'Error%':>8}")
    print("-" * 56)
    for name, true_val, opt_val in [
        ("f", f_true, f_opt),
        ("cx", cx_true, cx_opt),
        ("cy", cy_true, cy_opt),
        ("k1", k1_true, k1_opt),
        ("k2", k2_true, k2_opt),
        ("k3", k3_true, k3_opt),
        ("k4", k4_true, k4_opt),
    ]:
        err = abs(opt_val - true_val)
        pct = abs(err / true_val * 100) if abs(true_val) > 1e-10 else 0
        print(f"{name:<10} {true_val:>12.6f} {opt_val:>12.6f} {err:>12.6f} {pct:>7.2f}%")
    
    # ---- Verify undistorted lines are straight ----
    print(f"\nOverall improvement: {result['overall_improvement_pct']}%")
    print(f"Before: {result['overall_before_mean_px']} px mean deviation")
    print(f"After:  {result['overall_after_mean_px']} px mean deviation")
    
    # Undistort with recovered params and check
    cam_opt = cal.camera_matrix
    dist_opt = cal.dist_coeffs
    
    print("\nAfter undistortion with recovered params:")
    max_residual = 0
    for i, line in enumerate(lines_distorted):
        pts = np.array(line, dtype=np.float64).reshape(-1, 1, 2)
        undist = cv2.fisheye.undistortPoints(pts, cam_opt, dist_opt, P=cam_opt)
        undist = undist.reshape(-1, 2)
        dev = max_line_deviation(undist)
        max_residual = max(max_residual, dev)
        if dev > 1.0:
            print(f"  Line {i+1}: max deviation = {dev:.4f} px  WARNING")
        else:
            print(f"  Line {i+1}: max deviation = {dev:.4f} px  OK")
    
    # ---- Final verdict ----
    print("\n" + "=" * 70)
    if max_residual < 1.0:
        print("PASSED: All lines straight after undistortion (< 1 px)")
        print(f"   Max residual: {max_residual:.4f} px")
    elif max_residual < 5.0:
        print(f"MARGINAL: Max residual = {max_residual:.2f} px (want < 1 px)")
    else:
        print(f"FAILED: Max residual = {max_residual:.2f} px (want < 1 px)")
    print("=" * 70)
    
    return max_residual < 1.0


if __name__ == "__main__":
    success = test_optimizer()
    sys.exit(0 if success else 1)
