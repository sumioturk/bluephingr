#!/usr/bin/env python3
"""test_composite_proper.py — Test proper composite USB device descriptors.

Tries multiple composite configurations to find one iOS accepts:

1. USB 2.1 + misc device class (standard composite)
2. Keyboard with non-boot protocol
3. Different function ordering (keyboard first)

Usage:
    sudo python3 rpi/util/test_composite_proper.py
"""

import os
import signal
import struct
import sys
import threading
import time

GADGET_DIR = "/sys/kernel/config/usb_gadget/phingr"

MOUSE_DESC = bytes([
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x09, 0x01, 0xA1, 0x00,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x03, 0x15, 0x00, 0x25, 0x01,
    0x95, 0x03, 0x75, 0x01, 0x81, 0x02, 0x95, 0x01, 0x75, 0x05,
    0x81, 0x01, 0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x15, 0x81,
    0x25, 0x7F, 0x75, 0x08, 0x95, 0x02, 0x81, 0x06, 0x09, 0x38,
    0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x81, 0x06,
    0xC0, 0xC0,
])

KEYBOARD_DESC_WITH_LED = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7,
    0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,
    0x75, 0x08, 0x95, 0x01, 0x81, 0x01,
    # LED output
    0x05, 0x08, 0x19, 0x01, 0x29, 0x05,
    0x75, 0x01, 0x95, 0x05, 0x91, 0x02,
    0x75, 0x03, 0x95, 0x01, 0x91, 0x01,
    # Keys
    0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
    0x15, 0x00, 0x25, 0x65, 0x75, 0x08, 0x95, 0x06, 0x81, 0x00,
    0xC0,
])


def teardown():
    # Unbind all gadgets
    for udc_file in [f for f in
                     [f"{GADGET_DIR}/UDC"] +
                     list((p + "/UDC") for p in
                          [f"/sys/kernel/config/usb_gadget/{d}"
                           for d in os.listdir("/sys/kernel/config/usb_gadget/")]
                          if os.path.isdir(p.replace("/UDC", "")))
                     if os.path.exists(f)]:
        try:
            with open(udc_file, "w") as f:
                f.write("")
        except OSError:
            pass

    if not os.path.isdir(GADGET_DIR):
        return
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


def setup_composite(
    bcd_usb="0x0200",
    device_class="0x00",
    device_subclass="0x00",
    device_protocol="0x00",
    mouse_protocol="2",
    mouse_subclass="1",
    kbd_protocol="1",
    kbd_subclass="1",
    mouse_first=True,
    name="test",
):
    os.system("modprobe libcomposite")
    os.makedirs(f"{GADGET_DIR}/strings/0x409", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb0", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/functions/hid.usb1", exist_ok=True)
    os.makedirs(f"{GADGET_DIR}/configs/c.1/strings/0x409", exist_ok=True)

    def w(path, val):
        mode = "wb" if isinstance(val, bytes) else "w"
        with open(f"{GADGET_DIR}/{path}", mode) as f:
            f.write(val)

    w("idVendor", "0x1d6b")
    w("idProduct", "0x0104")
    w("bcdDevice", "0x0100")
    w("bcdUSB", bcd_usb)
    w("bDeviceClass", device_class)
    w("bDeviceSubClass", device_subclass)
    w("bDeviceProtocol", device_protocol)
    w("strings/0x409/serialnumber", "phingr001")
    w("strings/0x409/manufacturer", "phingr")
    w("strings/0x409/product", f"phingr {name}")

    # Mouse function
    mouse_fn = "hid.usb0" if mouse_first else "hid.usb1"
    w(f"functions/{mouse_fn}/protocol", mouse_protocol)
    w(f"functions/{mouse_fn}/subclass", mouse_subclass)
    w(f"functions/{mouse_fn}/report_length", "4")
    w(f"functions/{mouse_fn}/report_desc", MOUSE_DESC)

    # Keyboard function
    kbd_fn = "hid.usb1" if mouse_first else "hid.usb0"
    w(f"functions/{kbd_fn}/protocol", kbd_protocol)
    w(f"functions/{kbd_fn}/subclass", kbd_subclass)
    w(f"functions/{kbd_fn}/report_length", "8")
    w(f"functions/{kbd_fn}/report_desc", KEYBOARD_DESC_WITH_LED)

    w("configs/c.1/strings/0x409/configuration", "Config")
    w("configs/c.1/MaxPower", "250")

    os.symlink(f"{GADGET_DIR}/functions/hid.usb0",
               f"{GADGET_DIR}/configs/c.1/hid.usb0")
    os.symlink(f"{GADGET_DIR}/functions/hid.usb1",
               f"{GADGET_DIR}/configs/c.1/hid.usb1")

    udc = os.listdir("/sys/class/udc")[0]
    w("UDC", udc)


def start_led_reader(dev):
    def reader():
        try:
            fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
            while True:
                try:
                    os.read(fd, 1)
                except BlockingIOError:
                    time.sleep(0.01)
                except OSError:
                    break
        except Exception:
            pass
    threading.Thread(target=reader, daemon=True).start()


