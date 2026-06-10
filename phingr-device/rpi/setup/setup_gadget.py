#!/usr/bin/env python3
"""setup_gadget.py — Configure USB HID composite gadget (mouse + keyboard).

Uses the exact same code as test_composite_proper.py Config 1 which
is proven to work with iOS.

Usage:
    sudo python3 rpi/setup/setup_gadget.py
"""

import os
import sys
import subprocess

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

MOUSE_DESC = bytes([
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x09, 0x01, 0xA1, 0x00,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x03, 0x15, 0x00, 0x25, 0x01,
    0x95, 0x03, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x05,
    0x81, 0x01, 0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x15, 0x81,
    0x25, 0x7F, 0x75, 0x08, 0x95, 0x02, 0x81, 0x06, 0x09, 0x38,
    0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,
    0xC0, 0xC0,
])

KEYBOARD_DESC = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01,
    # Modifiers
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7,
    0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    # Reserved
    0x75, 0x08, 0x95, 0x01, 0x81, 0x01,
    # LED output (required for mobile)
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05,
    0x75, 0x01, 0x95, 0x05, 0x91, 0x02,
    0x75, 0x03, 0x95, 0x01, 0x91, 0x01,
    # Keys
    0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
    0x15, 0x00, 0x25, 0x65, 0x75, 0x08, 0x95, 0x06, 0x81, 0x00,
    0xC0,
])


def _cleanup_gadget(gadget_dir):
    """Remove a single gadget directory."""
    for link in ["hid.usb0", "hid.usb1"]:
        try:
            os.remove(f"{gadget_dir}/configs/c.1/{link}")
        except OSError:
            pass
    for d in [
        f"{gadget_dir}/configs/c.1/strings/0x409",
        f"{gadget_dir}/configs/c.1",
        f"{gadget_dir}/functions/hid.usb0",
        f"{gadget_dir}/functions/hid.usb1",
        f"{gadget_dir}/strings/0x409",
        gadget_dir,
    ]:
        try:
            os.rmdir(d)
        except OSError:
            pass


def teardown():
    """Remove all existing gadgets (including old 'fkios' name)."""
    # Unbind all gadgets from UDC
    base = "/sys/kernel/config/usb_gadget/"
    for name in os.listdir(base):
        udc_path = f"{base}{name}/UDC"
        if os.path.exists(udc_path):
            try:
                with open(udc_path, "w") as f:
                    f.write("")
            except OSError:
                pass

    # Clean up all gadget directories
    for name in os.listdir(base):
        _cleanup_gadget(f"{base}{name}")


def setup():
    """Create composite gadget — identical to test_composite_proper.py Config 1."""
    subprocess.run(["modprobe", "libcomposite"], check=True)

    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb1", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def w(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    # Device descriptor — USB 2.1 + Misc class (required for mobile composite)
    w("idVendor", "0x1d6b")
    w("idProduct", "0x0104")
    w("bcdDevice", "0x0100")
    w("bcdUSB", "0x0210")
    w("bDeviceClass", "0xEF")
    w("bDeviceSubClass", "0x02")
    w("bDeviceProtocol", "0x01")
    w("strings/0x409/serialnumber", "phingr001")
    w("strings/0x409/manufacturer", "phingr")
    w("strings/0x409/product", "phingr HID")

    # Function 0: Mouse (4 bytes)
    w("functions/hid.usb0/protocol", "2")
    w("functions/hid.usb0/subclass", "1")
    w("functions/hid.usb0/report_length", "4")
    w("functions/hid.usb0/report_desc", MOUSE_DESC)

    # Function 1: Keyboard (8 bytes)
    w("functions/hid.usb1/protocol", "1")
    w("functions/hid.usb1/subclass", "1")
    w("functions/hid.usb1/report_length", "8")
    w("functions/hid.usb1/report_desc", KEYBOARD_DESC)

    # Configuration
    w("configs/c.1/strings/0x409/configuration", "Config")
    w("configs/c.1/MaxPower", "250")

    os.symlink(f"{GADGET_DIR}/functions/hid.usb0",
               f"{GADGET_DIR}/configs/c.1/hid.usb0")
    os.symlink(f"{GADGET_DIR}/functions/hid.usb1",
               f"{GADGET_DIR}/configs/c.1/hid.usb1")

    # Bind to UDC
    udc_list = os.listdir("/sys/class/udc")
    if not udc_list:
        print("ERROR: No UDC found at /sys/class/udc/")
        print("The dwc2 kernel module is not loaded. This usually means:")
        print("  1. /boot/firmware/config.txt needs: dtoverlay=dwc2,dr_mode=peripheral")
        print("  2. /etc/modules needs: dwc2 and libcomposite")
        print("  3. A reboot is required after adding those entries")
        print("")
        print("Reboot and run bootstrap.sh again.")
        sys.exit(1)
    udc = udc_list[0]
    w("UDC", udc)

    print("USB HID gadget configured:")
    print("  /dev/hidg0 — mouse")
    print("  /dev/hidg1 — keyboard")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 setup_gadget.py")
        sys.exit(1)

    teardown()
    setup()
