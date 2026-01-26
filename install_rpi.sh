#!/bin/bash
# Installation script for Raspberry Pi Zero 2W
# Tested on Raspberry Pi OS Bookworm (Debian 12)

set -e

echo "=========================================="
echo "🐱 Cat/Ball Tracker - RPi Installation"
echo "=========================================="

# Update package lists first
echo ""
echo "📦 Updating package lists..."
sudo apt update

# Install system dependencies
# Note: libatlas-base-dev is replaced by libopenblas-dev on Bookworm
echo ""
echo "📦 Installing system dependencies..."
sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-numpy \
    python3-opencv \
    python3-flask \
    python3-scipy \
    python3-pillow \
    libopenblas-dev \
    libcamera-dev \
    libcap-dev \
    python3-libcamera \
    python3-picamera2

# Alternative: if libopenblas-dev fails, try:
# sudo apt install -y libatlas3-base

echo ""
echo "✅ System packages installed!"

# Create virtual environment with system packages
echo ""
echo "🐍 Setting up Python virtual environment..."
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Install remaining Python packages
echo ""
echo "📦 Installing Python packages..."
pip install --upgrade pip
pip install tflite-runtime gunicorn

echo ""
echo "=========================================="
echo "✅ Installation complete!"
echo ""
echo "To run the tracker:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "Then open: http://$(hostname -I | awk '{print $1}'):5000"
echo "=========================================="