def test_devices(mouse_dev, kbd_dev, test_name):
    print(f"\n{'='*60}")
    print(f"  {test_name}")
    print(f"  mouse={mouse_dev}  kbd={kbd_dev}")
    print(f"{'='*60}")

    time.sleep(2)  # wait for mobile enumeration

    start_led_reader(kbd_dev)
    time.sleep(0.3)

    # Test mouse
    print("  Mouse move ...", end=" ", flush=True)
    signal.alarm(3)
    try:
        with open(mouse_dev, "wb", buffering=0) as f:
            for _ in range(20):
                f.write(struct.pack("Bbbb", 0, 2, 0, 0))
                f.flush()
                time.sleep(0.02)
        signal.alarm(0)
        print("OK")
        mouse_ok = True
    except Exception:
        signal.alarm(0)
        print("BLOCKED")
        mouse_ok = False

    # Test keyboard
    print("  Keyboard 'a' ...", end=" ", flush=True)
    signal.alarm(3)
    try:
        with open(kbd_dev, "wb", buffering=0) as f:
            f.write(struct.pack("BBBBBBBB", 0, 0, 0x04, 0, 0, 0, 0, 0))
            f.flush()
            time.sleep(0.05)
            f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
            f.flush()
        signal.alarm(0)
        print("OK")
        kbd_ok = True
    except Exception:
        signal.alarm(0)
        print("BLOCKED")
        kbd_ok = False

    if mouse_ok and kbd_ok:
        # Test Cmd+H
        print("  Cmd+H ...", end=" ", flush=True)
        signal.alarm(3)
        try:
            with open(kbd_dev, "wb", buffering=0) as f:
                f.write(struct.pack("BBBBBBBB", 0x08, 0, 0x0B, 0, 0, 0, 0, 0))
                f.flush()
                time.sleep(0.05)
                f.write(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))
                f.flush()
            signal.alarm(0)
            print("OK")
        except Exception:
            signal.alarm(0)
            print("BLOCKED")

    return mouse_ok and kbd_ok


CONFIGS = [
    {
        "name": "Config 1: USB 2.1 + Misc device class",
        "bcd_usb": "0x0210",
        "device_class": "0xEF",
        "device_subclass": "0x02",
        "device_protocol": "0x01",
        "mouse_protocol": "2", "mouse_subclass": "1",
        "kbd_protocol": "1", "kbd_subclass": "1",
        "mouse_first": True,
    },
    {
        "name": "Config 2: USB 2.0 + non-boot keyboard",
        "bcd_usb": "0x0200",
        "device_class": "0x00",
        "device_subclass": "0x00",
        "device_protocol": "0x00",
        "mouse_protocol": "2", "mouse_subclass": "1",
        "kbd_protocol": "0", "kbd_subclass": "0",
        "mouse_first": True,
    },
    {
        "name": "Config 3: USB 2.1 + Misc + non-boot keyboard",
        "bcd_usb": "0x0210",
        "device_class": "0xEF",
        "device_subclass": "0x02",
        "device_protocol": "0x01",
        "mouse_protocol": "2", "mouse_subclass": "1",
        "kbd_protocol": "0", "kbd_subclass": "0",
        "mouse_first": True,
    },
    {
        "name": "Config 4: Keyboard first, mouse second",
        "bcd_usb": "0x0200",
        "device_class": "0x00",
        "device_subclass": "0x00",
        "device_protocol": "0x00",
        "mouse_protocol": "2", "mouse_subclass": "1",
        "kbd_protocol": "1", "kbd_subclass": "1",
        "mouse_first": False,
    },
    {
        "name": "Config 5: Both non-boot protocol",
        "bcd_usb": "0x0200",
        "device_class": "0x00",
        "device_subclass": "0x00",
        "device_protocol": "0x00",
        "mouse_protocol": "0", "mouse_subclass": "0",
        "kbd_protocol": "0", "kbd_subclass": "0",
        "mouse_first": True,
    },
    {
        "name": "Config 6: USB 2.1 + Misc + both non-boot + kbd first",
        "bcd_usb": "0x0210",
        "device_class": "0xEF",
        "device_subclass": "0x02",
        "device_protocol": "0x01",
        "mouse_protocol": "0", "mouse_subclass": "0",
        "kbd_protocol": "0", "kbd_subclass": "0",
        "mouse_first": False,
    },
]


def timeout_handler(signum, frame):
    raise TimeoutError("blocked")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Run as root")
        sys.exit(1)

    signal.signal(signal.SIGALRM, timeout_handler)

    for cfg in CONFIGS:
        teardown()
        time.sleep(0.5)

        name = cfg.pop("name")
        mouse_first = cfg.pop("mouse_first")

        try:
            setup_composite(**cfg, mouse_first=mouse_first, name=name)
        except Exception as e:
            print(f"\n  Setup failed for {name}: {e}")
            cfg["name"] = name
            cfg["mouse_first"] = mouse_first
            continue

        cfg["name"] = name
        cfg["mouse_first"] = mouse_first

        mouse_dev = "/dev/hidg0" if mouse_first else "/dev/hidg1"
        kbd_dev = "/dev/hidg1" if mouse_first else "/dev/hidg0"

        success = test_devices(mouse_dev, kbd_dev, name)

        if success:
            print(f"\n*** WORKING CONFIG: {name} ***")
            print(f"    Settings: {cfg}")
            break

    else:
        print("\n\nNo composite config worked with iOS.")
        print("Gadget swapping remains the only option.")

    teardown()
