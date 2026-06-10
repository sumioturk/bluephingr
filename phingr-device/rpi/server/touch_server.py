"""touch_server.py — HID server for mouse + keyboard on RPi Zero 2W.

Uses composite USB gadget (USB 2.1 + Misc device class) with both
mouse (/dev/hidg0) and keyboard (/dev/hidg1) simultaneously.

Protocol (newline-delimited JSON over TCP):
    {"action": "click"}
    {"action": "move", "dx": 50, "dy": -30}
    {"action": "scroll", "dy": -200}
    {"action": "drag", "dx": 0, "dy": 200, "duration_ms": 300, "steps": 20}
    {"action": "move_to", "x": 0.5, "y": 0.5}
    {"action": "reset"}
    {"action": "corner", "corner": "top_right"}
    {"action": "key", "key": "h", "modifiers": ["cmd"]}
    {"action": "hotkey", "name": "home"}
    {"action": "configure", "screen_w": 375, "screen_h": 667}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import threading
import time
from pathlib import Path

HID_MOUSE = Path("/dev/hidg0")
HID_KEYBOARD = Path("/dev/hidg1")
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7700

# Screen size in HID cursor units
# These are calibrated values — actual cursor travel for full screen
# Default: iPhone SE3 pixel dimensions. Calibrate to find real values.
DEFAULT_SCREEN_W = 750
DEFAULT_SCREEN_H = 1334

# Calibration: send this many HID units during calibration test move
CALIB_TEST_UNITS = 500

log = logging.getLogger("phingr.hid")

_screen_w = DEFAULT_SCREEN_W
_screen_h = DEFAULT_SCREEN_H
_cursor_x = 0.0
_cursor_y = 0.0

# ── HID key code mappings ────────────────────────────────────────────────

MODIFIERS = {
    "ctrl": 0x01, "lctrl": 0x01,
    "shift": 0x02, "lshift": 0x02,
    "alt": 0x04, "lalt": 0x04, "option": 0x04,
    "cmd": 0x08, "gui": 0x08, "lgui": 0x08, "command": 0x08, "meta": 0x08,
    "rctrl": 0x10, "rshift": 0x20,
    "ralt": 0x40, "roption": 0x40,
    "rcmd": 0x80, "rgui": 0x80,
}

KEYCODES = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22, "6": 0x23,
    "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "enter": 0x28, "return": 0x28, "esc": 0x29, "escape": 0x29,
    "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
    "minus": 0x2D, "equal": 0x2E, "lbracket": 0x2F, "rbracket": 0x30,
    "backslash": 0x31, "semicolon": 0x33, "quote": 0x34,
    "grave": 0x35, "comma": 0x36, "period": 0x37, "slash": 0x38,
    "capslock": 0x39,
    "f1": 0x3A, "f2": 0x3B, "f3": 0x3C, "f4": 0x3D, "f5": 0x3E,
    "f6": 0x3F, "f7": 0x40, "f8": 0x41, "f9": 0x42, "f10": 0x43,
    "f11": 0x44, "f12": 0x45,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "delete": 0x4C, "home": 0x4A, "end": 0x4D,
    "pageup": 0x4B, "pagedown": 0x4E,
}

HOTKEYS = {
    "home": (["cmd"], "h"), "app_switch": (["cmd"], "tab"),
    "spotlight": (["cmd"], "space"), "screenshot": (["cmd", "shift"], "3"),
    "close_app": (["cmd"], "q"), "select_all": (["cmd"], "a"),
    "copy": (["cmd"], "c"), "paste": (["cmd"], "v"),
    "cut": (["cmd"], "x"), "undo": (["cmd"], "z"),
    "redo": (["cmd", "shift"], "z"),
}

# ── Mouse ────────────────────────────────────────────────────────────────

def _mouse_report(buttons: int, dx: int, dy: int, wheel: int = 0) -> bytes:
    return struct.pack("Bbbb",
                       buttons,
                       max(-127, min(127, dx)),
                       max(-127, min(127, dy)),
                       max(-127, min(127, wheel)))


def _write_mouse(report: bytes) -> None:
    HID_MOUSE.write_bytes(report)


def _move_by(dx: int, dy: int) -> None:
    global _cursor_x, _cursor_y
    while dx != 0 or dy != 0:
        sx = max(-127, min(127, dx))
        sy = max(-127, min(127, dy))
        _write_mouse(_mouse_report(0, sx, sy))
        dx -= sx; dy -= sy
        _cursor_x += sx; _cursor_y += sy


async def _handle_click(button: int = 1, duration_ms: int = 50) -> None:
    _write_mouse(_mouse_report(1 << (button - 1), 0, 0))
    await asyncio.sleep(duration_ms / 1000.0)
    _write_mouse(_mouse_report(0, 0, 0))


async def _handle_drag(dx: int, dy: int, duration_ms: int = 300,
                       steps: int = 20) -> None:
    global _cursor_x, _cursor_y
    interval = duration_ms / 1000.0 / steps
    sdx, sdy = dx / steps, dy / steps
    rx, ry = 0.0, 0.0
    _write_mouse(_mouse_report(1, 0, 0))
    for _ in range(steps):
        rx += sdx; ry += sdy
        ix, iy = int(rx), int(ry)
        if ix or iy:
            mx = max(-127, min(127, ix))
            my = max(-127, min(127, iy))
            _write_mouse(_mouse_report(1, mx, my))
            _cursor_x += mx; _cursor_y += my
            rx -= mx; ry -= my
        await asyncio.sleep(interval)
    _write_mouse(_mouse_report(0, 0, 0))


async def _handle_scroll(dy: int, steps: int = 20) -> None:
    """Scroll by click-and-drag from current cursor position."""
    global _cursor_y
    dy_step = dy // steps if steps > 0 else dy
    _write_mouse(_mouse_report(1, 0, 0))
    await asyncio.sleep(0.05)
    for _ in range(abs(steps)):
        s = max(-127, min(127, dy_step))
        _write_mouse(_mouse_report(1, 0, s))
        _cursor_y += s
        await asyncio.sleep(0.015)
    _write_mouse(_mouse_report(0, 0, 0))


def _reset_to_origin() -> None:
    """Move cursor to (0,0) using a single fd and settle delay."""
    global _cursor_x, _cursor_y
    report = _mouse_report(0, -5, -5)
    with open(str(HID_MOUSE), "wb", buffering=0) as f:
        for _ in range(300):
            f.write(report)
    time.sleep(0.1)  # let iOS finish processing all reports
    _cursor_x = 0.0
    _cursor_y = 0.0


def _handle_reset() -> None:
    _reset_to_origin()


def _handle_move_to(x_norm: float, y_norm: float) -> None:
    """Move to absolute position. Always resets to origin first to avoid drift."""
    global _cursor_x, _cursor_y

    _reset_to_origin()

    tx = int(x_norm * _screen_w)
    ty = int(y_norm * _screen_h)
    step = 5
    with open(str(HID_MOUSE), "wb", buffering=0) as f:
        # Move X
        full, remain = divmod(tx, step)
        report_x = _mouse_report(0, step, 0)
        for _ in range(full):
            f.write(report_x)
        if remain:
            f.write(_mouse_report(0, remain, 0))
        # Move Y
        full, remain = divmod(ty, step)
        report_y = _mouse_report(0, 0, step)
        for _ in range(full):
            f.write(report_y)
        if remain:
            f.write(_mouse_report(0, 0, remain))
    time.sleep(0.05)  # let iOS finish processing
    _cursor_x = tx
    _cursor_y = ty


async def _handle_corner(corner: str, dwell_ms: int = 500) -> None:
    _handle_reset()
    if "right" in corner:
        _move_by(int(_screen_w + 100), 0)
    if "bottom" in corner:
        _move_by(0, int(_screen_h + 100))
    await asyncio.sleep(dwell_ms / 1000.0)


# ── Keyboard ─────────────────────────────────────────────────────────────

_kbd_led_started = False


def _ensure_led_reader() -> None:
    """Start LED reader on first keyboard use (not at boot)."""
    global _kbd_led_started
    if _kbd_led_started:
        return
    _kbd_led_started = True

    def reader():
        try:
            fd = os.open(str(HID_KEYBOARD), os.O_RDONLY | os.O_NONBLOCK)
            log.info("keyboard LED reader started (fd=%d)", fd)
            while True:
                try:
                    os.read(fd, 1)
                except BlockingIOError:
                    time.sleep(0.01)
                except OSError:
                    time.sleep(0.1)
        except Exception as e:
            log.warning("LED reader failed: %s", e)

    threading.Thread(target=reader, daemon=True).start()
    time.sleep(0.3)  # let reader settle before writing


def _write_keyboard(report: bytes) -> None:
    """Write keyboard report — open/write/close each time."""
    with open(str(HID_KEYBOARD), "wb", buffering=0) as f:
        f.write(report)
        f.flush()


def _key_press_sync(mod_mask: int, keycode: int, duration: float) -> None:
    """Complete key press (down + sleep + up) in one blocking call."""
    _ensure_led_reader()
    _write_keyboard(struct.pack("BBBBBBBB", mod_mask, 0, keycode, 0, 0, 0, 0, 0))
    time.sleep(duration)
    _write_keyboard(struct.pack("BBBBBBBB", 0, 0, 0, 0, 0, 0, 0, 0))


async def _handle_key(key: str, modifiers: list[str] | None = None,
                      duration_ms: int = 50) -> None:
    mod_mask = 0
    for m in (modifiers or []):
        mod_mask |= MODIFIERS.get(m.lower(), 0)
    keycode = KEYCODES.get(key.lower(), 0)
    if keycode == 0:
        raise ValueError(f"unknown key: {key}")

    loop = asyncio.get_event_loop()
    await asyncio.wait_for(
        loop.run_in_executor(None, _key_press_sync, mod_mask, keycode,
                             duration_ms / 1000.0),
        timeout=3.0,
    )


async def _handle_hotkey(name: str) -> None:
    if name not in HOTKEYS:
        raise ValueError(f"unknown hotkey: {name}. Available: {', '.join(HOTKEYS)}")
    mods, key = HOTKEYS[name]
    await _handle_key(key, mods)


# ── Dispatch ─────────────────────────────────────────────────────────────

async def _dispatch(cmd: dict) -> dict:
    global _screen_w, _screen_h
    action = cmd.get("action")

    if action == "click":
        await _handle_click(cmd.get("button", 1), cmd.get("duration_ms", 50))
    elif action == "move":
        _move_by(int(cmd.get("dx", 0)), int(cmd.get("dy", 0)))
    elif action == "move_to":
        _handle_move_to(cmd["x"], cmd["y"])
    elif action == "drag":
        await _handle_drag(int(cmd.get("dx", 0)), int(cmd.get("dy", 0)),
                           cmd.get("duration_ms", 300), cmd.get("steps", 20))
    elif action == "scroll":
        await _handle_scroll(int(cmd.get("dy", 0)), int(cmd.get("steps", 20)))
    elif action == "reset":
        _handle_reset()
    elif action == "corner":
        await _handle_corner(cmd["corner"], cmd.get("dwell_ms", 500))
    elif action == "tap":
        _handle_move_to(cmd["x"], cmd["y"])
        await asyncio.sleep(0.05)
        await _handle_click(cmd.get("button", 1), cmd.get("duration_ms", 50))
    elif action == "swipe":
        # Move to start, then drag to end (normalized coords)
        _handle_move_to(cmd["x0"], cmd["y0"])
        await asyncio.sleep(0.05)
        dx = int((cmd["x1"] - cmd["x0"]) * _screen_w)
        dy = int((cmd["y1"] - cmd["y0"]) * _screen_h)
        await _handle_drag(dx, dy, cmd.get("duration_ms", 300), cmd.get("steps", 20))
    elif action == "calib_move":
        # Calibration: reset to origin, then move a known number of HID units
        _reset_to_origin()
        axis = cmd.get("axis", "x")  # "x" or "y"
        units = cmd.get("units", CALIB_TEST_UNITS)
        step = 5
        with open(str(HID_MOUSE), "wb", buffering=0) as f:
            full, remain = divmod(units, step)
            if axis == "x":
                for _ in range(full):
                    f.write(_mouse_report(0, step, 0))
                if remain:
                    f.write(_mouse_report(0, remain, 0))
            else:
                for _ in range(full):
                    f.write(_mouse_report(0, 0, step))
                if remain:
                    f.write(_mouse_report(0, 0, remain))
        time.sleep(0.1)
    elif action == "calib_set":
        # User tells us where the cursor actually landed (normalized 0-1)
        # From this we compute the real screen size in HID units
        axis = cmd.get("axis", "x")
        landed = cmd.get("landed")  # 0-1 where cursor actually is
        units = cmd.get("units", CALIB_TEST_UNITS)
        if landed and landed > 0.01:
            if landed >= 0.95:
                return {"ok": False, "error": f"cursor landed at {landed:.0%} of screen {axis} — too close to the edge. Reduce calibration units and retry."}
            real_size = int(units / landed)
            if axis == "x":
                _screen_w = real_size
                log.info("calibrated screen_w = %d", _screen_w)
            else:
                _screen_h = real_size
                log.info("calibrated screen_h = %d", _screen_h)
    elif action == "calib_get":
        return {"ok": True, "screen_w": _screen_w, "screen_h": _screen_h,
                "calib_units": CALIB_TEST_UNITS}
    elif action == "configure":
        _screen_w = cmd.get("screen_w", _screen_w)
        _screen_h = cmd.get("screen_h", _screen_h)
    elif action == "key":
        await _handle_key(cmd["key"], cmd.get("modifiers"),
                          cmd.get("duration_ms", 50))
    elif action == "hotkey":
        await _handle_hotkey(cmd["name"])
    else:
        return {"ok": False, "error": f"unknown action: {action}"}

    return {"ok": True}


# ── TCP server ───────────────────────────────────────────────────────────

async def _client_handler(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
) -> None:
    addr = writer.get_extra_info("peername")
    log.info("client connected: %s", addr)
    try:
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=300)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            try:
                cmd = json.loads(line)
                result = await _dispatch(cmd)
            except asyncio.TimeoutError:
                result = {"ok": False, "error": "HID write timed out"}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            writer.write(json.dumps(result).encode() + b"\n")
            await writer.drain()
    finally:
        log.info("client disconnected: %s", addr)
        writer.close()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    server = await asyncio.start_server(
        _client_handler, LISTEN_HOST, LISTEN_PORT,
    )
    log.info("listening on %s:%d", LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
