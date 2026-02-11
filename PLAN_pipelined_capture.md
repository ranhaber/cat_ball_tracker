# Plan: Pipelined Capture + Thread Affinity

## Problem

The processing loop is sequential: capture waits for the camera, then processes.
During the 43ms idle wait inside `captured_request()`, the CPU does nothing.

```
Current (sequential):
|---capture(60ms: 43ms idle + 17ms memcpy)---|---motion(37ms)---|
                                              Total: 97ms → 10fps
```

## Solution: Option A — Capture Thread + Queue + Thread Affinity

### Architecture

```
Capture thread (Core 1):          Process thread (Core 0):
┌───────────────────────────┐     ┌───────────────────────────┐
│ captured_request()        │     │ queue.get()               │ ← instant
│   43ms idle wait (no CPU) │     │ inject cat (if active)    │
│ make_array("main") 15ms   │     │ motion_detect()  37ms     │
│ make_array("lores") 2ms   │     │ AI detect (if motion)     │
│ Y-plane copy              │     │ overlay data update        │
│ queue.put()               │     │ MJPEG annotation (if any) │
│   ↻ repeat                │     │   ↻ repeat                │
└───────────────────────────┘     └───────────────────────────┘
         │                                  ▲
         └──── queue.Queue(maxsize=1) ──────┘
```

### Timeline with overlap

```
Capture:  |--wait(43)--|--memcpy(17)--|--wait(43)--|--memcpy(17)--|
Process:                |------motion(37)------|------motion(37)------|
          ↑ memcpy overlaps with motion ↑

Effective frame time: max(60, 37) = 60ms → 16fps (vs current 97ms → 10fps)
```

### Thread Affinity (Pi Zero 2W, 4x Cortex-A53)

| Core | Thread               | Rationale                              |
|------|----------------------|----------------------------------------|
| 0    | CatDome-Proc         | Dedicated for motion + AI, hot cache   |
| 1    | CatDome-Cap          | Dedicated for memcpy, DMA-adjacent     |
| 2    | Flask + WebSocket    | Web serving, lower priority            |
| 3    | System / picamera2   | OS, camera internals, H.264 encoder    |

Set via `os.sched_setaffinity(0, {core_id})` at thread start.
Expected benefit: 5-15% from cache locality, no context switches.

### Expected Performance

| Metric              | Before (sequential) | After (pipelined)   |
|---------------------|---------------------|---------------------|
| cap (in PERF log)   | 61ms (includes wait)| ~1ms (queue.get)    |
| mot                 | 37ms                | 37ms (unchanged)    |
| Effective frame time| 97ms                | 60ms (camera-limited)|
| Processing FPS      | ~10fps              | ~16fps              |
| frame_skip          | 2 (every other)     | 1 (every frame)     |

### Implementation Details

**New: `_capture_loop` method (~30 lines)**
- Runs on dedicated thread `CatDome-Cap`
- Calls `captured_request()`, `make_array()`, Y-plane copy
- Puts `(frame, frame_lores, frame_lores_y, cap_ms)` into `queue.Queue(maxsize=1)`
- Handles file camera, mock camera, lores BGR conversion
- Respects `self.running` flag for shutdown

**Modified: `_process_loop`**
- Replace inline capture block (lines 529-574) with `queue.get(timeout=0.5)`
- All other processing unchanged (inject cat, phases, annotation, recording)
- `self._last_capture_ms` set from the tuple returned by queue

**Modified: `start()` method**
- Create `self._frame_queue = queue.Queue(maxsize=1)`
- Start capture thread before processing thread
- Set thread affinity for both threads

**Modified: `stop()` method**
- Signal `self.running = False`
- Capture thread exits, processing thread exits
- Join both threads

**Pending lores reconfigure:**
- Currently executed in processing thread because it uses camera APIs
- With capture thread: reconfigure moves to capture thread (it owns the camera)
- Processing thread sets `_pending_lores_reconfigure`, capture thread checks and executes

### Files Changed

- `web/app.py` — new `_capture_loop`, modified `_process_loop`, `start()`, `stop()`
- `config.py` — add `THREAD_AFFINITY_ENABLED = True` (optional, can disable on non-Pi)

### Risks

1. **Shutdown race**: capture thread may block in `captured_request()` when `stop()` is called.
   Mitigation: use timeout parameter or camera.stop() to unblock.

2. **Queue overflow**: if processing is slower than capture, `put(timeout=0.5)` drops the frame.
   This is correct behavior — always process the latest frame.

3. **Lores reconfigure**: must happen on the thread that owns the camera.
   Move reconfigure logic from process loop to capture loop.

4. **Thread affinity on non-Pi**: `os.sched_setaffinity` is Linux-only.
   Wrap in try/except, skip on Windows/Mac.

### Effort

~50 lines new code, ~20 lines modified. One new thread, one queue.
No changes to detection, tracking, or streaming logic.

---

## Solution: Option B — Zero-Copy from picamera2 DMA Buffers

### Background: How picamera2 Buffers Work

picamera2 uses DMA (Direct Memory Access) buffers allocated by the Linux V4L2/libcamera
stack. The camera ISP writes directly into these buffers — no CPU copy involved.

The buffer lifecycle is:

```
Camera ISP → DMA buffer (kernel) → mmap'd into userspace → CompletedRequest
                                                             │
                           ┌─────────────────────────────────┘
                           ▼
                    make_array()           MappedArray (ctx mgr)
                    ┌─────────────┐        ┌─────────────────────┐
                    │ np.copy()   │        │ np.array(b,copy=0)  │
                    │ returns NEW │        │ returns VIEW into   │
                    │ numpy array │        │ DMA buffer (0 copy) │
                    │ ~15ms main  │        │ ~0ms                │
                    │ ~ 2ms lores │        │                     │
                    └─────────────┘        └─────────────────────┘
                     (current code)         (zero-copy option)
```

**Source code proof** (from `picamera2/request.py`):

```python
# make_array() — ALWAYS copies:
def make_array(self, name):
    # "We don't want to send out an exported handle to the camera buffer,
    #  so we're going to have to do a copy."
    with MappedArray(self, name) as m:
        return np.copy(m.array)           # ← explicit copy

# MappedArray.__enter__() — zero-copy view:
def __enter__(self):
    b = self.__buffer.__enter__()
    array = np.array(b, copy=False)       # ← zero-copy
    array = helpers._make_array_shared(array, config)  # reshape, no copy
    self.__array = array
    return self
```

### The Constraint: Buffer Lifetime

The zero-copy view is valid **only while the CompletedRequest is held** (not released).
Once `request.release()` is called, the DMA buffer is re-queued to the camera and may
be overwritten by the next frame at any time.

```
  SAFE:     ├─ request held ──────── processing on view ──────── release ─┤
  UNSAFE:   ├─ request held ── release ─┤ ... ├─ processing on view (CORRUPT!) ─┤
```

This means: all read-only processing must complete before `request.release()`.
Any data that must outlive the request (snapshot, recording) must be explicitly copied.

### Current Copy Inventory

| Operation                        | Time   | Size     | Avoidable with zero-copy? |
|----------------------------------|--------|----------|---------------------------|
| `req.make_array("main")`        | ~15ms  | ~9.0 MB  | Yes — use MappedArray     |
| `req.make_array("lores")`       | ~2ms   | ~1.2 MB  | Yes — use MappedArray     |
| `lores_raw[:h, :].copy()` Y-pl  | ~1ms   | ~0.5 MB  | Yes — view is contiguous  |
| `frame_lores.copy()` for stream | ~1ms   | varies   | No — need writable copy   |
| `self.current_frame = frame`    | 0ms    | ref only | Must become a copy (*)    |
| **Total avoidable**             | **~18ms** |       |                           |

(*) Currently stores a reference to the copied array. With zero-copy, the view
becomes invalid after release, so `current_frame` must be an explicit copy — but
only when a snapshot or recording actually needs it (lazy copy).

### Approach B1: Zero-Copy Sequential (No Pipelining)

Hold the request open for the entire processing duration. Process directly on
the DMA buffer views. Copy only what must outlive the request.

