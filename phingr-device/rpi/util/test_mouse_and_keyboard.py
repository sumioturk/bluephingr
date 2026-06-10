#!/usr/bin/env python3
"""test_mouse_and_keyboard.py — Test mouse and keyboard together.

Tests various sequences to find what works and what blocks
in the composite gadget.

Usage:
    sudo python3 rpi/util/test_mouse_and_keyboard.py
"""

import os
import signal
import struct
import sys
import threading
import time

MOUSE_DEV = "/dev/hidg0"
KBD_DEV = "/dev/hidg1"


def timeout_handler(signum, frame):
    print("  BLOCKED (3s timeout)")
    # Don't exit — continue to next test


def led_reader():
    try:
        fd = os.open(KBD_DEV, os.O_RDONLY | os.O_NONBLOCK)
        while True:
            try:
                os.read(fd, 1)
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                time.sleep(0.1)
    except Exception:
        pass


def test_mouse_only():
    print("\n=== Test 1: Mouse only ===")
    signal.alarm(3)
    try:
        with open(MOUSE_DEV, "wb", buffering=0) as f:
            f.write(struct.pack("Bbbb", 0, 50, 0, 0))
            f.flush()
            print("  Mouse move: OK")
            time.sleep(0.05)
            f.write(struct.pack("Bbbb", 1, 0, 0, 0))
            f.flush()
            time.sleep(0.05)
            f.write(struct.pack("Bbbb", 0, 0, 0, 0))
            f.flush()
            print("  Mouse click: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  FAILED: {e}")


def test_keyboard_only():
    print("\n=== Test 2: Keyboard only ===")
    signal.alarm(3)
    try:
        with open(KBD_DEV, "wb", buffering=0) as f:
            f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
            f.flush()
            print("  Key down 'a': OK")
            time.sleep(0.05)
            f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            f.flush()
            print("  Key up: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  FAILED: {e}")


def test_mouse_then_keyboard():
    print("\n=== Test 3: Mouse first, then keyboard ===")
    signal.alarm(3)
    try:
        with open(MOUSE_DEV, "wb", buffering=0) as mf:
            mf.write(struct.pack("Bbbb", 0, 30, 0, 0))
            mf.flush()
            print("  Mouse move: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  Mouse FAILED: {e}")
        return

    time.sleep(0.1)

    signal.alarm(3)
    try:
        with open(KBD_DEV, "wb", buffering=0) as kf:
            kf.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
            kf.flush()
            print("  Key down: OK")
            time.sleep(0.05)
            kf.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            kf.flush()
            print("  Key up: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  Keyboard FAILED: {e}")


def test_keyboard_then_mouse():
    print("\n=== Test 4: Keyboard first, then mouse ===")
    signal.alarm(3)
    try:
        with open(KBD_DEV, "wb", buffering=0) as kf:
            kf.write(struct.pack("BBBBBBBB", 0, 0, 0x05, 0, 0, 0, 0, 0))
            kf.flush()
            print("  Key down 'b': OK")
            time.sleep(0.05)
            kf.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            kf.flush()
            print("  Key up: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  Keyboard FAILED: {e}")
        return

    time.sleep(0.1)

    signal.alarm(3)
    try:
        with open(MOUSE_DEV, "wb", buffering=0) as mf:
            mf.write(struct.pack("Bbbb", 0, -30, 0, 0))
            mf.flush()
            print("  Mouse move: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  Mouse FAILED: {e}")


def test_both_open():
    print("\n=== Test 5: Both fds open simultaneously ===")
    signal.alarm(3)
    try:
        mf = open(MOUSE_DEV, "wb", buffering=0)
        kf = open(KBD_DEV, "wb", buffering=0)
        print("  Both fds opened")

        mf.write(struct.pack("Bbbb", 0, 20, 0, 0))
        mf.flush()
        print("  Mouse move: OK")

        kf.write(struct.pack("BBBBBBBB", 0, 0, 0x06, 0, 0, 0, 0, 0))
        kf.flush()
        print("  Key down 'c': OK")

        time.sleep(0.05)
        kf.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
        kf.flush()
        print("  Key up: OK")

        mf.close()
        kf.close()
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  FAILED: {e}")


def test_cmd_h():
    print("\n=== Test 6: Cmd+H (home) ===")
    signal.alarm(3)
    try:
        with open(KBD_DEV, "wb", buffering=0) as kf:
            kf.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
            kf.flush()
            print("  Cmd+H down: OK")
            time.sleep(0.05)
            kf.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            kf.flush()
            print("  Cmd+H up: OK")
        signal.alarm(0)
    except Exception as e:
        signal.alarm(0)
        print(f"  FAILED: {e}")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root")
        sys.exit(1)

    for dev in [MOUSE_DEV, KBD_DEV]:
        if not os.path.exists(dev):
            print(f"{dev} not found")
            sys.exit(1)

    signal.signal(signal.SIGALRM, timeout_handler)

    # Start LED reader
    threading.Thread(target=led_reader, daemon=True).start()
    time.sleep(0.3)
    print("LED reader started")

    test_mouse_only()
    time.sleep(0.5)

    test_keyboard_only()
    time.sleep(0.5)

    test_mouse_then_keyboard()
    time.sleep(0.5)

    test_keyboard_then_mouse()
    time.sleep(0.5)

    test_both_open()
    time.sleep(0.5)

    test_cmd_h()

    print("\n=== All tests complete ===")
