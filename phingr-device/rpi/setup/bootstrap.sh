#!/usr/bin/env bash
# bootstrap.sh — One-shot setup for phingr on RPi Zero 2W.
#
# Installs all dependencies, configures USB gadget, and starts services.
# Safe to re-run — cleans up and rebuilds everything.
#
# Usage:
#   sudo bash rpi/setup/bootstrap.sh
#
# After first run (if dwc2 was just enabled), reboot and run again.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RPI_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$RPI_DIR")"

SKIP_PACKAGES=false
for arg in "$@"; do
    case "$arg" in
        --skip-packages|-s) SKIP_PACKAGES=true ;;
    esac
done

echo "============================================"
echo " phingr Bootstrap — RPi Zero 2W"
echo "============================================"
echo "Repo: $REPO_DIR"
if [ "$SKIP_PACKAGES" = true ]; then
    echo "Mode: skip package install"
fi
echo ""

# ── Must be root ─────────────────────────────────────────────────────────

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run as root: sudo bash rpi/setup/bootstrap.sh"
    exit 1
fi

# ── 0. Set hostname ──────────────────────────────────────────────────────

CURRENT_HOSTNAME=$(hostname)
if echo "$CURRENT_HOSTNAME" | grep -q "^phingr-"; then
    NEW_HOSTNAME="$CURRENT_HOSTNAME"
    echo "[0/7] Hostname already set: $CURRENT_HOSTNAME"
else
    # Generate 4 hex digits from the Pi's serial number for uniqueness
    SUFFIX=$(cat /proc/cpuinfo | grep Serial | awk '{print substr($3, length($3)-3)}')
    [ -z "$SUFFIX" ] && SUFFIX=$(head -c 2 /dev/urandom | od -An -tx1 | tr -d ' ')
    NEW_HOSTNAME="phingr-${SUFFIX}"
    echo "[0/7] Setting hostname: $NEW_HOSTNAME (was: $CURRENT_HOSTNAME)"
    hostnamectl set-hostname "$NEW_HOSTNAME"
    echo "  Access via: ${NEW_HOSTNAME}.local"
fi

# Always ensure /etc/hosts has the hostname (fixes "unable to resolve host")
sed -i '/127\.0\.1\.1/d' /etc/hosts
printf '127.0.1.1\t%s\n' "$NEW_HOSTNAME" >> /etc/hosts
echo ""

if [ "$SKIP_PACKAGES" = true ]; then
    echo "[1/7] Skipping system packages (--skip-packages)"
    echo "[2/7] Skipping Python packages (--skip-packages)"
else
    # ── 1. System packages ──────────────────────────────────────────────
    echo "[1/7] Installing system packages ..."
    apt-get update -qq
    apt-get install -y -qq \
        python3-picamera2 \
        python3-libcamera \
        libcamera-apps \
        python3-opencv \
        git \
        libimobiledevice-utils \
        ideviceinstaller \
        usbmuxd \
        > /dev/null 2>&1
    echo "  Done"

    # ── 2. Python packages ──────────────────────────────────────────────
    echo "[2/7] Installing Python packages ..."
    pip install --break-system-packages -q \
        aiohttp \
        2>/dev/null || pip3 install --break-system-packages -q aiohttp
    echo "  Done"
fi

# ── Boot config path (used by camera + USB gadget steps) ──────────────

NEEDS_REBOOT=false
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
else
    BOOT_CONFIG="/boot/config.txt"
fi

# ── 2.5. Camera setup ──────────────────────────────────────────────────

echo "[2.5/7] Configuring camera ..."

# Ensure start_x is NOT set (legacy camera stack conflicts with libcamera)
if grep -q '^start_x=1' "$BOOT_CONFIG" 2>/dev/null; then
    sed -i 's/^start_x=1/#start_x=1  # disabled by phingr (use libcamera instead)/' "$BOOT_CONFIG"
    echo "  Disabled legacy camera stack (start_x)"
    NEEDS_REBOOT=true
fi

# Note: default gpu_mem (64-76MB) is fine for camera on Pi Zero 2W.
# Do NOT set gpu_mem=128 — Pi Zero 2W only has 512MB and it can brick.

