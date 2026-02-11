"""
H.264 hardware-encoded WebSocket streaming route.

The Pi's VideoCore H.264 encoder runs at near-zero CPU cost, encoding the
lores YUV420 stream directly. Frames are sent as binary WebSocket messages
to the browser, where jMuxer decodes them using Media Source Extensions
(GPU-accelerated on the client). Overlay data (detections, perimeter, phase)
is sent as JSON text messages and drawn on a Canvas element client-side.

Protocol:
    Binary messages → H.264 NALUs (Annex B format) → fed to jMuxer
    Text messages   → JSON overlay data → drawn on Canvas

Routes:
    WS /ws/stream — H.264 + overlay WebSocket stream
"""

import time
import json

try:
    from flask_sock import Sock
    FLASK_SOCK_AVAILABLE = True
except ImportError:
    FLASK_SOCK_AVAILABLE = False
    print("[H264] flask-sock not installed — H.264 WebSocket streaming disabled")
    print("[H264] Install with: pip install flask-sock")

_sock = None  # Module-level Sock instance, initialized in init_h264_routes


def init_h264_routes(app, video_processor):
    """Register H.264 WebSocket routes on the Flask app.
    
    Unlike Blueprint routes, flask-sock registers directly on the app
    because WebSocket upgrade requires access to the WSGI app object.
    """
    global _sock
    
    if not FLASK_SOCK_AVAILABLE:
        print("[H264] Skipping H.264 route registration (flask-sock not available)")
        return
    
    _sock = Sock(app)
    
    @_sock.route('/ws/stream')
    def h264_stream(ws):
        """WebSocket endpoint for H.264 streaming + JSON overlays.
        
        Sends interleaved binary (H.264) and text (JSON overlay) messages.
        The browser distinguishes by message type.
        """
        n = video_processor.increment_h264_clients()
        print(f"[H264] WebSocket client connected ({n} active)")
        
        last_overlay_send = 0
        overlay_interval = 0.1  # Send overlay data at ~10Hz
        
        try:
            while True:
                # Get next H.264 frame from hardware encoder
                h264_data = video_processor.get_h264_frame(timeout=0.5)
                
                if h264_data is not None:
                    # Send H.264 NALU as binary message
                    try:
                        ws.send(h264_data)
                    except Exception:
                        break  # Client disconnected
                
                # Send overlay data at ~10Hz (not every frame — saves bandwidth)
                now = time.time()
                if now - last_overlay_send >= overlay_interval:
                    overlay = video_processor.get_overlay_data()
                    if overlay is not None:
                        try:
                            ws.send(json.dumps(overlay))
                        except Exception:
                            break
                    last_overlay_send = now
                    
        except Exception as e:
            print(f"[H264] WebSocket error: {e}")
        finally:
            n = video_processor.decrement_h264_clients()
            print(f"[H264] WebSocket client disconnected ({n} active)")
