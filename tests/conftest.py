"""
Test configuration — mock unavailable modules on Windows.

On Raspberry Pi: all modules are available, tests use real implementations.
On Windows/dev: Flask, picamera2, tflite_runtime are mocked so tests can run.

This file is auto-loaded by unittest discovery before any test module.
Import get_video_processor() in tests that need a VideoProcessor instance.
"""

import sys
import os
import platform
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Detect platform
IS_RPI = platform.machine().startswith('aarch64') or platform.machine().startswith('arm')
IS_WINDOWS = sys.platform == 'win32'


def _mock_missing_modules():
    """Mock modules that aren't available on the current platform.
    Only mocks what's actually missing — real modules are never replaced."""
    
    modules_to_mock = []
    
    # Flask (not installed on Windows dev machines)
    try:
        import flask
    except ImportError:
        modules_to_mock.append('flask')
    
    # picamera2 (only on RPi)
    try:
        import picamera2
    except ImportError:
        modules_to_mock.append('picamera2')
    
    # tflite_runtime (only on RPi)
    try:
        import tflite_runtime
    except ImportError:
        modules_to_mock.append('tflite_runtime')
        modules_to_mock.append('tflite_runtime.interpreter')
    
    for mod_name in modules_to_mock:
        if mod_name not in sys.modules:
            mock = MagicMock()
            # Flask needs special handling — create_app and Blueprint must be callable
            if mod_name == 'flask':
                mock.Flask = MagicMock(return_value=MagicMock())
                mock.Blueprint = MagicMock(return_value=MagicMock())
                mock.jsonify = MagicMock(return_value='{}')
                mock.request = MagicMock()
                mock.Response = MagicMock()
                mock.render_template = MagicMock()
            sys.modules[mod_name] = mock
    
    if modules_to_mock:
        print(f"[TEST] Mocked missing modules: {', '.join(modules_to_mock)}")


# Run mocking before any test imports
_mock_missing_modules()


def get_video_processor():
    """Get a VideoProcessor instance for testing.
    
    Works on both RPi (real Flask) and Windows (mocked Flask).
    Does NOT call start() — no camera, TFLite, or threads.
    """
    from web.app import VideoProcessor
    return VideoProcessor()
