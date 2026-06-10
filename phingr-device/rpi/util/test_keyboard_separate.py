#!/usr/bin/env python3
"""test_keyboard_separate.py — Test keyboard as sole HID device.

Tears down everything, sets up ONLY a keyboard (no mouse),
tests if iOS accepts it alone.

Usage:
    sudo python3 rpi/util/test_keyboard_separate.py
"""

import os
import signal
import struct
import sys
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

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


def setup():
    os.system("modprobe libcomposite")
    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def w(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    w("idVendor", "0x05ac")   # Apple
    w("idProduct", "0x024f")  # Apple Keyboard
    w("bcdDevice", "0x0100")
    w("bcdUSB", "0x0200")
    w("strings/0x409/serialnumber", "phingr001")
    w("strings/0x409/manufacturer", "Apple Inc.")
    w("strings/0x409/product", "Apple Keyboard")
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
    print("Keyboard-only gadget configured (Apple VID)")


def test():
    def timeout_handler(signum, frame):
        print("BLOCKED — keyboard rejected")
        sys.exit(1)

    signal.signal(signal.SIGALRM, timeout_handler)

    print("Waiting 2s for mobile to enumerate ...")
    time.sleep(2)

    print("Testing 'a' key ...")
    signal.alarm(3)
    f = open("/dev/hidg0", "wb")
    f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(0.05)
    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    signal.alarm(0)
    f.close()
    print("SUCCESS — 'a' sent!")

    print("Testing Cmd+H (home) ...")
    time.sleep(0.5)
    signal.alarm(3)
    f = open("/dev/hidg0", "wb")
    f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(0.05)
    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    signal.alarm(0)
    f.close()
    print("Cmd+H sent")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root")
        raise SystemExit(1)

    teardown()
    setup()
    test()
