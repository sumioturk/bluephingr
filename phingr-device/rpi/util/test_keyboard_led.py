#!/usr/bin/env python3
"""test_keyboard_led.py — Test keyboard with LED output report + reader thread.

iOS sends LED status (Caps Lock etc.) to the keyboard device. If these
aren't read, writes block. This test adds an LED output report to the
descriptor and runs a reader thread to consume LED updates.

Usage:
    sudo python3 rpi/util/test_keyboard_led.py
"""

import os
import signal
import struct
import sys
import threading
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

# Boot keyboard descriptor WITH LED output report
KEYBOARD_DESC = bytes([
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)

    # Modifier keys input (8 bits)
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

    # LED output report (5 bits + 3 padding)
    0x05, 0x08,        #   Usage Page (LEDs)
    0x19, 0x01,        #   Usage Minimum (Num Lock)
    0x29, 0x05,        #   Usage Maximum (Kana)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x05,        #   Report Count (5)
    0x91, 0x02,        #   Output (Data, Variable, Absolute)
    0x75, 0x03,        #   Report Size (3)
    0x95, 0x01,        #   Report Count (1)
    0x91, 0x01,        #   Output (Constant) padding

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


def setup_keyboard_only():
    """Set up keyboard as sole HID device with LED support."""
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
    w("functions/hid.usb0/protocol", "1")
    w("functions/hid.usb0/subclass", "1")
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
    print("Keyboard gadget configured (with LED output report)")


def led_reader(stop_event):
    """Read LED status reports from iOS in background."""
    try:
        fd = os.open("/dev/hidg0", os.O_RDONLY | os.O_NONBLOCK)
        while not stop_event.is_set():
            try:
                data = os.read(fd, 1)
                if data:
                    leds = data[0]
                    parts = []
                    if leds & 0x01: parts.append("NumLock")
                    if leds & 0x02: parts.append("CapsLock")
                    if leds & 0x04: parts.append("ScrollLock")
                    print(f"  [LED] {' '.join(parts) if parts else 'all off'}")
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                break
        os.close(fd)
    except Exception as e:
        print(f"  [LED reader] {e}")


def test():
    stop_event = threading.Event()
    reader = threading.Thread(target=led_reader, args=(stop_event,), daemon=True)
    reader.start()
    print("LED reader thread started")

    def timeout_handler(signum, frame):
        stop_event.set()
        print("BLOCKED — keyboard still rejected")
        print("Even with LED output report, iOS won't accept gadget keyboard")
        sys.exit(1)

    signal.signal(signal.SIGALRM, timeout_handler)

    print("Waiting 2s for mobile to enumerate ...")
    time.sleep(2)

    print("Pressing 'a' ...")
    signal.alarm(5)
    with open("/dev/hidg0", "wb") as f:
        # Key down
        f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
        f.flush()
        print("  key down OK")
        time.sleep(0.05)
        # Key up
        f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
        f.flush()
        print("  key up OK")
    signal.alarm(0)

    print("\nSUCCESS — keyboard accepted!")
    print("Testing Cmd+H (home) ...")
    time.sleep(0.5)

    with open("/dev/hidg0", "wb") as f:
        f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
        f.flush()
        time.sleep(0.05)
        f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
        f.flush()
    print("Cmd+H sent")

    stop_event.set()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_keyboard_led.py")
        raise SystemExit(1)

    teardown()
    setup_keyboard_only()
    test()
