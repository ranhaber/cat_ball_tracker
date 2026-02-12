"""
Developer API routes — system info, inject cat test, service control.

Routes:
    POST /api/dev/inject_cat        — Toggle cat injection test mode
    GET  /api/dev/inject_cat_image  — Test cat image for H.264 overlay
    GET  /api/dev/system            — Detailed system information
    GET  /api/dev/service/<name>    — Service status
    POST /api/dev/service/<name>    — Start/stop service
"""

import os
import cv2
from flask import Blueprint, jsonify, request, send_file
from processing.memory import reclaim_memory
import config

dev_bp = Blueprint('dev', __name__)


def init_dev_routes(video_processor):
    """Register developer routes with access to the video processor."""
    
    @dev_bp.route('/api/dev/inject_cat', methods=['POST'])
    def dev_inject_cat():
        """Toggle cat injection test mode."""
        if not getattr(video_processor, 'inject_cat_handler', None):
            return jsonify({"error": "Video processor not started"}), 503
        data = request.get_json() or {}
        action = data.get('action', 'toggle')
        
        if action == 'toggle':
            new_state = not video_processor.inject_cat
        elif action == 'start':
            new_state = True
        elif action == 'stop':
            new_state = False
        else:
            new_state = not video_processor.inject_cat
        
        if new_state:
            # Enable
            video_processor.inject_cat_handler.enable()
            video_processor.inject_cat = True
        else:
            # Disable
            video_processor.inject_cat = False
            video_processor.inject_cat_handler.disable()
            
            # Clear detection state
            video_processor.last_detections_with_world = []
            video_processor.detection_history = []
            
            # Request cleanup in process loop (avoids deadlock: never call reset/unload from here while loop may be in detect())
            video_processor._request_motion_reset_after_inject = True
            video_processor._request_unload_after_inject = True
            video_processor._phase = "IDLE"
            video_processor._phase_frame_counter = 0
            
            # Force memory reclaim (safe from this thread)
            reclaim_memory()
            print("[INJECT CLEANUP] Cat image freed, phase=IDLE, cleanup requested (motion reset + unload in process loop)")
        
        status = "active" if video_processor.inject_cat else "stopped"
        print(f"[INJECT API] Cat injection: {status}, "
              f"img_loaded={video_processor.inject_cat_handler._img is not None}, "
              f"current_frame={'SET' if video_processor.current_frame is not None else 'NONE'}, "
              f"stream_clients={video_processor.stream_clients}")
        return jsonify({"inject_cat": video_processor.inject_cat, "status": status})
    
    @dev_bp.route('/api/dev/inject_cat_image', methods=['GET'])
    def dev_inject_cat_image():
        """Serve the test cat image for H.264 overlay drawing."""
        cat_path = os.path.join(config.BASE_DIR, 'models', 'test_cat.png')
        if not os.path.isfile(cat_path):
            return jsonify({"error": "test_cat.png not found"}), 404
        return send_file(cat_path, mimetype='image/png')
    
    @dev_bp.route('/api/dev/system', methods=['GET'])
    def dev_system_info():
        """Get detailed system information for developer tab."""
        import subprocess
        info = {}
        
        # RAM
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            for line in meminfo.split('\n'):
                if line.startswith('MemTotal:'):
                    info['ram_total_kb'] = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    info['ram_available_kb'] = int(line.split()[1])
                elif line.startswith('MemFree:'):
                    info['ram_free_kb'] = int(line.split()[1])
                elif line.startswith('SwapTotal:'):
                    info['swap_total_kb'] = int(line.split()[1])
                elif line.startswith('SwapFree:'):
                    info['swap_free_kb'] = int(line.split()[1])
                elif line.startswith('Buffers:'):
                    info['buffers_kb'] = int(line.split()[1])
                elif line.startswith('Cached:'):
                    info['cached_kb'] = int(line.split()[1])
        except Exception:
            pass
        
        # Process memory
        try:
            pid = os.getpid()
            with open(f'/proc/{pid}/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        info['process_rss_kb'] = int(line.split()[1])
                    elif line.startswith('VmSwap:'):
                        info['process_swap_kb'] = int(line.split()[1])
                    elif line.startswith('Threads:'):
                        info['process_threads'] = int(line.split()[1])
        except Exception:
            pass
        
        # CPU temp
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                info['cpu_temp'] = round(int(f.read().strip()) / 1000, 1)
        except Exception:
            pass
        
        # Disk
        try:
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    parts = lines[1].split()
                    info['disk_total'] = parts[1]
                    info['disk_used'] = parts[2]
                    info['disk_free'] = parts[3]
                    info['disk_percent'] = parts[4]
        except Exception:
            pass
        
        # Uptime
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_sec = float(f.read().split()[0])
                hours = int(uptime_sec // 3600)
                mins = int((uptime_sec % 3600) // 60)
                info['uptime'] = f"{hours}h {mins}m"
        except Exception:
            pass
        
        # Swap activity (pages swapped in/out since boot)
        try:
            with open('/proc/vmstat', 'r') as f:
                for line in f:
                    if line.startswith('pswpin '):
                        info['swap_in_pages'] = int(line.split()[1])
                    elif line.startswith('pswpout '):
                        info['swap_out_pages'] = int(line.split()[1])
            info['swap_in_mb'] = round((info.get('swap_in_pages', 0) * 4) / 1024, 1)
            info['swap_out_mb'] = round((info.get('swap_out_pages', 0) * 4) / 1024, 1)
        except Exception:
            pass
        
        # Swappiness
        try:
            with open('/proc/sys/vm/swappiness', 'r') as f:
                info['swappiness'] = int(f.read().strip())
        except Exception:
            pass
        
        # Stream clients
        info['stream_clients'] = video_processor.stream_clients
        info['tflite_loaded'] = video_processor.detector.is_loaded() if video_processor.detector else False
        info['motion_detected'] = video_processor.motion_detected
        info['ai_runs'] = video_processor.ai_detections_count
        info['inject_cat'] = video_processor.inject_cat
        
        return jsonify(info)
    
    # Cache service status to avoid expensive subprocess forks (sudo+systemctl)
    _service_status_cache = {}  # {name: (status_str, timestamp)}
    _SERVICE_CACHE_TTL = 30.0   # Seconds between actual systemctl calls
    
    @dev_bp.route('/api/dev/service/<name>', methods=['GET'])
    def dev_service_status(name):
        """Get status of a system service (cached, checks at most once per 30s)."""
        import subprocess
        import time as _time
        allowed = ['rpi-connect']
        if name not in allowed:
            return jsonify({"error": f"Service '{name}' not allowed"}), 403
        
        # Return cached status if fresh enough
        cached = _service_status_cache.get(name)
        if cached and (_time.time() - cached[1]) < _SERVICE_CACHE_TTL:
            return jsonify({"service": name, "status": cached[0]})
        
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', name],
                capture_output=True, text=True, timeout=5)
            status = result.stdout.strip()
            _service_status_cache[name] = (status, _time.time())
            return jsonify({"service": name, "status": status})
        except Exception as e:
            return jsonify({"service": name, "status": "unknown", "error": str(e)})
    
    @dev_bp.route('/api/dev/service/<name>', methods=['POST'])
    def dev_service_control(name):
        """Start or stop a system service."""
        import subprocess
        allowed = ['rpi-connect']
        if name not in allowed:
            return jsonify({"error": f"Service '{name}' not allowed"}), 403
        
        data = request.get_json() or {}
        action = data.get('action', 'toggle')
        
        if action == 'toggle':
            result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', name],
                capture_output=True, text=True, timeout=5)
            action = 'stop' if result.stdout.strip() == 'active' else 'start'
        
        if action not in ['start', 'stop']:
            return jsonify({"error": "Action must be 'start', 'stop', or 'toggle'"}), 400
        
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', action, name],
                capture_output=True, text=True, timeout=10)
            
            status_result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', name],
                capture_output=True, text=True, timeout=5)
            
            # Update cache after toggle
            import time as _time
            _service_status_cache[name] = (status_result.stdout.strip(), _time.time())
            
            print(f"[DEV] Service {name}: {action} → {status_result.stdout.strip()}")
            return jsonify({
                "service": name,
                "action": action,
                "status": status_result.stdout.strip(),
                "success": result.returncode == 0
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
