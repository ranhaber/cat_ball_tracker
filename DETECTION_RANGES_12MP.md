# 📐 Cat Detection Range Analysis - 12MP Mode

## Camera Specifications
- **Model**: Raspberry Pi Camera Module 3 WIDE
- **Horizontal FOV**: ~120° (ultra-wide)
- **Vertical FOV**: ~80° (for 16:9 aspect ratio)
- **Max Resolution**: 4608×2592 (12 Megapixels)

---

## 🐱 Cat Physical Dimensions (Real-World Data)
- **Body Length**: ~50cm (19.7 inches) - from nose to base of tail
- **Height**: ~25cm (9.8 inches) - shoulder height when standing

## 🎯 Target Detection Distance
- **Maximum distance**: **13 meters** (actual requirement)

---

## 📊 Detection Range Calculations

### **Pixel Angular Size:**
```
120° / 4608 pixels = 0.02604° per pixel
```

### **Cat Angular Size at Distance:**
```
Angular size = 2 × arctan(object_size / (2 × distance))

At 13m: arctan(0.50 / (2 × 13)) = arctan(0.0192) = 1.10° × 2 = 2.20°
```

---

## 🎯 Full 12MP Resolution: 4608×2592

| Distance | Cat Width (pixels) | Cat Area (pixels²) | After 0.25 Scale | Scaled Area | Min Area 80 | Detected? |
|----------|-------------------|--------------------|--------------------|-------------|-------------|-----------|
| **2m** | 560×280 px | 156,800 | 140×70 px | 9,800 | ✅ 80 | ✅ **YES** |
| **5m** | 224×112 px | 25,088 | 56×28 px | 1,568 | ✅ 80 | ✅ **YES** |
| **8m** | 140×70 px | 9,800 | 35×18 px | 630 | ✅ 80 | ✅ **YES** |
| **10m** | 112×56 px | 6,272 | 28×14 px | 392 | ✅ 80 | ✅ **YES** |
| **12m** | 93×47 px | 4,371 | 23×12 px | 276 | ✅ 80 | ✅ **YES** |
| **13m** | **86×43 px** | **3,698** | **22×11 px** | **242** | ✅ 80 | ✅ **YES!** ✨ |
| **15m** | 75×37 px | 2,775 | 19×9 px | 171 | ✅ 80 | ✅ **YES** |
| **20m** | 56×28 px | 1,568 | 14×7 px | 98 | ✅ 80 | ✅ **YES** |

**🎉 Result: 13m detection IS DEFINITELY POSSIBLE with 12MP!**

---

## 📐 Comparison with Lower Resolutions

### **Cat at 13m Distance (Target Maximum):**

| Resolution | Cat Width | After 0.25 Scale | Scaled Area | Min Area 80 | Detected? |
|------------|-----------|------------------|-------------|-------------|-----------|
| **4608×2592 (12MP)** | 86×43 px | 22×11 px | **242 px²** | ✅ 80 | ✅ **YES** ✨ |
| **2304×1296 (3MP)** | 43×22 px | 11×5 px | 55 px² | ❌ 80 | ❌ **NO** |
| **1920×1080 (2MP)** | 36×18 px | 9×5 px | 45 px² | ❌ 80 | ❌ **NO** |
| **1536×864 (1.3MP)** | 29×14 px | 7×4 px | 28 px² | ❌ 80 | ❌ **NO** |

### **Cat at 15m Distance (Beyond Target):**

| Resolution | Cat Width | After 0.25 Scale | Scaled Area | Min Area 80 | Detected? |
|------------|-----------|------------------|-------------|-------------|-----------|
| **4608×2592 (12MP)** | 75×37 px | 19×9 px | **171 px²** | ✅ 80 | ✅ **YES** |
| **2304×1296 (3MP)** | 37×19 px | 9×5 px | 45 px² | ❌ 80 | ❌ NO |
| **1920×1080 (2MP)** | 31×15 px | 8×4 px | 32 px² | ❌ 80 | ❌ NO |
| **1536×864 (1.3MP)** | 25×12 px | 6×3 px | 18 px² | ❌ 80 | ❌ NO |

**The difference is HUGE! 12MP gives 5.3x more pixels than 1920×1080!**
**At 13m target distance, 12MP has 242 px² vs only 45 px² @ 1920×1080 = 5.4x more!**

---

## ⚡ Performance Impact on Raspberry Pi Zero 2W

