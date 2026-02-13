# Project guidelines for agents and developers

This document consolidates knowledge from README, code reviews, and optimization logs so any new agent or developer can continue effectively. **Read this first**, then use the linked docs for detail.

**When making architectural changes, always update AGENTS.md and README** (logging, threads, new modules, concurrency, or behavior that affects debugging or performance).

### Workflow rule: explain first, code only after approval

1. **Explain** what you plan to do and why (analysis, design, trade-offs) before writing any code or modifying any file.
2. **Wait for the user's explicit approval** before creating or editing files. Never write code, create files, or push changes without permission.
3. This applies to all changes: new features, bug fixes, optimizations, config edits, documentation updates, and commits/pushes.

---

## 1. What this project is

- **Cat Dome** — Real-time cat (and ball) detection and tracking on **Raspberry Pi Zero 2W** with Camera Module 3.
- **Goal:** Detect and track a cat in a Detection Zone, up to **13 m** range. TFLite stays loaded while a cat is present; unloads after idle timeouts.
- **Stack:** Python 3, Flask, OpenCV, TFLite (MobileNet SSD), picamera2. Runs headless via systemd; web UI is for monitoring/settings only.

**Version** is in `main.py` (`__version__`). Bump it when releasing; update README "Version" line to match.

---

## 2. Architecture (threads and flow)

**3 threads + picamera2 callback (v3.17.2):**

| Thread | Core | Role | Key constraint |
|--------|------|------|----------------|
| **picamera2 internal** | any | Camera ISP: delivers frames via `post_callback` | Copies DMA→ring buffer (~12ms), signals event; skips reader's slot |
| **CatDome-Proc** | 0 | Processing: motion → AI submit → track → annotate | Reads ring buffer; submits AI non-blocking |
| **CatDome-AI** | 1-3 | Async TFLite inference | Owns detector lifecycle (load/unload after 3s idle) |
| **CatDome-Log** | any | Async logging (queue → stdout) | Non-blocking plog() |

Plus Flask (CatDome-Main) for the web server.

**Frame pipeline:** picamera2 callback copies DMA→ring buffer → CatDome-Proc reads ring: inject cat → motion → phase logic → submit crop to AI queue (non-blocking) → fetch AI result (1-frame latency) → tracker → annotate → JPEG/overlay → recording.

**Ring buffer:** 3-slot pre-allocated numpy arrays (main + lores_y + lores_bgr). `np.copyto()` in callback, no per-frame allocation. Generation counter (`_ring_gen`) per slot detects torn reads (odd=writing, even=complete).

**Critical rules:**
- **CatDome-AI** is the ONLY thread that calls `detector.detect()`, `detector.unload_model()`, or loads the model.
- **CatDome-Proc** submits AI requests via `_submit_ai()` (non-blocking `put_nowait`); fetches results via `_ai_latest_result` (variable + lock, latest wins).
- **Ring buffer safety:** callback sets `_ring_gen[slot]` odd before write, even after. Process thread checks gen before+after to detect torn reads. `_ring_last_read` prevents processing the same slot twice.
- **inject_cat** must `frame.copy()` before `paste_on_frame()` to avoid mutating ring buffer slot.
- **Never from Flask:** Do not call `motion_detector.reset()` or `detector.unload_model()` from a route. Set flags; process loop checks at start of iteration.
- **Lores reconfigure** happens in CatDome-Proc (re-allocates ring lores arrays before frame wait).

Detailed architecture diagram: **README § System Architecture**. Crop vs resize: **README § Crop vs resize**.

---

## 3. Key concepts

### Phase state machine (IDLE → ACQUISITION → TRACKING → WATCH → IDLE)

- **IDLE:** Motion only, TFLite not loaded. Motion in zone → ACQUISITION.
- **ACQUISITION:** TFLite runs every processed frame; crop from motion or inject. Cat found → TRACKING. No motion 10 s → IDLE.
- **TRACKING:** TFLite every 2nd frame; motion crop. Motion stops → WATCH. No detection 30 s → IDLE.
- **WATCH:** TFLite every 2nd frame; often full frame (no crop). Motion again → TRACKING. No detection 30 s → IDLE.

