#!/bin/bash

# ============================================================================
# Cat Dome - Raspberry Pi Setup Script
# For Raspberry Pi OS Bookworm (64-bit recommended)
# Version: 1.2.0
# ============================================================================

set -e  # Exit on any error

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                                                               ║"
echo "║              🐱 Cat Dome Setup Script 🏀                      ║"
echo "║                       v1.2.0                                  ║"
echo "║                                                               ║"
echo "║     For Raspberry Pi OS Bookworm (64-bit)                     ║"
echo "║     Raspberry Pi Zero 2W + Camera Module 3                    ║"
echo "║                                                               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# ============================================================================
# Step 1: System Update
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Updating system packages..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sudo apt update
sudo apt upgrade -y
print_status "System updated"

# ============================================================================
# Step 2: Install System Dependencies
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Installing system dependencies..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

sudo apt install -y \
    python3-full \
    python3-pip \
    python3-venv \
    python3-opencv \
    python3-picamera2 \
    python3-flask \
    python3-numpy \
    python3-pil \
    libatlas-base-dev \
    libopenblas-dev \
    git \
    wget \
    unzip

print_status "System dependencies installed"

# ============================================================================
# Step 3: Enable Camera Interface
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Checking camera configuration..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check if camera is enabled in config.txt
if grep -q "^camera_auto_detect=1" /boot/firmware/config.txt 2>/dev/null || \
   grep -q "^camera_auto_detect=1" /boot/config.txt 2>/dev/null; then
    print_status "Camera auto-detect already enabled"
else
    print_warning "Enabling camera auto-detect..."
    # Try both possible locations for config.txt
    if [ -f /boot/firmware/config.txt ]; then
        echo "camera_auto_detect=1" | sudo tee -a /boot/firmware/config.txt
    elif [ -f /boot/config.txt ]; then
        echo "camera_auto_detect=1" | sudo tee -a /boot/config.txt
    fi
    print_status "Camera enabled (reboot required later)"
fi

# ============================================================================
# Step 4: Create Project Directory
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 4: Setting up project directory..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PROJECT_DIR="$HOME/cat_ball_tracker"

if [ -d "$PROJECT_DIR" ]; then
    print_status "Project directory already exists: $PROJECT_DIR"
else
    mkdir -p "$PROJECT_DIR"
    print_status "Created project directory: $PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# ============================================================================
# Step 5: Create Virtual Environment
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 5: Creating Python virtual environment..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Remove old venv if exists
if [ -d "venv" ]; then
    print_warning "Removing old virtual environment..."
    rm -rf venv
fi

# Create new venv with system site packages (for opencv, picamera2, etc.)
python3 -m venv venv --system-site-packages
source venv/bin/activate

print_status "Virtual environment created"

# Upgrade pip
pip install --upgrade pip
print_status "Pip upgraded"

# ============================================================================
# Step 6: Install TFLite Runtime
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 6: Installing TensorFlow Lite Runtime..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Detect architecture
ARCH=$(uname -m)
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

echo "Architecture: $ARCH"
echo "Python version: $PYTHON_VERSION"

# Try to install tflite-runtime
TFLITE_INSTALLED=false

# Try piwheels first
if pip install tflite-runtime --extra-index-url https://www.piwheels.org/simple 2>/dev/null; then
    print_status "TFLite runtime installed from piwheels"
    TFLITE_INSTALLED=true
fi

# If that failed, try specific wheels based on architecture
if [ "$TFLITE_INSTALLED" = false ]; then
    if [ "$ARCH" = "aarch64" ]; then
        # 64-bit ARM
        echo "Trying 64-bit wheel..."
        if pip install https://github.com/google-coral/pycoral/releases/download/v2.0.0/tflite_runtime-2.5.0.post1-cp311-cp311-linux_aarch64.whl 2>/dev/null; then
            print_status "TFLite runtime installed (64-bit)"
            TFLITE_INSTALLED=true
        elif pip install https://github.com/google-coral/pycoral/releases/download/v2.0.0/tflite_runtime-2.5.0.post1-cp39-cp39-linux_aarch64.whl 2>/dev/null; then
            print_status "TFLite runtime installed (64-bit, Python 3.9)"
            TFLITE_INSTALLED=true
        fi
    else
        # 32-bit ARM (armv7l)
        echo "Trying 32-bit wheel..."
        if pip install https://github.com/google-coral/pycoral/releases/download/v2.0.0/tflite_runtime-2.5.0.post1-cp311-cp311-linux_armv7l.whl 2>/dev/null; then
            print_status "TFLite runtime installed (32-bit)"
            TFLITE_INSTALLED=true
        elif pip install https://github.com/google-coral/pycoral/releases/download/v2.0.0/tflite_runtime-2.5.0.post1-cp39-cp39-linux_armv7l.whl 2>/dev/null; then
            print_status "TFLite runtime installed (32-bit, Python 3.9)"
            TFLITE_INSTALLED=true
        fi
    fi
fi

if [ "$TFLITE_INSTALLED" = false ]; then
    print_warning "TFLite runtime could not be installed"
    print_warning "The app will run in mock detection mode"
    print_warning "You can try installing it manually later"
else
    print_status "TFLite runtime is ready!"
fi

# ============================================================================
# Step 7: Install Additional Python Packages
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 7: Installing additional Python packages..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

pip install gunicorn
print_status "Gunicorn installed"

# ============================================================================
# Step 8: Download TFLite Model
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 8: Downloading TFLite detection model..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

