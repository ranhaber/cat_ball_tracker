"""
Status and detection mode routes.

Routes:
    GET  /api/status     — Current system status
    GET  /api/mode       — Current detection mode
    POST /api/mode       — Set detection mode (cat/ball)
"""

from flask import Blueprint, jsonify, request

status_bp = Blueprint('status', __name__)


def init_status_routes(video_processor):
    """Register status routes with access to the video processor."""
    
    @status_bp.route('/api/status')
    def get_status():
        """Get current system status"""
        return jsonify(video_processor.get_status())
    
    @status_bp.route('/api/mode', methods=['GET'])
    def get_mode():
        """Get current detection mode"""
        return jsonify({"mode": video_processor.get_detection_mode()})
    
    @status_bp.route('/api/mode', methods=['POST'])
    def set_mode():
        """Set detection mode"""
        data = request.get_json()
        mode = data.get('mode', 'cat')
        
        if mode not in ['cat', 'ball']:
            return jsonify({"error": "Invalid mode. Use 'cat' or 'ball'"}), 400
        
        video_processor.set_detection_mode(mode)
        return jsonify({"mode": mode, "success": True})
