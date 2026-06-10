#!/usr/bin/env bash
# teardown_gadget.sh — Remove the phingr USB HID gadget.

set -euo pipefail

GADGET_DIR="/sys/kernel/config/usb_gadget/phingr"

# Unbind any gadget using the UDC (even if our dir is gone)
for udc_file in /sys/kernel/config/usb_gadget/*/UDC; do
    [ -f "$udc_file" ] && echo "" > "$udc_file" 2>/dev/null || true
done

if [ ! -d "$GADGET_DIR" ]; then
    echo "No gadget to tear down"
    exit 0
fi

echo "Tearing down gadget ..."

# Unbind from UDC
echo "" > "$GADGET_DIR/UDC" 2>/dev/null || true

# Remove function symlinks from config
rm -f "$GADGET_DIR/configs/c.1/hid.usb0"
rm -f "$GADGET_DIR/configs/c.1/hid.usb1"

# Remove config dirs
rmdir "$GADGET_DIR/configs/c.1/strings/0x409" 2>/dev/null || true
rmdir "$GADGET_DIR/configs/c.1" 2>/dev/null || true

# Remove function dirs
rmdir "$GADGET_DIR/functions/hid.usb0" 2>/dev/null || true
rmdir "$GADGET_DIR/functions/hid.usb1" 2>/dev/null || true

# Remove gadget
rmdir "$GADGET_DIR/strings/0x409" 2>/dev/null || true
rmdir "$GADGET_DIR" 2>/dev/null || true

echo "Gadget removed"
