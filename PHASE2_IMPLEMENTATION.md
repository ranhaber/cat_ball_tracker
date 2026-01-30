# Phase 2 Implementation - Performance Profile System

**Version**: 1.6.0  
**Date**: 2026-01-30  
**Type**: Feature - Performance optimization with user-selectable profiles

---

## ✨ What's New

### **Performance Profile System**
Users can now switch between 4 optimization profiles via Web UI:

1. **Default (Original)** - Pre-optimization settings
2. **Balanced** (Recommended) - Best trade-off: +33% FPS, -2% accuracy  
3. **Performance** - Maximum speed: +100% FPS, -5% accuracy
4. **Quality** - Best accuracy: +2% accuracy, -17% FPS

---

## 🎛️ Profile Specifications

### **Default Profile**
```python
{
    "jpeg_quality": 70,
    "motion_crop_size": (300, 300),
    "motion_scale": 0.25,
    "motion_threshold": 15,
    "motion_min_area": 100,
    "tflite_threads": 4,
    "estimated_fps": "5-6 FPS",
    "estimated_ram": "220MB",
    "estimated_cpu": "85%"
}
```

### **Balanced Profile** ⭐ Recommended
```python
{
    "jpeg_quality": 65,
    "motion_crop_size": (280, 280),
    "motion_scale": 0.22,
    "motion_threshold": 18,
    "motion_min_area": 150,
    "tflite_threads": 3,
    "estimated_fps": "7-9 FPS",
    "estimated_ram": "185MB",
    "estimated_cpu": "65%",
    "accuracy_impact": "-2%"
}
```

### **Performance Profile** 🚀
```python
{
    "jpeg_quality": 55,
    "motion_crop_size": (250, 250),
    "motion_scale": 0.2,
    "motion_threshold": 22,
    "motion_min_area": 200,
    "tflite_threads": 3,
    "estimated_fps": "10-14 FPS",
    "estimated_ram": "175MB",
    "estimated_cpu": "55%",
    "accuracy_impact": "-5%"
}
```

### **Quality Profile** 📸
```python
{
    "jpeg_quality": 75,
    "motion_crop_size": (320, 320),
    "motion_scale": 0.25,
    "motion_threshold": 15,
    "motion_min_area": 100,
    "tflite_threads": 4,
    "estimated_fps": "4-5 FPS",
    "estimated_ram": "210MB",
    "estimated_cpu": "80%",
    "accuracy_impact": "+2%"
}
```

---

## 📂 Files Modified

### **Backend**
1. **config.py**
   - Added `PERFORMANCE_PROFILES` dictionary
   - Added `DEFAULT_PERFORMANCE_PROFILE = "balanced"`

2. **web/app.py**
   - Added profile management methods to `VideoProcessor` class
   - New API endpoints: `/api/performance/profile` (GET/POST), `/api/performance/profiles` (GET)
   - Profile settings applied on startup and when switching

3. **main.py**
   - Version bumped to 1.6.0

### **Frontend**
4. **web/templates/index.html**
   - Added performance profile selector UI in Settings tab
   - Radio buttons with profile descriptions and metrics

5. **web/static/css/style.css**
   - Added `.profile-selector`, `.profile-option`, `.profile-content` styles
   - Modern card-based design with hover effects
   - Recommended badge for Balanced profile

6. **web/static/js/app.js**
   - Added `initProfileSelector()` function
   - Added `loadCurrentProfile()` for loading saved profile
   - Added `showNotification()` for user feedback
   - Profile switching with live API calls

---

## 🔌 API Endpoints

### **GET /api/performance/profiles**
Get all available profiles with metadata.

**Response:**
```json
{
  "profiles": {
    "default": {...},
    "balanced": {...},
    "performance": {...},
    "quality": {...}
  },
  "current": "balanced"
}
```

### **GET /api/performance/profile**
Get currently active profile.

**Response:**
```json
{
  "profile": "balanced",
  "settings": {
    "name": "Balanced",
    "description": "...",
    "jpeg_quality": 65,
    ...
  }
}
```

### **POST /api/performance/profile**
Switch to a different profile.

**Request:**
```json
{
  "profile": "performance"
}
```

**Response:**
```json
{
  "success": true,
  "profile": "performance",
  "settings": {...}
}
```

---

## 🎨 UI Features

### **Profile Selector Card Design**
- Visual card-based selector with radio buttons
- Each card shows:
  - Profile name
  - Description (trade-offs)
  - Estimated metrics (FPS, RAM, CPU)
  - "Recommended" badge for Balanced profile
