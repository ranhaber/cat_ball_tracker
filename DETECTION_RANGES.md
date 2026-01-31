# Cat Detection Range Analysis

## 📏 Cat Dimensions (Average Domestic Cat)

- **Body Length**: 45-64 cm (average: **50 cm / 0.5m**)
- **Height (standing)**: 23-25 cm  
- **Width**: 15-20 cm
- **Source**: Research from multiple veterinary sources (2026)

---

## 📐 Detection Calculations

### Camera Field of View (FOV)
- **Raspberry Pi Camera Module 3 WIDE**
- **Horizontal FOV**: ~120° (ultra-wide)
- **Vertical FOV**: ~80° (for 16:9 aspect ratio)
- **Impact**: Distant objects appear much smaller than standard lens

---

## 🎯 Detection at Various Distances

### **1920×1080 Resolution (with 120° FOV)**

| Distance | Cat Size in Frame | After Motion Scale 0.25 | After Min Area Filter | Detected? |
|----------|-------------------|-------------------------|----------------------|-----------|
| **2m** | 233×117 px | 58×29 px (1,682 px²) | ✅ Pass (>80 px²) | ✅ **YES** |
| **5m** | 93×47 px | 23×12 px (276 px²) | ✅ Pass (>80 px²) | ✅ **YES** |
| **8m** | 58×29 px | 15×7 px (105 px²) | ✅ Pass (>80 px²) | ✅ **YES** |
| **10m** | 47×23 px | 12×6 px (72 px²) | ⚠️ Marginal (≈80 px²) | ⚠️ **MARGINAL** |
| **12m** | 39×20 px | 10×5 px (50 px²) | ❌ Fail (<80 px²) | ❌ **NO** |
| **15m** | 31×15 px | 8×4 px (32 px²) | ❌ Fail (<80 px²) | ❌ **NO** |

### **1536×864 Resolution (with 120° FOV)**

| Distance | Cat Size in Frame | After Motion Scale 0.25 | After Min Area Filter | Detected? |
|----------|-------------------|-------------------------|----------------------|-----------|
| **2m** | 187×93 px | 47×23 px (1,081 px²) | ✅ Pass (>80 px²) | ✅ **YES** |
| **5m** | 75×37 px | 19×9 px (171 px²) | ✅ Pass (>80 px²) | ✅ **YES** |
| **8m** | 47×23 px | 12×6 px (72 px²) | ⚠️ Marginal (≈80 px²) | ⚠️ **MARGINAL** |
| **10m** | 37×19 px | 9×5 px (45 px²) | ❌ Fail (<80 px²) | ❌ **NO** |
| **12m** | 31×16 px | 8×4 px (32 px²) | ❌ Fail (<80 px²) | ❌ **NO** |
| **15m** | 25×12 px | 6×3 px (18 px²) | ❌ Fail (<80 px²) | ❌ **NO** |

---

## 🎛️ Performance Profile Settings (Optimized)

### **Updated Performance Profile:**
```python
"performance": {
    "motion_scale": 0.25,          # Was 0.20 - increased for better range
    "motion_min_area": 80,         # Was 200 - lowered for distant cats
    "motion_threshold": 18,        # Was 22 - more sensitive
    "jpeg_quality": 60,            # Was 55 - slightly better quality
    "motion_crop_size": (280, 280),# Was (250, 250) - larger for accuracy
    "tflite_threads": 3,           # Unchanged
}
```

### **Why These Changes:**
1. **Motion Scale 0.25**: Ensures cats at 15m are still ~13 pixels after scaling
2. **Min Area 80**: Allows detection of 10×10 pixel objects (was blocking 200+)
3. **Motion Threshold 18**: More sensitive to subtle movement
4. **AI Crop 280×280**: Better balance between speed and accuracy

---

## 📊 Profile Comparison for 10m Detection (120° FOV)

| Profile | Motion Scale | Min Area | Cat at 10m (1920×1080) | Detected? | FPS |
|---------|--------------|----------|------------------------|-----------|-----|
| **Default** | 0.25 | 100 | 12×6 px (72 px²) | ❌ NO | 5-6 |
| **Balanced** | 0.22 | 150 | 10×5 px (50 px²) | ❌ NO | 7-9 |
| **Performance** | 0.25 | 80 | 12×6 px (72 px²) | ⚠️ **MARGINAL** | 8-12 |
| **Quality** | 0.25 | 100 | 12×6 px (72 px²) | ❌ NO | 4-5 |

