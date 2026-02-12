# Plan: Callback-Driven Capture + Ring Buffer + Async AI

## Goal

Eliminate the capture thread entirely. Use picamera2's `post_callback` to deliver
frames via callback, copy into a pre-allocated ring buffer (zero alloc), and run
TFLite on a dedicated AI thread (cores 1-3). Process thread on Core 0 does
motion + tracking + annotation, never blocked by camera wait or TFLite.

## Architecture (2 application threads + picamera2 internal)

```
picamera2 internal thread:        Core 0: Process thread         Cores 1-3: AI thread
┌──────────────────────────┐     ┌─────────────────────────┐     ┌─────────────────────┐
│ Camera ISP delivers frame│     │ frame_ready.wait()      │     │ ai_queue.get()      │
│ post_callback fires:     │     │ read ring_buf[read_idx] │     │ detect(crop)  ~450ms│
│   copyto(ring[write_idx])│────▶│ inject cat (if active)  │     │ push result         │
│   frame_ready.set()      │     │ motion_detect()         │     │                     │
│   (17ms, then idle)      │     │ submit crop to AI queue │────▶│                     │
│                          │     │ fetch AI result (noblock)│◀────│                     │
│                          │     │ tracker + annotation     │     │ auto-unload if IDLE │
└──────────────────────────┘     └─────────────────────────┘     └─────────────────────┘
```

## Ring Buffer Design

```python
class FrameRingBuffer:
    def __init__(self, n, main_shape, lores_shape, crop_shape, stream_shape):
        # Ring of main frames (capture writes, process reads)
        self.main = [np.empty(main_shape, dtype=np.uint8) for _ in range(n)]
        self.lores_y = [np.empty((lores_shape[0], lores_shape[1]), dtype=np.uint8) for _ in range(n)]
        self.lores_bgr = [np.empty(lores_shape, dtype=np.uint8) for _ in range(n)]
        self.has_lores_bgr = [False] * n  # Whether BGR was computed for this slot
        
        # Shared pre-allocated buffers (not ring — single instance reused)
        self.ai_crop = np.empty(crop_shape, dtype=np.uint8)
        self.stream_frame = np.empty(stream_shape, dtype=np.uint8)
        self.current_frame = np.empty(main_shape, dtype=np.uint8)
        
        self.write_idx = 0  # Next slot for camera callback to write
        self.read_idx = 0   # Next slot for process thread to read
        self.n = n
    
    def advance_write(self):
        self.write_idx = (self.write_idx + 1) % self.n
    
    def advance_read(self):
        self.read_idx = (self.read_idx + 1) % self.n
```

Size: 3 × (9.0 + 0.5 + 1.6) + 0.4 + 0.7 + 9.0 = **43MB** pre-allocated, never freed.

## Thread Safety

The ring buffer has a producer (camera callback) and a consumer (process thread).
With n=3 and camera at 10 FPS (100ms/frame), process at ~82ms/frame:

- Write always leads read by 1-2 slots
- If process is slow (TFLite blocking in sync mode), write wraps around and
  overwrites the oldest unread slot. This is acceptable — we always want the
  latest frame.
- `frame_ready` event ensures process doesn't read a partially-written slot:
  callback does copyto() THEN sets the event.

## Implementation Steps

### Step 1: FrameRingBuffer class
Add to web/app.py. Pre-allocates all buffers.

### Step 2: Camera callback (_frame_callback)
- Replaces _capture_loop entirely
- Uses MappedArray inside callback for zero-copy read from DMA
- Copies into ring buffer slot with np.copyto (zero alloc)
- Sets frame_ready event

### Step 3: Modify _process_loop
- Replace queue.get() with frame_ready.wait() + ring buffer read
- All other processing unchanged
- inject_cat writes to ring buffer copy (already writable)

### Step 4: Re-add _ai_loop (Phase 3)
- Same as before but with pre-allocated crop buffer
- Crop copy: np.copyto(pool.ai_crop, frame[cy:cy+ch, cx:cx+cw])
- AI thread on cores 1-3 (num_threads=3)

### Step 5: Update start() and stop()
- Create FrameRingBuffer
- Set picam2.post_callback
- Start AI thread + process thread (no capture thread)
- Remove _capture_loop

### Step 6: Config changes
- DEFAULT_FRAMERATE = 10
- TFLITE_NUM_THREADS = 3
- Remove CAPTURE_THREAD_CORE (no capture thread)

### Step 7: Lores reconfigure
- Currently done in capture thread
- Move to camera callback or process thread
- Camera callback is simplest (same thread that owns picamera2)

## Risks

1. **post_callback blocks camera thread:** Our callback does 17ms memcpy.
   At 10 FPS (100ms interval), 17ms is fine. If callback takes >100ms, frames drop.
   Mitigation: callback only does copyto + event.set, nothing else.

2. **Ring buffer overwrite:** If process is very slow (swap), camera may overwrite
   unread frames. This is intentional — always process latest frame.

3. **MappedArray in callback:** The callback receives a CompletedRequest, not a
   context manager. We need to verify MappedArray works here (it should — the
   request is valid during the callback).

4. **Inject cat writes to frame:** Inject modifies the frame. With ring buffer,
   it writes to ring_buf[idx] which is our memory (not DMA). Safe.

## Expected Performance

| Metric | Current (v3.14.0, 5 FPS) | Callback + Ring + AI (10 FPS) |
|--------|-------------------------|-------------------------------|
| Camera FPS | 5 | 10 |
| Motion updates/sec | 5 | ~7-8 (limited by 82ms processing) |
| AI detections/sec | 0.8 | ~2.2 |
| TFLite invoke | ~610ms (3 threads) | ~450ms (3 full cores) |
| Process blocked by TF | Yes (610ms) | No (async) |
| Per-frame allocation | ~11MB | 0 |
| GC pressure | Low | Near zero |
| Available RAM | ~155MB | ~113MB (stable) |
| Threads | 3 (Cap+Proc+Log) | 3 (AI+Proc+Log) |
| Capture thread | Core 1 (83% idle) | Eliminated |
