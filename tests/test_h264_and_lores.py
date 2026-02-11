"""Unit tests for v3.9.0-3.10.0 features:
- ISP lores dual-stream helpers
- Motion detector gray_input parameter
- H.264 streaming infrastructure
- Manual focus controls
- Overlay data generation
"""

import sys
import os
import unittest
import threading
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Must import conftest to mock missing modules on Windows
from tests.conftest import get_video_processor

import config
from detection.motion_detector import MotionDetector


# =============================================================================
# Motion Detector: gray_input parameter
# =============================================================================

class TestMotionDetectorGrayInput(unittest.TestCase):
    """Test motion detector with both BGR and grayscale inputs."""
    
    def setUp(self):
        self.detector = MotionDetector(
            detection_scale=0.5,
            motion_threshold=25,
            min_area=100,
            history_frames=3
        )
    
    def test_detect_bgr_default(self):
        """Standard BGR input works as before."""
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        result = self.detector.detect(frame)
        self.assertIn('motion_detected', result)
        self.assertIn('regions', result)
        self.assertIsInstance(result['regions'], list)
    
    def test_detect_gray_input(self):
        """Grayscale input with gray_input=True skips cvtColor."""
        gray_frame = np.zeros((540, 960), dtype=np.uint8)
        result = self.detector.detect(gray_frame, gray_input=True)
        self.assertIn('motion_detected', result)
        self.assertIn('regions', result)
    
    def test_gray_input_detects_motion(self):
        """Motion is detected from grayscale input (white square moves)."""
        # Build up background with blank frames
        for _ in range(3):
            blank = np.zeros((200, 300), dtype=np.uint8)
            self.detector.detect(blank, gray_input=True)
        
        # Introduce a bright square (motion)
        motion_frame = np.zeros((200, 300), dtype=np.uint8)
        motion_frame[50:100, 50:100] = 255
        result = self.detector.detect(motion_frame, gray_input=True)
        self.assertTrue(result['motion_detected'])
        self.assertGreater(len(result['regions']), 0)
    
    def test_gray_input_no_motion_on_static(self):
        """No motion detected on identical grayscale frames."""
        static = np.full((200, 300), 128, dtype=np.uint8)
        for _ in range(5):
            result = self.detector.detect(static, gray_input=True)
        self.assertFalse(result['motion_detected'])
    
    def test_bgr_and_gray_produce_similar_results(self):
        """BGR and grayscale paths both detect motion from the same scene."""
        det_bgr = MotionDetector(detection_scale=0.5, history_frames=3)
        det_gray = MotionDetector(detection_scale=0.5, history_frames=3)
        
        # Background
        for _ in range(3):
            bgr = np.zeros((200, 300, 3), dtype=np.uint8)
            gray = np.zeros((200, 300), dtype=np.uint8)
            det_bgr.detect(bgr)
            det_gray.detect(gray, gray_input=True)
        
        # Motion
        bgr_motion = np.zeros((200, 300, 3), dtype=np.uint8)
        bgr_motion[50:100, 50:100] = (255, 255, 255)
        gray_motion = np.zeros((200, 300), dtype=np.uint8)
        gray_motion[50:100, 50:100] = 255
        
        r_bgr = det_bgr.detect(bgr_motion)
        r_gray = det_gray.detect(gray_motion, gray_input=True)
        
        self.assertEqual(r_bgr['motion_detected'], r_gray['motion_detected'])


# =============================================================================
# H264StreamOutput
# =============================================================================

