#!/usr/bin/env python3
"""test_keyboard_composite.py — Test keyboard in composite gadget (mouse+kbd).

Tests if keyboard works when it's hidg1 alongside mouse on hidg0,
using the same separate-fd pattern as test_keyboard_led.py.

Run with the composite gadget active (setup_gadget.sh):
    sudo python3 rpi/util/test_keyboard_composite.py
"""

import os
import struct
import sys
import threading
import time

KBD_DEVICE = "/dev/hidg1"


def led_reader():
    fd = os.open(KBD_DEVICE, os.O_RDONLY | os.O_NONBLOCK)
    print(f"LED reader started (fd={fd})")
    while True:
        try:
            data = os.read(fd, 1)
            if data:
                print(f"  [LED] {data[0]:08b}")
        except BlockingIOError:
            time.sleep(0.01)
        except OSError:
            time.sleep(0.1)


def test():
    print(f"Opening {KBD_DEVICE} for writing ...")
    f = open(KBD_DEVICE, "wb", buffering=0)
    print("Write fd opened")

    time.sleep(0.5)

    # Press 'a'
    print("Pressing 'a' ...")
    f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
    f.flush()
    print("  key down OK")

    time.sleep(0.05)

    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    print("  key up OK")

    time.sleep(0.5)

    # Cmd+H (home)
    print("Pressing Cmd+H ...")
    f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
    f.flush()
    print("  key down OK")

    time.sleep(0.05)

    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    print("  key up OK")

    f.close()
    print("\nAll done!")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_keyboard_composite.py")
        sys.exit(1)

    if not os.path.exists(KBD_DEVICE):
        print(f"{KBD_DEVICE} not found — run setup_gadget.sh first")
        sys.exit(1)

    # Start LED reader thread
    threading.Thread(target=led_reader, daemon=True).start()

    test()
