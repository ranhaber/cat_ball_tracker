# Cat Detection Range Analysis

## Camera Specifications
- **Model**: Raspberry Pi Camera Module 3 WIDE
- **Horizontal FOV**: ~120° (ultra-wide)
- **Capture Resolution**: 2304×1296 (native 2×2 binned mode)
- **Pixel angular size**: 120° / 2304 = 0.052° per pixel

## Cat Dimensions (Average Domestic Cat)
- **Body Length**: ~50cm (nose to base of tail)
- **Height (standing)**: ~25cm

---

## Detection at Distance (2304×1296, 120° FOV)

### Motion Detection (lores 960×540, scale depends on profile)

**Performance profile** (`config.py` → `PERFORMANCE_PROFILES["performance"]`: `motion_scale=0.35`, `motion_min_area=50`):

| Distance | Cat in main frame | After 0.35 scale | Scaled area | Min area 50 | Motion? |
|----------|------------------|-------------------|-------------|-------------|---------|
| 2.5m | 220×110 px | 77×39 px | 3,003 | Pass | YES |
| 5m | 112×56 px | 39×20 px | 780 | Pass | YES |
| 8m | 70×35 px | 25×12 px | 300 | Pass | YES |
| 10m | 56×28 px | 20×10 px | 200 | Pass | YES |
| 12m | 47×23 px | 16×8 px | 128 | Pass | YES |
| **13m** | **43×22 px** | **15×8 px** | **120** | Pass | **YES** |
| 15m | 37×19 px | 13×7 px | 91 | Pass | YES |
| 20m | 28×14 px | 10×5 px | 50 | Marginal | MARGINAL |

**Balanced profile** (`config.py` → `PERFORMANCE_PROFILES["balanced"]`: `motion_scale=0.30`, `motion_min_area=80`):

| Distance | Cat in main frame | After 0.30 scale | Scaled area | Min area 80 | Motion? |
|----------|------------------|-------------------|-------------|-------------|---------|
| 2.5m | 220×110 px | 66×33 px | 2,178 | Pass | YES |
| 8m | 70×35 px | 21×11 px | 231 | Pass | YES |
| 10m | 56×28 px | 17×8 px | 136 | Pass | YES |
| 12m | 47×23 px | 14×7 px | 98 | Pass | YES |
| **13m** | **43×22 px** | **13×7 px** | **91** | Pass | **YES** |
| 15m | 37×19 px | 11×6 px | 66 | Fail | NO |

### TFLite Detection (300×300 crop = model input, no resize)

Crop is 300×300 — matches TFLite input exactly. No resize needed, cat pixels
are preserved 1:1 from the main frame.

| Distance | Cat in main | In 300×300 crop (= TFLite input) | Detectable? |
|----------|------------|----------------------------------|-------------|
| 2.5m | 220×110 px | **220×110 px** (40px margin) | YES |
| 5m | 112×56 px | **112×56 px** | YES |
| 8m | 70×35 px | **70×35 px** | YES |
| 10m | 56×28 px | **56×28 px** | YES |
| 13m | 43×22 px | **43×22 px** | MARGINAL |
| 15m | 37×19 px | **37×19 px** | MARGINAL |

At 13m the cat is 43×22 pixels in TFLite input (was 32×17 with the old
380→300 resize — 27% more pixels now). Above MobileNet SSD minimum
feature size (~20px).

---

## Current Profiles (v3.16.1, 10 FPS, async AI)

| Profile | motion_scale | min_area | crop_size | Reliable range | Measured FPS |
|---------|-------------|----------|-----------|----------------|-------------|
| **Balanced** | 0.30 | 80 | 300×300 | 0-13m | 10 |
| **Performance** | 0.35 | 50 | 300×300 | 0-13m | 10 |
| **Quality** | 0.35 | 80 | 300×300 | 0-12m (detail) | 10 |

All profiles use 300×300 crop matching TFLite's native input — no resize step,
27% more cat pixels vs the old 380-400px crops. AI runs async on Cores 1-3
(~190ms invoke, ~5 detections/sec at 10 FPS).

---

## Why 2304×1296 (Not Higher or Lower)

| Resolution | Cat at 13m | FPS | RAM | Verdict |
|------------|-----------|-----|-----|---------|
| 4608×2592 (12MP) | 86×43 px (easy) | 1-3 | ~450MB (exceeds Pi Zero) | Too heavy |
| **2304×1296 (2×2 binned)** | **43×22 px (OK)** | **10** | **~290MB** | **Current choice** |
| 1920×1080 | 36×18 px (too small) | 10+ | ~250MB | Insufficient range |
| 1536×864 | 29×14 px (too small) | 10+ | ~220MB | Insufficient range |

2304×1296 is the native 2×2 binned mode of the IMX708 sensor — the ISP
reads binned pixels directly, preserving the full 120° FOV with no crop or
software downscale. It gives enough pixels for 13m detection while fitting
in Pi Zero 2W's 416MB RAM.

---

## Conclusion

- **Reliable detection**: 0-12m (all profiles)
- **Marginal detection**: 12-13m (Performance profile, depends on lighting/contrast)
- **Not reliable**: >15m (cat too small in 120° ultra-wide frame)

For >15m detection, a standard (~70°) lens or higher resolution would be needed.
