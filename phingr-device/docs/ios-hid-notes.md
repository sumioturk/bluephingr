# iOS USB HID Notes

Findings from getting USB HID mouse and keyboard working with iOS
via Raspberry Pi Zero 2W USB gadget mode.

## USB Gadget Basics

- RPi Zero 2W connects to iPhone via the USB **data** port (not power)
- RPi runs in USB **device/gadget** mode using `dwc2` overlay and `libcomposite`
- iOS sees the RPi as a USB HID accessory
- Gadget config lives in `/sys/kernel/config/usb_gadget/`

### Enable gadget mode (one-time)

```
dtoverlay=dwc2,dr_mode=peripheral   # in /boot/firmware/config.txt
dwc2                                  # in /etc/modules
libcomposite                          # in /etc/modules
```

Reboot required after first enable.

## Mouse (Works)

iOS accepts USB HID mouse without issues. Standard boot mouse descriptor works.

### Descriptor

- Protocol: 2 (mouse)
- Subclass: 1 (boot interface)
- Report length: 4 bytes

### Report format (4 bytes)

| Byte | Content |
|------|---------|
| 0 | Buttons (bit0=left, bit1=right, bit2=middle) |
| 1 | X movement (signed, -127 to 127) |
| 2 | Y movement (signed, -127 to 127) |
| 3 | Scroll wheel (signed, -127 to 127) |

### iOS quirks — Mouse

- **Scroll wheel doesn't work** — iOS ignores mouse wheel reports. Scroll must be done via click-and-drag.
- **Pointer acceleration** — mobile applies acceleration to mouse movement. Large deltas (e.g. -127) move more than 127 pixels. Use small values (1-5px) for predictable movement.
- **Cursor must be activated** — iOS won't process scroll events until the cursor has been shown via a move report. Send a small move before scrolling.
- **AssistiveTouch required** — Enable Settings > Accessibility > Touch > AssistiveTouch for the mouse cursor to appear.
- **Hot corners** — With AssistiveTouch + Dwell enabled, moving cursor to screen corners triggers configurable actions (Home, App Switch, etc.)

## Keyboard (Works, with caveats)

iOS accepts USB HID keyboard but requires specific configuration.

### Critical: LED Output Report

iOS sends LED status reports (Caps Lock, Num Lock) to the keyboard device. **If these are not consumed, keyboard writes block indefinitely.**

Solution: include LED output report in the descriptor AND run a background reader thread.

### Descriptor

Must include the LED output section:

```
# LED output report (5 bits + 3 padding)
Usage Page (LEDs)
Usage Minimum (Num Lock)
Usage Maximum (Kana)
Report Size (1), Report Count (5)
Output (Data, Variable, Absolute)
Report Size (3), Report Count (1)
Output (Constant) — padding
```

### Report format (8 bytes)

| Byte | Content |
|------|---------|
| 0 | Modifier keys (bit0=LCtrl, bit1=LShift, bit2=LAlt, bit3=LGui/Cmd, bit4-7=right modifiers) |
| 1 | Reserved (0x00) |
| 2-7 | Up to 6 simultaneous key codes |

### LED reader thread

```python
def led_reader():
    fd = os.open("/dev/hidg1", os.O_RDONLY | os.O_NONBLOCK)
    while True:
        try:
            os.read(fd, 1)
        except BlockingIOError:
            time.sleep(0.01)

threading.Thread(target=led_reader, daemon=True).start()
```

**Must use a separate fd from the write fd.** Shared fd (O_RDWR) doesn't work reliably with Linux gadget HID.

### File descriptor management

- **LED reader**: own fd with `O_RDONLY | O_NONBLOCK`
- **Key writer**: open/write/close each time, OR keep a separate write fd
- **Never share fds** between reader and writer

### iOS quirks — Keyboard

- **Full Keyboard Access required** — Enable Settings > Accessibility > Keyboards > Full Keyboard Access for keyboard shortcuts to work.
- **Gadget-mode keyboards are restrictive** — iOS treats USB gadget keyboards differently from keyboards connected via Lightning Camera Connection Kit adapter.

## Composite Device (Mouse + Keyboard)

iOS **rejects** composite HID gadgets with standard USB 2.0 descriptors. The fix:

### Required: USB 2.1 + Miscellaneous Device Class

```python
w("bcdUSB", "0x0210")         # USB 2.1 (not 2.0!)
w("bDeviceClass", "0xEF")     # Miscellaneous
w("bDeviceSubClass", "0x02")  # Common Class
w("bDeviceProtocol", "0x01")  # IAD (Interface Association Descriptor)
```