```python
request = self.camera.captured_request()
try:
    with MappedArray(request, "main", write=False) as m_main, \
         MappedArray(request, "lores", write=False) as m_lores:
        frame = m_main.array              # zero-copy view (~0ms)
        lores_raw = m_lores.array         # zero-copy view (~0ms)
        lores_h = self._lores_resolution[1]
        frame_lores_y = lores_raw[:lores_h, :]  # view, no .copy() needed

        # ── All read-only processing on views ──
        # inject_cat: WRITES to frame → must copy first (see below)
        # motion_detect(frame_lores_y): read-only ✓
        # AI detect(frame[cy:cy+ch, cx:cx+cw]): read-only view of view ✓

        # ── Deferred copies (only when needed) ──
        if self.inject_cat:
            frame = np.copy(frame)  # need writable copy for pasting
        if self.stream_clients > 0:
            frame_lores = cv2.cvtColor(lores_raw, cv2.COLOR_YUV2BGR_I420)
        self.current_frame = np.copy(m_main.array)  # snapshot/recording
finally:
    request.release()
```

**Timeline:**
```
Sequential + zero-copy:
|--wait(43ms)--|--0ms--|------motion(37ms) + AI------|
                 ^no memcpy    ^processing on DMA view
                               Total: ~80ms → 12.5fps
```

**Pros:**
- Saves ~18ms of memcpy per frame (60% of capture time)
- Simple — no new threads, no queue
- ~80ms per frame → ~12.5fps (vs current 97ms → ~10fps, +25%)

**Cons:**
- DMA buffer held for ~37ms during processing → one fewer buffer available for camera
  (with `buffer_count=4`, camera still has 3 buffers — OK)
- Must copy for inject_cat (frame becomes writable) and current_frame (outlives request)
- No capture/processing overlap — still sequential

### Approach B2: Zero-Copy + Pipelined (Hold-Request Pattern)

Combine pipelining (Option A) with zero-copy. The capture thread passes the
**request itself** (not copied arrays) through the queue. The processing thread
works on zero-copy views and releases the request when done.

```
Capture thread (Core 1):             Process thread (Core 0):
┌───────────────────────────────┐    ┌───────────────────────────────────┐
│ req = captured_request()      │    │ req = queue.get()                 │
│   43ms idle wait (no CPU)     │    │ MappedArray(req, "main") → view  │ 0ms
│ req.acquire()  (bump refcount)│    │ MappedArray(req, "lores") → view │ 0ms
│ queue.put(req)                │    │ motion_detect(view)       37ms   │
│   ↻ repeat                   │    │ AI detect (if motion)             │
│                               │    │ copy frame only if needed         │
│   (no memcpy at all!)         │    │ req.release()                    │
└───────────────────────────────┘    └───────────────────────────────────┘
         │                                    ▲
         └──── queue.Queue(maxsize=1) ────────┘
```

**Timeline:**
```
Capture:  |--wait(43)--|--put--|--wait(43)--|--put--|
Process:                |---motion(37)---|---motion(37)---|
                          ^on DMA view      ^on DMA view

Effective frame time: max(43, 37) = 43ms → ~23fps (!)
```

Wait — the camera still delivers frames at ~16fps (60ms intervals). So:

```
Camera:   |──────60ms──────|──────60ms──────|──────60ms──────|
Capture:  |--wait(43)--put-|--wait(43)--put-|--wait(43)--put-|
Process:            |--motion(37)--|  |--motion(37)--|
                                   ↑idle           ↑idle

Effective frame time: 60ms (camera-limited) → ~16fps
```

Same FPS as Option A, but **capture thread does ~0ms of CPU work** (no memcpy).
The 17ms of CPU saved on the capture core is available for other tasks.

**Pros:**
- Same ~16fps as pipelined-with-copy, but much lower CPU usage
- Capture thread is almost pure idle-wait (no CPU burn on memcpy)
- ~18ms CPU savings per frame → ~30% less total CPU per frame
- Frees Core 1 for system tasks / reduces thermal throttling

**Cons:**
- Request held across threads — must carefully manage acquire/release lifecycle
- If processing thread is slow, DMA buffers accumulate (need `buffer_count ≥ 3`)
- Queue drops: if put() times out, must release the request (not just drop a numpy array)
- More complex error handling (request must always be released, even on exception)

### Approach B3: Hybrid (Copy Main, Zero-Copy Lores Only)

Minimal change: use MappedArray only for the lores stream (saves ~3ms), keep
`make_array("main")` as a copy (safe, simple). Compatible with Option A pipelining.

```python
with request as req:
    frame = req.make_array("main")              # 15ms copy (kept)
    with MappedArray(req, "lores", write=False) as m_lores:
        lores_raw = m_lores.array               # zero-copy
        lores_h = self._lores_resolution[1]
        frame_lores_y = lores_raw[:lores_h, :]  # zero-copy Y plane
        if self.stream_clients > 0:
            frame_lores = cv2.cvtColor(lores_raw, cv2.COLOR_YUV2BGR_I420)
        else:
            frame_lores_y = frame_lores_y.copy()  # must copy before exit
```

**Saves:** ~3ms (lores copy + Y-plane copy).
**Risk:** Low — main frame is still a safe copy, minimal code change.

### Comparison Table

| Approach                     | FPS   | CPU saved/frame | Complexity | Risk    |
|------------------------------|-------|-----------------|------------|---------|
| Current (sequential + copy)  | ~10   | baseline        | —          | —       |
| A: Pipelined + copy          | ~16   | 0 (redistributed)| Medium    | Medium  |
| B1: Zero-copy sequential     | ~12.5 | ~18ms           | Low        | Low     |
| B2: Zero-copy + pipelined    | ~16   | ~18ms           | High       | High    |
| B3: Hybrid (zc lores only)   | ~10   | ~3ms            | Low        | Low     |
| A + B1: Pipeline + zc seq    | ~16   | ~18ms           | Medium     | Medium  |
| A + B3: Pipeline + zc lores  | ~16   | ~3ms            | Medium     | Low     |

---

## Recommended Implementation: Phased Approach

### Overview

| Phase | What                        | FPS gain       | CPU saved    | Complexity | Risk   |
|-------|-----------------------------|----------------|--------------|------------|--------|
| 0     | TFLite file-cache warmup    | First detect: 3.5s→0.5s | none (boot) | Low | Low |
| 1     | Pipelined capture (Opt A)   | 10→16fps (IDLE)| overlap      | Medium     | Medium |
| 2     | Zero-copy hold-request (B2) | same 16fps     | ~18ms/frame  | Medium+    | Medium |
| 3     | TFLite inference thread     | 5→16fps (TRACKING) | unblocks proc | Medium | Medium |

Phase 0 is a quick win with no architectural changes — eliminates the 3.5s first-detection
cold-start penalty. Phase 1 gives the main FPS improvement during IDLE/ACQUISITION.
Phase 2 reduces CPU/thermal load by eliminating memcpy. Phase 3 removes the last
major bottleneck: the 175ms TFLite invoke that stalls the processing thread during
TRACKING, bringing tracking-phase FPS from ~5 to camera-limited ~16.

Skip B3 (hybrid lores-only zero-copy) — the 3ms saving isn't worth the code path.

### How the phases compose

```
Current (everything sequential on one thread):

Camera:  |──────100ms──────|──────100ms──────|──────100ms──────|
Process: |cap(60)│mot(28)│tf(175)│ann(26)│sleep│  ...repeats...
                          ↑ BLOCKED 175ms     ↑

FPS during IDLE:     ~10  (cap+mot = 97ms, limited by sequential capture)
FPS during TRACKING: ~5   (cap+mot+tf+ann ≈ 290ms per AI frame)
First detection:     3.5s (cold TFLite load + XNNPACK init)


After Phase 0 (warmup):
  First detection:   ~0.5s (file cache hot, XNNPACK re-init fast)
  Steady-state:      unchanged

After Phase 1 (pipelined capture):
  cap overlaps with processing → effective cap ≈ 0ms
  FPS during IDLE:     ~16  (camera-limited, mot=28ms < 60ms frame interval)
  FPS during TRACKING: ~5   (tf=175ms still blocks the process thread)

After Phase 2 (zero-copy):
  Same FPS, but ~18ms less CPU per frame (no memcpy on capture core)
  Reduces thermal throttling on Pi Zero 2W

After Phase 3 (TFLite thread):
  TFLite runs in parallel on cores 2-3, no longer blocks process thread
  FPS during TRACKING: ~16 (camera-limited, process thread only does mot+ann ≈ 55ms)
  Detection results arrive 2-3 frames late (tracker compensates)

Combined timeline (all 4 phases):

Camera:    |──────60ms──────|──────60ms──────|──────60ms──────|
Capture:   |--wait(43)--put-|--wait(43)--put-|--wait(43)--put-|  (Core 1)
Process:       |mot(28)─ann(26)│mot(28)─ann(26)│mot(28)─[result]─ann(26)│  (Core 0)
TFLite:              |─────────────tf(175)─────────────|         (Core 2-3)
                     ↑ submitted frame N                ↑ result ready (used at frame N+3)

Effective FPS: ~16 in ALL phases (camera-limited)
```

