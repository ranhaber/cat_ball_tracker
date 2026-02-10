"""
Video source, recording, and motion detection routes.

Routes:
    GET/POST  /api/video/source      — Video source (live/file)
    GET       /api/video/library     — List video files
    GET/POST  /api/video/recording   — Recording settings
    GET       /api/motion            — Motion detection settings
    POST      /api/motion/toggle     — Toggle motion-first mode
    POST      /api/motion/show_regions — Toggle motion region display
"""

import os
from flask import Blueprint, jsonify, request
from camera.camera_handler import FileCameraHandler
import settings

video_bp = Blueprint('video', __name__)


def init_video_routes(video_processor):
    """Register video/recording/motion routes with access to the video processor."""
    
    @video_bp.route('/api/video/source', methods=['GET'])
    def get_video_source():
        """Get current video source and file path"""
        return jsonify({
            "video_source": video_processor.video_source,
            "video_file_path": video_processor.video_file_path,
            "video_library_path": video_processor.video_library_path,
            "recording_enabled": video_processor.recording_enabled,
            "record_after_detection_sec": video_processor.record_after_detection_sec,
        })
    
    @video_bp.route('/api/video/source', methods=['POST'])
    def set_video_source():
        """Set video source: live or file. For file, provide video_file_path."""
        data = request.get_json() or {}
        source = data.get("video_source", "live")
        path = data.get("video_file_path")
        if source not in ("live", "file"):
            return jsonify({"error": "video_source must be 'live' or 'file'"}), 400
        if source == "file" and (not path or not os.path.isfile(path)):
            return jsonify({"error": "Valid video_file_path required for file source"}), 400
        video_processor.video_source = source
        video_processor.video_file_path = path if source == "file" else None
        settings.update_setting("video_source", video_processor.video_source)
        settings.update_setting("video_file_path", video_processor.video_file_path)
        if source == "file" and path:
            if video_processor.file_camera:
                video_processor.file_camera.stop()
            video_processor.file_camera = FileCameraHandler()
            try:
                video_processor.file_camera.start(path)
            except Exception as e:
                video_processor.file_camera = None
                video_processor.video_source = "live"
                return jsonify({"error": str(e)}), 400
        else:
            if video_processor.file_camera:
                video_processor.file_camera.stop()
                video_processor.file_camera = None
        return jsonify({"success": True, "video_source": video_processor.video_source,
                        "video_file_path": video_processor.video_file_path})
    
    @video_bp.route('/api/video/library', methods=['GET'])
    def get_video_library():
        """List video files in library dir (or optional path query param)."""
        import config
        path = request.args.get("path") or video_processor.video_library_path or getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos')
        if not os.path.isdir(path):
            return jsonify({"path": path, "files": [], "error": "Directory not found"})
        try:
            names = sorted([f for f in os.listdir(path) if f.lower().endswith(('.mp4', '.avi', '.mkv', '.mov'))])
            files = [{"name": n, "path": os.path.join(path, n)} for n in names]
            return jsonify({"path": path, "files": files})
        except Exception as e:
            return jsonify({"path": path, "files": [], "error": str(e)})
    
    @video_bp.route('/api/video/recording', methods=['GET'])
    def get_recording_settings():
        return jsonify({
            "recording_enabled": video_processor.recording_enabled,
            "record_after_detection_sec": video_processor.record_after_detection_sec,
            "video_library_path": video_processor.video_library_path,
        })
    
    @video_bp.route('/api/video/recording', methods=['POST'])
    def set_recording_settings():
        data = request.get_json() or {}
        if "recording_enabled" in data:
            video_processor.recording_enabled = bool(data["recording_enabled"])
            settings.update_setting("recording_enabled", video_processor.recording_enabled)
        if "record_after_detection_sec" in data:
            sec = int(data["record_after_detection_sec"])
            if 1 <= sec <= 60:
                video_processor.record_after_detection_sec = sec
                settings.update_setting("record_after_detection_sec", sec)
        if "video_library_path" in data:
            p = (data.get("video_library_path") or "").strip()
            video_processor.video_library_path = p or getattr(config, 'VIDEO_LIBRARY_PATH', '/home/ranhaber/cat_dome_videos')
            os.makedirs(video_processor.video_library_path, exist_ok=True)
            settings.update_setting("video_library_path", video_processor.video_library_path)
        return jsonify({"success": True, "recording_enabled": video_processor.recording_enabled,
                        "record_after_detection_sec": video_processor.record_after_detection_sec,
                        "video_library_path": video_processor.video_library_path})
    
    # =========================================================================
    # Motion Detection
    # =========================================================================
    
    @video_bp.route('/api/motion', methods=['GET'])
    def get_motion_settings():
        """Get motion detection settings"""
        return jsonify({
            "motion_first_enabled": video_processor.motion_first_enabled,
            "show_motion_regions": video_processor.show_motion_regions,
            "motion_detected": video_processor.motion_detected,
            "ai_detections_count": video_processor.ai_detections_count
        })
    
    @video_bp.route('/api/motion/toggle', methods=['POST'])
    def toggle_motion_first():
        """Toggle motion-first detection mode"""
        data = request.get_json() or {}
        enabled = data.get('enabled')
        
        if enabled is None:
            video_processor.motion_first_enabled = not video_processor.motion_first_enabled
        else:
            video_processor.motion_first_enabled = bool(enabled)
        
        settings.update_setting("motion_first_enabled", video_processor.motion_first_enabled)
        
        if video_processor.motion_detector:
            video_processor.motion_detector.reset()
        
        return jsonify({
            "success": True,
            "motion_first_enabled": video_processor.motion_first_enabled
        })
    
    @video_bp.route('/api/motion/show_regions', methods=['POST'])
    def toggle_show_motion_regions():
        """Toggle showing motion regions on video"""
        data = request.get_json() or {}
        show = data.get('show')
        
        if show is None:
            video_processor.show_motion_regions = not video_processor.show_motion_regions
        else:
            video_processor.show_motion_regions = bool(show)
        
        settings.update_setting("show_motion_regions", video_processor.show_motion_regions)
        print(f"[SETTING] Show motion regions: {video_processor.show_motion_regions}")
        
        return jsonify({
            "success": True,
            "show_motion_regions": video_processor.show_motion_regions
        })
