"""
Streaming and snapshot routes.

Routes:
    GET  /                  — Main page
    GET  /api/snapshot      — Single snapshot at capture resolution
    GET  /video_feed        — MJPEG video stream
"""

import time
from flask import Blueprint, Response, render_template, request

streaming_bp = Blueprint('streaming', __name__)


def init_streaming_routes(video_processor):
    """Register streaming routes with access to the video processor."""
    
    @streaming_bp.route('/')
    def index():
        """Serve main page"""
        return render_template('index.html')
    
    @streaming_bp.route('/api/snapshot')
    def snapshot_capture_resolution():
        """Single snapshot at capture resolution. If undistort=1, applies lens correction."""
        undistort = request.args.get('undistort', '0') == '1'
        jpeg = video_processor.get_frame_jpeg_capture_resolution(undistort=undistort)
        if jpeg:
            return Response(jpeg, mimetype='image/jpeg')
        return Response(status=503)
    
    @streaming_bp.route('/video_feed')
    def video_feed():
        """MJPEG video stream endpoint"""
        # Check if requesting a single snapshot (stream resolution)
        if request.args.get('snapshot'):
            jpeg = video_processor.get_frame_jpeg()
            if jpeg:
                return Response(jpeg, mimetype='image/jpeg')
            return Response(status=503)
        
        # Otherwise stream continuously (rate-limited to save CPU)
        def generate():
            video_processor.stream_clients += 1
            print(f"[STREAM] Client connected ({video_processor.stream_clients} active)")
            try:
                while True:
                    jpeg = video_processor.get_frame_jpeg()
                    if jpeg is not None:
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
                        )
                    # Limit stream to ~10 FPS max — saves CPU on JPEG encoding
                    time.sleep(0.1)
            finally:
                video_processor.stream_clients = max(0, video_processor.stream_clients - 1)
                print(f"[STREAM] Client disconnected ({video_processor.stream_clients} active)")
                    
        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
