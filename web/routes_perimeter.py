"""
Perimeter (Detection Zone) and top-down view routes.

Routes:
    GET    /api/perimeter  — Get perimeter points
    POST   /api/perimeter  — Set perimeter points (undistorted → raw conversion)
    DELETE /api/perimeter  — Clear perimeter
    GET    /api/topdown    — Top-down view data (world coordinates)
"""

from flask import Blueprint, jsonify, request

perimeter_bp = Blueprint('perimeter', __name__)


def init_perimeter_routes(video_processor):
    """Register perimeter routes with access to the video processor."""
    
    @perimeter_bp.route('/api/perimeter', methods=['GET'])
    def get_perimeter():
        """Get current perimeter points with resolution info"""
        return jsonify({
            "points": video_processor.get_perimeter(),
            "resolution": list(video_processor.current_resolution)
        })
    
    @perimeter_bp.route('/api/perimeter', methods=['POST'])
    def set_perimeter():
        """Set perimeter points.
        Points are clicked on the undistorted+cropped snapshot.
        They are converted to raw camera pixel space for:
        - Streaming overlay (draw_perimeter on raw frame)
        - Detection filtering (is_inside check on raw detection pixels)
        The top-down view re-undistorts them via pixel_to_world."""
        data = request.get_json()
        points = data.get('points', [])
        
        if len(points) < 3:
            return jsonify({"error": "Need at least 3 points"}), 400
        
        # Convert from undistorted+cropped space to raw camera space
        raw_points = video_processor._redistort_pixels(points)
        
        cam_width, cam_height = video_processor.current_resolution
        if video_processor.perimeter:
            video_processor.perimeter.set_saved_resolution(cam_width, cam_height)
        success = video_processor.set_perimeter(raw_points)
        
        if success:
            print(f"[SETTING] Perimeter: {len(raw_points)} points redistorted to raw {cam_width}x{cam_height}")
            print(f"  Undistorted first: {points[0]}, Raw: {raw_points[0]}")
        
        return jsonify({
            "success": success, 
            "points": video_processor.get_perimeter(),
            "camera_resolution": [cam_width, cam_height]
        })
    
    @perimeter_bp.route('/api/perimeter', methods=['DELETE'])
    def clear_perimeter():
        """Reset perimeter to default"""
        video_processor.clear_perimeter()
        return jsonify({"success": True, "points": video_processor.get_perimeter()})
    
    @perimeter_bp.route('/api/topdown', methods=['GET'])
    def get_topdown_view():
        """Get top-down (bird's eye) view data including:
        - Perimeter polygon in world coordinates
        - Tracked objects in world coordinates
        - World bounds for scaling"""
        data = video_processor.get_topdown_data()
        return jsonify(data)
