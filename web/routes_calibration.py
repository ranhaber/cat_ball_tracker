"""
Calibration routes — perspective calibration, lens calibration, coordinate conversion.

These routes handle the full calibration pipeline:
1. Lens calibration (plumb lines → distortion coefficients)
2. Perspective calibration (rectangles → homography matrix)
3. Coordinate conversion (pixel → world)

The calibration work order is preserved exactly:
- Lens calibration FIRST (corrects barrel distortion)
- Then perspective calibration on lens-corrected snapshots
- Then detection zone on lens-corrected snapshots

Routes:
    GET/POST/DELETE  /api/calibration           — Perspective calibration
    GET              /api/calibration/debug      — Diagnostic comparison
    GET/POST         /api/calibration/lines      — Calibration reference lines
    POST             /api/calibration/convert    — Pixel → world conversion
    GET/POST/DELETE  /api/lens_calibration       — Lens distortion calibration
    GET              /api/lens_calibration/analyze   — Per-line quality scores
    GET              /api/lens_calibration/progress  — Optimization progress
    GET/POST/DELETE  /api/lens_calibration/lines     — Lines data management
    POST             /api/lens_calibration/lines/recover — Recover from backup
    POST             /api/lens_calibration/lines/delete  — Delete specific lines
    POST             /api/lens_calibration/lines/append  — Append single line
"""

import math
from flask import Blueprint, jsonify, request
import settings

calibration_bp = Blueprint('calibration', __name__)


