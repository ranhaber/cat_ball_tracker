# Pre-allocation: Remaining Items

Ring buffer (v3.16.0) already pre-allocates main frame, lores Y, and lores BGR.
These items are still allocating per-frame:

## 1. Motion detector internal buffers

`detection/motion_detector.py` allocates 3 buffers every `detect()` call:

```python
# Current (allocates ~0.3MB per frame):
small_gray = cv2.resize(frame, (small_w, small_h))     # ~0.1MB
blurred = cv2.GaussianBlur(small_gray, ...)              # ~0.1MB
diff = cv2.absdiff(blurred, self.background)             # ~0.1MB
```

**Fix:** Pass pre-allocated buffers at init, use `dst=` parameter:

```python
cv2.resize(frame, (small_w, small_h), dst=self._small)  # 0 alloc
cv2.GaussianBlur(self._small, ..., dst=self._blur)      # 0 alloc
cv2.absdiff(self._blur, self.background, dst=self._diff) # 0 alloc
```

**Impact:** Saves ~3MB/s alloc churn at 10 FPS. Low risk.

## 2. AI crop copy in `_submit_ai()`

```python
# Current (allocates ~0.4MB per AI submit):
crop = frame[cy:cy+ch, cx:cx+cw].copy()
```

**Fix:** Pre-allocate a crop buffer in `__init__`, use `np.copyto`:

```python
self._ai_crop_buf = np.empty((max_crop, max_crop, 3), dtype=np.uint8)
# In _submit_ai:
src = frame[cy:cy+ch, cx:cx+cw]
np.copyto(self._ai_crop_buf[:ch, :cw], src)
crop = self._ai_crop_buf[:ch, :cw]
```

**Impact:** Saves ~2MB/s at 5 AI submits/sec. Low risk.

## 3. Inject cat frame copy

```python
# Current (allocates 9MB when inject active):
frame = frame.copy()  # Before paste_on_frame
```

This is intentional (protects ring buffer slot). Could use a pre-allocated
buffer instead, but inject is test-only mode — low priority.

## Expected total impact

| Metric | Current | After pre-alloc |
|--------|---------|-----------------|
| Per-frame alloc churn | ~0.7MB (motion+crop) | ~0.05MB (JPEG only) |
| GC pressure | Low (ring buffer helps) | Near zero |
| Priority | Low — system is stable at 10 FPS | Nice-to-have |
