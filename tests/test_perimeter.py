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
        # Square perimeter: (100,100) to (500,500)
        self.square_points = [[100, 100], [500, 100], [500, 500], [100, 500]]
    
    def test_set_and_get_points(self):
        """Points can be set and retrieved."""
        self.pm.set_points(self.square_points)
        points = self.pm.get_points()
        self.assertEqual(len(points), 4)
    
    def test_point_inside(self):
        """Center point is inside the perimeter."""
        self.pm.set_points(self.square_points)
        result = self.pm.is_inside((300, 300), (640, 480))
        self.assertTrue(result)
    
    def test_point_outside(self):
        """Point far outside is outside the perimeter."""
        self.pm.set_points(self.square_points)
        result = self.pm.is_inside((10, 10), (640, 480))
        self.assertFalse(result)
    
    def test_no_perimeter_always_inside(self):
        """With no perimeter set, all points are inside."""
        result = self.pm.is_inside((300, 300), (640, 480))
        self.assertTrue(result)
    
    def test_filter_detections_keeps_inside(self):
        """Detections inside perimeter are kept."""
        self.pm.set_points(self.square_points)
        detections = [(200, 200, 400, 400, 0.9, 17)]  # Center of perimeter
        filtered = self.pm.filter_detections(detections, frame_resolution=(640, 480))
        self.assertEqual(len(filtered), 1)
    
    def test_filter_detections_removes_outside(self):
        """Detections outside perimeter are removed."""
        self.pm.set_points(self.square_points)
        detections = [(0, 0, 50, 50, 0.9, 17)]  # Far outside
        filtered = self.pm.filter_detections(detections, frame_resolution=(640, 480))
        self.assertEqual(len(filtered), 0)
    
    def test_clear_resets(self):
        """Clear removes all points."""
        self.pm.set_points(self.square_points)
        self.pm.clear()
        points = self.pm.get_points()
        self.assertEqual(len(points), 0)


if __name__ == '__main__':
    unittest.main()