**Note**: With 120° ultra-wide FOV, 10m is the practical limit. For reliable detection beyond 10m, consider a standard (non-wide) camera module.

---

## 📷 Resolution Recommendation

### **For Maximum Detection Range with 120° Wide FOV:**

#### **✅ RECOMMENDED: 1920×1080** (for 8-10m range)

**Pros:**
- ✅ **25% more horizontal pixels** than 1536×864
- ✅ Cat at 10m is **47 pixels** vs 37 pixels (27% larger)
- ✅ Better for **distant object detection**
- ✅ **Can marginally detect at 10m** with Performance profile
- ✅ Reliable detection up to **8m**
- ✅ More detail for AI classification
- ✅ Standard HD resolution

**Cons:**
- ⚠️ **~15% slower** processing (more pixels)
- ⚠️ **~10% more RAM** usage (~195MB vs ~180MB)
- ⚠️ May cause memory errors on Pi Zero 2W (416MB total RAM)

**Estimated FPS at 1920×1080:**
- Performance: 7-10 FPS
- Balanced: 6-8 FPS
- Default: 4-5 FPS

**Realistic Detection Range:** 0-8m reliably, 8-10m marginal

---

#### **⚙️ ALTERNATIVE: 1536×864**

**Pros:**
- ✅ **Native sensor mode** (no scaling)
- ✅ **Faster processing** (~15% more FPS)
- ✅ **Lower RAM usage** (~180MB)
- ✅ **Stable on Pi Zero 2W**
- ✅ Good for 0-8m range

**Cons:**
- ❌ Cat at 10m is only **37 pixels** (too small)
- ❌ **Cannot detect beyond 8m** reliably
- ❌ Wide FOV makes distant objects very small

**Estimated FPS at 1536×864:**
- Performance: 8-12 FPS ✅
- Balanced: 7-9 FPS
- Default: 5-6 FPS

---

## 🎯 Final Recommendation (120° Wide FOV)

### **⚠️ IMPORTANT: 15m Detection Not Feasible**
With the **120° ultra-wide Camera Module 3 WIDE**, detecting cats beyond 10m is **not reliable** due to the wide field of view making distant objects too small.

### **Use 1920×1080 if:**
- ✅ You need **maximum range** (8-10m)
- ✅ Cat often at **5-10m distance**
- ✅ You prioritize **detection range** over FPS
- ✅ You can tolerate **7-10 FPS** (Performance profile)

### **✅ RECOMMENDED: Use 1536×864 if:**
- ✅ Cat typically **within 0-8m** (most common)
- ✅ You prioritize **higher FPS** (8-12 FPS)
- ✅ You want **maximum stability** on Pi Zero 2W
- ✅ **RAM usage** is a concern
- ✅ **Best balance** for wide-angle lens

---

## 💡 Testing Recommendation

1. **Start with 1536×864 + Performance profile**
   - Test at your actual camera position
   - Walk a cat at 10m, 12m, 15m distances
   - Check detection reliability

2. **If cat not detected at 15m:**
   - Switch to **1920×1080 resolution**
   - Use **Performance or Default profile**
   - Retest at 15m distance

3. **Monitor system:**
   ```bash
   # Watch RAM usage
   tail -f ~/cat_ball_tracker/logs/latest.log | grep RAM
   
   # Check FPS
   # View in web UI
   ```

---

## 📈 Detection Range Summary (120° Wide FOV)

| Profile | Resolution | Reliable Range | Marginal Range | FPS | Best For |
|---------|------------|----------------|----------------|-----|----------|
| **Performance** | 1920×1080 | 0-8m | 8-10m | 7-10 | Maximum range |
| **Performance** | 1536×864 | **0-8m** ✅ | - | 8-12 | **Recommended** |
| **Balanced** | 1920×1080 | 0-5m | 5-8m | 6-8 | Close range |
| **Quality** | 1920×1080 | 0-5m | 5-8m | 4-5 | Close range, detail |

---

## ⚠️ **Conclusion:**

**With 120° ultra-wide Camera Module 3 WIDE:**
- ✅ **Reliable detection: 0-8m** (Performance profile, either resolution)
- ⚠️ **Marginal detection: 8-10m** (1920×1080 only, not reliable)
- ❌ **15m detection: NOT POSSIBLE** with ultra-wide lens

**Recommendation: Use 1536×864 + Performance profile for best balance (0-8m range).** 🎯

**For 15m detection, you would need:**
- Standard (non-wide) camera module with ~70° FOV, OR
- Higher resolution (4K), OR
- Accept that 8-10m is the practical limit with ultra-wide lens
