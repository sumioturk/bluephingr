#!/usr/bin/env python3
"""test_keyboard_only.py — Test keyboard gadget in isolation (no mouse).

Tears down any existing gadget, creates a keyboard-only gadget,
and types 'a'. Open Notes or a text field on iOS before running.

Usage:
    sudo python3 rpi/util/test_keyboard_only.py
"""

import os
import struct
import sys
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

KEYBOARD_DESC = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    # Modifier keys (8 bits)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,        #   Usage Minimum (Left Control)
    0x29, 0xE7,        #   Usage Maximum (Right GUI)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)
    # Reserved byte
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x01,        #   Input (Constant)
    # Key codes (6 bytes)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0x00,        #   Usage Minimum (0)
    0x29, 0x65,        #   Usage Maximum (101)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x65,        #   Logical Maximum (101)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x06,        #   Report Count (6)
    0x81, 0x00,        #   Input (Data, Array)
    0xC0,              # End Collection
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

    w("idVendor", "0x1d6b")
    w("idProduct", "0x0104")
    w("bcdDevice", "0x0100")
    w("bcdUSB", "0x0200")
    w("strings/0x409/serialnumber", "phingr001")
    w("strings/0x409/manufacturer", "phingr")
    w("strings/0x409/product", "phingr Keyboard")
    w("functions/hid.usb0/protocol", "1")   # keyboard
    w("functions/hid.usb0/subclass", "1")   # boot interface
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
    print(f"Keyboard gadget configured (UDC: {udc})")


def press_key(f, keycode, mod_mask=0, duration=0.05):
    # Key down
    f.write(struct.pack("BBBBBBBB", mod_mask, 0, keycode, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(duration)
    # Key up
    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(0.03)


def test():
    print("Waiting 2s for mobile to enumerate ...")
    time.sleep(2)

    with open("/dev/hidg0", "wb") as f:
        # Type 'a'
        print("Pressing 'a' ...")
        press_key(f, 0x04)

        # Type 'b'
        print("Pressing 'b' ...")
        press_key(f, 0x05)

        # Press Cmd+H (home)
        print("Pressing Cmd+H (home) ...")
        press_key(f, 0x0B, mod_mask=0x08)

    print("Done — 'ab' should have appeared, then went to home screen.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_keyboard_only.py")
        raise SystemExit(1)

    teardown()
    setup()
    test()