---

### Phase 0: TFLite File-Cache Warmup

**Goal:** Reduce first-detection penalty from 3.5s to ~0.5s. No architectural changes.

#### The problem

When TFLite loads for the first time (on first motion detection), two things are slow:

1. **Model load (`ld=1243ms`)**: reads the `.tflite` file from the SD card (cold file cache)
2. **First invoke (`inv=2271ms`)**: XNNPACK delegate JIT-compiles optimized kernels for Cortex-A53

Total: **3536ms** before the first detection result. During this time the processing
thread is blocked — no frames are processed, the stream freezes, and the cat (or real
target) may have moved out of the detection zone before AI even starts.

#### The solution

At startup, load the model, run one dummy invoke to warm all caches, then immediately
unload. This puts the model file in the OS page cache and warms the XNNPACK JIT. The
next real load (on first motion) reads from RAM instead of SD card, and XNNPACK
re-initializes much faster.

The model is unloaded immediately after warmup, so the XNNPACK worker threads
(which busy-spin even when idle, burning ~100% of one core) are killed. The TFLite
spin-wait problem that motivated the lazy-load design is preserved.

#### Why unloading after warmup is safe

The current design is:
```
Startup:  TFLite NOT loaded (no spin-wait threads)
Motion:   TFLite loaded on demand → spin-wait begins
Idle 10s: TFLite unloaded → spin-wait stops
```

With warmup:
```
Startup:  TFLite loaded → dummy invoke → TFLite unloaded (total ~3.5s, one-time)
Motion:   TFLite loaded on demand (fast: file in page cache) → spin-wait begins
Idle 10s: TFLite unloaded → spin-wait stops
```

The system startup already takes ~6s for camera init. The warmup adds ~3.5s to boot,
making total boot ~9.5s. This is acceptable because:
- The systemd service starts on boot — the user isn't waiting
- The 3.5s warmup happens ONCE; every subsequent first-detection is ~6x faster

#### File: `detection/detector.py`

##### Step 1: Add `_warmup_file_cache()` method

Add this method to the `ObjectDetector` class, after the existing `_load_model()`:

```python
def _warmup_file_cache(self):
    """Pre-load model into OS file cache, then unload.

    This warms the OS page cache (model file stays in RAM) and triggers
    XNNPACK JIT compilation so subsequent loads are fast (~100-200ms
    instead of ~1200ms). The interpreter is unloaded immediately after
    to avoid the XNNPACK spin-wait CPU burn.

    Called once at startup. Adds ~3.5s to boot time but makes the
    first real detection ~6x faster (3.5s → 0.5s).
    """
    if not TFLITE_AVAILABLE:
        return
    model_path = os.path.join(config.MODELS_DIR, config.MODEL_FILENAME)
    if not os.path.exists(model_path):
        return

    plog("[DETECTOR] Warming file cache (one-time)...")
    self._load_model()
    if self.interpreter is None:
        return

    # Run one dummy invoke to trigger XNNPACK JIT kernel compilation.
    # Without this, the first real invoke is ~2.3s; with it, ~200-400ms.
    try:
        dummy = np.zeros(
            (1, self.input_h, self.input_w, 3), dtype=np.uint8)
        self.interpreter.set_tensor(
            self.input_details[0]['index'], dummy)
        self.interpreter.invoke()
    except Exception as e:
        plog("[DETECTOR] Warmup invoke failed: %s", e)

    # Unload: kills XNNPACK spin-wait threads, but OS page cache retains
    # the model file in RAM. Next _load_model() reads from RAM (~100ms).
    self.unload_model()
    plog("[DETECTOR] File cache warm, TFLite unloaded")
```

##### Step 2: Call warmup in `__init__`

In `ObjectDetector.__init__()`, after the existing `_ensure_model_exists()` call
(currently at line 62) and the "TFLite model ready" log message, add:

```python
        self._warmup_file_cache()
```

The full init sequence becomes:
```python
    self._ensure_model_exists()
    plog("TFLite model ready (will load on first motion detection)")
    self._warmup_file_cache()
```

##### Step 3: Add numpy import if not present

The warmup method uses `np.zeros()`. Verify that `import numpy as np` is at the
top of `detection/detector.py`. It should already be there (used by `_input_buf`
pre-allocation in `_load_model()`).

#### Expected results

| Metric                  | Before    | After warmup |
|-------------------------|-----------|--------------|
| Boot time               | ~6s       | ~9.5s        |
| First `ld` (model load) | 1243ms    | ~100-200ms   |
| First `inv` (invoke)    | 2271ms    | ~200-400ms   |
| First detection total   | 3536ms    | ~300-600ms   |
| Steady-state `inv`      | ~175ms    | ~175ms (unchanged) |
| IDLE CPU (no motion)    | 0% TFLite | 0% TFLite (unchanged) |

#### Testing Phase 0

1. Restart service: `sudo systemctl restart cat_dome`
2. Watch journal: should see `[DETECTOR] Warming file cache (one-time)...` followed
   by `Model loaded. Input shape: [...]` then `[DETECTOR] File cache warm, TFLite unloaded`
3. Trigger inject cat test. First PERF line should show `tf=...` with `ld=` well under 500ms
   (vs 1243ms before).
4. Verify no TFLite CPU spin during IDLE (check `htop` — no 100% core after boot).
5. Verify `ld=0.0` on subsequent loads (model was already loaded lazily, not re-warmed).

#### Memory consideration (Pi Zero 2W, 416MB RAM)

The `.tflite` model file is ~4MB. After warmup, it's in the OS page cache. The OS
can evict it under extreme memory pressure (avail < ~30MB). If this happens, the
next load falls back to SD card speed (~1.2s) — which is the same as the current
behavior. No downside risk.

#### Effort

~25 lines new code in `detection/detector.py`. No other files changed.
No changes to detection, tracking, streaming, or web routes.

---

### Phase 1: Pipelined Capture (Option A)

**Goal:** Overlap the 43ms camera idle-wait with the 37ms processing. 10fps → 16fps.

#### File: `web/app.py`

##### Step 1: Add `import queue` at top of file

Add `import queue` near the existing `import threading` (around line 6-15).

##### Step 2: Add `_capture_loop()` method to `VideoProcessor`

Create a new method. This is the capture thread's main loop. It replaces the
inline capture block currently at lines 536-581 of `_process_loop()`.

