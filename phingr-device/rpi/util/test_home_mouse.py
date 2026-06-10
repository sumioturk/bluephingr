#!/usr/bin/env python3
"""test_home_mouse.py — Go home using mouse via AssistiveTouch.

Prerequisites:
    1. Enable AssistiveTouch on iOS:
       Settings > Accessibility > Touch > AssistiveTouch > ON
    2. Mouse gadget must be configured (run setup_gadget.sh)

The script clicks the AssistiveTouch floating button, then clicks
"Home" in the popup menu.

The AssistiveTouch button defaults to bottom-right. If you've moved
it, adjust ASSISTIVE_TOUCH_X/Y below.

Usage:
    sudo python3 rpi/util/test_home_mouse.py
"""

import os
import struct
import sys
import time

# AssistiveTouch button position (normalized 0-1)
# Default is bottom-right area on iPhone SE3
ASSISTIVE_TOUCH_X = 0.92
ASSISTIVE_TOUCH_Y = 0.72

# "Home" button position in the AssistiveTouch popup menu
# It's typically at the bottom-center of the menu
HOME_BUTTON_X = 0.50
HOME_BUTTON_Y = 0.55

# iPhone SE3 screen in points
SCREEN_W = 375
SCREEN_H = 667


def write_mouse(f, buttons, dx, dy):
    f.write(struct.pack("Bbbb", buttons, dx, dy, 0))
    f.flush()


def reset_to_origin(f):
    """Move cursor to top-left corner using 1px steps."""
    for _ in range(800):
        write_mouse(f, 0, -1, -1)
    time.sleep(0.1)


def move_to(f, x_norm, y_norm):
    """Move cursor to normalized position (0-1) from origin."""
    reset_to_origin(f)
    target_x = int(x_norm * SCREEN_W)
    target_y = int(y_norm * SCREEN_H)
    # Move in 1px steps
    for _ in range(target_x):
        write_mouse(f, 0, 1, 0)
    for _ in range(target_y):
        write_mouse(f, 0, 0, 1)
    time.sleep(0.1)


def click(f, duration=0.05):
    """Left click."""
    write_mouse(f, 1, 0, 0)
    time.sleep(duration)
    write_mouse(f, 0, 0, 0)
    time.sleep(0.1)


def go_home(f):
    """Click AssistiveTouch button, then click Home in the menu."""
    print(f"Moving to AssistiveTouch button ({ASSISTIVE_TOUCH_X}, {ASSISTIVE_TOUCH_Y}) ...")
    move_to(f, ASSISTIVE_TOUCH_X, ASSISTIVE_TOUCH_Y)
    print("Clicking AssistiveTouch ...")
    click(f)

    # Wait for menu to appear
    time.sleep(0.8)

    print(f"Moving to Home button ({HOME_BUTTON_X}, {HOME_BUTTON_Y}) ...")
    move_to(f, HOME_BUTTON_X, HOME_BUTTON_Y)
    print("Clicking Home ...")
    click(f)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_home_mouse.py")
        raise SystemExit(1)

    if not os.path.exists("/dev/hidg0"):
        print("/dev/hidg0 not found — run setup_gadget.sh first")
        raise SystemExit(1)

    print("Make sure AssistiveTouch is enabled:")
    print("  Settings > Accessibility > Touch > AssistiveTouch > ON")
    print()

    with open("/dev/hidg0", "wb") as f:
        go_home(f)

    print("Done")
