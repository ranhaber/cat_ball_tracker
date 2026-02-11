#!/usr/bin/env python3
"""
Installation Verification Script
Run this to check if all dependencies are properly installed
"""

import sys

def check_package(name, import_name=None):
    """Check if a package is installed and importable"""
    import_name = import_name or name
    try:
        module = __import__(import_name)
        version = getattr(module, '__version__', 'unknown')
        print(f"  ✅ {name}: {version}")
        return True
    except ImportError as e:
        print(f"  ❌ {name}: NOT INSTALLED - {e}")
        return False

def main():
    print("=" * 60)
    print("🔍 Cat Dome - Installation Verification")
    print("=" * 60)
    print()
    
    # Python version
    print(f"🐍 Python Version: {sys.version}")
    print()
    
    # Check required packages
    print("📦 Checking Required Packages:")
    print("-" * 40)
    
    all_ok = True
    
    # Core packages
    all_ok &= check_package("numpy")
    all_ok &= check_package("opencv-python-headless", "cv2")
    all_ok &= check_package("Flask", "flask")
    all_ok &= check_package("Pillow", "PIL")
    all_ok &= check_package("scipy")
    
    print()
    print("📦 Checking Optional Packages:")
    print("-" * 40)
    
    # TFLite - optional for mock mode
    tflite_ok = check_package("tflite-runtime", "tflite_runtime")
    if not tflite_ok:
        print("     ⚠️  TFLite not installed - will use MOCK detections")
    
    # Picamera2 - optional, only on RPi
    picamera_ok = check_package("picamera2")
    if not picamera_ok:
        print("     ⚠️  picamera2 not available - will use MOCK camera")
    
    # simplejpeg - optional, faster JPEG encoding via libjpeg-turbo
    simplejpeg_ok = check_package("simplejpeg")
    if not simplejpeg_ok:
        print("     ⚠️  simplejpeg not installed - JPEG will use cv2 (slower)")
    
    # flask-sock - optional, WebSocket for H.264 hardware streaming
    flasksock_ok = check_package("flask-sock", "flask_sock")
    if not flasksock_ok:
        print("     ⚠️  flask-sock not installed - H.264 streaming disabled (MJPEG fallback)")
    
    print()
    print("=" * 60)
    
    if all_ok:
        print("✅ All required packages installed!")
        print()
        print("🎯 System will run in the following mode:")
        if picamera_ok:
            print("   📷 Camera: Real (picamera2)")
        else:
            print("   📷 Camera: MOCK (test pattern)")
        if tflite_ok:
            print("   🧠 Detection: Real (TensorFlow Lite)")
        else:
            print("   🧠 Detection: MOCK (random detections)")
        print()
        print("🚀 Run 'python main.py' to start the server!")
    else:
        print("❌ Some required packages are missing!")
        print("   Run: pip install -r requirements.txt")
    
    print("=" * 60)
    
    return 0 if all_ok else 1

if __name__ == '__main__':
    sys.exit(main())