```python
def _capture_loop(self):
    """Capture thread — blocks on camera, copies frames, feeds queue.

    Runs on a dedicated thread (CatDome-Cap). Owns the camera: all
    captured_request() and reconfigure calls happen here.
    """
    # Set OS thread name for htop/top visibility
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6')
        libc.prctl(15, b'CatDome-Cap', 0, 0, 0)
    except Exception:
        pass

    # Optional: pin to Core 1
    try:
        os.sched_setaffinity(0, {1})
    except Exception:
        pass

    while self.running:
        try:
            # ── Pending lores reconfigure ──
            # Must happen on the capture thread because it owns the camera.
            # The processing thread sets _pending_lores_reconfigure; we pick it up.
            if self._pending_lores_reconfigure is not None:
                new_lores_w, new_lores_h = self._pending_lores_reconfigure
                self._pending_lores_reconfigure = None
                if self.camera.reconfigure_lores(new_lores_w, new_lores_h):
                    old_lores = self._lores_resolution
                    self._lores_resolution = (new_lores_w, new_lores_h)
                    self._using_lores = True
                    profile = config.PERFORMANCE_PROFILES.get(self.current_profile, {})
                    adjusted_scale = self._lores_motion_scale(
                        profile.get("motion_scale", 0.25))
                    self.motion_detector.update_parameters(
                        detection_scale=adjusted_scale)
                    plog("[LORES] Reconfigured %s×%s → %s×%s, motion_scale=%.2f",
                         old_lores[0], old_lores[1], new_lores_w, new_lores_h,
                         adjusted_scale)

            # ── Capture a frame ──
            t0 = time.perf_counter()

            frame = None
            frame_lores = None
            frame_lores_y = None
            _lores_from_isp = False

            if (self.video_source == "file" and self.file_camera
                    and self.file_camera.running):
                frame = self.file_camera.get_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue
                if self._using_lores:
                    frame_lores = cv2.resize(
                        frame, self._lores_resolution,
                        interpolation=cv2.INTER_LINEAR)
            else:
                request = self.camera.get_request()
                if request is None:
                    # Mock camera fallback
                    frame = self.camera.get_frame()
                    if frame is None:
                        time.sleep(0.01)
                        continue
                    if self._using_lores:
                        frame_lores = cv2.resize(
                            frame, self._lores_resolution,
                            interpolation=cv2.INTER_LINEAR)
                else:
                    with request as req:
                        frame = req.make_array("main")
                        if self._using_lores:
                            lores_raw = req.make_array("lores")
                            lores_h_px = self._lores_resolution[1]
                            frame_lores_y = lores_raw[:lores_h_px, :].copy()
                            if self.stream_clients > 0:
                                frame_lores = cv2.cvtColor(
                                    lores_raw, cv2.COLOR_YUV2BGR_I420)
                            else:
                                _lores_from_isp = True

            cap_ms = round((time.perf_counter() - t0) * 1000, 1)

            # ── Put into queue (drop old frame if processing is behind) ──
            payload = (frame, frame_lores, frame_lores_y,
                       _lores_from_isp, cap_ms)
            try:
                self._frame_queue.put(payload, timeout=0.5)
            except queue.Full:
                # Processing thread is behind — drop this frame
                pass

        except Exception as e:
            plog("[CAPTURE] Error: %s", e)
            time.sleep(0.1)
```

**Key points an implementing agent must know:**
- The lores reconfigure block (currently at `_process_loop` lines 520-534) MOVES here.
  Delete it from `_process_loop()`.
- `self.stream_clients` is read cross-thread — this is safe because it's an int
  (atomic read on CPython/GIL). If it's briefly stale, the only effect is one extra
  or one skipped BGR conversion — harmless.
- `queue.Full` means processing is slower than capture. Dropping the frame is correct:
  we always want the latest frame.
- `_lores_from_isp` flag is passed through the queue so the processing thread knows
  whether deferred BGR conversion is available.

##### Step 3: Modify `_process_loop()` — replace capture block with queue.get()

**Delete** the entire inline capture block in `_process_loop()`. This is the code
between the `t_capture_start` timing line and the `self._last_capture_ms` line
(approximately lines 536-581, from `t_capture_start = time.perf_counter()` through
the end of the `with request as req:` block).

Also **delete** the lores reconfigure block (lines 520-534) — it moved to
`_capture_loop()`.

**Replace** with:

```python
                # ── Frame from capture thread ──
                try:
                    payload = self._frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                (frame, frame_lores, frame_lores_y,
                 _lores_from_isp, cap_ms) = payload
                if frame is None:
                    continue
                self._last_capture_ms = cap_ms
```

The indentation must match the existing code (4 levels = 16 spaces, inside
`while self.running: try:`).

**Everything after** this point in `_process_loop()` stays unchanged:
`frame_h, frame_w = frame.shape[:2]`, inject_cat, phase state machine, annotation,
recording, perf logging — all untouched.

##### Step 4: Modify `start()` — create queue, start both threads

In the `start()` method, after the camera/lores setup (after line ~452) and before
starting the processing thread (currently line 464):

```python
        # Create frame queue for capture → processing pipeline
        self._frame_queue = queue.Queue(maxsize=1)

        # Start capture thread (must start before processing thread)
        self.running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="CatDome-Cap")
        self._capture_thread.start()
```

**Move** `self.running = True` up (it's currently at line 464, before the process
thread start). It must be set before starting the capture thread.

The existing process thread start stays as-is (line 465-466). Optionally add
thread affinity to pin it to Core 0:

```python
        # Add after process_thread.start():
        # Optional: pin processing thread to Core 0
        # (Done inside _process_loop() start, similar to capture thread)
```

Or add the affinity inside `_process_loop()` at the top, after the thread name:
```python
        try:
            os.sched_setaffinity(0, {0})
        except Exception:
            pass
```

##### Step 5: Modify `stop()` — join both threads

After `self.running = False` (line 473), join the capture thread:

```python
    def stop(self):
        """Stop all components"""
        self.running = False
        self._stop_recording()
        # Wait for capture thread to finish
        if hasattr(self, '_capture_thread') and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)
        if self.file_camera:
            self.file_camera.stop()
            self.file_camera = None
        if self.camera:
            self.camera.stop()
        print("Video processor stopped")
```

The capture thread will exit because `self.running = False` and
`captured_request()` will either return (with a frame) or fail after
`camera.stop()` is called. The 3s timeout prevents hanging.

##### Step 6: Handle the `_pending_lores_reconfigure` comment

The comment at line 520-521 says "Must execute here (processing thread) because
camera capture is on this thread." — this is no longer true. Update the comment
in `_capture_loop()` and remove the reconfigure block from `_process_loop()`.

The processing thread can still SET the flag (`self._pending_lores_reconfigure`).
No — actually, the Flask thread sets it (via `set_stream_resolution()`). The capture
thread picks it up. This is correct cross-thread communication via a volatile flag.

#### File: `config.py` (optional)

```python
# Thread affinity: pin capture/processing to specific cores (Pi Zero 2W)
THREAD_AFFINITY_ENABLED = True
CAPTURE_THREAD_CORE = 1
PROCESS_THREAD_CORE = 0
```

Wrap affinity calls in `if config.THREAD_AFFINITY_ENABLED:` so it can be disabled
on dev machines.

#### Testing Phase 1

1. Run on Pi Zero 2W. Check PERF log: `cap` should drop from ~61ms to ~1ms.
2. FPS should increase from ~10 to ~16 (camera-limited).
3. Verify inject_cat still works (frame is modified after capture).
4. Verify snapshot works (`get_frame_jpeg_capture_resolution()`).
5. Verify lores reconfigure works (change stream resolution from web UI).
6. Verify clean shutdown (`sudo systemctl stop catdome`).
7. Verify file camera mode still works.

---

### Phase 2: Zero-Copy Hold-Request (Option B2, applied to Phase 1)

**Goal:** Eliminate ~18ms/frame of memcpy CPU. Same 16fps, but ~30% less CPU load
per frame. Reduces thermal throttling risk on Pi Zero 2W.

**Approach:** Instead of copying arrays in the capture thread and passing numpy
arrays through the queue, pass the **CompletedRequest itself**. The processing
thread opens `MappedArray` (zero-copy view), processes on the DMA buffer, copies
only what it needs, then releases the request.

#### Why this works

The processing thread already needs the data for:
- Motion detection: uses `frame_lores_y` (Y-plane) — read-only on small buffer
- AI detection: uses `frame[cy:cy+ch, cx:cx+cw]` — read-only view of main
- inject_cat: writes to `frame` — needs copy ONLY when inject is active
- Annotation: uses `frame_lores` or `frame` for stream resize — produces a new copy
- `self.current_frame`: stores for snapshot — needs copy to outlive the request
- Recording: `annotated = frame` — reference only, same frame

With zero-copy, ALL the read-only operations work directly on the DMA buffer.
Copies happen only for:
- `self.current_frame` (always, ~15ms, but can be made lazy — see below)
- `inject_cat` paste (only when inject is active — rare/testing only)
- Stream annotation (already copies via resize/cvtColor — no change)

**Lazy `current_frame` optimization:** `self.current_frame` is only READ by
`get_frame_jpeg_capture_resolution()` (called on snapshot button click from web UI).
Instead of copying every frame, store a "frame ready" callback or copy only on
snapshot request. But this adds complexity — start with always-copy and optimize
later if profiling shows it matters.

#### File: `web/app.py`

##### Step 1: Import MappedArray

At the top of the file, add:

```python
try:
    from picamera2.request import MappedArray
except ImportError:
    MappedArray = None  # Not available on dev machines / mock camera
```

##### Step 2: Rewrite `_capture_loop()` — pass request through queue

Replace the `with request as req: make_array(...)` block in `_capture_loop()`
with passing the raw request:

