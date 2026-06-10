#!/usr/bin/env python3
"""test_keyboard.py — Test USB HID keyboard on iOS.

Run on the RPi as root. Assumes gadget is configured with keyboard
on /dev/hidg1 (run setup_gadget.sh first).

Usage:
    sudo python3 rpi/util/test_keyboard.py home
    sudo python3 rpi/util/test_keyboard.py app_switch
    sudo python3 rpi/util/test_keyboard.py spotlight
    sudo python3 rpi/util/test_keyboard.py screenshot
    sudo python3 rpi/util/test_keyboard.py type "hello world"
"""

import os
import struct
import sys
import time

KBD_DEVICE = "/dev/hidg1"

MODIFIERS = {
    "ctrl": 0x01, "shift": 0x02, "alt": 0x04, "option": 0x04,
    "cmd": 0x08, "command": 0x08,
}

KEYCODES = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22, "6": 0x23,
    "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "enter": 0x28, "escape": 0x29, "backspace": 0x2A, "tab": 0x2B,
    "space": 0x2C,
}

HOTKEYS = {
    "home":       (["cmd"], "h"),
    "app_switch": (["cmd"], "tab"),
    "spotlight":  (["cmd"], "space"),
    "screenshot": (["cmd", "shift"], "3"),
    "close_app":  (["cmd"], "q"),
}


def press_key(f, key, modifiers=None, duration=0.05):
    mod_mask = 0
    for m in (modifiers or []):
        mod_mask |= MODIFIERS.get(m, 0)
    keycode = KEYCODES.get(key, 0)
    if keycode == 0:
        print(f"Unknown key: {key}")
        return
    # Key down
    f.write(struct.pack("BBBBBBBB", mod_mask, 0, keycode, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(duration)
    # Key up
    f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
    f.flush()
    time.sleep(0.03)


def type_text(f, text):
    for ch in text:
        if ch == " ":
            press_key(f, "space")
        elif ch == "\n":
            press_key(f, "enter")
        elif ch.isupper():
            press_key(f, ch.lower(), ["shift"])
        else:
            press_key(f, ch)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_keyboard.py <command>")
        raise SystemExit(1)

    if not os.path.exists(KBD_DEVICE):
        print(f"{KBD_DEVICE} not found — run setup_gadget.sh first")
        raise SystemExit(1)

    command = sys.argv[1] if len(sys.argv) > 1 else "home"

    with open(KBD_DEVICE, "wb") as f:
        if command == "type":
            text = sys.argv[2] if len(sys.argv) > 2 else "hello"
            print(f"Typing: {text}")
            type_text(f, text)
        elif command in HOTKEYS:
            mods, key = HOTKEYS[command]
            print(f"Pressing {'+'.join(mods)}+{key} ({command})")
            press_key(f, key, mods)
        else:
            print(f"Unknown command: {command}")
            print(f"Available: {', '.join(HOTKEYS)}, type")
            raise SystemExit(1)

    print("Done")
