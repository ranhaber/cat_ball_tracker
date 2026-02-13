"""Unit tests for performance profiles.

Tests profile configuration, switching, and that settings are applied correctly.
Does NOT start camera or TFLite — tests the configuration logic only.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import tests.conftest  # noqa: F401
from tests.conftest import get_video_processor


class TestPerformanceProfiles(unittest.TestCase):
    """Test performance profile configuration and switching."""
    
    def _make_processor(self):
        """Create a VideoProcessor for profile testing (no camera/TFLite)."""
        return get_video_processor()
    
    # ── Config-level tests ──
    
    def test_profiles_exist_in_config(self):
        """Performance profiles dict exists and is non-empty."""
        self.assertIsInstance(config.PERFORMANCE_PROFILES, dict)
        self.assertGreater(len(config.PERFORMANCE_PROFILES), 0)
    
    def test_required_profiles_present(self):
        """Required profile names exist."""
        for name in ["balanced", "performance", "quality"]:
            self.assertIn(name, config.PERFORMANCE_PROFILES,
                         f"Profile '{name}' missing from config")
    
    def test_profile_has_required_keys(self):
        """Each profile has all required settings keys."""
        required_keys = [
            "name", "description", "jpeg_quality", "motion_crop_size",
            "motion_scale", "motion_threshold", "motion_min_area",
            "tflite_threads", "detection_range"
        ]
        for profile_name, profile in config.PERFORMANCE_PROFILES.items():
            for key in required_keys:
                self.assertIn(key, profile,
                             f"Profile '{profile_name}' missing key '{key}'")
    
    def test_jpeg_quality_range(self):
        """JPEG quality is between 1 and 100 for all profiles."""
        for name, profile in config.PERFORMANCE_PROFILES.items():
            q = profile["jpeg_quality"]
            self.assertGreaterEqual(q, 1, f"Profile '{name}' JPEG quality too low: {q}")
            self.assertLessEqual(q, 100, f"Profile '{name}' JPEG quality too high: {q}")
    
    def test_tflite_threads_range(self):
        """TFLite threads is between 1 and 4 for all profiles."""
        for name, profile in config.PERFORMANCE_PROFILES.items():
            t = profile["tflite_threads"]
            self.assertGreaterEqual(t, 1, f"Profile '{name}' threads too low: {t}")
            self.assertLessEqual(t, 4, f"Profile '{name}' threads too high: {t}")
    
    def test_motion_scale_range(self):
        """Motion scale is between 0.1 and 1.0 for all profiles."""
        for name, profile in config.PERFORMANCE_PROFILES.items():
            s = profile["motion_scale"]
            self.assertGreaterEqual(s, 0.1, f"Profile '{name}' scale too low: {s}")
            self.assertLessEqual(s, 1.0, f"Profile '{name}' scale too high: {s}")
    
    def test_default_profile_exists(self):
        """Default profile name is valid."""
        self.assertIn(config.DEFAULT_PERFORMANCE_PROFILE, config.PERFORMANCE_PROFILES)
    
    # ── VideoProcessor-level tests ──
    
    def test_initial_profile_loaded(self):
        """VideoProcessor loads a profile on init."""
        vp = self._make_processor()
        self.assertIsNotNone(vp.current_profile)
        self.assertIn(vp.current_profile, config.PERFORMANCE_PROFILES)
    
    def test_get_performance_profiles(self):
        """get_performance_profiles returns profiles, current, and default."""
        vp = self._make_processor()
        result = vp.get_performance_profiles()
        self.assertIn("profiles", result)
        self.assertIn("current", result)
        self.assertIn("default", result)
        self.assertEqual(result["profiles"], config.PERFORMANCE_PROFILES)
        self.assertEqual(result["default"], config.DEFAULT_PERFORMANCE_PROFILE)
    
    def test_get_current_profile(self):
        """get_current_profile returns profile name and settings."""
        vp = self._make_processor()
        result = vp.get_current_profile()
        self.assertIn("profile", result)
        self.assertIn("settings", result)
        self.assertIsInstance(result["settings"], dict)
    
    def test_get_performance_settings(self):
        """get_performance_settings returns current and options."""
        vp = self._make_processor()
        result = vp.get_performance_settings()
        self.assertIn("current", result)
        self.assertIn("options", result)
        self.assertIn("resolution", result["current"])
        self.assertIn("stream_resolution", result["current"])
        self.assertIn("framerate", result["current"])
        self.assertIn("frame_skip", result["current"])
    
    def test_set_invalid_profile_fails(self):
        """Setting a non-existent profile returns False."""
        vp = self._make_processor()
        result = vp.set_performance_profile("nonexistent_profile")
        self.assertFalse(result)
    
    def test_set_valid_profile_succeeds(self):
        """Setting a valid profile returns True and updates current."""
        vp = self._make_processor()
        for profile_name in config.PERFORMANCE_PROFILES:
            result = vp.set_performance_profile(profile_name)
            self.assertTrue(result, f"Failed to set profile '{profile_name}'")
            self.assertEqual(vp.current_profile, profile_name)
    
    def test_profile_applies_jpeg_quality(self):
        """Switching profile updates JPEG quality."""
        vp = self._make_processor()
        for name, profile in config.PERFORMANCE_PROFILES.items():
            vp.set_performance_profile(name)
            self.assertEqual(vp.current_jpeg_quality, profile["jpeg_quality"],
                           f"Profile '{name}' didn't set JPEG quality")
    
    def test_set_frame_skip_valid(self):
        """Valid frame skip values are accepted."""
        vp = self._make_processor()
        for skip in config.FRAME_SKIP_OPTIONS:
            result = vp.set_frame_skip(skip)
            self.assertTrue(result, f"Frame skip {skip} rejected")
            self.assertEqual(vp.current_frame_skip, skip)
    
    def test_set_frame_skip_invalid(self):
        """Invalid frame skip values are rejected."""
        vp = self._make_processor()
        result = vp.set_frame_skip(999)
        self.assertFalse(result)
    
    def test_set_stream_resolution_valid(self):
        """Valid stream resolutions are accepted."""
        vp = self._make_processor()
        for res in config.STREAM_RESOLUTION_OPTIONS:
            result = vp.set_stream_resolution(res[0], res[1])
            self.assertTrue(result, f"Stream res {res} rejected")
            self.assertEqual(vp.current_stream_resolution, res)
    
    def test_set_stream_resolution_invalid(self):
        """Invalid stream resolutions are rejected."""
        vp = self._make_processor()
        result = vp.set_stream_resolution(9999, 9999)
        self.assertFalse(result)
    
    def test_capture_resolution_fixed(self):
        """Capture resolution cannot be changed (fixed at 2304x1296)."""
        vp = self._make_processor()
        result = vp.set_resolution(640, 480)
        self.assertFalse(result)
        self.assertEqual(vp.current_resolution, config.DEFAULT_RESOLUTION)


if __name__ == '__main__':
    unittest.main()