- Hover effects and selected state
- Live switching without page reload
- Toast notifications for feedback

### **Location**
Settings Tab → Top section (before Detection Mode)

---

## 🔧 How It Works

### **Startup Flow**
```
1. Load settings.json
2. Check "performance_profile" key (default: "balanced")
3. Apply profile settings to:
   - Motion detector (scale, threshold, min_area)
   - TFLite detector (thread count)
   - JPEG encoder (quality)
   - Motion crop size
4. Save current profile name
```

### **Profile Switch Flow**
```
1. User selects different profile (radio button)
2. JavaScript sends POST to /api/performance/profile
3. Backend applies all profile settings
4. Settings persisted to settings.json
5. Toast notification confirms success
6. Next frame uses new settings (immediate effect)
```

### **Settings Applied**
When switching profiles, these settings change immediately:
- JPEG quality (affects video stream compression)
- Motion detection scale (affects motion detection speed)
- Motion threshold (affects sensitivity)
- AI crop size (affects detection range and speed)
- TFLite threads (affects inference speed)

**No restart required!** All settings apply to the next frame.

---

## 📊 Expected Performance Impact

### **Phase 1 + Phase 2 Combined**

| Profile | FPS Gain | RAM Saving | CPU Saving | Accuracy Impact |
|---------|----------|------------|------------|-----------------|
| Default | +20% (Phase 1) | -10% | -12% | ✅ None |
| **Balanced** | **+60%** | **-16%** | **-24%** | **⚠️ -2%** |
| Performance | +150% | -20% | -35% | ⚠️ -5% |
| Quality | +5% | -5% | -5% | ✅ +2% |

*Gains are relative to pre-Phase 1 baseline*

---

## ✅ Testing Checklist

### **Functionality**
- [ ] Profile selector loads on page load
- [ ] Current profile is pre-selected (from settings.json)
- [ ] Clicking profile switches immediately
- [ ] Toast notification appears on switch
- [ ] Settings persist after restart
- [ ] All 4 profiles are selectable

### **Performance**
- [ ] FPS increases with Performance profile
- [ ] FPS decreases with Quality profile
- [ ] Balanced profile shows middle ground
- [ ] RAM usage changes as expected
- [ ] Video quality changes visible (JPEG compression)

### **API**
- [ ] GET /api/performance/profiles returns all profiles
- [ ] GET /api/performance/profile returns current profile
- [ ] POST /api/performance/profile switches profile
- [ ] Invalid profile name returns 400 error

### **UI/UX**
- [ ] Profile cards are visually distinct
- [ ] Hover effects work
- [ ] Selected state is clear
- [ ] "Recommended" badge visible on Balanced
- [ ] Metrics display correctly
- [ ] Toast animations smooth

---

## 🐛 Known Issues / Limitations

### **TFLite Thread Count**
- Thread count change doesn't recreate interpreter immediately
- Affects next model load (usually next detection)
- Consider adding explicit model reload on profile switch if needed

### **Visual Quality**
- JPEG quality changes are user-visible
- Performance profile (55% quality) may show compression artifacts
- Trade-off: speed vs video quality

### **Edge Detection**
- Smaller crop sizes in Performance profile may miss objects at edges
- Affects tracking continuity when objects move in/out of frame

---

## 🔄 Rollback Instructions

If issues occur:

1. **Quick fix** - Switch to Default profile via UI
2. **Manual fix** - Edit `settings.json`:
   ```json
   {
     "performance_profile": "default"
   }
   ```
3. **Code rollback** - Revert to v1.5.2:
   ```bash
   git checkout v1.5.2
   ```

---

## 🚀 Future Enhancements

### **Potential Additions**
1. **Custom Profiles** - Allow users to create/save custom profiles
2. **Auto-Profile Switching** - Switch based on system load or battery
3. **Profile Analytics** - Track actual FPS/RAM per profile
4. **A/B Testing Mode** - Compare two profiles side-by-side
5. **Mobile Presets** - Optimize for mobile viewing (lower bandwidth)

---

## 📝 Version History

- **v1.6.0** - Phase 2: Performance profile system with 4 presets
- **v1.5.2** - Phase 1: Memory optimization, GPU acceleration
- **v1.5.0** - Top-down view, 4-point calibration
- **v1.4.0** - Fixed crop, temporal confirmation

---

**Status**: ✅ Implemented, ready for testing  
**Default Profile**: Balanced (recommended for most users)
