# Code review: concurrency and deadlocks

Review date: 2025-02-07. Focus: locks, lock ordering, cross-thread calls, and data races.

---

## Lock inventory

| Lock | Owner | Purpose |
|------|--------|--------|
| `VideoProcessor.frame_lock` | app.py | Protects `current_frame` (process loop writes; Flask reads in `get_frame_jpeg_capture_resolution`) |
| `VideoProcessor._cached_jpeg_lock` | app.py | Protects `_cached_jpeg` (process loop writes; Flask reads in `get_frame_jpeg`) |
| `VideoProcessor._stream_clients_lock` | app.py | Protects `_stream_clients` (Flask setter; process loop + Flask read) |
| `CameraHandler.frame_lock` | camera_handler.py | Protects `frame` in mock capture thread; `get_frame()` reads under lock |
| `MotionDetector._lock` | motion_detector.py | Protects params + history; `detect()` copies params under lock then does heavy work unlocked |

---

## Deadlock analysis

### app.py lock ordering

When the process loop holds **both** JPEG and frame locks, it **always** takes `_cached_jpeg_lock` then `frame_lock` (inject block and phase block). Flask **never** holds both: `get_frame_jpeg()` takes only `_cached_jpeg_lock`; `get_frame_jpeg_capture_resolution()` takes only `frame_lock`. So there is no A→B and B→A ordering between these two locks → **no deadlock** between app locks.

### Cross-thread cleanup (inject stop)

Inject stop **used to** call `motion_detector.reset()` and `detector.unload_model()` from the **Flask thread** while the process loop could be inside `detect()` or `motion_detector.detect()`, risking deadlock or use-after-free.

**Fixed:** Cleanup is requested via flags (`_request_motion_reset_after_inject`, `_request_unload_after_inject`) and performed at the **start of the next process-loop iteration**. No lock is held across thread boundaries; the process loop never calls into Flask.

### Camera handler

Process loop calls `camera.get_request()` or `camera.get_frame()`; it does **not** hold any VideoProcessor lock during those calls. Capture thread (mock) holds only `camera.frame_lock`. No nested lock with VideoProcessor → **no deadlock**.

### Motion detector

Process loop calls `motion_detector.detect()` without holding any app lock. `detect()` holds `_lock` only briefly to copy parameters; heavy work is outside the lock → **no deadlock**.

---

## Data races

### 1. `stream_clients` getter

The getter returns `self._stream_clients` **without** holding `_stream_clients_lock`, while the setter updates it under the lock. A concurrent read during write is a data race (on some platforms int reads are effectively atomic, but the contract should be consistent).

**Fix:** Read under lock in the getter.

### 2. `stream_clients += 1` / decrement in streaming route

In `routes_streaming.py`, `video_processor.stream_clients += 1` is a **read-modify-write** (getter, then setter with new value). Two clients connecting at once can both read 0 and both set 1, losing a count.

**Fix:** Add `increment_stream_clients()` and `decrement_stream_clients()` on VideoProcessor that perform the change under `_stream_clients_lock`, and use them from the streaming route.

### 3. `current_frame` read in routes_dev print

The log line reads `video_processor.current_frame is not None` without holding `frame_lock`. This is best-effort logging; acceptable (no correctness dependency).

---

## Hold-time and latency

- **get_frame_jpeg_capture_resolution():** Holds `frame_lock` only while doing `self.current_frame.copy()`. Undistort and encode run **after** releasing the lock. For large frames the copy can take tens of ms; the process loop will block when it tries to set `current_frame`. Acceptable.
- **get_frame_jpeg():** Holds `_cached_jpeg_lock` only for returning the cached bytes reference; hold time is minimal.

---

## Summary

| Topic | Status |
|-------|--------|
| Deadlock between app locks | OK — consistent order (jpeg then frame); Flask never holds both |
| Deadlock on inject stop | Fixed — cleanup via flags in process loop |
| Camera / motion detector | OK — no nested lock with VideoProcessor |
| `stream_clients` getter | Race — fix by reading under lock |
| `stream_clients` += / -= in route | Race — fix with increment/decrement methods |