# ArduCam IMX519 driver — not included in stock Pi OS, needs ArduCam's installer
if [ "$SKIP_PACKAGES" != true ]; then
    ARDUCAM_MARKER="/opt/phingr/.arducam_imx519_installed"
    if [ ! -f "$ARDUCAM_MARKER" ]; then
        echo "  Installing ArduCam IMX519 driver ..."
        ARDUCAM_SCRIPT="/tmp/install_pivariety_pkgs.sh"
        curl -sL -o "$ARDUCAM_SCRIPT" \
            https://github.com/ArduCAM/Arducam-Pivariety-V4L2-Driver/releases/download/install_script/install_pivariety_pkgs.sh
        chmod +x "$ARDUCAM_SCRIPT"
        bash "$ARDUCAM_SCRIPT" -p libcamera_dev
        bash "$ARDUCAM_SCRIPT" -p libcamera_apps
        rm -f "$ARDUCAM_SCRIPT"
        mkdir -p /opt/phingr
        touch "$ARDUCAM_MARKER"
        echo "  ArduCam IMX519 driver installed (reboot required to load kernel module)"
        NEEDS_REBOOT=true
    else
        echo "  ArduCam IMX519 driver already installed"
    fi
fi

# IMX519 requires explicit overlay — camera_auto_detect must be OFF
# (auto_detect conflicts with third-party camera drivers)
if grep -q '^camera_auto_detect=1' "$BOOT_CONFIG" 2>/dev/null; then
    sed -i 's/^camera_auto_detect=1/camera_auto_detect=0  # disabled for ArduCam IMX519/' "$BOOT_CONFIG"
    echo "  Disabled camera_auto_detect (required for IMX519)"
    NEEDS_REBOOT=true
fi
if ! grep -q '^dtoverlay=imx519' "$BOOT_CONFIG" 2>/dev/null; then
    # Add in [all] section
    if grep -q '^\[all\]' "$BOOT_CONFIG"; then
        sed -i '/^\[all\]/a dtoverlay=imx519' "$BOOT_CONFIG"
    else
        printf '\n[all]\ndtoverlay=imx519\n' >> "$BOOT_CONFIG"
    fi
    echo "  Added dtoverlay=imx519"
    NEEDS_REBOOT=true
fi

# Verify camera detection (only if not needing reboot)
if [ "$NEEDS_REBOOT" = false ]; then
    CAM_DETECTED=$(vcgencmd get_camera 2>/dev/null | grep -o 'detected=[0-9]*' | cut -d= -f2)
    if [ "$CAM_DETECTED" = "0" ] || [ -z "$CAM_DETECTED" ]; then
        # Also try libcamera (some cameras don't show in vcgencmd but work with libcamera)
        LIBCAM_DETECTED=$(libcamera-hello --list-cameras 2>&1 | grep -c 'Available cameras' || echo "0")
        if [ "$LIBCAM_DETECTED" = "0" ]; then
            echo "  WARNING: No camera detected."
            echo "    - Check CSI ribbon cable (contacts face the board)"
            echo "    - Pi Zero 2W needs a mini CSI cable (22-pin, narrower than standard)"
            echo "    - Try: sudo reboot, then re-run bootstrap"
        else
            echo "  Camera detected (libcamera)"
        fi
    else
        echo "  Camera detected"
    fi
fi

# ── 3. Enable dwc2 USB gadget overlay ───────────────────────────────────

echo "[3/7] Configuring USB gadget support ..."

# Disable otg_mode=1 — it forces host mode and blocks dwc2 peripheral
if grep -q '^otg_mode=1' "$BOOT_CONFIG" 2>/dev/null; then
    sed -i 's/^otg_mode=1/#otg_mode=1  # disabled by phingr (conflicts with dwc2 peripheral)/' "$BOOT_CONFIG"
    echo "  Disabled otg_mode=1 (was blocking peripheral mode)"
    NEEDS_REBOOT=true
fi

# Check if dwc2 overlay is already correctly in [all] section
# (not inside a board-specific section like [cm4] or [cm5])
DWC2_OK=false
if grep -q '^\[all\]' "$BOOT_CONFIG"; then
    # Check that dtoverlay=dwc2 appears AFTER [all] and not inside another section
    ALL_LINE=$(grep -n '^\[all\]' "$BOOT_CONFIG" | head -1 | cut -d: -f1)
    DWC2_LINE=$(grep -n 'dtoverlay=dwc2' "$BOOT_CONFIG" | tail -1 | cut -d: -f1)
    if [ -n "$DWC2_LINE" ] && [ "$DWC2_LINE" -gt "$ALL_LINE" ]; then
        DWC2_OK=true
    fi
fi

if [ "$DWC2_OK" = false ]; then
    # Remove any misplaced dwc2 lines and add under [all]
    sed -i '/dtoverlay=dwc2/d' "$BOOT_CONFIG"
    if grep -q '^\[all\]' "$BOOT_CONFIG"; then
        sed -i '/^\[all\]/a dtoverlay=dwc2,dr_mode=peripheral' "$BOOT_CONFIG"
    else
        printf '\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\n' >> "$BOOT_CONFIG"
    fi
    echo "  dwc2 overlay set in [all] section (dr_mode=peripheral)"
    NEEDS_REBOOT=true
