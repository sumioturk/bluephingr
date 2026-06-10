#!/usr/bin/env bash
# setup_gadget.sh — Configure RPi Zero 2W as USB HID mouse + keyboard.
#
# Run once after boot (or via systemd) with root privileges.
# Creates two HID devices:
#   /dev/hidg0 — mouse (4 bytes: buttons, dx, dy, wheel)
#   /dev/hidg1 — keyboard (8 bytes: modifiers, reserved, keys[6])

set -euo pipefail

GADGET_DIR="/sys/kernel/config/usb_gadget/phingr"
# Resolve symlinks to find the real script directory
REAL_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(cd "$(dirname "$REAL_PATH")" && pwd)"

# Tear down existing gadget if present
if [ -d "$GADGET_DIR" ]; then
    echo "Removing existing gadget ..."
    bash "$SCRIPT_DIR/teardown_gadget.sh"
fi

modprobe libcomposite

mkdir -p "$GADGET_DIR"
cd "$GADGET_DIR"

# USB device descriptor — USB 2.1 with proper composite device class
# Required for mobile to accept both mouse and keyboard in one gadget
echo 0x1d6b > idVendor    # Linux Foundation
echo 0x0104 > idProduct    # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0210 > bcdUSB       # USB 2.1 (required for composite on iOS)
echo 0xEF   > bDeviceClass    # Miscellaneous
echo 0x02   > bDeviceSubClass # Common Class
echo 0x01   > bDeviceProtocol # IAD

mkdir -p strings/0x409
echo "fedcba9876543210" > strings/0x409/serialnumber
echo "phingr"             > strings/0x409/manufacturer
echo "phingr HID"         > strings/0x409/product

# =========================================================================
# Function 0: Mouse (4 bytes)
# =========================================================================
mkdir -p functions/hid.usb0
echo 2 > functions/hid.usb0/protocol    # mouse
echo 1 > functions/hid.usb0/subclass    # boot interface
echo 4 > functions/hid.usb0/report_length

# Mouse report descriptor (buttons + X + Y + wheel)
echo -ne '\x05\x01'     > functions/hid.usb0/report_desc  # Usage Page (Generic Desktop)
echo -ne '\x09\x02'    >> functions/hid.usb0/report_desc  # Usage (Mouse)
echo -ne '\xa1\x01'    >> functions/hid.usb0/report_desc  # Collection (Application)
echo -ne '\x09\x01'    >> functions/hid.usb0/report_desc  #   Usage (Pointer)
echo -ne '\xa1\x00'    >> functions/hid.usb0/report_desc  #   Collection (Physical)
echo -ne '\x05\x09'    >> functions/hid.usb0/report_desc  #     Usage Page (Buttons)
echo -ne '\x19\x01'    >> functions/hid.usb0/report_desc  #     Usage Minimum (1)
echo -ne '\x29\x03'    >> functions/hid.usb0/report_desc  #     Usage Maximum (3)
echo -ne '\x15\x00'    >> functions/hid.usb0/report_desc  #     Logical Minimum (0)
echo -ne '\x25\x01'    >> functions/hid.usb0/report_desc  #     Logical Maximum (1)
echo -ne '\x95\x03'    >> functions/hid.usb0/report_desc  #     Report Count (3)
echo -ne '\x75\x01'    >> functions/hid.usb0/report_desc  #     Report Size (1)
echo -ne '\x81\x02'    >> functions/hid.usb0/report_desc  #     Input (Data, Variable, Absolute)
echo -ne '\x95\x01'    >> functions/hid.usb0/report_desc  #     Report Count (1)
echo -ne '\x75\x05'    >> functions/hid.usb0/report_desc  #     Report Size (5)
echo -ne '\x81\x01'    >> functions/hid.usb0/report_desc  #     Input (Constant) padding
echo -ne '\x05\x01'    >> functions/hid.usb0/report_desc  #     Usage Page (Generic Desktop)
echo -ne '\x09\x30'    >> functions/hid.usb0/report_desc  #     Usage (X)
echo -ne '\x09\x31'    >> functions/hid.usb0/report_desc  #     Usage (Y)
echo -ne '\x15\x81'    >> functions/hid.usb0/report_desc  #     Logical Minimum (-127)
echo -ne '\x25\x7f'    >> functions/hid.usb0/report_desc  #     Logical Maximum (127)
echo -ne '\x75\x08'    >> functions/hid.usb0/report_desc  #     Report Size (8)
echo -ne '\x95\x02'    >> functions/hid.usb0/report_desc  #     Report Count (2)
echo -ne '\x81\x06'    >> functions/hid.usb0/report_desc  #     Input (Data, Variable, Relative)
echo -ne '\x09\x38'    >> functions/hid.usb0/report_desc  #     Usage (Wheel)
echo -ne '\x15\x81'    >> functions/hid.usb0/report_desc  #     Logical Minimum (-127)
echo -ne '\x25\x7f'    >> functions/hid.usb0/report_desc  #     Logical Maximum (127)
echo -ne '\x75\x08'    >> functions/hid.usb0/report_desc  #     Report Size (8)
echo -ne '\x95\x01'    >> functions/hid.usb0/report_desc  #     Report Count (1)
echo -ne '\x81\x06'    >> functions/hid.usb0/report_desc  #     Input (Data, Variable, Relative)
echo -ne '\xc0'        >> functions/hid.usb0/report_desc  #   End Collection
echo -ne '\xc0'        >> functions/hid.usb0/report_desc  # End Collection

