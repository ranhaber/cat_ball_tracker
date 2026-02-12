#!/usr/bin/env python3
"""Stage 1: Verify picamera2 post_callback works on this Pi.

Run with cat_dome stopped:
    sudo systemctl stop cat_dome
    cd ~/cat_ball_tracker && source venv/bin/activate
    python tests/test_post_callback.py

Expected output:
    Camera started @ 10fps
    [CB] Frame 1: main=(1296, 2304, 3), lores available, time=17.2ms
    [CB] Frame 2: main=(1296, 2304, 3), lores available, time=16.8ms
    ...
    [CB] Frame 20: ...
    SUCCESS: post_callback received 20 frames in ~2.0s
    Average callback time: 17.1ms

If post_callback doesn't fire, you'll see:
    FAIL: post_callback did not fire (0 frames in 3s)
"""

import time
import sys
import os
import threading
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from picamera2 import Picamera2
    from picamera2.request import MappedArray
except ImportError:
    print("ERROR: picamera2 not available")
    sys.exit(1)

# Test state
frame_count = 0
callback_times = []
frame_shapes = []
lock = threading.Lock()

def frame_callback(request):
    """Called by picamera2 camera thread when a frame is ready."""
    global frame_count
    t0 = time.perf_counter()
    
    try:
        # Test 1: Can we access the main stream via MappedArray?
        with MappedArray(request, "main", write=False) as m:
            shape = m.array.shape
            # Test 2: Can we copy data out? (simulates ring buffer copyto)
            # Don't actually copy — just verify the array is valid
            assert m.array.dtype == np.uint8
            assert len(shape) == 3  # (H, W, C)
        
        # Test 3: Can we access lores?
        lores_ok = False
        try:
            with MappedArray(request, "lores", write=False) as m:
                lores_shape = m.array.shape
                lores_ok = True
        except Exception:
            pass
        
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        
        with lock:
            frame_count += 1
            callback_times.append(elapsed)
            frame_shapes.append(shape)
            n = frame_count
        
        lores_str = "lores available" if lores_ok else "NO lores"
        print(f"[CB] Frame {n}: main={shape}, {lores_str}, time={elapsed}ms")
        
    except Exception as e:
        print(f"[CB] ERROR: {e}")


def main():
    print("Stage 1: Testing picamera2 post_callback")
    print("=" * 50)
    
    # Create camera
    picam2 = Picamera2()
    
    # Configure with main + lores (same as Cat Dome)
    config = picam2.create_video_configuration(
        main={"size": (2304, 1296), "format": "RGB888"},
        lores={"size": (960, 540), "format": "YUV420"},
        raw=None,  # No raw stream (saves ~20MB)
        buffer_count=4
    )
    picam2.configure(config)
    
    # Set callback BEFORE starting
    picam2.post_callback = frame_callback
    
    # Start camera at 10 FPS
    picam2.start()
    print("Camera started @ 10fps")
    print("Waiting for 20 frames via post_callback...")
    print()
    
    # Wait for frames
    deadline = time.time() + 5.0  # 5s timeout
    while frame_count < 20 and time.time() < deadline:
        time.sleep(0.1)
    
    # Stop
    picam2.stop()
    picam2.close()
    
    # Report
    print()
    print("=" * 50)
    if frame_count >= 20:
        avg = sum(callback_times) / len(callback_times)
        print(f"SUCCESS: post_callback received {frame_count} frames")
        print(f"Average callback time: {avg:.1f}ms")
        print(f"Frame shape: {frame_shapes[0]}")
        print()
        print("post_callback is working. Safe to proceed with Stage 2.")
    elif frame_count > 0:
        print(f"PARTIAL: Got {frame_count} frames (expected 20)")
        print("post_callback works but may be slow or dropping frames.")
    else:
        print("FAIL: post_callback did not fire (0 frames in 5s)")
        print("This Pi's picamera2 may not support post_callback.")
        print("Fall back to the capture thread approach.")


if __name__ == "__main__":
    main()