class TestH264StreamOutput(unittest.TestCase):
    """Test H264StreamOutput buffer for WebSocket streaming."""
    
    def test_import(self):
        """H264StreamOutput can be imported."""
        from camera.camera_handler import H264StreamOutput
        output = H264StreamOutput()
        self.assertIsNone(output.frame)
    
    def test_write_and_get_frame(self):
        """Written data can be retrieved via get_frame."""
        from camera.camera_handler import H264StreamOutput
        output = H264StreamOutput()
        
        test_data = b'\x00\x00\x00\x01\x67test_nalu'
        output.write(test_data)
        
        frame = output.get_frame(timeout=1.0)
        self.assertEqual(frame, test_data)
    
    def test_get_frame_clears_buffer(self):
        """get_frame returns None on second call (consumed)."""
        from camera.camera_handler import H264StreamOutput
        output = H264StreamOutput()
        
        output.write(b'data')
        output.get_frame(timeout=0.1)
        frame2 = output.get_frame(timeout=0.1)
        self.assertIsNone(frame2)
    
    def test_get_frame_timeout(self):
        """get_frame returns None when no data and timeout expires."""
        from camera.camera_handler import H264StreamOutput
        output = H264StreamOutput()
        
        frame = output.get_frame(timeout=0.05)
        self.assertIsNone(frame)
    
    def test_threaded_write_read(self):
        """Writer thread and reader thread communicate correctly."""
        from camera.camera_handler import H264StreamOutput
        output = H264StreamOutput()
        received = []
        
        def writer():
            for i in range(5):
                output.write(f"frame_{i}".encode())
                import time; time.sleep(0.01)
        
        def reader():
            for _ in range(5):
                f = output.get_frame(timeout=1.0)
                if f:
                    received.append(f)
        
        t_w = threading.Thread(target=writer)
        t_r = threading.Thread(target=reader)
        t_r.start()
        t_w.start()
        t_w.join()
        t_r.join()
        
        self.assertGreater(len(received), 0)


# =============================================================================
# VideoProcessor: H.264 client tracking
# =============================================================================

class TestVideoProcessorH264Clients(unittest.TestCase):
    """Test H.264 WebSocket client counter (without starting camera)."""
    
    def setUp(self):
        self.vp = get_video_processor()
    
    def test_initial_h264_clients_zero(self):
        """H.264 client count starts at 0."""
        self.assertEqual(self.vp.h264_clients, 0)
    
    def test_increment_h264_clients(self):
        """Incrementing increases the count."""
        n = self.vp.increment_h264_clients()
        self.assertEqual(n, 1)
        self.assertEqual(self.vp.h264_clients, 1)
        # Clean up
        self.vp.decrement_h264_clients()
    
    def test_decrement_h264_clients(self):
        """Decrementing decreases the count."""
        self.vp.increment_h264_clients()
        self.vp.increment_h264_clients()
        n = self.vp.decrement_h264_clients()
        self.assertEqual(n, 1)
        self.vp.decrement_h264_clients()
    
    def test_decrement_never_negative(self):
        """Client count never goes below 0."""
        n = self.vp.decrement_h264_clients()
        self.assertEqual(n, 0)
        self.assertEqual(self.vp.h264_clients, 0)


# =============================================================================
# VideoProcessor: Overlay data
# =============================================================================

class TestOverlayData(unittest.TestCase):
    """Test overlay data generation for H.264 Canvas rendering."""
    
    def setUp(self):
        self.vp = get_video_processor()
    
    def test_initial_overlay_is_none(self):
        """Overlay data is None before any frame is processed."""
        self.assertIsNone(self.vp.get_overlay_data())
    
    def test_update_overlay_data_basic(self):
        """_update_overlay_data produces a valid dict."""
        self.vp._update_overlay_data(
            last_detections=[],
            motion_regions_in_perimeter=[],
            crop_region=None,
            tracked_objects={}
        )
        data = self.vp.get_overlay_data()
        self.assertIsNotNone(data)
        self.assertIn('phase', data)
        self.assertIn('fps', data)
        self.assertIn('detections', data)
        self.assertIn('capture_res', data)
        self.assertEqual(data['capture_res'], [2304, 1296])
    
    def test_overlay_with_detections(self):
        """Detections are correctly serialized."""
        det = [(100, 200, 300, 400, 0.87, 17)]  # x1,y1,x2,y2,conf,class_id
        self.vp._update_overlay_data(det, [], None, {})
        data = self.vp.get_overlay_data()
        self.assertEqual(len(data['detections']), 1)
        d = data['detections'][0]
        self.assertEqual(d['x1'], 100)
        self.assertEqual(d['y2'], 400)
        self.assertEqual(d['conf'], 0.87)
        self.assertEqual(d['class'], 'Cat')
    
    def test_overlay_with_motion_regions(self):
        """Motion regions are included when show_motion is on."""
        self.vp.show_motion_regions = True
        regions = [(50, 60, 120, 80)]
        self.vp._update_overlay_data([], regions, None, {})
        data = self.vp.get_overlay_data()
        self.assertEqual(len(data['motion_regions']), 1)
        self.assertEqual(data['motion_regions'][0], [50, 60, 120, 80])
    
    def test_overlay_motion_hidden_when_disabled(self):
        """Motion regions are empty when show_motion_regions is False."""
        self.vp.show_motion_regions = False
        regions = [(50, 60, 120, 80)]
        self.vp._update_overlay_data([], regions, None, {})
        data = self.vp.get_overlay_data()
        self.assertEqual(data['motion_regions'], [])


