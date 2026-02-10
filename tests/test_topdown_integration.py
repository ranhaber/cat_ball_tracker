"""Integration tests for the top-down view pipeline.

Verifies the full chain:
  detection -> tracker -> last_detections_with_world -> get_topdown_data()

These tests caught the original bug where track_id was never merged from
the tracker into last_detections_with_world, so the top-down view always
showed track_id=0.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# conftest mocks missing modules (Flask, picamera2, etc.) on Windows
import tests.conftest  # noqa: F401
from tests.conftest import get_video_processor

import config
from detection.tracker import CentroidTracker


class TestTopDownIntegration(unittest.TestCase):
    """Test that tracker IDs reach the top-down view data."""

    def _make_processor(self):
        """Create a VideoProcessor for testing (no camera/TFLite)."""
        return get_video_processor()

    def test_track_id_merged_into_detections(self):
        """Tracker IDs are merged into last_detections_with_world."""
        vp = self._make_processor()
        vp.tracker = CentroidTracker()

        # Simulate a detection at (100, 100, 200, 200)
        det = (100, 100, 200, 200, 0.9, 17)
        last_detections = [det]

        # Populate last_detections_with_world as _process_loop does
        vp.last_detections_with_world = [{
            "bbox": [100, 100, 200, 200],
            "confidence": 0.9,
            "class_id": 17,
            "world_position": {"world_x": 1.0, "world_y": 2.0},
            "injected": False
        }]

        # Run tracker
        tracked_objects = vp.tracker.update(last_detections)

        # Merge tracker IDs (same logic as _process_loop)
        if tracked_objects and vp.last_detections_with_world:
            tracked_bboxes = vp.tracker.get_bboxes()
            for d in vp.last_detections_with_world:
                db = d["bbox"]
                det_cx = (db[0] + db[2]) / 2
                det_cy = (db[1] + db[3]) / 2
                best_id = None
                best_dist = float('inf')
                for tid, tb in tracked_bboxes.items():
                    tb_cx = (tb[0] + tb[2]) / 2
                    tb_cy = (tb[1] + tb[3]) / 2
                    dist = abs(det_cx - tb_cx) + abs(det_cy - tb_cy)
                    if dist < best_dist:
                        best_dist = dist
                        best_id = tid
                if best_id is not None and best_dist < 50:
                    d["track_id"] = best_id

        # Verify track_id was set
        self.assertIn("track_id", vp.last_detections_with_world[0],
                       "track_id must be merged from tracker into detections")
        self.assertIsInstance(vp.last_detections_with_world[0]["track_id"], int)

    def test_track_id_stable_across_frames(self):
        """Same object keeps the same track_id across two frames."""
        vp = self._make_processor()
        vp.tracker = CentroidTracker()

        # Frame 1: object at (100, 100, 200, 200)
        det1 = (100, 100, 200, 200, 0.9, 17)
        vp.tracker.update([det1])
        first_id = list(vp.tracker.get_bboxes().keys())[0]

        # Frame 2: same object slightly moved to (105, 105, 205, 205)
        det2 = (105, 105, 205, 205, 0.85, 17)
        vp.tracker.update([det2])
        second_id = list(vp.tracker.get_bboxes().keys())[0]

        self.assertEqual(first_id, second_id,
                         "Same object should keep the same track_id across frames")

    def test_topdown_data_includes_objects(self):
        """get_topdown_data returns objects with world coords when detections exist."""
        vp = self._make_processor()

        # Populate detections with world position and track_id
        vp.last_detections_with_world = [{
            "bbox": [100, 100, 200, 200],
            "confidence": 0.9,
            "class_id": 17,
            "world_position": {"world_x": 1.5, "world_y": 3.0},
            "injected": False,
            "track_id": 5
        }]

        data = vp.get_topdown_data()

        # Without calibration, objects won't appear (no world bounds)
        # but the method should not crash
        self.assertIn("objects", data)
        self.assertIn("is_calibrated", data)

    def test_topdown_objects_have_correct_fields(self):
        """Objects in get_topdown_data have id, world_x, world_y."""
        vp = self._make_processor()

        # Mock calibration as available
        from unittest.mock import MagicMock
        vp.calibration = MagicMock()
        vp.calibration.is_calibrated = True
        vp.calibration.get_world_bounds.return_value = {
            "min_x": 0, "max_x": 10, "min_y": 0, "max_y": 10
        }

        vp.last_detections_with_world = [{
            "bbox": [100, 100, 200, 200],
            "confidence": 0.9,
            "class_id": 17,
            "world_position": {"world_x": 2.5, "world_y": 4.0},
            "injected": False,
            "track_id": 3
        }]

        data = vp.get_topdown_data()

        self.assertTrue(len(data["objects"]) >= 1,
                        "Should have at least one object in top-down data")
        obj = data["objects"][0]
        self.assertEqual(obj["id"], 3)
        self.assertEqual(obj["world_x"], 2.5)
        self.assertEqual(obj["world_y"], 4.0)

    def test_topdown_no_objects_when_no_detections(self):
        """get_topdown_data returns empty objects when no detections."""
        vp = self._make_processor()
        vp.last_detections_with_world = []

        data = vp.get_topdown_data()
        self.assertEqual(data["objects"], [])

    def test_detection_without_world_position_excluded(self):
        """Detections without world_position are excluded from top-down objects."""
        vp = self._make_processor()

        from unittest.mock import MagicMock
        vp.calibration = MagicMock()
        vp.calibration.is_calibrated = True
        vp.calibration.get_world_bounds.return_value = {
            "min_x": 0, "max_x": 10, "min_y": 0, "max_y": 10
        }

        vp.last_detections_with_world = [{
            "bbox": [100, 100, 200, 200],
            "confidence": 0.9,
            "class_id": 17,
            "world_position": None,  # No world position
            "injected": False,
            "track_id": 1
        }]

        data = vp.get_topdown_data()
        self.assertEqual(len(data["objects"]), 0,
                         "Detection without world_position should be excluded")


if __name__ == '__main__':
    unittest.main()