```python
def _capture_loop(self):
    """Capture thread — blocks on camera, feeds request/frame to queue.

    For real camera: passes CompletedRequest (processing thread does zero-copy).
    For mock/file camera: passes numpy arrays (no DMA buffer to map).
    """
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6')
        libc.prctl(15, b'CatDome-Cap', 0, 0, 0)
    except Exception:
        pass

    try:
        os.sched_setaffinity(0, {1})
    except Exception:
        pass

    while self.running:
        try:
            # ── Pending lores reconfigure ──
            if self._pending_lores_reconfigure is not None:
                new_lores_w, new_lores_h = self._pending_lores_reconfigure
                self._pending_lores_reconfigure = None
                if self.camera.reconfigure_lores(new_lores_w, new_lores_h):
                    old_lores = self._lores_resolution
                    self._lores_resolution = (new_lores_w, new_lores_h)
                    self._using_lores = True
                    profile = config.PERFORMANCE_PROFILES.get(
                        self.current_profile, {})
                    adjusted_scale = self._lores_motion_scale(
                        profile.get("motion_scale", 0.25))
                    self.motion_detector.update_parameters(
                        detection_scale=adjusted_scale)
                    plog("[LORES] Reconfigured %s×%s → %s×%s",
                         old_lores[0], old_lores[1],
                         new_lores_w, new_lores_h)

            t0 = time.perf_counter()

            if (self.video_source == "file" and self.file_camera
                    and self.file_camera.running):
                # File source: numpy arrays, no DMA buffer
                frame = self.file_camera.get_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue
                frame_lores = None
                if self._using_lores:
                    frame_lores = cv2.resize(
                        frame, self._lores_resolution,
                        interpolation=cv2.INTER_LINEAR)
                cap_ms = round((time.perf_counter() - t0) * 1000, 1)
                payload = ("numpy", frame, frame_lores, None, False, cap_ms)

            else:
                request = self.camera.get_request()
                if request is None:
                    # Mock camera: numpy arrays
                    frame = self.camera.get_frame()
                    if frame is None:
                        time.sleep(0.01)
                        continue
                    frame_lores = None
                    if self._using_lores:
                        frame_lores = cv2.resize(
                            frame, self._lores_resolution,
                            interpolation=cv2.INTER_LINEAR)
                    cap_ms = round(
                        (time.perf_counter() - t0) * 1000, 1)
                    payload = ("numpy", frame, frame_lores,
                               None, False, cap_ms)
                else:
                    # Real camera: pass request for zero-copy in proc thread
                    # Do NOT enter the `with request as req:` context —
                    # processing thread will do MappedArray + release.
                    cap_ms = round(
                        (time.perf_counter() - t0) * 1000, 1)
                    payload = ("request", request, cap_ms)

            try:
                # If queue is full, drop the OLD frame (not the new one).
                # This ensures we always process the LATEST frame.
                try:
                    old = self._frame_queue.get_nowait()
                    # If we dropped a request, we must release it!
                    if old[0] == "request":
                        try:
                            old[1].release()
                        except Exception:
                            pass
                except queue.Empty:
                    pass
                self._frame_queue.put_nowait(payload)
            except queue.Full:
                # Should not happen after get_nowait, but safety:
                if payload[0] == "request":
                    try:
                        payload[1].release()
                    except Exception:
                        pass

        except Exception as e:
            plog("[CAPTURE] Error: %s", e)
            time.sleep(0.1)
```

**Critical detail:** The queue now holds either:
- `("numpy", frame, frame_lores, frame_lores_y, _lores_from_isp, cap_ms)` — for
  mock/file camera (same as Phase 1)
- `("request", CompletedRequest, cap_ms)` — for real camera (new in Phase 2)

When dropping old queue entries, we MUST `release()` any CompletedRequest we drop.
Failing to do so leaks DMA buffers and eventually starves the camera pipeline.

##### Step 3: Rewrite `_process_loop()` capture section — zero-copy unwrap

Replace the `queue.get()` block in `_process_loop()` (from Phase 1) with:

```python
                # ── Frame from capture thread ──
                try:
                    payload = self._frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                _held_request = None  # Track for release in finally
                frame = None
                frame_lores = None
                frame_lores_y = None
                _lores_from_isp = False

                if payload[0] == "numpy":
                    # Mock/file camera: arrays already copied
                    _, frame, frame_lores, frame_lores_y, \
                        _lores_from_isp, cap_ms = payload
                    if frame is None:
                        continue
                    self._last_capture_ms = cap_ms

                elif payload[0] == "request":
                    # Real camera: zero-copy from DMA buffer
                    _, request, cap_ms = payload
                    _held_request = request
                    self._last_capture_ms = cap_ms

                    try:
                        # Open zero-copy views into DMA buffer.
                        # These are numpy arrays backed by mmap'd kernel memory.
                        # Valid until request.release() — do ALL processing first.
                        self._m_main = MappedArray(
                            request, "main", write=False)
                        self._m_main.__enter__()
                        frame = self._m_main.array  # zero-copy view, ~0ms

                        if self._using_lores:
                            self._m_lores = MappedArray(
                                request, "lores", write=False)
                            self._m_lores.__enter__()
                            lores_raw = self._m_lores.array  # zero-copy
                            lores_h_px = self._lores_resolution[1]
                            # Y-plane slice: contiguous view, no copy needed.
                            # Motion detector reads this; it's valid until
                            # we release the request at end of iteration.
                            frame_lores_y = lores_raw[:lores_h_px, :]
                            if self.stream_clients > 0:
                                # cvtColor produces a NEW array (not a view),
                                # so this is safe after release too.
                                frame_lores = cv2.cvtColor(
                                    lores_raw, cv2.COLOR_YUV2BGR_I420)
                            else:
                                _lores_from_isp = True
                    except Exception as e:
                        plog("[ZEROCOPY] MappedArray failed: %s", e)
                        # Fallback: release request and skip this frame
                        if _held_request:
                            try:
                                request.release()
                            except Exception:
                                pass
                            _held_request = None
                        continue
```

##### Step 4: Add request release at end of each iteration

At the **very end** of the `try:` block inside the `while self.running:` loop
(after all processing, annotation, recording, perf logging — currently around
line 1040), add the release logic:

```python
                # ── Release DMA buffer back to camera ──
                # MUST happen after ALL processing that reads frame/lores views.
                if _held_request is not None:
                    # Close MappedArray contexts
                    try:
                        if hasattr(self, '_m_lores') and self._m_lores:
                            self._m_lores.__exit__(None, None, None)
                            self._m_lores = None
                    except Exception:
                        pass
                    try:
                        if hasattr(self, '_m_main') and self._m_main:
                            self._m_main.__exit__(None, None, None)
                            self._m_main = None
                    except Exception:
                        pass
                    try:
                        _held_request.release()
                    except Exception:
                        pass
                    _held_request = None
```

Also add the same release in the outer `except Exception:` handler to avoid
leaking buffers on error:

```python
            except Exception as e:
                plog("[PROC] Error: %s", e)
                # Release any held DMA buffer on error
                if _held_request is not None:
                    try:
                        if hasattr(self, '_m_lores') and self._m_lores:
                            self._m_lores.__exit__(None, None, None)
                        if hasattr(self, '_m_main') and self._m_main:
                            self._m_main.__exit__(None, None, None)
                        _held_request.release()
                    except Exception:
                        pass
                    _held_request = None
                time.sleep(0.1)
```

##### Step 5: Fix `self.current_frame` — must copy before release

Currently at line 976:
```python
                    with self.frame_lock:
                        self.current_frame = frame
```

With zero-copy, `frame` is a view into the DMA buffer that becomes invalid after
release. Change to:

```python
                    with self.frame_lock:
                        # Must copy: frame may be a DMA view released at end of iteration
                        self.current_frame = np.copy(frame) if _held_request else frame
```

This is the ONE mandatory copy per frame (~15ms for 2304×1296×3). To optimize
further, see "Lazy current_frame" below.

##### Step 6: Fix `inject_cat` — must copy before writing

Currently at line 590-597:
```python
                if self.inject_cat and self.inject_cat_handler:
                    frame = self.inject_cat_handler.paste_on_frame(frame)
```

`paste_on_frame()` writes to the array. With zero-copy, `frame` is read-only DMA
memory (writing to it corrupts the camera buffer). Change to:

