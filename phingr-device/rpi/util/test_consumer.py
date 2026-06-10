#!/usr/bin/env python3
"""test_consumer.py — Test USB HID Consumer Control on iOS.

Consumer Control devices send media keys, system keys, and
application-level commands. iOS may accept these where it
rejects a standard keyboard.

Usage:
    sudo python3 rpi/util/test_consumer.py
"""

import os
import struct
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

# Consumer Control HID descriptor
# Report format (2 bytes): usage code (16-bit LE)
CONSUMER_DESC = bytes([
    0x05, 0x0C,        # Usage Page (Consumer)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x03,  #   Logical Maximum (1023)
    0x19, 0x00,        #   Usage Minimum (0)
    0x2A, 0xFF, 0x03,  #   Usage Maximum (1023)
    0x75, 0x10,        #   Report Size (16)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x00,        #   Input (Data, Array)
    0xC0,              # End Collection
])

# Consumer Control usage codes
CONSUMER_KEYS = {
    "home":         0x0223,  # AC Home
    "back":         0x0224,  # AC Back
    "search":       0x0221,  # AC Search
    "play_pause":   0x00CD,  # Play/Pause
    "next_track":   0x00B5,  # Scan Next Track
    "prev_track":   0x00B6,  # Scan Previous Track
    "vol_up":       0x00E9,  # Volume Up
    "vol_down":     0x00EA,  # Volume Down
    "mute":         0x00E2,  # Mute
    "brightness_up":   0x006F,  # Brightness Up
    "brightness_down": 0x0070,  # Brightness Down
    "lock":         0x019E,  # Lock (System Sleep)
}

REPORT_LENGTH = 2


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
    w("strings/0x409/product", "phingr Consumer Control")
    w("functions/hid.usb0/protocol", "0")
    w("functions/hid.usb0/subclass", "0")
    w("functions/hid.usb0/report_length", str(REPORT_LENGTH))
    w("functions/hid.usb0/report_desc", CONSUMER_DESC)
    w("configs/c.1/strings/0x409/configuration", "Config")
    w("configs/c.1/MaxPower", "250")

    os.symlink(
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/configs/c.1/hid.usb0",
    )
    udc = os.listdir("/sys/class/udc")[0]
    w("UDC", udc)
    print(f"Consumer Control gadget configured (UDC: {udc})")


def press_consumer_key(f, usage_code, duration=0.1):
    """Send a consumer control key press and release."""
    # Key down
    f.write(struct.pack("<H", usage_code))
    f.flush()
    time.sleep(duration)
    # Key up (send 0)
    f.write(struct.pack("<H", 0))
    f.flush()
    time.sleep(0.05)


def test():
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("blocked")

    signal.signal(signal.SIGALRM, timeout_handler)

    print("Waiting 2s for mobile to enumerate ...")
    time.sleep(2)

    print("Testing volume up ...")
    signal.alarm(3)
    try:
        with open("/dev/hidg0", "wb") as f:
            press_consumer_key(f, CONSUMER_KEYS["vol_up"])
        signal.alarm(0)
        print("SUCCESS — Consumer Control accepted!")
        print()

        # Try more keys
        with open("/dev/hidg0", "wb") as f:
            for name in ["vol_down", "home", "play_pause"]:
                code = CONSUMER_KEYS[name]
                print(f"Pressing {name} (0x{code:04X}) ...")
                press_consumer_key(f, code)
                time.sleep(0.5)

        print("\nDone!")
        print(f"Available keys: {', '.join(CONSUMER_KEYS.keys())}")

    except TimeoutError:
        signal.alarm(0)
        print("BLOCKED — iOS rejected Consumer Control too")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_consumer.py")
        raise SystemExit(1)

    teardown()
    setup()
    test()
    teardown()
