#!/usr/bin/env python3
"""test_keyboard_write.py — Raw write test to /dev/hidg1.

Tests if iOS accepts keyboard HID reports. Open Notes or a text
field on iOS before running. If it prints "keyboard works", the
keyboard is accepted. If it hangs, iOS is rejecting it.

Prerequisites:
    - setup_gadget.sh run (both mouse + keyboard)
    - iOS: Settings > Accessibility > Keyboards > Full Keyboard Access > ON

Usage:
    sudo python3 rpi/util/test_keyboard_write.py
"""

import os
import signal
import struct
import sys
import time

KBD_DEVICE = "/dev/hidg1"


def timeout_handler(signum, frame):
    print("BLOCKED — iOS rejected the keyboard")
    print("Check:")
    print("  1. Full Keyboard Access enabled in iOS Settings")
    print("  2. /dev/hidg1 exists")
    print("  3. iPhone is unlocked")
    sys.exit(1)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_keyboard_write.py")
        raise SystemExit(1)

    if not os.path.exists(KBD_DEVICE):
        print(f"{KBD_DEVICE} not found — run setup_gadget.sh first")
        raise SystemExit(1)

    print(f"Testing write to {KBD_DEVICE} ...")
    print("(will timeout in 3s if blocked)")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(3)

    f = open(KBD_DEVICE, "wb")

    # Press 'a'
    f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
    f.flush()
    print("write OK — 'a' pressed")

    time.sleep(0.05)

    # Release
    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    print("release OK")

    signal.alarm(0)
    f.close()

    print()
    print("Keyboard works! 'a' should have appeared on iOS.")
    print()
    print("Now testing Cmd+H (home) ...")
    time.sleep(0.5)

    signal.alarm(3)
    f = open(KBD_DEVICE, "wb")
    # Cmd+H
    f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(0.05)
    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    signal.alarm(0)
    f.close()
    print("Cmd+H sent — should have gone to home screen")