```python
                if self.inject_cat and self.inject_cat_handler:
                    # Zero-copy frame is read-only DMA memory — must copy before writing
                    if _held_request is not None:
                        frame = np.copy(frame)
                    frame = self.inject_cat_handler.paste_on_frame(frame)
```

When `inject_cat` is disabled (normal production use), no copy happens here.

##### Step 7: Verify all other `frame` usage is read-only

Audit every use of `frame` after capture. All of these are safe with a read-only
DMA view (no changes needed):

| Usage                                    | Line | Read/Write | Safe? |
|------------------------------------------|------|------------|-------|
| `frame_h, frame_w = frame.shape[:2]`    | 583  | Read       | Yes   |
| `frame[cy:cy+ch, cx:cx+cw]` (AI crop)  | 790  | Read view  | Yes   |
| `self.detector.detect(frame)`           | 801  | Read       | Yes   |
| `frame.shape` (crop region calc)        | 692  | Read       | Yes   |
| `annotated = frame`                     | 900  | Alias      | Yes*  |
| `_resize_for_stream(frame, ...)`        | 907  | Read       | Yes   |
| `self.current_frame = frame`            | 976  | Copy (Step 5) | Yes |

(*) `annotated` is only passed to `self._recording_writer.write(annotated)` at
line 987. OpenCV's `VideoWriter.write()` reads the array — safe. But if recording
writes happen after the DMA buffer is released, we get corruption. Since the
release is at the END of the iteration (after recording), this is fine.

##### Lazy `current_frame` Optimization (optional, Phase 2b)

The `self.current_frame = np.copy(frame)` copy is ~15ms and happens EVERY frame,
but is only READ on snapshot (rare button click). To make it lazy:

```python
                    # Instead of copying every frame, store a "copy on demand" sentinel
                    with self.frame_lock:
                        if _held_request is not None:
                            # Store a copy — required because DMA buffer is released
                            # TODO: could defer copy to snapshot time if profiling shows
                            # this 15ms matters. Would need to hold the request longer
                            # or use a double-buffer scheme.
                            self.current_frame = np.copy(frame)
                        else:
                            self.current_frame = frame
```

A more aggressive optimization: only copy when a snapshot is pending. But this
requires the snapshot endpoint to signal the processing thread, adding latency
to the snapshot path. Not recommended unless profiling proves the 15ms matters.

#### Buffer Count Consideration

With zero-copy, one DMA buffer is held during processing (~37ms). At 60ms frame
intervals with `buffer_count=4`:
- 1 buffer: being filled by camera ISP
- 1 buffer: held by processing thread (zero-copy view)
- 2 buffers: available for camera pipeline and H.264 encoder

This is safe. Do NOT reduce `buffer_count` below 4 when H.264 encoding is active.
If CPU load testing shows the processing thread holds buffers too long (e.g., AI
detection takes >60ms), increase to `buffer_count=5`.

#### Format-Specific Contiguity Notes

- **RGB888 main** (2304×1296×3): stride = 6912 = w×3 → fully C-contiguous.
  `MappedArray` reshape is a free view. No issues.
- **YUV420 lores** (960×540): reshaped to (810, stride). Y plane = rows 0-539.
  If stride = 960 (no padding): Y plane slice is C-contiguous.
  If stride > 960 (64-byte aligned): Y plane has row padding but OpenCV handles
  strided arrays natively. Verify at runtime with:
  `assert frame_lores_y.data.c_contiguous or frame_lores_y.strides[1] == 1`

#### Testing Phase 2

1. **FPS unchanged:** Still ~16fps (camera-limited). Verify via PERF log.
2. **CPU reduction:** Check `htop` — capture thread core should be nearly idle
   (no 17ms memcpy spike). Processing thread CPU should be ~same.
3. **Thermal:** Run for 30 minutes. Compare CPU temp vs Phase 1 baseline.
4. **Buffer leak test:** Run for 1 hour. If DMA buffers leak, captured_request()
   will start timing out (>1s) or camera will hang. Monitor via PERF log `cap` time.
5. **Inject cat:** Must still work (triggers np.copy before paste).
6. **Snapshot:** Verify snapshot JPEG is valid (not corrupted/black).
7. **Recording:** Verify recorded MP4 frames are valid.
8. **Stream:** Verify MJPEG stream shows correct frames.
9. **Edge case: frame drop.** Stop the process thread (breakpoint/sleep 5s). Resume.
   Verify dropped requests are released (no buffer starvation).
10. **Edge case: shutdown.** `sudo systemctl stop catdome` — no hang, no crash.

#### Rollback

If Phase 2 causes instability, revert to Phase 1 by changing the capture thread
back to `make_array()` and passing numpy arrays through the queue (remove the
`"request"` payload path). The processing thread changes are isolated to the
payload unwrap section — easy to `git revert`.

---

### Phase 3: TFLite Inference Thread

**Goal:** Move TFLite inference off the processing thread so it no longer blocks
motion detection, annotation, or stream updates. Tracking-phase FPS: ~5 → ~16.

#### The problem

In TRACKING phase, TFLite `invoke()` takes **175ms** and runs synchronously on
the processing thread. During that time:
- No new frames are processed (motion detection stalls)
- The MJPEG/H.264 stream freezes for 175ms every 3rd frame
- Effective FPS drops to ~5 even though the camera delivers frames at ~16fps

This is the **single biggest bottleneck** once pipelining (Phase 1) is in place.

#### The solution: async AI with request/result queues

Move `detector.detect()` to a dedicated thread (`CatDome-AI`) pinned to cores 2-3.
The processing thread submits crop regions and fetches results non-blocking:

```
Core 0: Process thread           Core 2-3: AI thread
┌──────────────────────────┐     ┌──────────────────────────────┐
│ frame from cap queue     │     │ ai_queue.get(block=True)     │
│ inject cat (if active)   │     │   (crop, inject_bbox, meta)  │
│ motion_detect()   28ms   │     │                              │
│ if needs_AI:             │     │ detector.detect(crop)  175ms │
│   ai_queue.put(crop)     │─────│   (XNNPACK on 2 cores)      │
│                          │     │                              │
│ result = try_get()       │◄────│ result_queue.put(detections) │
│ if result:               │     │   ↻ repeat                   │
│   filter + world coords  │     │                              │
│   phase transitions      │     │                              │
│ tracking (use latest)    │     │                              │
│ annotation + JPEG  26ms  │     │                              │
│   ↻ repeat               │     │                              │
└──────────────────────────┘     └──────────────────────────────┘
        │                              ▲         │
        └── ai_queue (maxsize=1) ──────┘         │
        ◄── result_queue (maxsize=1) ────────────┘
```

#### Timeline comparison

**Before Phase 3 (TFLite on process thread, every 3rd frame):**

```
Process: |mot─ann│mot─ann│mot─────────tf(175)──────────ann│mot─ann│mot─ann│...
Frame:     N       N+1         N+2 (STALLED 175ms)          N+3     N+4
                                    ↑ stream frozen
Total 3-frame cycle: 55+55+260 = 370ms → ~2.7 FPS per 3 frames → effective ~8 FPS
```

**After Phase 3 (TFLite on separate thread):**

```
Process: |mot─ann│mot─ann│mot─[submit]─[get_result]─ann│mot─ann│mot─ann│...
Frame:     N       N+1              N+2                   N+3     N+4
AI:             |───────────────tf(175)────────────────|
                ↑ submitted at frame N+1                ↑ result arrives at N+2

Process time per frame: mot(28)+ann(26) = 54ms → ~16 FPS (camera-limited!)
```

The process thread is never blocked by TFLite. It submits a crop, continues with
motion + annotation, and picks up the result on a later frame.

#### Detection latency tradeoff

Detection results arrive **2-3 frames behind** (175ms / 60ms ≈ 3 frames). This means:

- Frame N: cat enters Detection Zone, motion detected
- Frame N: crop submitted to AI thread
- Frame N+3: AI result arrives → ACQUISITION → TRACKING phase transition

The **tracker handles this naturally** — it already uses centroid distance matching
and tolerates gaps. The detection is still applied to the correct frame coordinates
because the crop region was computed at submit time.

For the top-down view and annotation, results are drawn on the current frame using
the last available detection. The bounding box may be 2-3 frames stale, but at
2px/frame cat movement this is ~6px offset — well within the tracking tolerance.

#### Thread affinity update

