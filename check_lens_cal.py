"""Check lens calibration quality: measure line straightness before/after undistortion."""
import json
import numpy as np
import cv2

# Load lines
with open(r"C:\Users\rahaber\Downloads\lens_lines.json", "r") as f:
    lines_data = json.load(f)

lines = lines_data["lines"]
image_width = lines_data["image_width"]
image_height = lines_data["image_height"]
print(f"Image: {image_width}x{image_height}")
print(f"Lines: {len(lines)} ({sum(len(l) for l in lines)} points total)")
print()

def measure_straightness(points_list, camera_matrix=None, dist_coeffs=None, label=""):
    """Measure how straight each line is. Returns per-line and overall stats."""
    all_before = []
    all_after = []
    
    for i, line_pts in enumerate(points_list):
        pts = np.array(line_pts, dtype=np.float64)
        n = len(pts)
        
        # Before: distance from best-fit line (raw pixels)
        A = np.column_stack([pts, np.ones(n)])
        _, _, Vt = np.linalg.svd(A)
        abc = Vt[-1]
        norm = np.sqrt(abc[0]**2 + abc[1]**2)
        dist_before = np.abs(A @ abc) / norm if norm > 1e-12 else np.zeros(n)
        
        # After: undistort then measure
        if camera_matrix is not None and dist_coeffs is not None:
            pts_cv = pts.reshape(-1, 1, 2)
            undist = cv2.undistortPoints(pts_cv, camera_matrix, dist_coeffs, P=camera_matrix)
            pts_u = undist.reshape(-1, 2)
        else:
            pts_u = pts
        
        A2 = np.column_stack([pts_u, np.ones(n)])
        _, _, Vt2 = np.linalg.svd(A2)
        abc2 = Vt2[-1]
        norm2 = np.sqrt(abc2[0]**2 + abc2[1]**2)
        dist_after = np.abs(A2 @ abc2) / norm2 if norm2 > 1e-12 else np.zeros(n)
        
        mean_b = np.mean(dist_before)
        mean_a = np.mean(dist_after)
        max_a = np.max(dist_after)
        imp = (1.0 - mean_a / mean_b) * 100 if mean_b > 1e-6 else 0
        
        all_before.extend(dist_before)
        all_after.extend(dist_after)
        
        if mean_b > 2.0 or mean_a > 2.0:  # Only show lines with significant error
            print(f"  Line {i+1:2d} ({n:2d} pts): before={mean_b:6.2f}px  after={mean_a:6.2f}px  max={max_a:6.2f}px  imp={imp:+.1f}%")
    
    overall_b = np.mean(all_before)
    overall_a = np.mean(all_after)
    overall_imp = (1.0 - overall_a / overall_b) * 100 if overall_b > 1e-6 else 0
    print(f"\n  OVERALL: before={overall_b:.2f}px  after={overall_a:.2f}px  improvement={overall_imp:.1f}%")
    print(f"  Max error after: {np.max(all_after):.2f}px")
    
    # Count lines where undistortion made things WORSE
    worse = 0
    for i, line_pts in enumerate(points_list):
        pts = np.array(line_pts, dtype=np.float64)
        n = len(pts)
        A = np.column_stack([pts, np.ones(n)])
        _, _, Vt = np.linalg.svd(A)
        abc = Vt[-1]
        norm = np.sqrt(abc[0]**2 + abc[1]**2)
        db = np.mean(np.abs(A @ abc) / norm) if norm > 1e-12 else 0
        
        if camera_matrix is not None and dist_coeffs is not None:
            pts_cv = pts.reshape(-1, 1, 2)
            undist = cv2.undistortPoints(pts_cv, camera_matrix, dist_coeffs, P=camera_matrix)
            pts_u = undist.reshape(-1, 2)
        else:
            pts_u = pts
        A2 = np.column_stack([pts_u, np.ones(n)])
        _, _, Vt2 = np.linalg.svd(A2)
        abc2 = Vt2[-1]
        norm2 = np.sqrt(abc2[0]**2 + abc2[1]**2)
        da = np.mean(np.abs(A2 @ abc2) / norm2) if norm2 > 1e-12 else 0
        if da > db + 0.1:
            worse += 1
    print(f"  Lines where undistortion made it WORSE: {worse}/{len(points_list)}")

