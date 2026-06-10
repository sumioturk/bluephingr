"""web_server.py — phingr web UI and API server.

Serves the web interface and proxies commands to touch_server.py
over TCP. No HID code here — all input handling is in touch_server.

Requires:
    - touch_server.py running on localhost:7700
    - Pi camera (optional, for live preview)

Usage:
    python3 rpi/server/web_server.py
    python3 rpi/server/web_server.py --port 8080 --touch-port 7700
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import threading
import time

log = logging.getLogger("phingr.web")

# ── Configuration ─────────────────────────────────────────────────────────

TOUCH_HOST = "127.0.0.1"
TOUCH_PORT = 7700

# Server-side calibration storage (shared between browser clients and phingr-cli)
_calib_data = {"handles": None, "table": None}

_camera = None
_camera_lock = threading.Lock()

# ── libimobiledevice gateway ─────────────────────────────────────────────────
#
# Generic exec endpoint + SSE syslog stream. Connects to iPhone over WiFi
# via usbmuxd network discovery.
# Requires: apt install libimobiledevice-utils usbmuxd ideviceinstaller
# One-time iPhone setup: Finder → iPhone → "Show this iPhone when on Wi-Fi"

# Allowlist: only idevice* tools may be executed via the exec endpoint.
_IDEVICE_ALLOWLIST = {
    'idevice_id', 'ideviceinfo', 'idevicename', 'idevicediagnostics',
    'idevicescreenshot', 'idevicesyslog', 'ideviceinstaller', 'idevicepair',
    'idevicebackup2', 'idevicedebugserverproxy', 'ideviceimagemounter',
    'idevicenotificationproxy', 'idevicedebug',
}


async def idevice_exec(args: list[str], timeout: float = 30.0) -> dict:
    """Run a whitelisted idevice command and return stdout/stderr/returncode."""
    if not args:
        return {"ok": False, "error": "no command"}
    cmd = args[0]
    if cmd not in _IDEVICE_ALLOWLIST:
        return {"ok": False, "error": f"'{cmd}' not in allowlist"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode('utf-8', errors='replace'),
            "stderr": stderr.decode('utf-8', errors='replace'),
        }
    except asyncio.TimeoutError:
        try: proc.terminate()
        except Exception: pass
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": "timeout"}
    except FileNotFoundError:
        return {"ok": False, "returncode": -2, "stdout": "",
                "stderr": f"{cmd} not found — apt install libimobiledevice-utils"}
    except Exception as e:
        return {"ok": False, "returncode": -3, "stdout": "", "stderr": str(e)}


# ── External relays ─────────────────────────────────────────────────────────
#
# Four general-purpose relays driven from the Pi's GPIO header. Useful for
# power-cycling the phone, toggling a charger, switching a light for the
# camera, etc. Pins are BCM numbering and chosen to avoid the USB gadget and
# camera. Set RELAY_ACTIVE_HIGH to match your board: True means the relay
# energizes when the GPIO is driven HIGH (3.3V); False means it energizes on
# LOW (0V) — typical of the cheap optocoupler relay modules.
RELAY_PINS = [17, 27, 22, 23]          # BCM GPIO for relays 1-4
RELAY_ACTIVE_HIGH = True               # this board energizes on HIGH (3.3V)
RELAY_NAMES = ["Relay 1", "Relay 2", "Relay 3", "Relay 4"]

_relays: list = []                     # gpiozero OutputDevice list (or empty)
_relay_state = [False] * len(RELAY_PINS)
_relay_lock = threading.Lock()
_relay_available = False


# ── Touch server client ──────────────────────────────────────────────────

class TouchClient:
    """Async TCP client for touch_server.py."""

    def __init__(self, host: str = TOUCH_HOST, port: int = TOUCH_PORT) -> None:
        self._host = host
        self._port = port
        self._reader = None
        self._writer = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self._host, self._port,
        )
        log.info("connected to touch server at %s:%d", self._host, self._port)

    async def send(self, cmd: dict) -> dict:
        """Send a command and return the response. Auto-reconnects."""
        async with self._lock:
            for attempt in range(2):
                try:
                    if self._writer is None or self._writer.is_closing():
                        await self.connect()
                    self._writer.write(json.dumps(cmd).encode() + b"\n")
                    await self._writer.drain()
                    line = await asyncio.wait_for(
                        self._reader.readline(), timeout=5.0,
                    )
                    if not line:
                        raise ConnectionError("empty response")
                    return json.loads(line)
                except (ConnectionError, OSError, asyncio.TimeoutError):
                    self._writer = None
                    if attempt == 0:
                        log.warning("touch server connection lost, reconnecting...")
                    else:
                        return {"ok": False, "error": "touch server unreachable"}
        return {"ok": False, "error": "touch server unreachable"}

    async def close(self) -> None:
        if self._writer:
            self._writer.close()


_touch = TouchClient()


# ── Camera ────────────────────────────────────────────────────────────────

CAMERA_PRESETS = {
    "ultrahigh": {"width": 2328, "height": 1748, "fps": 5,  "label": "Ultra High (2K)"},
    "high":      {"width": 1920, "height": 1080, "fps": 10, "label": "High (FHD)"},
    "baseline":  {"width": 1280, "height": 720,  "fps": 10, "label": "Baseline (HD)"},
}

_current_preset = "high"


def camera_set_preset(preset: str) -> bool:
    """Switch camera to a named resolution preset. Returns True on success."""
    global _camera, _current_preset
    if preset not in CAMERA_PRESETS:
        return False
    p = CAMERA_PRESETS[preset]
    log.info("Switching camera to %s: %dx%d @ %dfps", preset, p["width"], p["height"], p["fps"])
    with _camera_lock:
        if _camera is not None:
            try:
                log.info("Stopping camera...")
                _camera.stop()
                _camera.close()
                log.info("Camera closed")
            except Exception as e:
                log.warning("Camera close error (non-fatal): %s", e)
            _camera = None
    time.sleep(1)
    camera_init(p["width"], p["height"], p["fps"])
    if _camera is not None:
        _current_preset = preset
        log.info("Preset switched to %s", preset)
        return True
    log.warning("Preset switch to %s failed — camera not available", preset)
    return False


def camera_init(width: int = 1920, height: int = 1080, fps: int = 10) -> None:
    global _camera
    try:
        from picamera2 import Picamera2
        from libcamera import controls
        _camera = Picamera2()
        config = _camera.create_still_configuration(
            main={"size": (width, height), "format": "RGB888"},
            controls={"FrameRate": float(fps)},
        )
        _camera.configure(config)
        _camera.start()
        try:
            _camera.set_controls({
                "ExposureTime": 16667,
                "AeEnable": False,
                "FrameRate": float(fps),
            })
        except Exception as e:
            log.warning("camera exposure controls failed: %s", e)
        try:
            _camera.set_controls({
                "AfMode": controls.AfModeEnum.Continuous,
                "AfSpeed": controls.AfSpeedEnum.Fast,
            })
            log.info("continuous AF enabled")
        except Exception as e:
            log.warning("AF not available on this camera: %s", e)
        time.sleep(2)
        log.info("camera started: %dx%d @ %dfps", width, height, fps)
    except Exception as e:
        log.warning("camera not available: %s", e)
        _camera = None


def camera_focus_and_lock() -> bool:
    """Trigger autofocus, wait for it to settle, then lock focus."""
    if _camera is None:
        return False
    try:
        from libcamera import controls
        # AfMode must be set to Auto before AfTrigger is sent — one call each
        _camera.set_controls({"AfMode": controls.AfModeEnum.Auto})
        time.sleep(0.1)
        _camera.set_controls({"AfTrigger": controls.AfTriggerEnum.Start})
        # Poll AfState until focused or timeout
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.1)
            md = _camera.capture_metadata()
            af_state = md.get("AfState")
            if af_state == controls.AfStateEnum.Focused:
                break
            if af_state == controls.AfStateEnum.Failed:
                log.warning("AF failed to converge")
                break
        # Lock focus by switching to manual mode
        _camera.set_controls({"AfMode": controls.AfModeEnum.Manual})
        log.info("focus locked")
        return True
    except Exception as e:
        log.warning("focus lock failed: %s", e)
        return False


def camera_focus_unlock() -> bool:
    """Re-enable continuous autofocus."""
    if _camera is None:
        return False
    try:
        from libcamera import controls
        _camera.set_controls({
            "AfMode": controls.AfModeEnum.Continuous,
            "AfSpeed": controls.AfSpeedEnum.Fast,
        })
        log.info("focus unlocked (continuous AF)")
        return True
    except Exception as e:
        log.warning("focus unlock failed: %s", e)
        return False


def camera_detect_screens() -> list:
    """Detect bright rectangular regions (phone screen) in camera frame.

    Assumes screen is the bright part, rest is dark (dark box setup).
    Uses Otsu's thresholding to auto-find the brightness boundary.
    Returns list of candidates sorted by area (largest first).
    """
    if _camera is None:
        return []
    import cv2
    import numpy as np

    with _camera_lock:
        arr = _camera.capture_array()
    arr = cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)
    h, w = arr.shape[:2]

    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # Blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (11, 11), 0)

    # Otsu's threshold — automatically finds the boundary between
    # bright screen and dark background
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Clean up — close small gaps, remove noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    # Find contours of bright regions
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < (w * h * 0.03):  # skip tiny
            continue

        # Get the minimum area rectangle (handles slight rotation)
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect)
        pts = box.astype(int).tolist()

        # Sort corners: TL, TR, BR, BL
        pts.sort(key=lambda p: p[1])
        top = sorted(pts[:2], key=lambda p: p[0])
        bottom = sorted(pts[2:], key=lambda p: p[0])
        ordered = [top[0], top[1], bottom[1], bottom[0]]

        # Clamp to image bounds
        for p in ordered:
            p[0] = max(0, min(w - 1, p[0]))
            p[1] = max(0, min(h - 1, p[1]))

        corners = [{"x": round(p[0] / w, 4), "y": round(p[1] / h, 4)} for p in ordered]

        candidates.append({
            "corners": corners,
            "area": round(area / (w * h), 4),
        })

    candidates.sort(key=lambda c: c["area"], reverse=True)
    return candidates[:10]


def camera_capture_jpeg(quality: int = 70) -> bytes | None:
    if _camera is None:
        return None
    import cv2
    if not _camera_lock.acquire(timeout=3):
        return None  # lock busy (camera switching)
    try:
        if _camera is None:
            return None  # camera closed while waiting for lock
        arr = _camera.capture_array()
    except Exception as e:
        log.warning("camera capture failed: %s", e)
        return None
    finally:
        _camera_lock.release()
    # Rotate 90 degrees clockwise for portrait view
    arr = cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)
    _, jpeg = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return jpeg.tobytes()


def _camera_restart() -> None:
    """Restart the camera after a timeout/error."""
    global _camera
    if _camera is None:
        return
    p = CAMERA_PRESETS.get(_current_preset, CAMERA_PRESETS["high"])
    try:
        _camera.stop()
        _camera.close()
    except Exception:
        pass
    _camera = None
    time.sleep(1)
    camera_init(p["width"], p["height"], p["fps"])
    if _camera is not None:
        log.info("camera restarted")
    else:
        log.warning("camera restart failed")




# ── External relays ─────────────────────────────────────────────────────────

def relay_init() -> None:
    """Set up the GPIO relay outputs. Degrades gracefully off-Pi."""
    global _relays, _relay_available
    try:
        from gpiozero import OutputDevice
        _relays = [
            OutputDevice(pin, active_high=RELAY_ACTIVE_HIGH, initial_value=False)
            for pin in RELAY_PINS
        ]
        _relay_available = True
        log.info("relays ready on BCM pins %s (active_%s)",
                 RELAY_PINS, "high" if RELAY_ACTIVE_HIGH else "low")
    except Exception as e:
        _relays = []
        _relay_available = False
        log.warning("relays not available: %s", e)


def relay_set(index: int, on: bool) -> bool:
    """Switch a single relay on/off. Returns True on success."""
    if index < 0 or index >= len(RELAY_PINS):
        return False
    with _relay_lock:
        if _relay_available and index < len(_relays):
            try:
                if on:
                    _relays[index].on()
                else:
                    _relays[index].off()
            except Exception as e:
                log.warning("relay %d set failed: %s", index, e)
                return False
        _relay_state[index] = bool(on)
    log.info("relay %d -> %s", index + 1, "ON" if on else "OFF")
    return True


def relay_state() -> list:
    """Return the current state of every relay."""
    with _relay_lock:
        return [
            {"index": i, "name": RELAY_NAMES[i], "on": _relay_state[i]}
            for i in range(len(RELAY_PINS))
        ]


# ── Web handlers ──────────────────────────────────────────────────────────

async def handle_api(request):
    from aiohttp import web
    path = request.path
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}

    try:
        # Mouse — proxy to touch server
        if path == "/api/mouse/click":
            return web.json_response(await _touch.send({"action": "click", **body}))
        elif path == "/api/mouse/move":
            return web.json_response(await _touch.send({"action": "move", **body}))
        elif path == "/api/mouse/move_to":
            return web.json_response(await _touch.send({"action": "move_to", **body}))
        elif path == "/api/mouse/drag":
            return web.json_response(await _touch.send({"action": "drag", **body}))
        elif path == "/api/mouse/scroll":
            return web.json_response(await _touch.send({"action": "scroll", **body}))
        elif path == "/api/mouse/reset":
            return web.json_response(await _touch.send({"action": "reset"}))
        elif path == "/api/mouse/corner":
            return web.json_response(await _touch.send({"action": "corner", **body}))

        # Keyboard — proxy to touch server
        elif path == "/api/keyboard/key":
            return web.json_response(await _touch.send({"action": "key", **body}))
        elif path == "/api/keyboard/hotkey":
            return web.json_response(await _touch.send({"action": "hotkey", **body}))
        elif path == "/api/keyboard/type":
            text = body.get("text", "")
            delay = body.get("delay_ms", 30)
            for ch in text:
                if ch == " ":
                    await _touch.send({"action": "key", "key": "space"})
                elif ch == "\n":
                    await _touch.send({"action": "key", "key": "enter"})
                elif ch.isupper():
                    await _touch.send({"action": "key", "key": ch.lower(), "modifiers": ["shift"]})
                else:
                    await _touch.send({"action": "key", "key": ch})
                await asyncio.sleep(delay / 1000.0)
            return web.json_response({"ok": True})

        # Tap (atomic move_to + click in touch server)
        elif path == "/api/tap":
            return web.json_response(await _touch.send({"action": "tap", **body}))

        # Swipe (move_to start + drag to end)
        elif path == "/api/swipe":
            return web.json_response(await _touch.send({"action": "swipe", **body}))

        # Camera focus
        elif path == "/api/camera/focus":
            ok = await asyncio.get_event_loop().run_in_executor(None, camera_focus_and_lock)
            return web.json_response({"ok": ok})
        elif path == "/api/camera/autofocus":
            ok = await asyncio.get_event_loop().run_in_executor(None, camera_focus_unlock)
            return web.json_response({"ok": ok})
        elif path == "/api/camera/detect_screen":
            candidates = await asyncio.get_event_loop().run_in_executor(None, camera_detect_screens)
            return web.json_response({"ok": True, "candidates": candidates})
        elif path == "/api/camera/preset":
            if request.method == "GET":
                return web.json_response({
                    "ok": True,
                    "current": _current_preset,
                    "presets": {k: v["label"] for k, v in CAMERA_PRESETS.items()},
                })
            preset = body.get("preset", "")
            try:
                ok = await asyncio.get_event_loop().run_in_executor(None, camera_set_preset, preset)
            except Exception as e:
                log.warning("Preset switch failed: %s", e)
                ok = False
            return web.json_response({"ok": ok, "preset": preset if ok else _current_preset})

        # Calibration
        elif path == "/api/calib/move":
            return web.json_response(await _touch.send({"action": "calib_move", **body}))
        elif path == "/api/calib/set":
            return web.json_response(await _touch.send({"action": "calib_set", **body}))
        elif path == "/api/calib/get":
            return web.json_response(await _touch.send({"action": "calib_get"}))
        elif path == "/api/calib/table":
            if request.method == "GET":
                return web.json_response({"ok": True, **_calib_data})
            # Store calibration table + optional handles
            if body.get("tableX") and body.get("tableY"):
                _calib_data["table"] = {"tableX": body["tableX"], "tableY": body["tableY"]}
            if body.get("handles"):
                _calib_data["handles"] = body["handles"]
            log.info(f"Calibration stored: handles={'yes' if _calib_data['handles'] else 'no'}, "
                     f"table={'yes' if _calib_data['table'] else 'no'}")
            return web.json_response({"ok": True})

        elif path == "/api/calib/handles":
            if request.method == "GET":
                return web.json_response({"ok": True, "handles": _calib_data["handles"]})
            _calib_data["handles"] = body.get("handles")
            log.info(f"Handles stored: {_calib_data['handles'] is not None}")
            return web.json_response({"ok": True})

        # Configure
        elif path == "/api/configure":
            return web.json_response(await _touch.send({"action": "configure", **body}))

        # Screenshot (local camera)
        elif path == "/api/screenshot":
            jpeg = camera_capture_jpeg()
            if jpeg is None:
                return web.json_response({"error": "camera not available"}, status=503)
            return web.Response(body=jpeg, content_type="image/jpeg")

        # ── libimobiledevice exec gateway ─────────────────────────────────
        # POST {"cmd": "ideviceinfo -k DeviceName"} or {"args": [...]}
        elif path == "/api/idevice/exec":
            args = body.get("args") or []
            if not args:
                raw = body.get("cmd", "")
                import shlex
                try:
                    args = shlex.split(raw)
                except ValueError as e:
                    return web.json_response({"ok": False, "error": str(e)}, status=400)
            timeout = float(body.get("timeout", 30))
            return web.json_response(await idevice_exec(args, timeout))

        # Relays
        elif path == "/api/relay":
            if request.method == "GET":
                return web.json_response({
                    "ok": True,
                    "available": _relay_available,
                    "relays": relay_state(),
                })
            # POST: {"index": 0, "on": true} or {"index": 0, "toggle": true}
            try:
                index = int(body.get("index"))
            except (TypeError, ValueError):
                return web.json_response({"ok": False, "error": "missing/invalid index"}, status=400)
            if "toggle" in body:
                current = _relay_state[index] if 0 <= index < len(_relay_state) else False
                on = not current
            else:
                on = bool(body.get("on"))
            ok = relay_set(index, on)
            if not ok:
                return web.json_response({"ok": False, "error": "invalid relay index"}, status=400)
            return web.json_response({"ok": True, "index": index, "on": on})

        else:
            return web.json_response({"error": f"unknown: {path}"}, status=404)

    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_idevice_syslog(request):
    """SSE stream of idevicesyslog. Retries internally on device disconnect."""
    from aiohttp import web
    udid = request.rel_url.query.get('udid')
    process = request.rel_url.query.get('process')
    resp = web.StreamResponse()
    resp.content_type = 'text/event-stream'
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    await resp.prepare(request)
    try:
        while True:
            cmd = ['idevicesyslog']
            if udid:    cmd += ['-u', udid]
            if process: cmd += ['-p', process]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=15.0)
                    except asyncio.TimeoutError:
                        await resp.write(b': ping\n\n')
                        continue
                    if not line:
                        break
                    text = line.decode('utf-8', errors='replace').rstrip('\n\r')
                    await resp.write(('data: ' + text + '\n\n').encode())
            finally:
                try: proc.terminate()
                except Exception: pass
                try: await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception: pass
            # Device disconnected — wait and retry
            await resp.write(b'data: [no device — retrying in 5s]\n\n')
            await asyncio.sleep(5.0)
    except (ConnectionResetError, ConnectionError, BrokenPipeError):
        pass
    except Exception as e:
        log.warning("syslog stream: %s", e)
    return resp


async def handle_stream(request):
    from aiohttp import web
    response = web.StreamResponse()
    response.content_type = "multipart/x-mixed-replace; boundary=frame"
    await response.prepare(request)
    try:
        while True:
            jpeg = camera_capture_jpeg(quality=70)
            if jpeg is None:
                await asyncio.sleep(1)
                continue
            await response.write(
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )
            await asyncio.sleep(0.1)  # ~10fps
    except (ConnectionResetError, ConnectionError, BrokenPipeError):
        pass  # client disconnected — normal


async def handle_index(request):
    from aiohttp import web
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    index_path = os.path.join(static_dir, "index.html")
    return web.FileResponse(index_path)


async def run_server(port: int = 8080) -> None:
    from aiohttp import web

    @web.middleware
    async def cors_middleware(request, handler):
        """Allow cross-origin requests + iframe embedding from phingr-cli."""
        resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        # Allow iframe embedding from any origin
        resp.headers.pop("X-Frame-Options", None)
        resp.headers["Content-Security-Policy"] = "frame-ancestors *"
        return resp

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_index)
    app.router.add_static("/static", static_dir)
    app.router.add_get("/api/stream", handle_stream)
    app.router.add_get("/api/screenshot", handle_api)
    app.router.add_get("/api/calib/handles", handle_api)
    app.router.add_get("/api/calib/table", handle_api)
    app.router.add_get("/api/calib/get", handle_api)
    app.router.add_get("/api/camera/preset", handle_api)
    app.router.add_get("/api/relay", handle_api)
    app.router.add_get("/api/idevice/syslog/stream", handle_idevice_syslog)
    app.router.add_post("/api/{tail:.*}", handle_api)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("web server on http://0.0.0.0:%d", port)
    await asyncio.Event().wait()


async def main(port: int, cam_width: int, cam_height: int,
               touch_port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    global _touch
    _touch = TouchClient(TOUCH_HOST, touch_port)
    camera_init(cam_width, cam_height)
    relay_init()
    await run_server(port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="phingr web server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--touch-port", type=int, default=TOUCH_PORT)
    parser.add_argument("--cam-width", type=int, default=1920)
    parser.add_argument("--cam-height", type=int, default=1080)
    args = parser.parse_args()
    asyncio.run(main(args.port, args.cam_width, args.cam_height, args.touch_port))