| Core | Thread         | Work                                    | CPU budget |
|------|----------------|-----------------------------------------|------------|
| 0    | CatDome-Proc   | motion(28ms) + tracking + annotation    | ~54ms/60ms |
| 1    | CatDome-Cap    | camera wait(43ms) + memcpy(17ms)        | ~17ms/60ms |
| 2-3  | CatDome-AI     | TFLite invoke (175ms, num_threads=2)    | ~175ms/180ms |

Key: **reduce TFLite `num_threads` from 3 to 2** since AI is pinned to 2 cores.
This also means XNNPACK spin-wait (when loaded) only burns cores 2-3, leaving
cores 0-1 completely free for capture + processing.

#### File: `web/app.py`

##### Step 1: Add AI queues to `__init__`

In `VideoProcessor.__init__()`, alongside the existing state variables:

```python
        # AI thread queues (Phase 3: async TFLite inference)
        self._ai_request_queue = None   # Created in start()
        self._ai_result_queue = None    # Created in start()
        self._ai_thread = None
        self._last_ai_detections = []   # Latest detections from AI thread
        self._last_ai_crop_region = None  # Crop region used for last AI result
        self._ai_frame_counter = 0      # Which frame the last result was for
```

##### Step 2: Add `_ai_loop()` method

This is the AI thread's main loop. It blocks waiting for crops, runs TFLite, and
returns detections.

```python
def _ai_loop(self):
    """AI inference thread — runs TFLite on submitted crops.

    Blocks on ai_request_queue, runs detector.detect(), puts results
    on ai_result_queue. Pinned to cores 2-3 for XNNPACK thread affinity.
    """
    # Set OS thread name
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6')
        libc.prctl(15, b'CatDome-AI', 0, 0, 0)
    except Exception:
        pass

    # Pin to cores 2-3 (XNNPACK uses num_threads=2 within these cores)
    try:
        os.sched_setaffinity(0, {2, 3})
    except Exception:
        pass

    while self.running:
        try:
            # Block until the process thread submits a crop
            try:
                request = self._ai_request_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            crop_frame, crop_region, inject_info, frame_counter = request

            # Run TFLite inference (this is the 175ms blocking call)
            detections = self.detector.detect(crop_frame)

            # Remap crop-local coordinates to full-frame coordinates
            if crop_region is not None:
                cx, cy, cw, ch = crop_region
                detections = [
                    (x1 + cx, y1 + cy, x2 + cx, y2 + cy, conf, cls)
                    for x1, y1, x2, y2, conf, cls in detections
                ]

            # Inject Cat fallback: if TFLite didn't find the pasted cat,
            # inject a synthetic detection at the known bbox.
            if inject_info is not None:
                bbox, cat_class_id, proximity = inject_info
                tflite_found = any(
                    abs((d[0]+d[2])/2 - (bbox[0]+bbox[2])/2) < proximity and
                    abs((d[1]+d[3])/2 - (bbox[1]+bbox[3])/2) < proximity
                    for d in detections
                )
                if not tflite_found:
                    detections.append((
                        bbox[0], bbox[1], bbox[2], bbox[3],
                        config.INJECT_FALLBACK_CONFIDENCE, cat_class_id))

            # Put result — drop old result if process thread hasn't picked it up
            try:
                self._ai_result_queue.get_nowait()  # discard stale result
            except queue.Empty:
                pass
            self._ai_result_queue.put(
                (detections, crop_region, frame_counter))

        except Exception as e:
            plog("[AI] Error: %s", e)
            import traceback
            traceback.print_exc()
            time.sleep(0.1)
```

**Key points for the implementing agent:**

- `crop_frame` is the cropped numpy array (380×380×3 or full frame). It was copied
  from the main frame at submit time, so it's safe even if the DMA buffer is released.
- `crop_region` is `(cx, cy, cw, ch)` or `None`. When not None, detection coordinates
  must be offset by `(cx, cy)` to get full-frame coordinates.
- `inject_info` is `(bbox, cat_class_id, proximity)` or `None`. The fallback detection
  logic (currently at app.py lines 809-821) moves HERE from the process loop.
- `frame_counter` lets the process thread know which frame the result is for (useful
  for latency logging, not required for correctness).