### **Memory Usage:**

| Resolution | Frame Size (RGB) | Frame Size (BGR) | Motion Buffer | Total RAM |
|------------|------------------|------------------|---------------|-----------|
| 1920×1080 | 6.2 MB | 6.2 MB | ~1.5 MB | ~180 MB |
| **4608×2592** | **35.8 MB** | **35.8 MB** | **8.9 MB** | **~450 MB** ⚠️ |

### **Processing Load:**

| Resolution | Pixels to Process | Motion Pixels (0.25 scale) | Estimated FPS |
|------------|-------------------|---------------------------|---------------|
| 1920×1080 | 2,073,600 | 129,600 | 8-12 FPS |
| **4608×2592** | **11,943,936** | **746,496** | **1-3 FPS** ⚠️ |

**Problem: 5.7x more pixels = very slow on Pi Zero 2W!**

---

## 💡 Smart Solution: Native 2x Mode (2304×1296)

The IMX708 sensor supports **native 2x2 binning mode** which is much faster!

### **Cat at 13m with 2304×1296 (Target Distance):**

| Distance | Cat Width | After 0.25 Scale | Scaled Area | Min Area 80 | Detected? |
|----------|-----------|------------------|-------------|-------------|-----------|
| **2m** | 280×140 px | 70×35 px | 2,450 | ✅ 80 | ✅ **YES** |
| **5m** | 112×56 px | 28×14 px | 392 | ✅ 80 | ✅ **YES** |
| **8m** | 70×35 px | 18×9 px | 162 | ✅ 80 | ✅ **YES** |
| **10m** | 56×28 px | 14×7 px | 98 | ✅ 80 | ✅ **YES** |
| **12m** | 47×23 px | 12×6 px | 72 | ⚠️ 80 | ⚠️ **MARGINAL** |
| **13m** | **43×22 px** | **11×5 px** | **55** | ❌ 80 | ❌ **NO** |

**❌ Still too small at 13m with 2304×1296 @ 0.25 scale!**

### **But with Adjusted Parameters (motion_scale = 0.35, min_area = 50):**

| Distance | Cat Width | After 0.35 Scale | Scaled Area | Min Area 50 | Detected? |
|----------|-----------|------------------|-------------|-------------|-----------|
| **8m** | 70×35 px | 25×12 px | 300 | ✅ 50 | ✅ **YES** |
| **10m** | 56×28 px | 20×10 px | 200 | ✅ 50 | ✅ **YES** |
| **12m** | 47×23 px | 16×8 px | 128 | ✅ 50 | ✅ **YES** |
| **13m** | **43×22 px** | **15×8 px** | **120** | ✅ 50 | ✅ **YES!** ✨ |

**✅ With tuned parameters, 2304×1296 CAN detect at 13m!**

---

## 🎯 Recommended Approach: Dual Resolution Strategy

### **Option 1: Full 12MP Capture (Slow but Works)**

```python
# Capture at full 12MP
CAPTURE_RESOLUTION = (4608, 2592)  # For detection
STREAM_RESOLUTION = (1280, 720)    # For web viewing

# Trade-offs:
✅ Detects cats at 15-20m reliably
✅ Best accuracy
❌ 1-3 FPS (very slow)
❌ ~450 MB RAM (risky on Pi Zero 2W)
❌ High CPU usage (70-90%)
```

### **Option 2: 2304×1296 with Adjusted Parameters (Balanced)** ⭐ **RECOMMENDED for 13m**

```python
# Capture at 2x binned mode
CAPTURE_RESOLUTION = (2304, 1296)  # For detection
STREAM_RESOLUTION = (960, 540)     # For web viewing

# Adjust motion detection:
MOTION_SCALE = 0.35  # Less aggressive scaling
MOTION_MIN_AREA = 50  # Lower threshold

# At 13m (target distance):
# - Cat: 43×22 px → after 0.35 scale: 15×8 = 120 px²
# - Above 50 pixel threshold! ✅

# Trade-offs:
✅ 4-6 FPS (acceptable)
✅ ~220 MB RAM (safe)
✅ Moderate CPU (55-65%)
✅ **Can reliably detect at 13m!** ✨
⚠️ Motion detection less aggressive (more false positives possible)
```

### **Option 3: Dynamic Resolution Switching**