# =============================================================================
# VideoProcessor: Lores helpers
# =============================================================================

class TestLoresHelpers(unittest.TestCase):
    """Test ISP lores stream helper methods."""
    
    def setUp(self):
        self.vp = get_video_processor()
    
    def test_lores_motion_scale_when_not_using_lores(self):
        """When lores is not active, scale is returned unchanged."""
        self.vp._using_lores = False
        result = self.vp._lores_motion_scale(0.30)
        self.assertEqual(result, 0.30)
    
    def test_lores_motion_scale_when_using_lores(self):
        """When lores is active, scale is adjusted proportionally."""
        self.vp._using_lores = True
        self.vp._lores_resolution = (960, 540)
        # 0.30 * (2304/960) = 0.72
        result = self.vp._lores_motion_scale(0.30)
        self.assertAlmostEqual(result, 0.72, places=2)
    
    def test_lores_motion_scale_capped_at_1(self):
        """Adjusted scale is capped at 1.0."""
        self.vp._using_lores = True
        self.vp._lores_resolution = (480, 270)
        # 0.30 * (2304/480) = 1.44 → capped to 1.0
        result = self.vp._lores_motion_scale(0.30)
        self.assertEqual(result, 1.0)
    
    def test_scale_motion_to_main_when_not_using_lores(self):
        """Regions are unchanged when not using lores."""
        self.vp._using_lores = False
        motion = {"regions": [(10, 20, 30, 40)], "combined_region": (10, 20, 30, 40)}
        result = self.vp._scale_motion_to_main(motion, 2304, 1296)
        self.assertEqual(result["regions"][0], (10, 20, 30, 40))
    
    def test_scale_motion_to_main_scales_correctly(self):
        """Regions are scaled from lores to main coordinates."""
        self.vp._using_lores = True
        self.vp._lores_resolution = (960, 540)
        motion = {"regions": [(100, 100, 50, 50)], "combined_region": (100, 100, 50, 50)}
        self.vp.motion_detector = MotionDetector()
        
        result = self.vp._scale_motion_to_main(motion, 2304, 1296)
        # 100 * (2304/960) = 240
        self.assertEqual(result["regions"][0][0], 240)


# =============================================================================
# Camera Handler: _build_controls
# =============================================================================

class TestBuildControls(unittest.TestCase):
    """Test camera controls builder (manual focus configuration)."""
    
    def test_build_controls_includes_framerate(self):
        """Controls always include FrameRate."""
        from camera.camera_handler import CameraHandler
        handler = CameraHandler.__new__(CameraHandler)
        handler.fps = 15
        controls = handler._build_controls()
        self.assertEqual(controls['FrameRate'], 15)
    
    def test_build_controls_includes_af_mode(self):
        """Controls include AfMode when configured."""
        from camera.camera_handler import CameraHandler
        handler = CameraHandler.__new__(CameraHandler)
        handler.fps = 10
        # AF_MODE is set in config
        controls = handler._build_controls()
        if hasattr(config, 'AF_MODE') and config.AF_MODE is not None:
            self.assertIn('AfMode', controls)
            self.assertEqual(controls['AfMode'], config.AF_MODE)
            self.assertIn('LensPosition', controls)


if __name__ == '__main__':
    unittest.main()