def init_calibration_routes(video_processor):
    """Register calibration routes with access to the video processor."""
    
    # =========================================================================
    # Perspective Calibration
    # =========================================================================
    
    @calibration_bp.route('/api/calibration', methods=['GET'])
    def get_calibration():
        """Get current calibration status and points"""
        calib = video_processor.get_calibration()
        # Also include saved lines
        saved = settings.load_settings()
        calib["lines"] = saved.get("calibration_lines", [])
        return jsonify(calib)
    
    @calibration_bp.route('/api/calibration', methods=['POST'])
    def set_calibration():
        """Set calibration from one or more rectangles."""
        data = request.get_json()
        rectangles = data.get('rectangles', [])
        
        if not rectangles:
            return jsonify({"error": "Need at least 1 rectangle"}), 400
        
        for i, rect in enumerate(rectangles):
            if not rect.get("pixels") or len(rect["pixels"]) != 4:
                return jsonify({"error": f"Rectangle {i+1} needs exactly 4 pixel points"}), 400
            if not rect.get("side_lengths") or len(rect["side_lengths"]) != 4:
                return jsonify({"error": f"Rectangle {i+1} needs exactly 4 side lengths"}), 400
            try:
                rect["side_lengths"] = [float(x) for x in rect["side_lengths"]]
                rect["pixels"] = [[float(p[0]), float(p[1])] for p in rect["pixels"]]
            except (TypeError, ValueError, IndexError):
                return jsonify({"error": f"Rectangle {i+1} has invalid data"}), 400
            if rect.get("diagonal") is not None:
                try:
                    rect["diagonal"] = float(rect["diagonal"])
                except (TypeError, ValueError):
                    rect["diagonal"] = None
        
        success = video_processor.set_calibration_from_rectangles(rectangles)
        
        if success:
            return jsonify({
                "success": True,
                "calibration": video_processor.get_calibration()
            })
        return jsonify({"error": "Calibration failed"}), 400
    
    @calibration_bp.route('/api/calibration', methods=['DELETE'])
    def clear_calibration():
        """Clear calibration"""
        video_processor.clear_calibration()
        # Also clear saved calibration lines
        settings.update_setting("calibration_lines", [])
        print("[SETTING] Calibration cleared")
        return jsonify({"success": True, "calibration": video_processor.get_calibration()})
    
    @calibration_bp.route('/api/calibration/debug', methods=['GET'])
    def calibration_debug():
        """Diagnostic: compare calibration rectangles, perimeter, and world coords."""
        debug = {
            "lens_calibration": "ON" if video_processor.lens_calibration and video_processor.lens_calibration.is_calibrated else "OFF",
            "is_calibrated": video_processor.calibration.is_calibrated if video_processor.calibration else False,
        }
        
        # Camera resolution
        frame_res = None
        if video_processor.camera and video_processor.camera.running:
            frame_res = video_processor.camera.get_resolution()
        debug["camera_resolution"] = list(frame_res) if frame_res else None
        
        # Perimeter info
        perim_saved_res = None
        if hasattr(video_processor.perimeter, 'saved_resolution'):
            perim_saved_res = list(video_processor.perimeter.saved_resolution)
        debug["perimeter_saved_resolution"] = perim_saved_res
        
        # Calibration rectangles (original pixels)
        rects = video_processor.calibration.rectangles if video_processor.calibration else []
        debug["rectangles"] = []
        for i, rect in enumerate(rects):
            debug["rectangles"].append({
                "index": i + 1,
                "pixels": rect.get("pixels", []),
                "side_lengths": rect.get("side_lengths", []),
                "diagonal": rect.get("diagonal"),
            })
        
        # Calibration points (pixel + world, as used by homography)
        cal_pts = video_processor.calibration.calibration_points if video_processor.calibration else []
        debug["calibration_points"] = []
        for i, cp in enumerate(cal_pts):
            debug["calibration_points"].append({
                "index": i,
                "pixel": [round(cp["pixel"][0], 1), round(cp["pixel"][1], 1)],
                "world": [round(cp["world"][0], 4), round(cp["world"][1], 4)],
            })
        
        # Perimeter points and their world transformations
        perim_points = video_processor.get_perimeter()
        debug["perimeter_points"] = []
        if perim_points and video_processor.calibration and video_processor.calibration.is_calibrated:
            for i, point in enumerate(perim_points):
                px, py = float(point[0]), float(point[1])
                
                # Perimeter pixels are in raw camera space (redistorted at save)
                world_pos = video_processor.pixel_to_world(px, py, already_undistorted=False)
                
                debug["perimeter_points"].append({
                    "index": i,
                    "pixel": [round(px, 1), round(py, 1)],
                    "world": [round(world_pos[0], 4), round(world_pos[1], 4)] if world_pos else None,
                    "note": "already undistorted (clicked on corrected image)"
                })
            
            # Compute side lengths in top-down view
            world_pts = [p["world"] for p in debug["perimeter_points"] if p["world"]]
            n = len(world_pts)
            sides = []
            for i in range(n):
                j = (i + 1) % n
                dx = world_pts[j][0] - world_pts[i][0]
                dy = world_pts[j][1] - world_pts[i][1]
                sides.append(round(math.sqrt(dx*dx + dy*dy), 4))
            debug["topdown_side_lengths"] = sides
        
        return jsonify(debug)
    
    @calibration_bp.route('/api/calibration/lines', methods=['GET'])
    def get_calibration_lines():
        """Get saved calibration lines"""
        saved = settings.load_settings()
        lines = saved.get("calibration_lines", [])
        return jsonify({"lines": lines, "is_calibrated": len(lines) > 0})
    
    @calibration_bp.route('/api/calibration/lines', methods=['POST'])
    def save_calibration_lines():
        """Save calibration lines"""
        data = request.get_json()
        lines = data.get('lines', [])
        settings.update_setting("calibration_lines", lines)
        print(f"[SETTING] Calibration lines updated: {len(lines)} lines defined")
        return jsonify({"success": True, "lines": lines, "is_calibrated": len(lines) > 0})
    
    @calibration_bp.route('/api/calibration/convert', methods=['POST'])
    def convert_coordinates():
        """Convert pixel coordinates to world coordinates"""
        data = request.get_json()
        pixel_x = data.get('x')
        pixel_y = data.get('y')
        
        if pixel_x is None or pixel_y is None:
            return jsonify({"error": "x and y coordinates required"}), 400
        
        world_pos = video_processor.pixel_to_world(float(pixel_x), float(pixel_y))
        
        if world_pos:
            return jsonify({
                "pixel": {"x": pixel_x, "y": pixel_y},
                "world": {"x": round(world_pos[0], 2), "y": round(world_pos[1], 2)}
            })
        return jsonify({"error": "Not calibrated or conversion failed"}), 400
    
    # =========================================================================
    # Lens Calibration
    # =========================================================================
    
    @calibration_bp.route('/api/lens_calibration', methods=['GET'])
    def get_lens_calibration():
        """Get lens calibration status and parameters."""
        if video_processor.lens_calibration:
            return jsonify(video_processor.lens_calibration.get_status())
        return jsonify({"is_calibrated": False})
    
    @calibration_bp.route('/api/lens_calibration', methods=['POST'])
    def set_lens_calibration():
        """Run lens calibration from plumb lines.
        Body: { lines: [[[x,y],[x,y],[x,y],...], ...], image_width: W, image_height: H }
        """
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        lines = data.get('lines', [])
        image_width = data.get('image_width', 0)
        image_height = data.get('image_height', 0)
        if not lines or not image_width or not image_height:
            return jsonify({"error": "Missing lines, image_width, or image_height"}), 400
        try:
            result = video_processor.lens_calibration.calibrate(lines, image_width, image_height)
            return jsonify({"success": True, "calibration": result})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            print(f"[LENS] Calibration error: {e}")
            return jsonify({"error": f"Calibration failed: {e}"}), 500
    
    @calibration_bp.route('/api/lens_calibration/analyze', methods=['GET'])
    def analyze_lens_lines():
        """Analyze all lines and return per-line quality scores."""
        if not video_processor.lens_calibration or not video_processor.lens_calibration.lines:
            return jsonify({"error": "No lines data available"}), 404
        result = video_processor.lens_calibration.analyze_lines()
        return jsonify(result)
    
    @calibration_bp.route('/api/lens_calibration/progress', methods=['GET'])
    def get_lens_progress():
        """Poll calibration progress during optimization."""
        if video_processor.lens_calibration:
            return jsonify(video_processor.lens_calibration.get_progress())
        return jsonify({"in_progress": False, "iteration": 0, "max_iterations": 0})
    
    @calibration_bp.route('/api/lens_calibration', methods=['DELETE'])
    def clear_lens_calibration():
        """Clear lens calibration and delete saved file."""
        if video_processor.lens_calibration:
            video_processor.lens_calibration.clear()
        return jsonify({"success": True})
    
    @calibration_bp.route('/api/lens_calibration/lines', methods=['GET'])
    def export_lens_lines():
        """Export lines/points data as JSON."""
        if not video_processor.lens_calibration or not video_processor.lens_calibration.lines:
            return jsonify({"lines": [], "num_lines": 0, "total_points": 0,
                            "image_width": 0, "image_height": 0})
        data = video_processor.lens_calibration.export_lines()
        return jsonify(data)
    
    @calibration_bp.route('/api/lens_calibration/lines', methods=['POST'])
    def import_lens_lines():
        """Import lines/points data from JSON. Replaces all lines."""
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        try:
            result = video_processor.lens_calibration.import_lines(data)
            return jsonify({"success": True, **result})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    
    @calibration_bp.route('/api/lens_calibration/lines', methods=['DELETE'])
    def clear_lens_lines():
        """Delete all lines (but keep calibration result if any)."""
        if video_processor.lens_calibration:
            video_processor.lens_calibration.clear_lines()
        return jsonify({"success": True})
    
    @calibration_bp.route('/api/lens_calibration/lines/recover', methods=['POST'])
    def recover_lens_lines():
        """Recover lines from lens_calibration.json after accidental deletion."""
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        count = video_processor.lens_calibration.recover_lines_from_calibration()
        if count > 0:
            return jsonify({"success": True, "recovered_lines": count})
        return jsonify({"error": "No lines found in calibration data to recover"}), 404
    
    @calibration_bp.route('/api/lens_calibration/lines/delete', methods=['POST'])
    def delete_lens_lines():
        """Delete specific lines by number (1-based).
        Body: { line: 1 } or { lines: [1, 2] }
        """
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        line_numbers = data.get('lines', [])
        single = data.get('line', None)
        if single is not None:
            line_numbers = [int(single)]
        if not line_numbers:
            return jsonify({"error": "Specify 'line' (number) or 'lines' (array of numbers)"}), 400
        try:
            remaining = video_processor.lens_calibration.delete_lines([int(n) for n in line_numbers])
            return jsonify({"success": True, "remaining_lines": remaining})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    
    @calibration_bp.route('/api/lens_calibration/lines/append', methods=['POST'])
    def append_lens_line():
        """Append a single line. Auto-saves to file."""
        if not video_processor.lens_calibration:
            return jsonify({"error": "Lens calibration not available"}), 500
        data = request.get_json()
        points = data.get('points', [])
        image_width = data.get('image_width', 0)
        image_height = data.get('image_height', 0)
        try:
            count = video_processor.lens_calibration.append_line(points, image_width, image_height)
            return jsonify({"success": True, "num_lines": count})
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
