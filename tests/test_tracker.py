"""Unit tests for CentroidTracker (detection/tracker.py)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection.tracker import CentroidTracker


class TestTracker(unittest.TestCase):
    """Test centroid-based object tracking."""
    
    def setUp(self):
        self.tracker = CentroidTracker()
    
    def test_new_object_gets_id(self):
        """A new detection gets assigned a tracking ID."""
        detections = [(100, 100, 200, 200, 0.9, 17)]
        tracked = self.tracker.update(detections)
        self.assertGreater(len(tracked), 0)
    
    def test_same_object_keeps_id(self):
        """Same object in similar position keeps the same ID."""
        det1 = [(100, 100, 200, 200, 0.9, 17)]
        tracked1 = self.tracker.update(det1)
        ids1 = list(tracked1.keys())
        
        # Slightly moved
        det2 = [(105, 105, 205, 205, 0.9, 17)]
        tracked2 = self.tracker.update(det2)
        ids2 = list(tracked2.keys())
        
        self.assertEqual(ids1[0], ids2[0])
    
    def test_no_detections_clears(self):
        """No detections eventually clears tracked objects."""
        det = [(100, 100, 200, 200, 0.9, 17)]
        self.tracker.update(det)
        
        # Several frames with no detections
        for _ in range(50):
            self.tracker.update([])
        
        self.assertEqual(self.tracker.get_object_count(), 0)
    
    def test_reset_clears_all(self):
        """Reset clears all tracked objects."""
        det = [(100, 100, 200, 200, 0.9, 17)]
        self.tracker.update(det)
        self.tracker.reset()
        self.assertEqual(self.tracker.get_object_count(), 0)


if __name__ == '__main__':
    unittest.main()