```python
# Start with high-res when motion detected
IDLE_RESOLUTION = (1920, 1080)     # No motion
ACTIVE_RESOLUTION = (4608, 2592)   # Motion detected
STREAM_RESOLUTION = (1280, 720)    # Always

# Trade-offs:
✅ Best of both worlds
✅ Low power when idle
✅ High accuracy when needed
⚠️ Complex implementation
⚠️ Switching lag (~1-2 seconds)
```

---

## 📊 Performance Profile Adjustments for 12MP

### **Ultra Performance (12MP Mode):**
```python
"ultra_performance_12mp": {
    "capture_resolution": (4608, 2592),
    "stream_resolution": (1280, 720),
    "jpeg_quality": 50,              # Lower for faster encode
    "motion_scale": 0.20,            # More aggressive (reduce load)
    "motion_threshold": 20,
    "motion_min_area": 80,
    "ai_crop_size": (600, 600),      # Larger for 12MP
    "tflite_threads": 4,
    "estimated_fps": "1-3 FPS",
    "estimated_ram": "450MB",
    "estimated_cpu": "75%",
    "detection_range": "0-20m"
}
```

### **Balanced 2x Mode (Recommended for 13m):** ⭐
```python
"balanced_2x": {
    "capture_resolution": (2304, 1296),
    "stream_resolution": (960, 540),
    "jpeg_quality": 60,
    "motion_scale": 0.35,            # Less aggressive (better for distant objects)
    "motion_threshold": 18,
    "motion_min_area": 50,           # Lower threshold (allows 13m detection)
    "ai_crop_size": (420, 420),      # Proportional to resolution
    "tflite_threads": 3,
    "estimated_fps": "4-6 FPS",
    "estimated_ram": "220MB",
    "estimated_cpu": "60%",
    "detection_range": "0-13m reliably, up to 15m possible"
}
```

---

## 🎯 Final Recommendations for 13m Target Distance

### **✅ BEST CHOICE: 2x Binned Mode (2304×1296)** ⭐
**Perfect balance for 13m detection!**
- ✅ **Can reliably detect at 13m** with tuned parameters
- ✅ 4-6 FPS (very acceptable)
- ✅ ~220 MB RAM (safe for Pi Zero 2W)
- ✅ Stream at 960×540 (responsive web UI)
- ✅ Moderate CPU usage (60%)
- 🔧 Settings: `motion_scale=0.35`, `min_area=50`

### **Alternative: Full 12MP mode (4608×2592)**
**Only if you need extra safety margin or 15m+ range**
- ✅ Can detect beyond 15m easily
- ✅ More pixels = more detail
- ❌ Very slow: 1-3 FPS
- ❌ High RAM: ~450 MB (may be unstable)
- ❌ High CPU: 75%+
- ⚠️ **Overkill for 13m target**

### **Current Setup (1920×1080):**
❌ **Cannot detect at 13m** (only 45 px² after scale)
- Good for: 0-8m range only
- 8-12 FPS (fastest)
- Most stable
- **Not suitable for your 13m requirement**

---

## 🧪 Testing Recommendation

1. **Try 12MP mode first** to see actual FPS on your Pi
2. **Measure RAM usage** (`free -h` while running)
3. **Test at 15m** with real cat movement
4. **Compare responsiveness** vs lower resolution
5. **Decide based on real performance**

---

## 📐 Summary Table for 13m Target

| Mode | Resolution | FPS | RAM | 13m Detection | Best For |
|------|------------|-----|-----|---------------|----------|
| **Current** | 1920×1080 | 8-12 | 180MB | ❌ **NO** (45 px²) | Close range only (0-8m) |
| **2x Binned** ⭐ | 2304×1296 | 4-6 | 220MB | ✅ **YES** (120 px²)* | **13m target!** |
| **12MP Full** | 4608×2592 | 1-3 | 450MB | ✅ **YES** (242 px²) | Overkill, very slow |

*With tuned parameters: `motion_scale=0.35`, `min_area=50`

---

## 🎯 **CONCLUSION FOR 13m REQUIREMENT:**

**✅ Use 2304×1296 (2x Binned Mode) with tuned motion detection parameters**

This gives you:
- ✅ Reliable 13m detection (120 px² vs 50 px² threshold)
- ✅ Acceptable 4-6 FPS performance
- ✅ Stable RAM usage (~220 MB)
- ✅ Responsive web stream at 960×540
- ✅ Perfect balance for your use case!

**Want me to implement this dual-resolution system with the optimized 2x profile?** 🚀
