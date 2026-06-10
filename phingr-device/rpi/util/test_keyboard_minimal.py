#!/usr/bin/env python3
"""test_keyboard_minimal.py — Minimal keyboard test matching test_composite_proper pattern.

Tests keyboard writes using the exact same code pattern as
test_composite_proper.py (which works), but without creating
the gadget. Run with the composite gadget already active.

Usage:
    sudo python3 rpi/util/test_keyboard_minimal.py
"""

import os
import struct
import sys
import threading
import time

KBD = "/dev/hidg1"


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root")
        sys.exit(1)

    if not os.path.exists(KBD):
        print(f"{KBD} not found")
        sys.exit(1)

    # LED reader — exact same as test_composite_proper.py
    def led_reader():
        fd = os.open(KBD, os.O_RDONLY | os.O_NONBLOCK)
        print(f"LED reader fd={fd}")
        while True:
            try:
                os.read(fd, 1)
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                break

    threading.Thread(target=led_reader, daemon=True).start()
    time.sleep(0.3)

    # Write 'a'
    print("Writing key 'a' ...")
    with open(KBD, "wb", buffering=0) as f:
        f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
        f.flush()
        time.sleep(0.05)
        f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
        f.flush()
    print("'a' done")

    time.sleep(0.3)

    # Write Cmd+H
    print("Writing Cmd+H (home) ...")
    with open(KBD, "wb", buffering=0) as f:
        f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
        f.flush()
        time.sleep(0.05)
        f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
        f.flush()
    print("Cmd+H done")