- The result queue uses get_nowait + put to always hold the latest result. If the
  process thread is slower than AI (shouldn't happen), old results are discarded.

##### Step 3: Modify `_process_loop()` — submit crops and fetch results

The current AI detection block in the process loop (ACQUISITION/TRACKING phases) is:

```python
# Current (synchronous, blocks 175ms):
run_ai_detection = True
crop_region = self.inject_cat_handler.get_crop_region(...) or \
              self.motion_detector.get_fixed_crop_region(...)
# ... later in "AI DETECTION" section:
if run_ai_detection:
    cropped_frame = frame[cy:cy+ch, cx:cx+cw]
    detections = self.detector.detect(cropped_frame)  # ← 175ms BLOCK
    # ... fallback inject, filter, world coords, phase transition
```

Replace with **two separate operations**: submit and fetch.

**Submit (in ACQUISITION/TRACKING phase blocks, where `run_ai_detection = True`):**

Replace the crop region + `run_ai_detection = True` blocks. Instead of setting
`run_ai_detection`, submit to the AI queue:

```python
                    # ── PHASE: ACQUISITION ──
                    elif self._phase == "ACQUISITION":
                        # ... motion detection (unchanged) ...

                        # Submit crop to AI thread every frame during acquisition
                        crop_size = self.current_motion_crop_size
                        if self.inject_cat and self.inject_cat_handler:
                            crop_region = self.inject_cat_handler.get_crop_region(
                                frame_w, frame_h, crop_size)
                        elif motion_regions_in_perimeter:
                            crop_region = self.motion_detector.get_fixed_crop_region(
                                frame.shape, crop_size=crop_size)
                        else:
                            crop_region = None

                        if crop_region is not None:
                            cx, cy, cw, ch = crop_region
                            crop_frame = frame[cy:cy+ch, cx:cx+cw].copy()  # MUST copy
                        else:
                            crop_frame = frame.copy()  # full frame, MUST copy

                        # Build inject fallback info
                        inject_info = None
                        if (self.inject_cat and self.inject_cat_handler
                                and self.inject_cat_handler.bbox):
                            inject_info = (
                                self.inject_cat_handler.bbox,
                                config.COCO_CLASSES.get('cat', 17),
                                config.INJECT_BBOX_PROXIMITY_PX)

                        # Submit (non-blocking, drop old if AI thread is busy)
                        try:
                            self._ai_request_queue.get_nowait()
                        except queue.Empty:
                            pass
                        self._ai_request_queue.put_nowait(
                            (crop_frame, crop_region, inject_info,
                             self.frame_count))

                        # Timeout: no motion for 10s → back to IDLE
                        if not self.inject_cat and (now - self._last_motion_time
                                > self._acquisition_timeout):
                            # ... unchanged ...
```

**IMPORTANT:** The crop frame is `.copy()`'d at submit time. If using zero-copy
(Phase 2), `frame` is a DMA view that becomes invalid after release. The copy
ensures the AI thread has a stable buffer to work with. This copy is small
(380×380×3 = ~434KB, takes <1ms).

Do the same for TRACKING phase (every `PHASE_TRACKING_AI_INTERVAL` frames) and
WATCH phase (every `PHASE_WATCH_AI_INTERVAL` frames).

**Fetch (before tracking, replaces the "AI DETECTION" section):**

Replace the entire `if run_ai_detection:` block (currently lines 786-874) with a
non-blocking fetch:

```python
                    # ── Fetch AI result (non-blocking) ──
                    # The AI thread runs TFLite asynchronously. We check for a result
                    # every frame and use it immediately if available.
                    try:
                        ai_result = self._ai_result_queue.get_nowait()
                        detections, result_crop_region, result_frame_id = ai_result

                        # Perimeter filter + temporal confirmation
                        # (same logic as before, moved from the old "AI DETECTION" block)
                        frame_res = (frame_w, frame_h)
                        detections = self.perimeter.filter_detections(
                            detections, frame_resolution=frame_res)
                        self.ai_detections_count += 1

                        # Temporal confirmation
                        self.detection_history.append(len(detections) > 0)
                        if len(self.detection_history) > self.confirm_frames:
                            self.detection_history.pop(0)
                        if self.confirm_frames > 1:
                            confirmed = (len(self.detection_history)
                                         >= self.confirm_frames
                                         and all(self.detection_history))
                            if not confirmed:
                                detections = []

                        last_detections = detections

                        # Phase transitions
                        if len(detections) > 0:
                            self._last_detection_time = now
                            if self._phase == "ACQUISITION":
                                self._phase = "TRACKING"
                                self._phase_frame_counter = 0
                                plog("[PHASE] ACQUISITION → TRACKING (cat detected!)")

                        # World coordinates
                        self.last_detections_with_world = []
                        for det in detections:
                            x1, y1, x2, y2, conf, class_id = det
                            world_pos = None
                            if (self.calibration
                                    and self.calibration.is_calibrated):
                                bcx = (x1 + x2) / 2
                                bcy = y2
                                wp = self.pixel_to_world(
                                    bcx, bcy, already_undistorted=False)
                                if wp:
                                    world_pos = {
                                        "world_x": round(wp[0], 2),
                                        "world_y": round(wp[1], 2)}
                            is_injected = (
                                self.inject_cat
                                and conf == config.INJECT_FALLBACK_CONFIDENCE
                                and self.inject_cat_handler
                                and self.inject_cat_handler.bbox
                                and abs(x1 - self.inject_cat_handler.bbox[0]) < 5)
                            self.last_detections_with_world.append({
                                "bbox": [x1, y1, x2, y2],
                                "confidence": round(conf, 2),
                                "class_id": class_id,
                                "world_position": world_pos,
                                "injected": is_injected,
                            })

                    except queue.Empty:
                        pass  # No new AI result this frame — use last_detections as-is
```

**Delete** the old `if run_ai_detection:` block entirely (lines 786-874).
**Delete** the `run_ai_detection = False` initialization (line 639).
The `crop_region` variable is still set in the phase blocks for PERF logging.

##### Step 4: Modify `start()` — create AI queues + thread

After creating the capture queue and thread, add:

```python
        # AI inference thread (Phase 3: async TFLite)
        self._ai_request_queue = queue.Queue(maxsize=1)
        self._ai_result_queue = queue.Queue(maxsize=1)
        self._ai_thread = threading.Thread(
            target=self._ai_loop, daemon=True, name="CatDome-AI")
        self._ai_thread.start()
```

##### Step 5: Reduce TFLite num_threads to 2

In `config.py`, change:

```python
TFLITE_NUM_THREADS = 2  # Cores 2-3 dedicated to AI thread (was 3)
```

And in each performance profile:
```python
"tflite_threads": 2,  # was 3
```

With thread affinity pinning the AI thread to cores 2-3, TFLite's 2 XNNPACK
workers map 1:1 to those cores. Using 3 threads on 2 cores causes context
switching overhead.

**Expected invoke time change:** 175ms with 3 threads → ~220ms with 2 threads
(~25% slower per invoke). But since invoke no longer blocks the process thread,
the effective FPS improves dramatically.

##### Step 6: Modify `stop()` — join AI thread

```python
    def stop(self):
        self.running = False
        self._stop_recording()
        if hasattr(self, '_capture_thread') and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=3.0)
        if hasattr(self, '_ai_thread') and self._ai_thread.is_alive():
            # Unblock AI thread if it's waiting on the queue
            try:
                self._ai_request_queue.put_nowait(None)
            except queue.Full:
                pass
            self._ai_thread.join(timeout=3.0)
        # ... rest unchanged ...
```

The AI thread checks `self.running` on each loop iteration. The sentinel `None`
put on the queue ensures it wakes up if blocked on `queue.get()`.

In `_ai_loop`, add a check after `queue.get()`:
```python
            request = self._ai_request_queue.get(timeout=1.0)
            if request is None:
                break  # Shutdown sentinel
```

##### Step 7: Update PERF logging

The PERF log format changes because TFLite timing is no longer measured in the
process thread. Options:

1. **Simple:** Log `tf=-` on non-result frames, log `tf=` on frames where a result
   was fetched. The timing comes from `detector._last_perf` which is set by the
   AI thread (safe to read cross-thread since it's replaced atomically as a dict).

2. **Better:** Have the AI thread include timing in the result tuple:
   ```python
   self._ai_result_queue.put(
       (detections, crop_region, frame_counter, perf_dict))
   ```
   The process thread logs it when the result arrives.

#### Thread safety analysis

| Shared state                    | Writer       | Reader        | Safe? |
|---------------------------------|--------------|---------------|-------|
| `self.detector.detect()`        | AI thread    | —             | Yes (exclusive) |
| `self.detector._last_perf`      | AI thread    | Process thread| Yes (dict replace is atomic under GIL) |
| `self._ai_request_queue`        | Process      | AI            | Yes (Queue is thread-safe) |
| `self._ai_result_queue`         | AI           | Process       | Yes (Queue is thread-safe) |
| `self.inject_cat_handler.bbox`  | Process      | AI (via inject_info) | N/A — copied at submit |
| `self.running`                  | Main/Flask   | All threads   | Yes (bool, atomic under GIL) |
| `self.detector.interpreter`     | AI thread    | —             | ⚠ See note below |

**`detector.interpreter` thread safety note:** The process thread currently calls
`detector.unload_model()` when transitioning to IDLE (lines 698, 770, 807). With
the AI thread running, unloading while `invoke()` is in progress would crash.

**Solution:** The AI thread must be the ONLY thread that calls `detect()`,
`_load_model()`, and `unload_model()`. Move the unload calls out of the phase
block and into the AI thread:

```python
# In _ai_loop, after processing the request:
# If no request received for 10s (queue timeout keeps firing), unload
if self._ai_idle_seconds > 10 and self.detector.is_loaded():
    self.detector.unload_model()
    cv2.setNumThreads(1)
    self._ai_idle_seconds = 0
```

Remove `self.detector.unload_model()` from the IDLE/WATCH transitions in
`_process_loop()`. Replace with a flag: `self._ai_should_unload = True`, which
the AI thread checks.

#### Expected performance

| Metric                     | Phase 1 only | Phase 1+3 |
|----------------------------|-------------|-----------|
| FPS during IDLE            | ~16         | ~16       |
| FPS during ACQUISITION     | ~5-8        | ~16       |
| FPS during TRACKING        | ~5-8        | ~16       |
| AI detection latency       | 0 frames    | 2-3 frames |
| TFLite invoke time         | ~175ms      | ~220ms (2 threads) |
| Process thread blocked by AI| 175ms/3 frames | 0ms    |
| Stream smoothness          | Stutters every 3rd frame | Smooth |

#### Testing Phase 3

1. **FPS in TRACKING:** Should be ~16 FPS (camera-limited) instead of ~5 FPS.
   Check PERF log — `tf=` should only appear on frames where a result was fetched.
2. **Detection latency:** Use inject cat test. Cat should be detected within 2-3
   frames of entering the zone (vs 1 frame before). Verify phase transitions
   still happen (IDLE → ACQUISITION → TRACKING).
3. **Stream smoothness:** Watch MJPEG stream during TRACKING. Should be smooth
   ~16 FPS, no 175ms freezes.
4. **Top-down view:** World coordinates should update when AI results arrive.
   May be 2-3 frames behind the stream video.
5. **TFLite unload:** Let the cat stop moving (or stop inject). After 10s idle,
   verify TFLite unloads (journal: `[DETECTOR] Model unloaded`). Verify no
   100% CPU spin on cores 2-3 after unload.
6. **Thread affinity:** `htop` should show CatDome-AI on cores 2-3 only,
   CatDome-Proc on core 0, CatDome-Cap on core 1.
7. **Shutdown:** `sudo systemctl stop catdome` — no hang. AI thread must exit
   cleanly even if blocked in `invoke()` (the 1.0s queue timeout handles this;
   TFLite invoke is not interruptible but completes within 220ms).

#### Rollback

If Phase 3 causes issues (race conditions, detection gaps, etc.), revert to
synchronous detection by:
1. Remove `_ai_loop()` and AI thread from `start()`
2. Change ACQUISITION/TRACKING to set `run_ai_detection = True` instead of
   submitting to the queue
3. Restore the `if run_ai_detection:` block with synchronous `detector.detect()`
4. Restore `TFLITE_NUM_THREADS = 3`

The queues and AI thread are isolated — removing them doesn't affect capture
pipelining (Phase 1) or zero-copy (Phase 2).
