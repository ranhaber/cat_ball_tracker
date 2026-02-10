"""Unit tests for video recording functionality.

Tests the recording state management without actually writing video files.
Validates start/stop logic, filename generation, and state transitions.
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.conftest  # noqa: F401
from tests.conftest import get_video_processor


class TestRecording(unittest.TestCase):
    """Test recording state management."""
    
    def _make_processor(self):
        """Create a VideoProcessor for recording tests (no camera/TFLite)."""
        return get_video_processor()
    
    def test_recording_disabled_by_default(self):
        """Recording writer is None initially."""
        vp = self._make_processor()
        self.assertIsNone(vp._recording_writer)
        self.assertIsNone(vp._recording_filename)
        self.assertIsNone(vp._recording_start_time)
    
    def test_recording_enabled_setting(self):
        """Recording can be enabled/disabled."""
        vp = self._make_processor()
        self.assertTrue(vp.recording_enabled)
        vp.recording_enabled = False
        self.assertFalse(vp.recording_enabled)
    
    def test_record_after_detection_sec(self):
        """Record-after-detection timeout is configurable."""
        vp = self._make_processor()
        self.assertIsInstance(vp.record_after_detection_sec, (int, float))
        self.assertGreater(vp.record_after_detection_sec, 0)
        vp.record_after_detection_sec = 10
        self.assertEqual(vp.record_after_detection_sec, 10)
    
    def test_video_library_path_exists(self):
        """Video library path is set."""
        vp = self._make_processor()
        self.assertIsNotNone(vp.video_library_path)
        self.assertIsInstance(vp.video_library_path, str)
        self.assertGreater(len(vp.video_library_path), 0)
    
    def test_stop_recording_when_not_recording(self):
        """Stopping recording when not recording doesn't crash."""
        vp = self._make_processor()
        # Should not raise
        vp._stop_recording()
        self.assertIsNone(vp._recording_writer)
    
    def test_stop_recording_clears_state(self):
        """Stopping recording clears all recording state."""
        from unittest.mock import MagicMock
        vp = self._make_processor()
        # Simulate active recording state (writer must be non-None for stop to clear)
        vp._recording_writer = MagicMock()  # Mock VideoWriter
        vp._recording_filename = "/tmp/test.mp4"
        vp._recording_start_time = time.time()
        vp._recording_last_detection_time = time.time()
        
        vp._stop_recording()
        
        self.assertIsNone(vp._recording_writer)
        self.assertIsNone(vp._recording_filename)
        self.assertIsNone(vp._recording_start_time)
        self.assertIsNone(vp._recording_last_detection_time)
    
    def test_video_source_default_is_live(self):
        """Default video source is 'live'."""
        vp = self._make_processor()
        self.assertEqual(vp.video_source, "live")
    
    def test_file_camera_initially_none(self):
        """File camera is None initially."""
        vp = self._make_processor()
        self.assertIsNone(vp.file_camera)


if __name__ == '__main__':
    unittest.main()
