"""Unit tests for InjectCat (processing/inject_cat.py)."""

import sys
import os
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockPerimeter:
    """Mock PerimeterManager for testing."""
    def __init__(self, points=None):
        self._points = points or []
        self.saved_resolution = (2304, 1296)
    
    def get_points(self):
        return self._points
    
    def is_inside(self, point, frame_res):
        return True


class TestInjectCat(unittest.TestCase):
    """Test inject cat movement and positioning."""
    
    def _make_inject(self, perimeter_points=None):
        """Create an InjectCat instance with mock dependencies."""
        from processing.inject_cat import InjectCat
        
        if perimeter_points is None:
            perimeter_points = [[500, 400], [1800, 400], [1800, 1000], [500, 1000]]
        
        mock_perim = MockPerimeter(perimeter_points)
        
        def mock_pixel_to_world(px, py, **kwargs):
            return (px / 1000.0, py / 1000.0)
        
        inject = InjectCat(mock_perim, None, mock_pixel_to_world)
        return inject
    
    def test_enable_disable(self):
        """Enable and disable work without error."""
        inject = self._make_inject()
        inject.enable()
        self.assertTrue(inject.active)
        inject.disable()
        self.assertFalse(inject.active)
    
    def test_paste_on_frame_no_crash(self):
        """Pasting on a frame doesn't crash (even without cat image)."""
        inject = self._make_inject()
        inject.enable()
        frame = np.zeros((1296, 2304, 3), dtype=np.uint8)
        result = inject.paste_on_frame(frame)
        self.assertIsNotNone(result)
    
    def test_vertex_cycling(self):
        """Vertex index advances on each position init."""
        inject = self._make_inject()
        inject.enable()
        
        # Call init multiple times
        indices = []
        for _ in range(6):
            inject._initialized = False
            inject._init_position(2304, 1296)
            indices.append(inject._vertex_idx)
        
        # Should cycle through 0,1,2,3,0,1 (4-vertex polygon)
        self.assertEqual(indices, [1, 2, 3, 0, 1, 2])
    
    def test_get_crop_region(self):
        """Crop region is computed correctly when bbox exists."""
        inject = self._make_inject()
        inject.bbox = (100, 200, 250, 300)
        region = inject.get_crop_region(2304, 1296)
        self.assertIsNotNone(region)
        cx, cy, cw, ch = region
        self.assertEqual(cw, 380)
        self.assertEqual(ch, 380)
    
    def test_get_crop_region_none_without_bbox(self):
        """Crop region is None when no bbox."""
        inject = self._make_inject()
        inject.bbox = None
        region = inject.get_crop_region(2304, 1296)
        self.assertIsNone(region)
    
    def test_disable_frees_resources(self):
        """Disable frees cat image and cached data."""
        inject = self._make_inject()
        inject.enable()
        inject.disable()
        self.assertIsNone(inject._img)
        self.assertIsNone(inject._cached)


if __name__ == '__main__':
    unittest.main()
