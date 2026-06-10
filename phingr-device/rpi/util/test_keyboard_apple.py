#!/usr/bin/env python3
"""test_keyboard_apple.py — Test keyboard with Apple vendor ID.

Tries multiple approaches to get iOS to accept a keyboard:
1. Apple vendor ID (0x05ac) to mimic an Apple keyboard
2. Consumer Control descriptor (media keys)

Usage:
    sudo python3 rpi/util/test_keyboard_apple.py
"""

import os
import struct
import sys
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

# Standard boot keyboard descriptor
KEYBOARD_DESC = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7,
    0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x75, 0x08, 0x95, 0x01, 0x81, 0x01,
    0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
    0x15, 0x00, 0x25, 0x65, 0x75, 0x08, 0x95, 0x06, 0x81, 0x00,
    0xC0,
])


def teardown():
    if not os.path.isdir(GADGET_DIR):
        return
    try:
        with open(f"{GADGET_DIR}/UDC", "w") as f:
            f.write("")
    except OSError:
        pass
    for link in ["hid.usb0", "hid.usb1"]:
        try:
            os.remove(f"{GADGET_DIR}/configs/c.1/{link}")
        except OSError:
            pass
    for d in [
        f"{GADGET_DIR}/configs/c.1/strings/0x409",
        f"{GADGET_DIR}/configs/c.1",
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/functions/hid.usb1",
        f"{GADGET_DIR}/strings/0x409",
        GADGET_DIR,
    ]:
        try:
            os.rmdir(d)
        except OSError:
            pass


def setup(vendor_id="0x05ac", product_id="0x024f", product_name="Apple Keyboard"):
    """Configure keyboard gadget with given USB IDs."""
    os.system("modprobe libcomposite")
    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def w(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    w("idVendor", vendor_id)
    w("idProduct", product_id)
    w("bcdDevice", "0x0100")
    w("bcdUSB", "0x0200")
    w("strings/0x409/serialnumber", "phingr001")
    w("strings/0x409/manufacturer", "Apple Inc.")
    w("strings/0x409/product", product_name)
    w("functions/hid.usb0/protocol", "1")
    w("functions/hid.usb0/subclass", "1")
    w("functions/hid.usb0/report_length", "8")
    w("functions/hid.usb0/report_desc", KEYBOARD_DESC)
    w("configs/c.1/strings/0x409/configuration", "Config")
    w("configs/c.1/MaxPower", "250")

    os.symlink(
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/configs/c.1/hid.usb0",
    )
    udc = os.listdir("/sys/class/udc")[0]
    w("UDC", udc)
    print(f"Keyboard gadget configured as '{product_name}' ({vendor_id}:{product_id})")


def test_write():
    """Test if /dev/hidg0 blocks (iOS rejecting) or succeeds."""
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("write blocked — iOS rejected the keyboard")

    signal.signal(signal.SIGALRM, timeout_handler)

    print("Waiting 2s for mobile to enumerate ...")
    time.sleep(2)

    print("Testing write to /dev/hidg0 ...")
    signal.alarm(3)  # 3 second timeout
    try:
        with open("/dev/hidg0", "wb") as f:
            # Press 'a'
            f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
            f.flush()
            time.sleep(0.05)
            # Release
            f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            f.flush()
        signal.alarm(0)
        print("SUCCESS — keyboard accepted by iOS!")
        return True
    except TimeoutError:
        signal.alarm(0)
        print("BLOCKED — iOS rejected this keyboard")
        return False


CONFIGS = [
    # (vendor_id, product_id, product_name)
    ("0x05ac", "0x024f", "Apple Keyboard (USB)"),
    ("0x05ac", "0x0256", "Apple Wireless Keyboard"),
    ("0x1d6b", "0x0001", "Linux HID Keyboard"),
    ("0x046d", "0xc31c", "Logitech Keyboard K120"),
]


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_keyboard_apple.py")
        raise SystemExit(1)

    # Try each config until one works
    for vid, pid, name in CONFIGS:
        print(f"\n{'='*50}")
        print(f"Trying: {name} ({vid}:{pid})")
        print(f"{'='*50}")
        teardown()
        setup(vid, pid, name)
        if test_write():
            print(f"\n*** WORKING CONFIG: {name} ({vid}:{pid}) ***")
            print("Pressing Cmd+H (home) ...")
            with open("/dev/hidg0", "wb") as f:
                f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
                f.flush()
                time.sleep(0.05)
                f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
                f.flush()
            break
    else:
        print("\nNo keyboard config was accepted by iOS.")
        print("iOS may require MFi certification for keyboard HID.")

    teardown()
