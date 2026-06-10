#!/usr/bin/env python3
"""test_scroll.py — Test mouse scroll wheel on iOS.

Run on the RPi as root. Assumes mouse gadget is already configured
(run setup_gadget.sh first).

Usage:
    sudo python3 rpi/util/test_scroll.py
    sudo python3 rpi/util/test_scroll.py up
    sudo python3 rpi/util/test_scroll.py down 10
"""

import struct
import sys
import time


def move_to_center(f):
    """Reset to top-left then move to center of screen (iPhone SE3)."""
    # Reset to top-left using small steps (avoid pointer acceleration)
    for _ in range(800):
        f.write(struct.pack("Bbbb", 0, -1, -1, 0))
        f.flush()
    time.sleep(0.1)
    # Move to center (375/2=187 right, 667/2=333 down)
    for _ in range(187):
        f.write(struct.pack("Bbbb", 0, 1, 0, 0))
        f.flush()
    for _ in range(333):
        f.write(struct.pack("Bbbb", 0, 0, 1, 0))
        f.flush()
    time.sleep(0.1)


def scroll(direction: str = "down", amount: int = 200, steps: int = 30):
    """Scroll by click-and-drag. iOS doesn't support scroll wheel.

    direction: "up" or "down"
    amount: drag distance in pixels
    steps: number of move reports (more = smoother)
    """
    dy_per_step = amount // steps
    if direction == "up":
        dy_per_step = -dy_per_step

    with open("/dev/hidg0", "wb") as f:
        move_to_center(f)

        # Press left button
        f.write(struct.pack("Bbbb", 1, 0, 0, 0))
        f.flush()
        time.sleep(0.05)

        # Drag
        for _ in range(steps):
            f.write(struct.pack("Bbbb", 1, 0, dy_per_step, 0))
            f.flush()
            time.sleep(0.015)

        # Release
        f.write(struct.pack("Bbbb", 0, 0, 0, 0))
        f.flush()


if __name__ == "__main__":
    import os
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_scroll.py [up|down] [pixels]")
        raise SystemExit(1)

    direction_arg = sys.argv[1] if len(sys.argv) > 1 else "down"
    amount = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    print(f"Scrolling {direction_arg} ({amount}px) ...")
    scroll(direction_arg, amount)
    print("Done")
