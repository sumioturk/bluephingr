#!/usr/bin/env python3
"""test_mouse.py — Test USB HID by configuring a simple mouse gadget.

Run on the RPi as root to verify the USB HID path works with iOS.
If a cursor appears and moves, the USB connection is good and the
issue is with the touch digitizer descriptor.

Usage:
    sudo python3 rpi/util/test_mouse.py
"""

import glob
import os
import struct
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

# Minimal mouse HID descriptor
MOUSE_DESC = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Buttons)
    0x19, 0x01,        #     Usage Minimum (1)
    0x29, 0x03,        #     Usage Maximum (3)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x95, 0x03,        #     Report Count (3)
    0x75, 0x01,        #     Report Size (1)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)
    0x95, 0x01,        #     Report Count (1)
    0x75, 0x05,        #     Report Size (5)
    0x81, 0x01,        #     Input (Constant) padding
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x02,        #     Report Count (2)
    0x81, 0x06,        #     Input (Data, Variable, Relative)
    0xC0,              #   End Collection
    0xC0,              # End Collection
])


def teardown_gadget():
    """Remove existing gadget if present."""
    if not os.path.isdir(GADGET_DIR):
        return
    # Unbind
    try:
        with open(f"{GADGET_DIR}/UDC", "w") as f:
            f.write("")
    except OSError:
        pass
    # Remove symlink and dirs
    for path in [
        f"{GADGET_DIR}/configs/c.1/hid.usb0",
    ]:
        try:
            os.remove(path)
        except OSError:
            pass
    for path in [
        f"{GADGET_DIR}/configs/c.1/strings/0x409",
        f"{GADGET_DIR}/configs/c.1",
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/strings/0x409",
        GADGET_DIR,
    ]:
        try:
            os.rmdir(path)
        except OSError:
            pass


def setup_mouse_gadget():
    """Configure a USB HID mouse gadget."""
    os.system("modprobe libcomposite")

    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def write(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    write("idVendor", "0x1d6b")
    write("idProduct", "0x0104")
    write("bcdDevice", "0x0100")
    write("bcdUSB", "0x0200")
    write("strings/0x409/serialnumber", "phingr001")
    write("strings/0x409/manufacturer", "phingr")
    write("strings/0x409/product", "phingr Mouse Test")
    write("functions/hid.usb0/protocol", "2")
    write("functions/hid.usb0/subclass", "1")
    write("functions/hid.usb0/report_length", "3")
    write("functions/hid.usb0/report_desc", MOUSE_DESC)
    write("configs/c.1/strings/0x409/configuration", "Config")
    write("configs/c.1/MaxPower", "250")

    os.symlink(
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/configs/c.1/hid.usb0",
    )

    udc = os.listdir("/sys/class/udc")[0]
    write("UDC", udc)
    print(f"Mouse gadget configured (UDC: {udc})")


def test_mouse_movement():
    """Move the cursor right to prove HID works."""
    print("Waiting 1s for mobile to enumerate ...")
    time.sleep(1)

    print("Moving cursor right ...")
    with open("/dev/hidg0", "wb") as f:
        for _ in range(50):
            f.write(struct.pack("bbb", 0, 10, 0))  # no buttons, X+10
            f.flush()
            time.sleep(0.02)

    print("Done — cursor should have moved right on iOS.")
    print("If nothing happened, check the USB cable and port.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_mouse.py")
        raise SystemExit(1)

    teardown_gadget()
    setup_mouse_gadget()
    test_mouse_movement()
