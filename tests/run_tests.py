#!/usr/bin/env python3
"""
Cat Dome — Manual Test Runner

Usage:
    python tests/run_tests.py              # Run all tests
    python tests/run_tests.py perimeter    # Run only perimeter tests
    python tests/run_tests.py calibration  # Run only calibration tests
    python tests/run_tests.py memory       # Run only memory tests
    python tests/run_tests.py inject_cat   # Run only inject cat tests
    python tests/run_tests.py tracker      # Run only tracker tests

Run from the project root directory:
    cd cat_ball_tracker
    python tests/run_tests.py
"""

import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_tests(module_name=None):
    """Run unit tests, optionally filtered by module name."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    if module_name:
        # Run specific module
        test_module = f"tests.test_{module_name}"
        try:
            suite.addTests(loader.loadTestsFromName(test_module))
            print(f"Running tests from: {test_module}")
        except (ModuleNotFoundError, AttributeError) as e:
            print(f"Error loading {test_module}: {e}")
            print(f"\nAvailable test modules:")
            _list_test_modules()
            return False
    else:
        # Run all tests
        test_dir = os.path.dirname(os.path.abspath(__file__))
        suite.addTests(loader.discover(test_dir, pattern="test_*.py"))
        print("Running all tests...")
    
    print("=" * 60)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(f"✅ All {result.testsRun} tests passed!")
    else:
        failed = len(result.failures) + len(result.errors)
        print(f"❌ {failed} of {result.testsRun} tests failed")
    
    return result.wasSuccessful()


def _list_test_modules():
    """List available test modules."""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    for f in sorted(os.listdir(test_dir)):
        if f.startswith("test_") and f.endswith(".py"):
            name = f[5:-3]  # Remove "test_" prefix and ".py" suffix
            print(f"  - {name}")


if __name__ == '__main__':
    module = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_tests(module)
    sys.exit(0 if success else 1)
