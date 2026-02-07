"""Check where the 45 lens calibration lines are located across the image."""
import json
import numpy as np

with open(r"C:\Users\rahaber\Downloads\lens_lines.json", "r") as f:
    data = json.load(f)

lines = data["lines"]
w, h = data["image_width"], data["image_height"]
print(f"Image: {w}x{h}")
print(f"Lines: {len(lines)}")

# Collect all points
all_x = []
all_y = []
for line in lines:
    for pt in line:
        all_x.append(pt[0])
        all_y.append(pt[1])

all_x = np.array(all_x)
all_y = np.array(all_y)

print(f"\nPoint coverage:")
print(f"  X range: {all_x.min():.0f} to {all_x.max():.0f} (image: 0 to {w})")
print(f"  Y range: {all_y.min():.0f} to {all_y.max():.0f} (image: 0 to {h})")

# Divide image into 5 horizontal zones
zones = [(0, w*0.2, "Far left (0-20%)"), 
         (w*0.2, w*0.4, "Left (20-40%)"),
         (w*0.4, w*0.6, "Center (40-60%)"),
         (w*0.6, w*0.8, "Right (60-80%)"),
         (w*0.8, w, "Far right (80-100%)")]

print(f"\nPoints per horizontal zone:")
for x_min, x_max, label in zones:
    count = np.sum((all_x >= x_min) & (all_x < x_max))
    pct = count / len(all_x) * 100
    bar = "#" * int(pct / 2)
    print(f"  {label:25s}: {count:4d} points ({pct:5.1f}%) {bar}")

# Lines that span the left edge (any point with x < 200)
left_edge_lines = sum(1 for line in lines if any(pt[0] < 200 for pt in line))
right_edge_lines = sum(1 for line in lines if any(pt[0] > w - 200 for pt in line))
print(f"\nLines touching left edge (x<200):  {left_edge_lines}/{len(lines)}")
print(f"Lines touching right edge (x>{w-200}): {right_edge_lines}/{len(lines)}")

# Per-line: show x-range
print(f"\nPer-line X coverage:")
for i, line in enumerate(lines):
    xs = [pt[0] for pt in line]
    x_min, x_max = min(xs), max(xs)
    span = x_max - x_min
    # Normalize to image width for visual
    bar_start = int(x_min / w * 50)
    bar_end = int(x_max / w * 50)
    bar = " " * bar_start + "#" * max(1, bar_end - bar_start)
    print(f"  Line {i+1:2d} ({len(line):2d}pts): x={x_min:6.0f}-{x_max:6.0f} (span {span:5.0f}px) |{bar}")
