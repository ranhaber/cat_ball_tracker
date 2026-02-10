"""
Performance settings and profile routes.

Routes:
    GET  /api/performance                   — Current performance settings
    POST /api/performance/resolution        — Set capture resolution (deprecated/fixed)
    POST /api/performance/stream_resolution — Set streaming resolution
    POST /api/performance/framerate         — Set camera framerate
    POST /api/performance/frameskip         — Set detection frame skip
    GET  /api/performance/threshold         — Get detection threshold
    POST /api/performance/threshold         — Set detection threshold
    GET  /api/performance/confirm_frames    — Get confirmation frames
    POST /api/performance/confirm_frames    — Set confirmation frames
    GET  /api/performance/profiles          — Get all profiles
    GET  /api/performance/profile           — Get current profile
    POST /api/performance/profile           — Set active profile
"""

from flask import Blueprint, jsonify, request
import config

performance_bp = Blueprint('performance', __name__)


def init_performance_routes(video_processor):
    """Register performance routes with access to the video processor."""
    
    @performance_bp.route('/api/performance', methods=['GET'])
    def get_performance():
        """Get current performance settings and available options"""
        return jsonify(video_processor.get_performance_settings())
    
    @performance_bp.route('/api/performance/resolution', methods=['POST'])
    def set_resolution():
        """Set camera resolution (capture resolution - fixed at 2304x1296)"""
        return jsonify({"error": "Capture resolution is fixed at 2304x1296"}), 400
    
    @performance_bp.route('/api/performance/stream_resolution', methods=['POST'])
    def set_stream_resolution():
        """Set streaming resolution (for web viewing)"""
        data = request.get_json()
        width = data.get('width')
        height = data.get('height')
        
        if not width or not height:
            return jsonify({"error": "Width and height required"}), 400
        
        success = video_processor.set_stream_resolution(int(width), int(height))
        if success:
            return jsonify({"success": True, "stream_resolution": [width, height]})
        return jsonify({"error": "Invalid stream resolution"}), 400
    
    @performance_bp.route('/api/performance/framerate', methods=['POST'])
    def set_framerate():
        """Set camera framerate"""
        data = request.get_json()
        fps = data.get('fps')
        
        if fps is None:
            return jsonify({"error": "FPS value required"}), 400
        
        success = video_processor.set_framerate(int(fps))
        if success:
            return jsonify({"success": True, "framerate": fps})
        return jsonify({"error": "Invalid framerate"}), 400
    
    @performance_bp.route('/api/performance/frameskip', methods=['POST'])
    def set_frameskip():
        """Set detection frame skip"""
        data = request.get_json()
        skip = data.get('skip')
        
        if skip is None:
            return jsonify({"error": "Skip value required"}), 400
        
        success = video_processor.set_frame_skip(int(skip))
        if success:
            return jsonify({"success": True, "frame_skip": skip})
        return jsonify({"error": "Invalid frame skip value"}), 400
    
    @performance_bp.route('/api/performance/threshold', methods=['GET'])
    def get_threshold():
        """Get current detection threshold"""
        return jsonify({"threshold": video_processor.get_detection_threshold()})
    
    @performance_bp.route('/api/performance/threshold', methods=['POST'])
    def set_threshold():
        """Set detection confidence threshold"""
        data = request.get_json()
        threshold = data.get('threshold')
        
        if threshold is None:
            return jsonify({"error": "Threshold value required"}), 400
        
        threshold = float(threshold)
        if threshold < 0.1 or threshold > 0.9:
            return jsonify({"error": "Threshold must be between 0.1 and 0.9"}), 400
        
        video_processor.set_detection_threshold(threshold)
        return jsonify({"success": True, "threshold": threshold})
    
    @performance_bp.route('/api/performance/confirm_frames', methods=['GET'])
    def get_confirm_frames():
        """Get current confirmation frames setting"""
        return jsonify({"confirm_frames": video_processor.confirm_frames})
    
    @performance_bp.route('/api/performance/confirm_frames', methods=['POST'])
    def set_confirm_frames():
        """Set detection confirmation frames (temporal confirmation)"""
        data = request.get_json()
        frames = data.get('frames')
        
        if frames is None:
            return jsonify({"error": "Frames value required"}), 400
        
        frames = int(frames)
        if frames < 1 or frames > 5:
            return jsonify({"error": "Frames must be between 1 and 5"}), 400
        
        video_processor.set_confirm_frames(frames)
        return jsonify({"success": True, "confirm_frames": frames})
    
    @performance_bp.route('/api/performance/profiles', methods=['GET'])
    def get_profiles():
        """Get all available performance profiles"""
        return jsonify(video_processor.get_performance_profiles())
    
    @performance_bp.route('/api/performance/profile', methods=['GET'])
    def get_current_profile():
        """Get current active performance profile"""
        return jsonify(video_processor.get_current_profile())
    
    @performance_bp.route('/api/performance/profile', methods=['POST'])
    def set_profile():
        """Set active performance profile"""
        data = request.get_json()
        profile_name = data.get('profile')
        
        if not profile_name:
            return jsonify({"error": "Profile name required"}), 400
        
        success = video_processor.set_performance_profile(profile_name)
        if success:
            return jsonify({
                "success": True,
                "profile": profile_name,
                "settings": config.PERFORMANCE_PROFILES.get(profile_name, {})
            })
        return jsonify({"error": "Invalid profile name"}), 400
