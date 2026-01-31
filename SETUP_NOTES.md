# Setup Notes

## Git Executable Permission Issue

**Problem**: When cloning this repository on Linux/Raspberry Pi, the `start_Cat_Dome.sh` script may not have execute permissions, causing the systemd service to fail with "exit code 203/EXEC".

**Root Cause**: The repository is maintained from Windows, which doesn't properly track Unix executable bits in git.

---

## ✅ **One-Time Fix (Run on Raspberry Pi)**

If you're the repository maintainer and want to fix this for all future clones:

```bash
cd ~/cat_ball_tracker

# Set executable permission locally
chmod +x start_Cat_Dome.sh

# Update git index to track the executable bit
git update-index --chmod=+x start_Cat_Dome.sh

# Check that it's marked as executable (should show 100755)
git ls-files --stage start_Cat_Dome.sh

# Commit the change
git add start_Cat_Dome.sh
git commit -m "Set executable bit for start_Cat_Dome.sh"

# Push to remote
git push
```

After this, anyone cloning the repo will get the file with correct permissions.

---

## 🔧 **Quick Fix for New Installations**

If you just cloned the repo and the service won't start:

```bash
cd ~/cat_ball_tracker
chmod +x start_Cat_Dome.sh
sudo systemctl restart cat_dome
```

---

## 📋 **Verification**

Check if the file is executable:

```bash
ls -la start_Cat_Dome.sh
```

Should show: `-rwxr-xr-x` (with 'x' for execute permission)

If it shows: `-rw-r--r--` (no 'x'), run `chmod +x start_Cat_Dome.sh`

---

## 🎯 **For Future Contributors**

When adding new shell scripts to the repository:

1. **On Linux/Mac:**
   ```bash
   chmod +x your_script.sh
   git add your_script.sh
   git commit
   ```

2. **On Windows:**
   ```bash
   git add your_script.sh
   git update-index --chmod=+x your_script.sh
   git commit
   ```

This ensures the executable bit is properly stored in git.