When **inject_cat** is True, the cat is pasted on the camera frame (simulating a real cat). The full pipeline runs normally: motion detection sees the cat, AI detects it, tracker tracks it. On first inject frame, IDLE is force-transitioned to ACQUISITION (no motion history yet). The DMA frame is copied before pasting (inject writes to the frame).

### Crop vs resize

- **Crop:** One place — AI region. We take a rectangle from the full frame at **same resolution** (e.g. 380×380 or 400×400 from profile). Slice only: `frame[cy:cy+ch, cx:cx+cw]`.
- **Resize:** Three places — (1) motion: full frame → ¼ size for motion; (2) TFLite: crop or full frame → model input (e.g. 300×300); (3) stream: raw frame → stream resolution **first**, then draw annotations on the small frame (avoids drawing on the 9 MB capture frame). Detector skips resize when input already matches model size (e.g. crop 300×300).
- **Scaled perimeter cache:** Perimeter polygon scaled to stream resolution is pre-computed once (`_get_scaled_perimeter`) and cached. Invalidated when perimeter is set/cleared or stream resolution changes. Detection boxes and motion regions are scaled inline with simple multiply (cheap).

All profiles use 300×300 crop matching TFLite's native input — no resize step, 27% more cat pixels at distance vs the old 380-400px crops. See DETECTION_RANGES.md for pixel-size analysis at each distance.

### Inject Cat (test mode)

- **Purpose:** Validate pipeline without a real cat. Pastes a moving cat image on the live frame; pipeline runs as normal.
- **Enable/disable:** `POST /api/dev/inject_cat` (routes_dev). On disable we clear state, set phase to IDLE, and **request** motion reset and TFLite unload via flags; the **process loop** performs reset/unload at the start of the next iteration (never from Flask).
- **Movement:** `processing/inject_cat.py` — vertex-to-vertex; `paste_on_frame()` updates position each call. Stream is updated every iteration when inject_cat so the cat moves visibly.
- **Inject stop → 100% CPU:** While inject is ON the loop runs `time.sleep(INJECT_MODE_SLEEP_SEC)` each iteration; when inject is turned OFF that sleep is no longer used. If the camera returns frames very quickly (or mock returns immediately), the loop can spin at full speed. Cleanup (TFLite unload, `cv2.setNumThreads(1)`) runs at the **start** of the next iteration; if it is delayed or the loop is still tight afterward, CPU stays high. See **README § Inject Cat stop — CPU spike and debug plan**.

### Settings and config

- **Runtime state** (resolution, profile, phase, stream_clients, etc.) lives on **VideoProcessor** (`web/app.py`). Do not mutate `config.*` at runtime for per-profile values; use e.g. `current_motion_crop_size` (already done).
- **Persisted settings:** `settings.py` (JSON). Loaded in VideoProcessor `__init__`; routes call `settings.update_setting()` when user changes values.
- **Constants and profiles:** `config.py` (PERFORMANCE_PROFILES, MOTION_DETECTION_SCALE, etc.).

---

## 4. Concurrency and locks (critical)

**Lock inventory:** See **docs/CODE_REVIEW_DEADLOCKS.md**.

- **VideoProcessor:** `frame_lock` (current_frame), `_cached_jpeg_lock` (_cached_jpeg), `_stream_clients_lock` (_stream_clients).
- **CameraHandler:** `frame_lock` (capture thread vs get_frame).
- **MotionDetector:** `_lock` (params + history; hold briefly, do heavy work unlocked).

**Rules:**

1. **Lock order when holding two:** Always **`_cached_jpeg_lock` then `frame_lock`** in the process loop. Flask never holds both (only one of get_frame_jpeg / get_frame_jpeg_capture_resolution).
2. **Never from Flask:** Do not call `motion_detector.reset()` or `detector.unload_model()` from a route. Set flags (`_request_motion_reset_after_inject`, `_request_unload_after_inject`); process loop checks at **start of loop** and performs reset/unload there.
3. **stream_clients:** Use the **getter** (reads under lock) and **increment_stream_clients() / decrement_stream_clients()** for connect/disconnect.
4. **Process loop:** Do not hold any VideoProcessor lock while calling `camera.*` or `motion_detector.detect()`.

---

## 5. Where things live

