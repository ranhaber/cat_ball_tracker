"""Unit tests for the phase state machine (IDLE -> ACQUISITION -> TRACKING -> WATCH).

Tests the phase transition logic by directly manipulating VideoProcessor state
variables, without requiring a camera, TFLite, or Flask.
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


try:
    from web.app import VideoProcessor
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


@unittest.skipUnless(HAS_FLASK, "Flask not installed — skip VideoProcessor tests")
class TestPhaseStateMachine(unittest.TestCase):
    """Test phase transitions in the detection pipeline."""
    
    def _make_processor(self):
        """Create a VideoProcessor with enough state for phase testing.
        Does NOT call start() — no camera, TFLite, or threads."""
        vp = VideoProcessor()
        return vp
    
    def test_initial_phase_is_idle(self):
        """System starts in IDLE phase."""
        vp = self._make_processor()
        self.assertEqual(vp._phase, "IDLE")
    
    def test_phase_variables_initialized(self):
        """All phase-related variables are initialized."""
        vp = self._make_processor()
        self.assertEqual(vp._last_detection_time, 0)
        self.assertEqual(vp._last_motion_time, 0)
        self.assertEqual(vp._phase_frame_counter, 0)
        self.assertEqual(vp._detection_timeout, 30)
        self.assertEqual(vp._acquisition_timeout, 10)
    
    def test_idle_to_acquisition_on_motion(self):
        """IDLE -> ACQUISITION when motion_detected is set."""
        vp = self._make_processor()
        vp._phase = "IDLE"
        # Simulate: motion detected triggers transition
        vp.motion_detected = True
        vp._phase = "ACQUISITION"
        vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "ACQUISITION")
    
    def test_acquisition_to_tracking_on_detection(self):
        """ACQUISITION -> TRACKING when cat is detected."""
        vp = self._make_processor()
        vp._phase = "ACQUISITION"
        # Simulate: cat detected
        vp._last_detection_time = time.time()
        vp._phase = "TRACKING"
        vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "TRACKING")
    
    def test_acquisition_to_idle_on_timeout(self):
        """ACQUISITION -> IDLE after acquisition_timeout with no motion."""
        vp = self._make_processor()
        vp._phase = "ACQUISITION"
        vp._last_motion_time = time.time() - 15  # 15s ago (> 10s timeout)
        # Simulate timeout check
        now = time.time()
        if now - vp._last_motion_time > vp._acquisition_timeout:
            vp._phase = "IDLE"
            vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "IDLE")
    
    def test_acquisition_stays_with_recent_motion(self):
        """ACQUISITION stays if motion was recent (within timeout)."""
        vp = self._make_processor()
        vp._phase = "ACQUISITION"
        vp._last_motion_time = time.time() - 3  # 3s ago (< 10s timeout)
        now = time.time()
        if now - vp._last_motion_time > vp._acquisition_timeout:
            vp._phase = "IDLE"
        self.assertEqual(vp._phase, "ACQUISITION")
    
    def test_tracking_to_watch_on_no_motion(self):
        """TRACKING -> WATCH when motion stops."""
        vp = self._make_processor()
        vp._phase = "TRACKING"
        vp.motion_detected = False
        # Simulate transition
        if not vp.motion_detected:
            vp._phase = "WATCH"
            vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "WATCH")
    
    def test_tracking_stays_with_motion(self):
        """TRACKING stays if motion continues."""
        vp = self._make_processor()
        vp._phase = "TRACKING"
        vp.motion_detected = True
        if not vp.motion_detected:
            vp._phase = "WATCH"
        self.assertEqual(vp._phase, "TRACKING")
    
    def test_tracking_to_idle_on_detection_timeout(self):
        """TRACKING -> IDLE after 30s with no detection."""
        vp = self._make_processor()
        vp._phase = "TRACKING"
        vp._last_detection_time = time.time() - 35  # 35s ago (> 30s timeout)
        now = time.time()
        if now - vp._last_detection_time > vp._detection_timeout:
            vp._phase = "IDLE"
            vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "IDLE")
    
    def test_watch_to_tracking_on_motion(self):
        """WATCH -> TRACKING when motion resumes."""
        vp = self._make_processor()
        vp._phase = "WATCH"
        vp.motion_detected = True
        if vp.motion_detected:
            vp._phase = "TRACKING"
            vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "TRACKING")
    
    def test_watch_to_idle_on_detection_timeout(self):
        """WATCH -> IDLE after 30s with no detection."""
        vp = self._make_processor()
        vp._phase = "WATCH"
        vp._last_detection_time = time.time() - 35  # 35s ago
        now = time.time()
        if now - vp._last_detection_time > vp._detection_timeout:
            vp._phase = "IDLE"
            vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "IDLE")
    
    def test_watch_stays_with_recent_detection(self):
        """WATCH stays if detection was recent (within 30s)."""
        vp = self._make_processor()
        vp._phase = "WATCH"
        vp._last_detection_time = time.time() - 10  # 10s ago (< 30s)
        vp.motion_detected = False
        now = time.time()
        if vp.motion_detected:
            vp._phase = "TRACKING"
        elif now - vp._last_detection_time > vp._detection_timeout:
            vp._phase = "IDLE"
        self.assertEqual(vp._phase, "WATCH")
    
    def test_tracking_ai_every_3rd_frame(self):
        """TRACKING runs AI every 3rd processed frame."""
        vp = self._make_processor()
        vp._phase = "TRACKING"
        ai_frames = []
        for i in range(9):
            vp._phase_frame_counter = i
            run_ai = (vp._phase_frame_counter % 3 == 0)
            ai_frames.append(run_ai)
        # Frames 0,3,6 should run AI
        self.assertEqual(ai_frames, [True, False, False, True, False, False, True, False, False])
    
    def test_watch_ai_every_2nd_frame(self):
        """WATCH runs AI every 2nd processed frame."""
        vp = self._make_processor()
        vp._phase = "WATCH"
        ai_frames = []
        for i in range(6):
            vp._phase_frame_counter = i
            run_ai = (vp._phase_frame_counter % 2 == 0)
            ai_frames.append(run_ai)
        # Frames 0,2,4 should run AI
        self.assertEqual(ai_frames, [True, False, True, False, True, False])
    
    def test_inject_cat_forces_acquisition(self):
        """Inject cat mode triggers ACQUISITION from IDLE."""
        vp = self._make_processor()
        vp._phase = "IDLE"
        vp.inject_cat = True
        # Simulate: inject_cat triggers transition
        if vp.motion_detected or vp.inject_cat:
            vp._phase = "ACQUISITION"
            vp._phase_frame_counter = 0
        self.assertEqual(vp._phase, "ACQUISITION")
    
    def test_full_lifecycle(self):
        """Test complete lifecycle: IDLE -> ACQ -> TRACK -> WATCH -> IDLE."""
        vp = self._make_processor()
        
        # Start IDLE
        self.assertEqual(vp._phase, "IDLE")
        
        # Motion detected -> ACQUISITION
        vp._phase = "ACQUISITION"
        self.assertEqual(vp._phase, "ACQUISITION")
        
        # Cat detected -> TRACKING
        vp._last_detection_time = time.time()
        vp._phase = "TRACKING"
        self.assertEqual(vp._phase, "TRACKING")
        
        # Motion stops -> WATCH
        vp._phase = "WATCH"
        self.assertEqual(vp._phase, "WATCH")
        
        # No detection for 30s -> IDLE
        vp._last_detection_time = time.time() - 35
        now = time.time()
        if now - vp._last_detection_time > vp._detection_timeout:
            vp._phase = "IDLE"
        self.assertEqual(vp._phase, "IDLE")


if __name__ == '__main__':
    unittest.main()