This is the standard way real composite HID devices (e.g. Apple Magic Keyboard with trackpad) identify themselves.

### What doesn't work

| Configuration | Result |
|--------------|--------|
| USB 2.0 + class 0x00 (default) | Mouse works, keyboard blocked |
| USB 2.0 + any device class | Keyboard blocked |
| Keyboard alone (no mouse) | Works (keyboard-only gadget) |
| Mouse alone (no keyboard) | Works (mouse-only gadget) |

### What works

| Configuration | Result |
|--------------|--------|
| USB 2.1 + class 0xEF/0x02/0x01 | Both mouse and keyboard work |

### Gadget setup must be done in Python

Shell script `echo` commands write values slightly differently than Python `open().write()` to sysfs files. The shell version was rejected by iOS while the Python version worked. **Always use Python for gadget setup.**

## Touch Digitizer (Does NOT work)

We attempted USB HID touch screen digitizer — iOS rejects all variations.

### Tested descriptors

| Descriptor | Result |
|-----------|--------|
| Minimal (tip switch + X + Y) | Writes block — iOS rejects |
| With Contact Count + Contact ID | Writes block |
| With In Range + Physical dimensions + Units | Writes block |
| Various vendor IDs (Apple, Logitech) | All rejected |

iOS only accepts touch digitizer input from MFi-certified devices or the built-in touchscreen. USB gadget touch digitizers are blocked.

## Cursor Coordinate System

### Screen dimensions

iOS HID mouse cursor moves in **pixel** space, not point space.

| Device | Points | Pixels (HID space) |
|--------|--------|-------------------|
| iPhone SE3 | 375 x 667 | 750 x 1334 |
| iPhone 15 | 393 x 852 | 1179 x 2556 |

### Absolute positioning via reset + move

Since HID mouse is relative, absolute positioning requires:

1. **Reset to origin**: send many (-5, -5) reports to slam cursor to top-left corner
2. **Settle delay**: 100ms for mobile to process all reports
3. **Move to target**: send (step, 0) and (0, step) reports

```python
# Reset
report = mouse_report(0, -5, -5)
with open("/dev/hidg0", "wb", buffering=0) as f:
    for _ in range(200):
        f.write(report)
time.sleep(0.1)

# Move to target (normalized 0-1)
tx = int(x_norm * 750)  # screen width in pixels
ty = int(y_norm * 1334)
step = 5
with open("/dev/hidg0", "wb", buffering=0) as f:
    for _ in range(tx // step):
        f.write(mouse_report(0, step, 0))
    if tx % step:
        f.write(mouse_report(0, tx % step, 0))
    for _ in range(ty // step):
        f.write(mouse_report(0, 0, step))
    if ty % step:
        f.write(mouse_report(0, 0, ty % step))
time.sleep(0.05)
```

### Movement step size

| Step size | Behavior |
|-----------|----------|
| 1px | May be ignored by iOS |
| 5px | Reliable, minimal acceleration |
| 10+ px | Noticeable acceleration, less predictable |
| 127px | Maximum per report, heavy acceleration |

**5px is the sweet spot** for reliable cursor positioning.

### Using a single fd

Always use a single open fd for a burst of reports. Opening and closing per report (800+ times) is slow and may cause timing issues.

```python
# Good
with open("/dev/hidg0", "wb", buffering=0) as f:
    for _ in range(200):
        f.write(report)

# Bad — slow and unreliable
for _ in range(200):
    Path("/dev/hidg0").write_bytes(report)
```

## iOS Settings Required

| Setting | Path | Purpose |
|---------|------|---------|
| AssistiveTouch | Accessibility > Touch > AssistiveTouch | Shows mouse cursor |
| Full Keyboard Access | Accessibility > Keyboards > Full Keyboard Access | Enables keyboard shortcuts |
| Hot Corners | AssistiveTouch > Hot Corners | Assign actions to cursor corners |
| Dwell | AssistiveTouch > Dwell | Auto-action when cursor stops at corner |
| Pointer size | Accessibility > Pointer Control | Adjust cursor size/visibility |

## iOS Keyboard Shortcuts

With Full Keyboard Access enabled:

| Shortcut | Action |
|----------|--------|
| Cmd+H | Home |
| Cmd+Tab | App Switcher |
| Cmd+Space | Spotlight |
| Cmd+Shift+3 | Screenshot |
| Cmd+Q | Close App |
| Cmd+C/V/X/Z | Copy/Paste/Cut/Undo |
