#!/usr/bin/env python3
"""test_touch.py — Test USB HID touch digitizer with iOS.

Run on the RPi as root. Configures a touch digitizer gadget and
sends a tap at the center of the screen.

Usage:
    sudo python3 rpi/util/test_touch.py
"""

import os
import struct
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

# iOS-compatible single-finger touch screen descriptor.
# Based on the Microsoft digitizer descriptor reference with
# fields iOS requires: In Range, Contact ID, Contact Count,
# Contact Count Maximum, Physical dimensions with Unit.
TOUCH_DESC = bytes([
    0x05, 0x0D,        # Usage Page (Digitizers)
    0x09, 0x04,        # Usage (Touch Screen)
    0xA1, 0x01,        # Collection (Application)

    # Contact Count Maximum (Feature)
    0x09, 0x55,        #   Usage (Contact Count Maximum)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x01,        #   Report Count (1)
    0xB1, 0x02,        #   Feature (Data, Variable, Absolute)

    # Finger collection
    0x09, 0x22,        #   Usage (Finger)
    0xA1, 0x02,        #   Collection (Logical)

    # Tip Switch
    0x09, 0x42,        #     Usage (Tip Switch)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x75, 0x01,        #     Report Size (1)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)

    # In Range
    0x09, 0x32,        #     Usage (In Range)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)

    # 6 bits padding
    0x75, 0x06,        #     Report Size (6)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x01,        #     Input (Constant)

    # Contact ID
    0x09, 0x51,        #     Usage (Contact Identifier)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x01,        #     Report Count (1)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)

    # X
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x15, 0x00,        #     Logical Minimum (0)
    0x26, 0xFF, 0x0F,  #     Logical Maximum (4095)
    0x35, 0x00,        #     Physical Minimum (0)
    0x46, 0x00, 0x04,  #     Physical Maximum (1024)
    0x55, 0x0E,        #     Unit Exponent (-2)
    0x65, 0x11,        #     Unit (cm)
    0x75, 0x10,        #     Report Size (16)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)

    # Y
    0x09, 0x31,        #     Usage (Y)
    0x15, 0x00,        #     Logical Minimum (0)
    0x26, 0xFF, 0x0F,  #     Logical Maximum (4095)
    0x35, 0x00,        #     Physical Minimum (0)
    0x46, 0x00, 0x07,  #     Physical Maximum (1792)
    0x81, 0x02,        #     Input (Data, Variable, Absolute)

    0xC0,              #   End Collection (Finger)

    # Contact Count (Input)
    0x05, 0x0D,        #   Usage Page (Digitizers)
    0x09, 0x54,        #   Usage (Contact Count)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x01,        #   Report Count (1)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)

    0xC0,              # End Collection (Application)
])

# Report format (7 bytes):
#   byte 0:    Tip Switch (bit 0) | In Range (bit 1) | padding (6 bits)
#   byte 1:    Contact ID
#   bytes 2-3: X (16-bit LE, 0-4095)
#   bytes 4-5: Y (16-bit LE, 0-4095)
#   byte 6:    Contact Count
REPORT_LENGTH = 7


def teardown_gadget():
    if not os.path.isdir(GADGET_DIR):
        return
    try:
        with open(f"{GADGET_DIR}/UDC", "w") as f:
            f.write("")
    except OSError:
        pass
    for path in [f"{GADGET_DIR}/configs/c.1/hid.usb0"]:
        try:
            os.remove(path)
        except OSError:
            pass
    for path in [
        f"{GADGET_DIR}/configs/c.1/strings/0x409",
        f"{GADGET_DIR}/configs/c.1",
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/strings/0x409",
        GADGET_DIR,
    ]:
        try:
            os.rmdir(path)
        except OSError:
            pass


def setup_touch_gadget():
    os.system("modprobe libcomposite")

    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def write(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    write("idVendor", "0x1d6b")
    write("idProduct", "0x0104")
    write("bcdDevice", "0x0100")
    write("bcdUSB", "0x0200")
    write("strings/0x409/serialnumber", "phingr001")
    write("strings/0x409/manufacturer", "phingr")
    write("strings/0x409/product", "phingr Touch")
    write("functions/hid.usb0/protocol", "0")
    write("functions/hid.usb0/subclass", "0")
    write("functions/hid.usb0/report_length", str(REPORT_LENGTH))
    write("functions/hid.usb0/report_desc", TOUCH_DESC)
    write("configs/c.1/strings/0x409/configuration", "Config")
    write("configs/c.1/MaxPower", "250")

    os.symlink(
        f"{GADGET_DIR}/functions/hid.usb0",
        f"{GADGET_DIR}/configs/c.1/hid.usb0",
    )

    udc = os.listdir("/sys/class/udc")[0]
    write("UDC", udc)
    print(f"Touch gadget configured (UDC: {udc})")


def build_report(tip: bool, x_norm: float, y_norm: float,
                 contact_count: int = 1) -> bytes:
    """Build a 7-byte touch report.

    byte 0: bit0=tip, bit1=in_range, bits2-7=padding
    byte 1: contact ID
    bytes 2-3: X (LE)
    bytes 4-5: Y (LE)
    byte 6: contact count
    """
    flags = 0
    if tip:
        flags = 0x03  # tip=1, in_range=1
    x = int(max(0.0, min(1.0, x_norm)) * 4095)
    y = int(max(0.0, min(1.0, y_norm)) * 4095)
    cc = contact_count if tip else 0
    return struct.pack("<BBHHB", flags, 1, x, y, cc)


def test_tap():
    print("Waiting 1s for mobile to enumerate ...")
    time.sleep(1)

    print("Tapping center of screen ...")
    with open("/dev/hidg0", "wb") as f:
        # Touch down
        f.write(build_report(True, 0.5, 0.5))
        f.flush()
        time.sleep(0.05)
        # Touch up
        f.write(build_report(False, 0.5, 0.5, 0))
        f.flush()

    print("Done — you should have seen a tap on iOS.")


def test_swipe_down():
    print("Swiping down ...")
    with open("/dev/hidg0", "wb") as f:
        for i in range(20):
            t = i / 19
            y = 0.3 + 0.4 * t
            f.write(build_report(True, 0.5, y))
            f.flush()
            time.sleep(0.015)
        f.write(build_report(False, 0.5, 0.7, 0))
        f.flush()
    print("Done — content should have scrolled.")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root: sudo python3 test_touch.py")
        raise SystemExit(1)

    teardown_gadget()
    setup_touch_gadget()
    test_tap()
    time.sleep(0.5)
    test_swipe_down()
