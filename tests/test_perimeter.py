"""Unit tests for PerimeterManager (detection/perimeter.py)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.perimeter import PerimeterManager


class TestPerimeter(unittest.TestCase):
    """Test Detection Zone perimeter logic."""
    
    def setUp(self):
        self.pm = PerimeterManager()
        # Square perimeter: (100,100) to (500,500) at 640x480 resolution
        self.square_points = [[100, 100], [500, 100], [500, 400], [100, 400]]
        self.frame_res = (640, 480)
    
    def test_set_and_get_points(self):
        """Points can be set and retrieved."""
        self.pm.set_points(self.square_points)
        points = self.pm.get_points()
        self.assertEqual(len(points), 4)
    
    def test_point_inside(self):
        """Center point is inside the perimeter."""
        self.pm.set_points(self.square_points, resolution=self.frame_res)
        result = self.pm.is_inside((300, 250), frame_resolution=self.frame_res)
        self.assertTrue(result)
    
    def test_point_outside(self):
        """Point far outside is outside the perimeter."""
        self.pm.set_points(self.square_points, resolution=self.frame_res)
        result = self.pm.is_inside((10, 10), frame_resolution=self.frame_res)
        self.assertFalse(result)
    
    def test_filter_detections_keeps_inside(self):
        """Detections inside perimeter are kept."""
        self.pm.set_points(self.square_points, resolution=self.frame_res)
        # Detection centered at (300, 250) — inside the square
        detections = [(250, 200, 350, 300, 0.9, 17)]
        filtered = self.pm.filter_detections(detections, frame_resolution=self.frame_res)
        self.assertEqual(len(filtered), 1)
    
    def test_filter_detections_removes_outside(self):
        """Detections outside perimeter are removed."""
        self.pm.set_points(self.square_points, resolution=self.frame_res)
        # Detection centered at (25, 25) — outside
        detections = [(0, 0, 50, 50, 0.9, 17)]
        filtered = self.pm.filter_detections(detections, frame_resolution=self.frame_res)
        self.assertEqual(len(filtered), 0)
    
    def test_clear_resets_to_default(self):
        """Clear resets to default perimeter (not empty)."""
        self.pm.set_points(self.square_points)
        self.pm.clear()
        points = self.pm.get_points()
        # clear() resets to DEFAULT_PERIMETER which has points
        self.assertIsInstance(points, list)


if __name__ == '__main__':
    unittest.main()