else
    if grep -q 'dtoverlay=dwc2.*dr_mode=peripheral' "$BOOT_CONFIG"; then
        echo "  dwc2 overlay already in [all] section (dr_mode=peripheral)"
    elif grep -q 'dtoverlay=dwc2.*dr_mode=otg' "$BOOT_CONFIG"; then
        sed -i 's/dtoverlay=dwc2,dr_mode=otg/dtoverlay=dwc2,dr_mode=peripheral/' "$BOOT_CONFIG"
        echo "  Updated dr_mode: otg -> peripheral"
        NEEDS_REBOOT=true
    else
        # dtoverlay=dwc2 present but no dr_mode — append it
        sed -i 's/dtoverlay=dwc2$/dtoverlay=dwc2,dr_mode=peripheral/' "$BOOT_CONFIG"
        echo "  Added dr_mode=peripheral to dwc2 overlay"
        NEEDS_REBOOT=true
    fi
fi

# Check if UDC is available (dwc2 may be built-in, not a module)
if [ -z "$(ls /sys/class/udc/ 2>/dev/null)" ]; then
    modprobe dwc2 2>/dev/null || true
    modprobe libcomposite 2>/dev/null || true
    # Still no UDC? Need reboot.
    if [ -z "$(ls /sys/class/udc/ 2>/dev/null)" ]; then
        NEEDS_REBOOT=true
    fi
fi

# Ensure modules load on boot (both legacy and systemd paths)
for mod in dwc2 libcomposite; do
    if ! grep -q "^${mod}$" /etc/modules 2>/dev/null; then
        echo "$mod" >> /etc/modules
    fi
done
# Also use /etc/modules-load.d/ (newer systemd, /etc/modules may be ignored)
mkdir -p /etc/modules-load.d
printf 'dwc2\nlibcomposite\n' > /etc/modules-load.d/phingr.conf

# Note: do NOT blacklist dwc_otg — it's built into the kernel on Pi Zero 2W
# and required for boot. The dtoverlay=dwc2 is sufficient to make the USB
# controller available for gadget mode alongside dwc_otg.

# Remove any previous blacklist (from older bootstrap versions)
if [ -f /etc/modprobe.d/phingr.conf ] && grep -q 'blacklist dwc_otg' /etc/modprobe.d/phingr.conf 2>/dev/null; then
    rm -f /etc/modprobe.d/phingr.conf
    echo "  Removed dwc_otg blacklist (was causing boot failure)"
    NEEDS_REBOOT=true
fi

if [ "$NEEDS_REBOOT" = true ]; then
    echo ""
    echo "============================================"
    echo "  REBOOT REQUIRED"
    echo "============================================"
    echo ""
    echo "  Bootstrap changed system configuration that requires a reboot:"
    if [ -z "$(ls /sys/class/udc/ 2>/dev/null)" ]; then
        echo "    - USB gadget (dwc2) not yet active"
    fi
    if [ -f /opt/phingr/.arducam_imx519_installed ]; then
        CAM_DETECTED=$(vcgencmd get_camera 2>/dev/null | grep -o 'detected=[0-9]*' | cut -d= -f2)
        if [ "$CAM_DETECTED" = "0" ] || [ -z "$CAM_DETECTED" ]; then
            echo "    - ArduCam IMX519 camera driver just installed"
        fi
    fi
    echo ""
    echo "  Run:  sudo reboot"
    echo "  Then: sudo bash $(realpath "$0") -s"
    echo ""
    echo "  (Use -s to skip package install — already done)"
    echo ""
    exit 0
fi

echo "  Done (dwc2 loaded)"

# ── 4. Tear down existing HID gadget ────────────────────────────────────

echo "[4/7] Setting up USB HID gadget (mouse + keyboard) ..."
python3 "$SCRIPT_DIR/setup_gadget.py"

# Verify devices
if [ -e /dev/hidg0 ] && [ -e /dev/hidg1 ]; then
    echo "  /dev/hidg0 (mouse) ✓"
    echo "  /dev/hidg1 (keyboard) ✓"