| Concern | Location |
|--------|----------|
| Version | `main.py` __version__ |
| Config & profiles | `config.py` |
| Persisted settings | `settings.py`; loaded in `VideoProcessor.__init__` |
| Process loop, phase machine, JPEG cache | `web/app.py` — VideoProcessor, `_process_loop` |
| Camera callback + ring buffer | `web/app.py` — `_frame_callback`, `_ring_*` |
| Async AI thread | `web/app.py` — `_ai_loop`, `_submit_ai` (Cores 1-3) |
| Frame capture (real/mock) | `camera/camera_handler.py` |
| Motion detection | `detection/motion_detector.py` |
| TFLite (load on demand, unload on idle) | `detection/detector.py` |
| Tracker (centroid IDs) | `detection/tracker.py` |
| Detection Zone, filter_detections | `detection/perimeter.py` |
| Inject cat (paste, movement) | `processing/inject_cat.py` |
| Async logging (queue + writer thread) | `processing/async_log.py` — `setup_async_logging()`, `plog()` |
| Stream client count, get_frame_jpeg | `web/app.py` |
| Routes (streaming, dev, calibration, etc.) | `web/routes_*.py` |
| Tests | `tests/` — `run_tests.py`; conftest mocks camera/Flask/TFLite |

**Project structure (full):** README § Project Structure.

---

## 6. Testing and changes

- **Run tests:** `python tests/run_tests.py` (optionally `python tests/run_tests.py inject_cat` for one module). Tests use mocks (no real camera/TFLite). **All tests must pass** before committing.
- **Adding features:** Prefer extending existing modules (e.g. new route in appropriate `routes_*.py`, new phase logic in _process_loop with same lock/thread rules). If adding locks, document in CODE_REVIEW_DEADLOCKS and preserve lock order.
- **Performance:** All hot-path buffers are pre-allocated (ring buffer, motion detector, stream frame, AI crop double-buffer). Avoid new per-frame allocations; use dst= parameter or pre-alloc buffers. Allocation churn is <1MB/sec.

---

## 7. Common pitfalls

- **Init vs start:** VideoProcessor loads settings and sets phase/profile in **`__init__`**, not in a setter. Keep one place for “load settings and apply to state.”
- **Inject off:** Cleanup (motion reset, unload) must run in the **process loop** via flags, not from Flask. After inject stop the loop has no per-iteration sleep; a small rate-limit sleep when not in inject mode keeps CPU bounded (see app.py loop).
- **stream_clients:** Use increment/decrement methods and locked getter; no raw += from routes.
- **Config mutation:** Don’t change `config.MOTION_CROP_SIZE` at runtime; use `VideoProcessor.current_motion_crop_size` (and similar for other profile-driven values).
- **Null checks:** Guard `inject_cat_handler` (and similar) in routes — return 503 if processor not started.
- **13 m range:** All profiles use 300×300 crop (matches TFLite input, no resize). At 13m the cat is 43×22px — above MobileNet minimum (~20px). See DETECTION_RANGES.md.

---

## 8. Reference documents

| Document | Use for |
|----------|--------|
| **README.md** | User-facing overview, setup, API, phase diagram, frame timeline, crop vs resize, 13 m and efficiency notes. |
| **docs/CODE_REVIEW_DEADLOCKS.md** | Lock inventory, deadlock analysis, data races, hold-time. |
| **docs/CODE_REVIEW.md** | Past high/medium/low review items; many already fixed (frame storage, config mutation, inject_cat_handler guard). |

| **AGENTS.md** (this file) | Single entry point for agents: architecture, rules, where to look, pitfalls. |

---

## 9. Quick checklist for a new agent

- [ ] Read this file and CODE_REVIEW_DEADLOCKS for concurrency.
- [ ] For process-loop changes: preserve lock order (jpeg then frame); no reset/unload from Flask.
- [ ] For new routes: use VideoProcessor getters/setters or dedicated methods (e.g. increment_stream_clients); guard optional handlers (inject_cat_handler, etc.).
- [ ] For crop/size changes: all profiles use 300×300 (matches TFLite input). See README § Crop vs resize and DETECTION_RANGES.md.
- [ ] Run `python tests/run_tests.py` after changes; fix any failures.
- [ ] Bump version in main.py (and README) when releasing; commit message can reference version and main change.
