#!/usr/bin/env python3
"""test_gadget_swap.py — Test swapping between mouse and keyboard gadgets.

Since iOS doesn't work reliably with composite (mouse+keyboard) gadget,
this tests creating them as separate gadgets and swapping between them.

Usage:
    sudo python3 rpi/util/test_gadget_swap.py
"""

import os
import struct
import sys
import threading
import time

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
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7,
    0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x75, 0x08, 0x95, 0x01, 0x81, 0x01,
    # LED output
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05,
    0x75, 0x01, 0x95, 0x05, 0x91, 0x02,
    0x75, 0x03, 0x95, 0x01, 0x91, 0x01,
    # Keys
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


def setup_gadget(desc: bytes, protocol: str, report_length: int, product: str):
    os.system("modprobe libcomposite")
    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def w(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    w("idVendor", "0x1d6b")
    w("idProduct", "0x0104")
    w("bcdDevice", "0x0100")
    w("bcdUSB", "0x0200")
    w("strings/0x409/serialnumber", "phingr001")
    w("strings/0x409/manufacturer", "phingr")
    w("strings/0x409/product", product)
    w("functions/hid.usb0/protocol", protocol)
    w("functions/hid.usb0/subclass", "1")
    w("functions/hid.usb0/report_length", str(report_length))
    w("functions/hid.usb0/report_desc", desc)
    w("configs/c.1/strings/0x409/configuration", "Config")
    w("configs/c.1/MaxPower", "250")

    os.symlink(f"{GADGET_DIR}/functions/hid.usb0",
               f"{GADGET_DIR}/configs/c.1/hid.usb0")

    udc = os.listdir("/sys/class/udc")[0]
    w("UDC", udc)


def switch_to_mouse():
    print("Switching to mouse gadget ...")
    teardown()
    setup_gadget(MOUSE_DESC, "2", 4, "phingr Mouse")
    time.sleep(1)
    print("  Mouse ready on /dev/hidg0")


def switch_to_keyboard():
    print("Switching to keyboard gadget ...")
    teardown()
    setup_gadget(KEYBOARD_DESC, "1", 8, "phingr Keyboard")
    time.sleep(1)
    # Start LED reader
    def led_reader():
        try:
            fd = os.open("/dev/hidg0", os.O_RDONLY | os.O_NONBLOCK)
            while True:
                try:
                    os.read(fd, 1)
                except BlockingIOError:
                    time.sleep(0.01)
                except OSError:
                    break
        except Exception:
            pass
    threading.Thread(target=led_reader, daemon=True).start()
    time.sleep(0.5)
    print("  Keyboard ready on /dev/hidg0")


def test_mouse():
    print("  Moving cursor ...")
    with open("/dev/hidg0", "wb", buffering=0) as f:
        for _ in range(50):
            f.write(struct.pack("Bbbb", 0, 2, 0, 0))
            f.flush()
            time.sleep(0.02)
    print("  Mouse: OK")


def test_keyboard():
    print("  Pressing Cmd+H (home) ...")
    with open("/dev/hidg0", "wb", buffering=0) as f:
        f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
        f.flush()
        time.sleep(0.05)
        f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
        f.flush()
    print("  Keyboard: OK")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root")
        sys.exit(1)

    # Test 1: Mouse
    switch_to_mouse()
    test_mouse()
    time.sleep(1)

    # Test 2: Swap to keyboard
    switch_to_keyboard()
    test_keyboard()
    time.sleep(1)

    # Test 3: Swap back to mouse
    switch_to_mouse()
    test_mouse()

    print("\n=== Gadget swap works! ===")
    print("Mouse and keyboard can't coexist in composite mode on iOS,")
    print("but swapping between them works.")