else
    echo "  WARNING: HID devices not at expected numbers (hidg0/hidg1)"
    ls -la /dev/hidg* 2>/dev/null || echo "  No /dev/hidg* found"
    echo ""
    echo "  *** REBOOT REQUIRED ***"
    echo "  Stale HID devices from a previous session are causing"
    echo "  incorrect numbering. Run:"
    echo "    sudo reboot"
    echo "  Then re-run:"
    echo "    sudo bash rpi/setup/bootstrap.sh"
    echo ""
    exit 0
fi

# ── 6. Install systemd services ─────────────────────────────────────────

echo "[6/7] Installing systemd services ..."

SERVER_DIR="$RPI_DIR/server"

# Stop and remove old fkios services (from before rename)
for old_svc in fkios-web fkios-touch fkios-updater fkios-capture; do
    systemctl stop "$old_svc.service" 2>/dev/null || true
    systemctl disable "$old_svc.service" 2>/dev/null || true
    rm -f "/etc/systemd/system/$old_svc.service"
done

# Stop existing phingr services
systemctl stop phingr-web.service 2>/dev/null || true
systemctl stop phingr-updater.service 2>/dev/null || true
systemctl stop phingr-touch.service 2>/dev/null || true

# Kill anything on port 7700 (in case old process lingers)
fuser -k 7700/tcp 2>/dev/null || true

# Install services
for svc in phingr-web.service phingr-updater.service phingr-touch.service phingr-capture.service; do
    if [ -f "$SCRIPT_DIR/$svc" ]; then
        cp "$SCRIPT_DIR/$svc" /etc/systemd/system/
        echo "  Installed $svc"
    fi
done

# Deploy to /opt/phingr
mkdir -p /opt/phingr

# Server scripts
for f in web_server.py touch_server.py capture_server.py updater.py; do
    if [ -f "$SERVER_DIR/$f" ]; then
        cp "$SERVER_DIR/$f" /opt/phingr/
    fi
done

# Static web files
if [ -d "$SERVER_DIR/static" ]; then
    mkdir -p /opt/phingr/static
    cp "$SERVER_DIR/static/"* /opt/phingr/static/
fi

# Setup scripts
for f in setup_gadget.py setup_gadget.sh teardown_gadget.sh; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" /opt/phingr/
    fi
done

chmod +x /opt/phingr/setup_gadget.sh /opt/phingr/teardown_gadget.sh 2>/dev/null || true

systemctl daemon-reload
systemctl enable phingr-touch.service
systemctl enable phingr-web.service
systemctl enable phingr-updater.service
systemctl enable usbmuxd --now 2>/dev/null || true
echo "  Done"

# ── 7. Start services ───────────────────────────────────────────────────

echo "[7/7] Starting services ..."
systemctl start phingr-touch.service
sleep 1
systemctl start phingr-web.service
systemctl start phingr-updater.service

# Wait and check status
sleep 2
TOUCH_STATUS=$(systemctl is-active phingr-touch.service 2>/dev/null || echo "failed")
WEB_STATUS=$(systemctl is-active phingr-web.service 2>/dev/null || echo "failed")
UPD_STATUS=$(systemctl is-active phingr-updater.service 2>/dev/null || echo "failed")

echo ""
echo "============================================"
echo " phingr Bootstrap Complete"
echo "============================================"
echo ""
echo "  HID server:   $TOUCH_STATUS  (mouse + keyboard on :7700)"
echo "  Web server:   $WEB_STATUS  (UI + API on :8080)"
echo "  Auto-updater: $UPD_STATUS"
echo "  Mouse:       /dev/hidg0"
echo "  Keyboard:    /dev/hidg1"
echo ""

# Get IP address and hostname
IP=$(hostname -I | awk '{print $1}')
HN=$(hostname)
echo "  Hostname: ${HN}.local"
echo "  Web UI:   http://${HN}.local:8080  (or http://${IP}:8080)"
echo "  SSH:      ssh $(whoami)@${HN}.local"
echo ""

if [ "$WEB_STATUS" != "active" ]; then
    echo "  Web server failed. Check logs:"
    echo "    sudo journalctl -u phingr-web -n 20 --no-pager"
    echo ""
fi

echo "  Device setup:"
echo "    1. Connect phone via USB data cable"
echo "    2. Lock screen auto-rotation (REQUIRED for accurate cursor control)"
echo "       iOS:     Control Center > tap rotation lock icon"
echo "       Android: Settings > Display > Auto-rotate OFF"
echo "    3. Enable external pointer support:"
echo "       iOS:     Settings > Accessibility > Touch > AssistiveTouch > ON"
echo "       iOS:     Settings > Accessibility > Keyboards > Full Keyboard Access > ON"
echo "    4. (Optional) Set hot corners for Home, App Switch, etc."
echo ""