# --- Test 1: No correction (raw pixels) ---
print("=" * 60)
print("RAW PIXELS (no correction):")
print("=" * 60)
measure_straightness(lines)

# --- Test 2: OLD calibration (k1=+0.016, from local file) ---
print("\n" + "=" * 60)
print("OLD CALIBRATION (k1=+0.016, k2=-0.028):")
print("=" * 60)
old_cam = np.array([[932.87, 0, 1152], [0, 932.87, 648], [0, 0, 1]], dtype=np.float64)
old_dist = np.array([[0.016335, -0.028421, 0, 0, 0]], dtype=np.float64)
measure_straightness(lines, old_cam, old_dist)

# --- Test 3: NEW calibration (k1=0, k2=-0.035, k3=0.0017) ---
print("\n" + "=" * 60)
print("NEW CALIBRATION (k1=0, k2=-0.035, k3=0.0017):")
print("=" * 60)
new_cam = np.array([[982.3, 0, 1152], [0, 982.3, 648], [0, 0, 1]], dtype=np.float64)
new_dist = np.array([[0, -0.03457228, 0, 0, 0.00171917]], dtype=np.float64)
measure_straightness(lines, new_cam, new_dist)

# --- Test 4: Try letting k1 be free (no constraint) ---
print("\n" + "=" * 60)
print("OPTIMIZING WITH FREE k1 (no sign constraint):")
print("=" * 60)
from scipy.optimize import least_squares

all_points = []
line_masks = []
idx = 0
for line in lines:
    mask = []
    for pt in line:
        all_points.append(pt)
        mask.append(idx)
        idx += 1
    line_masks.append(mask)
all_points = np.array(all_points, dtype=np.float64)

cx0, cy0 = image_width / 2.0, image_height / 2.0
f0 = (image_width / 2.0) / np.tan(np.radians(102.0 / 2.0))

def _undistort(params):
    f, cx, cy, k1, k2, p1, p2, k3 = params
    cam = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=np.float64)
    dist = np.array([[k1, k2, p1, p2, k3]], dtype=np.float64)
    pts = all_points.reshape(-1, 1, 2)
    out = cv2.undistortPoints(pts, cam, dist, P=cam)
    return out.reshape(-1, 2), cam, dist

def _line_distances(undist_pts, mask):
    lpts = undist_pts[mask]
    A = np.column_stack([lpts, np.ones(len(lpts))])
    _, _, Vt = np.linalg.svd(A)
    abc = Vt[-1]
    norm = np.sqrt(abc[0]**2 + abc[1]**2)
    if norm < 1e-12:
        return np.zeros(len(lpts))
    return (A @ abc) / norm

def residuals(params):
    try:
        undist_pts, _, _ = _undistort(params)
    except cv2.error:
        return np.full(len(all_points), 1e6)
    res = []
    for mask in line_masks:
        res.append(_line_distances(undist_pts, mask))
    return np.concatenate(res)

# FREE k1: allow -5 to +5
x0 = np.array([f0, cx0, cy0, 0.0, 0.0, 0.0, 0.0, 0.0])
lower = [200, cx0 - image_width * 0.1, cy0 - image_height * 0.1, -5.0, -5.0, -0.01, -0.01, -5.0]
upper = [3000, cx0 + image_width * 0.1, cy0 + image_height * 0.1, 5.0, 5.0, 0.01, 0.01, 5.0]

result = least_squares(residuals, x0, method='trf', bounds=(lower, upper),
                       max_nfev=50000, xtol=1e-14, ftol=1e-14)
f_opt, cx_opt, cy_opt, k1, k2, p1, p2, k3 = result.x
print(f"  Optimal: f={f_opt:.1f}, cx={cx_opt:.1f}, cy={cy_opt:.1f}")
print(f"  k1={k1:.6f}, k2={k2:.6f}, k3={k3:.6f}, p1={p1:.6f}, p2={p2:.6f}")

free_cam = np.array([[f_opt, 0, cx_opt], [0, f_opt, cy_opt], [0, 0, 1]], dtype=np.float64)
free_dist = np.array([[k1, k2, p1, p2, k3]], dtype=np.float64)
measure_straightness(lines, free_cam, free_dist)
