#!/bin/bash
# Cat Dome - Installation Script
# For Raspberry Pi Zero 2W with Camera Module 3
# Tested on Raspberry Pi OS Bookworm (64-bit)

set -e

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                                                               ║"
echo "║              🐱 Cat Dome - Installation Script 🏀             ║"
echo "║                                                               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Update package lists
echo "📦 Updating package lists..."
sudo apt update

# Install system dependencies
echo ""
echo "📦 Installing system dependencies..."
sudo apt install -y \
    python3-full \
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

# Try to install TFLite (may not work on all Python versions)
echo ""
echo "📦 Installing TFLite runtime..."
pip install tflite-runtime --extra-index-url https://www.piwheels.org/simple || {
    echo "⚠️ TFLite installation failed - will run in mock mode"
}

# Install gunicorn for production
pip install gunicorn

# Download model if not exists
echo ""
echo "📥 Checking for detection model..."
if [ ! -f "models/ssd_mobilenet_v1_coco.tflite" ]; then
    mkdir -p models
    echo "Downloading model..."
    wget -q -O models/ssd_mobilenet_v1_coco.tflite \
        "https://storage.googleapis.com/download.tensorflow.org/models/tflite/coco_ssd_mobilenet_v1_1.0_quant_2018_06_29.zip" || {
        echo "⚠️ Model download failed - will download on first run"
    }
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "=========================================="
echo "To run Cat Dome manually:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "To install as a service (auto-start on boot):"
echo "  chmod +x start_Cat_Dome.sh"
echo "  sudo cp cat_dome.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable cat_dome"
echo "  sudo systemctl start cat_dome"
echo ""
echo "Web interface: http://$(hostname -I | awk '{print $1}'):5000"
echo "=========================================="