MODELS_DIR="$PROJECT_DIR/models"
mkdir -p "$MODELS_DIR"

if [ -f "$MODELS_DIR/detect.tflite" ]; then
    print_status "Model already exists"
else
    echo "Downloading COCO SSD MobileNet model..."
    cd "$MODELS_DIR"
    
    wget -q "https://storage.googleapis.com/download.tensorflow.org/models/tflite/coco_ssd_mobilenet_v1_1.0_quant_2018_06_29.zip" -O model.zip
    unzip -o model.zip
    rm model.zip
    
    print_status "Model downloaded: $MODELS_DIR/detect.tflite"
    cd "$PROJECT_DIR"
fi

# ============================================================================
# Step 9: Test Camera
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 9: Testing camera..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if libcamera-hello --list-cameras 2>/dev/null | grep -q "Available cameras"; then
    print_status "Camera detected!"
    libcamera-hello --list-cameras
else
    print_warning "Camera not detected"
    print_warning "Make sure the camera ribbon cable is connected properly"
    print_warning "You may need to reboot after running this script"
fi

# ============================================================================
# Step 10: Create Systemd Service (Optional)
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 10: Creating systemd service for auto-start..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SERVICE_FILE="/etc/systemd/system/cat-dome.service"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Cat Dome - Detection & Tracking System
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$PROJECT_DIR/start_Cat_Dome.sh
Restart=on-failure
RestartSec=10

# Logging (goes to both journald AND dated log files via wrapper script)
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Make the startup script executable
chmod +x "$PROJECT_DIR/start_Cat_Dome.sh" 2>/dev/null || print_warning "start_Cat_Dome.sh not found yet"

sudo systemctl daemon-reload
print_status "Systemd service created: cat-dome.service"
echo ""
echo "  To enable auto-start on boot:"
echo "    sudo systemctl enable cat-dome"
echo ""
echo "  To start/stop/status:"
echo "    sudo systemctl start cat-dome"
echo "    sudo systemctl stop cat-dome"
echo "    sudo systemctl status cat-dome"

# ============================================================================
# Step 11: Install rpi-connect-lite (remote access, controlled from Developer tab)
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 11: Installing rpi-connect-lite (optional remote access)..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if dpkg -l rpi-connect-lite 2>/dev/null | grep -q '^ii'; then
    print_status "rpi-connect-lite already installed"
else
    sudo apt install -y rpi-connect-lite 2>/dev/null && \
        print_status "rpi-connect-lite installed" || \
        print_warning "rpi-connect-lite not available (may not be supported on this Pi)"
fi

# Disable by default to save ~13MB RAM. Enable from Developer tab when needed.
sudo systemctl disable rpi-connect 2>/dev/null || true
sudo systemctl stop rpi-connect 2>/dev/null || true
print_status "rpi-connect stopped and disabled (enable from Developer tab in web UI)"

# ============================================================================
# Step 12: Sudoers for Developer Tab (service control from web UI)
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 12: Setting up sudoers for web UI service control..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

SUDOERS_FILE="/etc/sudoers.d/catdome"
sudo tee "$SUDOERS_FILE" > /dev/null << EOF
# Allow Cat Dome web UI to control rpi-connect service
$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl start rpi-connect, /usr/bin/systemctl stop rpi-connect, /usr/bin/systemctl is-active rpi-connect, /usr/bin/systemctl start rpi-connect.service, /usr/bin/systemctl stop rpi-connect.service, /usr/bin/systemctl is-active rpi-connect.service
EOF
sudo chmod 440 "$SUDOERS_FILE"
print_status "Sudoers configured for Developer tab service control"

# ============================================================================
# Step 13: Optimize swappiness (reduce unnecessary swap on low-RAM system)
# ============================================================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 13: Optimizing swap settings..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

CURRENT_SWAPPINESS=$(cat /proc/sys/vm/swappiness)
if [ "$CURRENT_SWAPPINESS" -gt 10 ]; then
    sudo sysctl vm.swappiness=10
    if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
        echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf > /dev/null
    fi
    print_status "Swappiness reduced from $CURRENT_SWAPPINESS to 10 (only swap when necessary)"
else
    print_status "Swappiness already at $CURRENT_SWAPPINESS (OK)"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete! 🎉                         ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "Project directory: $PROJECT_DIR"
echo "Python version: $PYTHON_VERSION"
echo "Architecture: $ARCH"
echo ""

if [ "$TFLITE_INSTALLED" = true ]; then
    echo -e "${GREEN}✓ TFLite runtime: INSTALLED${NC}"
else
    echo -e "${YELLOW}! TFLite runtime: NOT INSTALLED (will use mock detection)${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next Steps:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. Copy your project files to: $PROJECT_DIR"
echo "   (if not already there)"
echo ""
echo "2. Activate the virtual environment:"
echo "   cd $PROJECT_DIR"
echo "   source venv/bin/activate"
echo ""
echo "3. Run the application:"
echo "   python main.py"
echo ""
echo "4. Open in browser:"
echo "   http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "5. Set up calibration (Zone tab):"
echo "   a. Lens Calibration: mark straight lines → Calibrate"
echo "   b. Perspective Calibration: add rectangles with known dimensions"
echo "   c. Detection Zone: draw perimeter on lens-corrected image"
echo ""
echo "6. (Optional) Reboot to ensure camera is fully enabled:"
echo "   sudo reboot"
echo ""
echo "📖 Click the Help button in the web UI for detailed instructions!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
