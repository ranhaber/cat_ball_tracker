# Pre-allocation: Status

All hot-path pre-allocation is complete as of v3.17.1.

## Implemented

| Buffer | File | Size | Savings |
|--------|------|------|---------|
| Ring buffer (main+lores_y+lores_bgr) | `web/app.py` | 31.6MB | v3.16.0 |
| Motion: resize, blur, f32, delta, thresh | `detection/motion_detector.py` | ~1.86MB/frame | v3.17.1 |
| Stream frame buffer | `web/app.py` `_resize_for_stream` | ~691KB/frame | v3.17.1 |
| AI crop buffer | `web/app.py` `_submit_ai` | ~270KB/call | v3.17.1 |
| TFLite input buffer | `detection/detector.py` `_input_buf` | 270KB | pre-existing |

## Remaining (unavoidable)

| Allocation | Size | Why |
|-----------|------|-----|
| JPEG encode output | ~80KB/frame | `simplejpeg`/`cv2.imencode` API returns new `bytes` |
| `findContours` result | ~1KB | Returns Python list — can't pre-alloc |
| frame_history deque (float32 copies) | ~518KB × 3 slots | Each history slot must be independent |
| Python dicts/lists (detections, overlay) | ~2KB | Tiny, not worth pooling |

## Allocation churn summary

| Phase | Before (v3.16) | After (v3.17.1) |
|-------|----------------|-----------------|
| IDLE (no stream) | ~18.6 MB/sec | ~0.08 MB/sec |
| IDLE (streaming) | ~26.3 MB/sec | ~0.8 MB/sec |
| TRACKING (no stream) | ~21.3 MB/sec | ~0.1 MB/sec |
| TRACKING (streaming) | ~29.0 MB/sec | ~0.9 MB/sec |
