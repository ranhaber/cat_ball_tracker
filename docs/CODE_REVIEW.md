# Code Review — Cat Dome (continued)

Review date: 2025-02-07. Focus: clarity, consistency, naming, and remaining issues after the init fix.

---

## Summary

- **Critical:** None (VideoProcessor `__init__` bug was fixed earlier).
- **High:** 2 items (frame storage when no clients; config mutation).
- **Medium:** 3 items (defensive checks; magic numbers; comment accuracy).
- **Low:** 4 items (docstrings; duplicate config; style).

---

## High priority

### 1. `current_frame` not updated when no stream clients

**Where:** `web/app.py` — `_process_loop`, annotation & frame storage block (~517–530).

**Issue:** When `stream_clients == 0`, we never assign to `self.current_frame`. Only the branch `if self.stream_clients > 0` updates it. So when there are no viewers, the last frame from when there were clients stays in `current_frame`. When a new client connects, they may see a stale frame until the next processed frame.

**Recommendation:** In the `else` branch (no clients), set `self.current_frame = frame` (or a copy) under `frame_lock`, so the first client always gets the latest frame. Recording already uses `annotated` and is correct.  
**Done (v3.6.2):** Added else branch that sets `self.current_frame = frame` under `frame_lock`.

---

### 2. Mutating `config.MOTION_CROP_SIZE` at runtime

**Where:** `web/app.py` — `_apply_performance_profile()` line 980:  
`config.MOTION_CROP_SIZE = profile["motion_crop_size"]`

**Issue:** Performance profiles overwrite a module-level constant. That works but is surprising and makes config both “defaults” and “current runtime state.” Other profile fields (e.g. `current_jpeg_quality`) live on `VideoProcessor`.

**Recommendation:** Add `self.current_motion_crop_size` (or similar) on `VideoProcessor`, set it in `_apply_performance_profile` and in `__init__` from the saved profile, and use it in the process loop instead of `config.MOTION_CROP_SIZE`. Leave `config.MOTION_CROP_SIZE` as the default only (e.g. for motion_detector default).  
**Done (v3.6.2):** Implemented `current_motion_crop_size` on VideoProcessor; no more config mutation.

---

## Medium priority

### 3. Inject Cat API assumes `inject_cat_handler` is set

**Where:** `web/routes_dev.py` — `dev_inject_cat()` uses `video_processor.inject_cat_handler.enable()` / `.disable()` with no null check.

**Issue:** `inject_cat_handler` is created in `video_processor.start()`. In production, `run_server()` calls `start()` before serving, so it is always set when the API is used. If the app were ever used without `start()` (e.g. test or alternate entry point), this would raise `AttributeError`.

**Recommendation:** Guard at the start of the handler, e.g.  
`if not getattr(video_processor, 'inject_cat_handler', None): return jsonify({"error": "Video processor not started"}), 503`  
**Done (v3.6.2):** Added guard in `dev_inject_cat()`; returns 503 when handler is missing.

---

### 4. Magic numbers in status overlay

**Where:** `web/app.py` — `_draw_status()`: e.g. `max(text_w + 15, 250)`, `text_h + 55`, font scale `0.6` / `0.5`, thickness `2` / `1`.

**Recommendation:** Either leave as-is (local to one small function) or define named constants in `config.py` (e.g. `STATUS_BOX_MIN_WIDTH`, `STATUS_FONT_SCALE`) for consistency with the rest of the project.  
**Done (v3.6.2):** Added `STATUS_*` constants in config; `_draw_status()` uses them.

---

### 5. Comment vs config value

**Where:** `config.py` line 239: `MOTION_CROP_SIZE = (300, 300)` with comment “Fixed crop size matching AI input (no scaling!)”. At runtime this is overwritten by the active performance profile (380, 400, or 450).

**Recommendation:** Update the comment to state that this is the default before any profile is applied and that profiles override it at runtime.  
**Done (v3.6.2):** Comment updated; notes profile override via VideoProcessor.current_motion_crop_size.

---

## Low priority

### 6. `config.py` — redundant early `FRAME_WIDTH` / `FRAME_HEIGHT`

**Where:** Lines 48–49 set `FRAME_WIDTH = 2304`, `FRAME_HEIGHT = 1296`; lines 282–285 set them again from `DEFAULT_RESOLUTION` and `DEFAULT_STREAM_RESOLUTION`.

**Recommendation:** Comment at 48–49 already says “Updated below.” No code change needed; optional: remove the first assignment and define `FRAME_WIDTH`/`FRAME_HEIGHT` only after `DEFAULT_RESOLUTION` (and adjust `DEFAULT_PERIMETER` to use that resolution or the same names).

---

### 7. Docstrings for route initializers

**Where:** `web/routes_*.py` — `init_*_routes(video_processor)` functions have minimal or no docstring.

**Recommendation:** One-line docstring per init function, e.g. “Register streaming routes and pass `video_processor` to closures.”

---

### 8. `settings.py` — path not config-derived

**Where:** `settings.py` uses `SETTINGS_FILE = "settings.json"` (relative to cwd). Other paths use `config.BASE_DIR`.

**Recommendation:** For consistency and predictable location, use e.g. `os.path.join(config.BASE_DIR, "settings.json")` (or keep as-is and document that settings are cwd-relative).

---

### 9. Recording fourcc loop

**Where:** `web/app.py` — `_start_recording()`: tries `getattr(config, 'RECORDING_FOURCC', 'avc1'), 'mp4v', 'X264'`. `cv2.VideoWriter_fourcc(*fourcc_name)` is correct for 4-character codes.

**Recommendation:** No change. Only note: on some systems one of these may fail to open; the loop already falls back to the next.

---

## What’s in good shape

- **Modularity:** Routes in blueprints, processing in `processing/`, detection in `detection/`, clear separation.
- **Naming:** Phase names (IDLE, ACQUISITION, TRACKING, WATCH), method names, and public APIs are clear.
- **Docstrings:** `VideoProcessor`, `InjectCat`, `TFLiteDetector`, `MotionDetector`, and main modules have useful docstrings.
- **Phase state machine:** Comments and structure in `_process_loop` match the README and are easy to follow.
- **Tests:** 70 tests; `conftest` and test layout are clear; no user files modified by tests.
- **Config:** Grouped sections and comments make constants easy to find.

---

## Suggested order of work

1. **High:** Fix frame storage when `stream_clients == 0` (add `else` branch).
2. **High:** Replace runtime `config.MOTION_CROP_SIZE` mutation with `VideoProcessor.current_motion_crop_size` (or equivalent).
3. **Medium:** Add null check for `inject_cat_handler` in `routes_dev.py` inject_cat endpoint.
4. **Medium:** Update `config.py` comment for `MOTION_CROP_SIZE` to reflect profile override.
5. **Low/optional:** Docstrings for route inits; optional constants for status overlay; optional `settings.json` path via `config.BASE_DIR`.

If you tell me which of these you want to implement (e.g. “do 1 and 3 only”), I can apply the changes and keep version/README/tests in sync.