# =========================================================================
# Function 1: Keyboard (8 bytes)
# =========================================================================
mkdir -p functions/hid.usb1
echo 1 > functions/hid.usb1/protocol    # keyboard
echo 1 > functions/hid.usb1/subclass    # boot interface
echo 8 > functions/hid.usb1/report_length

# Keyboard report descriptor (with LED output report — required for mobile)
# Input (8 bytes): modifiers(1) + reserved(1) + keys(6)
# Output (1 byte): LED status (iOS sends Caps Lock etc. — must be read)
echo -ne '\x05\x01'     > functions/hid.usb1/report_desc  # Usage Page (Generic Desktop)
echo -ne '\x09\x06'    >> functions/hid.usb1/report_desc  # Usage (Keyboard)
echo -ne '\xa1\x01'    >> functions/hid.usb1/report_desc  # Collection (Application)
# Modifier keys (8 bits)
echo -ne '\x05\x07'    >> functions/hid.usb1/report_desc  #   Usage Page (Keyboard/Keypad)
echo -ne '\x19\xe0'    >> functions/hid.usb1/report_desc  #   Usage Minimum (Left Control)
echo -ne '\x29\xe7'    >> functions/hid.usb1/report_desc  #   Usage Maximum (Right GUI)
echo -ne '\x15\x00'    >> functions/hid.usb1/report_desc  #   Logical Minimum (0)
echo -ne '\x25\x01'    >> functions/hid.usb1/report_desc  #   Logical Maximum (1)
echo -ne '\x75\x01'    >> functions/hid.usb1/report_desc  #   Report Size (1)
echo -ne '\x95\x08'    >> functions/hid.usb1/report_desc  #   Report Count (8)
echo -ne '\x81\x02'    >> functions/hid.usb1/report_desc  #   Input (Data, Variable, Absolute)
# Reserved byte
echo -ne '\x75\x08'    >> functions/hid.usb1/report_desc  #   Report Size (8)
echo -ne '\x95\x01'    >> functions/hid.usb1/report_desc  #   Report Count (1)
echo -ne '\x81\x01'    >> functions/hid.usb1/report_desc  #   Input (Constant)
# LED output report (5 bits + 3 padding) — iOS requires this
echo -ne '\x05\x08'    >> functions/hid.usb1/report_desc  #   Usage Page (LEDs)
echo -ne '\x19\x01'    >> functions/hid.usb1/report_desc  #   Usage Minimum (Num Lock)
echo -ne '\x29\x05'    >> functions/hid.usb1/report_desc  #   Usage Maximum (Kana)
echo -ne '\x75\x01'    >> functions/hid.usb1/report_desc  #   Report Size (1)
echo -ne '\x95\x05'    >> functions/hid.usb1/report_desc  #   Report Count (5)
echo -ne '\x91\x02'    >> functions/hid.usb1/report_desc  #   Output (Data, Variable, Absolute)
echo -ne '\x75\x03'    >> functions/hid.usb1/report_desc  #   Report Size (3)
echo -ne '\x95\x01'    >> functions/hid.usb1/report_desc  #   Report Count (1)
echo -ne '\x91\x01'    >> functions/hid.usb1/report_desc  #   Output (Constant) padding
# Key codes (6 bytes)
echo -ne '\x05\x07'    >> functions/hid.usb1/report_desc  #   Usage Page (Keyboard/Keypad)
echo -ne '\x19\x00'    >> functions/hid.usb1/report_desc  #   Usage Minimum (0)
echo -ne '\x29\x65'    >> functions/hid.usb1/report_desc  #   Usage Maximum (101)
echo -ne '\x15\x00'    >> functions/hid.usb1/report_desc  #   Logical Minimum (0)
echo -ne '\x25\x65'    >> functions/hid.usb1/report_desc  #   Logical Maximum (101)
echo -ne '\x75\x08'    >> functions/hid.usb1/report_desc  #   Report Size (8)
echo -ne '\x95\x06'    >> functions/hid.usb1/report_desc  #   Report Count (6)
echo -ne '\x81\x00'    >> functions/hid.usb1/report_desc  #   Input (Data, Array)
echo -ne '\xc0'        >> functions/hid.usb1/report_desc  # End Collection

# =========================================================================
# Configuration — link both functions
# =========================================================================
mkdir -p configs/c.1/strings/0x409
echo "phingr HID Config" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/

# Bind to UDC
UDC_NAME=$(ls /sys/class/udc/ 2>/dev/null | head -1)
if [ -z "$UDC_NAME" ]; then
    echo "ERROR: No UDC found at /sys/class/udc/"
    echo "The dwc2 kernel module is not loaded. Reboot and run bootstrap.sh again."
    exit 1
fi
echo "$UDC_NAME" > UDC 2>/dev/null || {
    echo "UDC busy — unbinding and retrying ..."
    echo "" > /sys/kernel/config/usb_gadget/*/UDC 2>/dev/null || true
    sleep 1
    echo "$UDC_NAME" > UDC
}

echo "USB HID gadget configured:"
echo "  /dev/hidg0 — mouse"
echo "  /dev/hidg1 — keyboard"
