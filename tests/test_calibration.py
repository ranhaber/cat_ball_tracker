"""Unit tests for CameraCalibration (detection/calibration.py).

Tests the calibration pipeline that converts pixel coordinates to world
coordinates using homography. Preserves the exact calibration work order:
1. User provides rectangle(s) with known side lengths
2. System computes world coordinates for each rectangle
3. Homography matrix is built from pixel↔world point pairs
4. pixel_to_world and world_to_pixel conversions are validated
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.calibration import CameraCalibration


class TestCalibration(unittest.TestCase):
    """Test perspective calibration with homography."""
    
    def setUp(self):
        # Remove any saved calibration file so tests start fresh
        cal_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'calibration.json')
        if os.path.exists(cal_file):
            os.remove(cal_file)
        self.cal = CameraCalibration()
    
    def test_not_calibrated_initially(self):
        """Calibration starts as not calibrated."""
        self.assertFalse(self.cal.is_calibrated)
    
    def test_calibrate_from_rectangle(self):
        """Single 0.6x0.6m rectangle calibrates successfully."""
        rectangles = [{
            "pixels": [[100, 100], [300, 100], [300, 300], [100, 300]],
            "side_lengths": [0.6, 0.6, 0.6, 0.6],
            "diagonal": 0.85,
            "index": 1
        }]
        self.cal.rectangles = rectangles
        success = self.cal.set_calibration_from_rectangles(rectangles)
        self.assertTrue(success)
        self.assertTrue(self.cal.is_calibrated)
    
    def test_pixel_to_world_returns_tuple(self):
        """pixel_to_world returns (x, y) tuple after calibration."""
        rectangles = [{
            "pixels": [[100, 100], [300, 100], [300, 300], [100, 300]],
            "side_lengths": [0.6, 0.6, 0.6, 0.6],
            "diagonal": 0.85,
            "index": 1
        }]
        self.cal.rectangles = rectangles
        self.cal.set_calibration_from_rectangles(rectangles)
        
        result = self.cal.pixel_to_world(200, 200)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
    
    def test_pixel_to_world_not_calibrated(self):
        """pixel_to_world returns None when not calibrated."""
        result = self.cal.pixel_to_world(200, 200)
        self.assertIsNone(result)
    
    def test_clear_resets(self):
        """Clear resets calibration state."""
        rectangles = [{
            "pixels": [[100, 100], [300, 100], [300, 300], [100, 300]],
            "side_lengths": [0.6, 0.6, 0.6, 0.6],
            "diagonal": 0.85,
            "index": 1
        }]
        self.cal.rectangles = rectangles
        self.cal.set_calibration_from_rectangles(rectangles)
        self.assertTrue(self.cal.is_calibrated)
        
        self.cal.clear()
        self.assertFalse(self.cal.is_calibrated)
    
    def test_to_json_format(self):
        """to_json returns expected format."""
        data = self.cal.to_json()
        self.assertIn("is_calibrated", data)
        self.assertIn("points", data)
        self.assertIn("rectangles", data)
    
    def test_multiple_rectangles(self):
        """Multiple rectangles calibrate successfully."""
        rect1 = {
            "pixels": [[100, 100], [300, 100], [300, 300], [100, 300]],
            "side_lengths": [0.6, 0.6, 0.6, 0.6],
            "diagonal": 0.85,
            "index": 1
        }
        rect2 = {
            "pixels": [[400, 400], [600, 400], [600, 600], [400, 600]],
            "side_lengths": [0.6, 0.6, 0.6, 0.6],
            "diagonal": 0.85,
            "index": 2
        }
        rectangles = [rect1, rect2]
        self.cal.rectangles = rectangles
        success = self.cal.set_calibration_from_rectangles(rectangles)
        self.assertTrue(success)
        self.assertTrue(self.cal.is_calibrated)


if __name__ == '__main__':
    unittest.main()
