"""Unit tests for memory management utilities (processing/memory.py)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processing.memory import get_system_info, get_ram_stats, reclaim_memory


class TestMemory(unittest.TestCase):
    """Test memory management utilities."""
    
    def test_get_system_info_returns_dict(self):
        """get_system_info returns a dict with expected keys."""
        info = get_system_info()
        self.assertIsInstance(info, dict)
        self.assertIn("ram_used_mb", info)
        self.assertIn("ram_total_mb", info)
        self.assertIn("ram_percent", info)
        self.assertIn("cpu_percent", info)
        self.assertIn("cpu_temp", info)
    
    def test_get_ram_stats_returns_string(self):
        """get_ram_stats returns a non-empty string."""
        stats = get_ram_stats()
        self.assertIsInstance(stats, str)
        # On Windows this returns 'N/A', on Linux it returns actual stats
        self.assertTrue(len(stats) > 0)
    
    def test_reclaim_memory_does_not_crash(self):
        """reclaim_memory runs without error on any platform."""
        # Should not raise any exception
        reclaim_memory()
    
    def test_reclaim_memory_after_large_alloc(self):
        """reclaim_memory works after freeing a large allocation."""
        import numpy as np
        # Allocate and free a large array
        big_array = np.zeros((1000, 1000, 3), dtype=np.uint8)
        del big_array
        # Should not raise
        reclaim_memory()


if __name__ == '__main__':
    unittest.main()
