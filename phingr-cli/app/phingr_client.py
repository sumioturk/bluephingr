"""Async HTTP client for the phingr device API."""

import io
import logging
from functools import wraps

import httpx
from PIL import Image

logger = logging.getLogger("phingr-cli")


class DeviceError(Exception):
    """Raised when the device is unreachable or returns an error."""
    pass


def _handle_device_errors(func):
    """Decorator to log API calls and convert httpx errors into DeviceError."""
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        # Build log message from function name and args
        name = func.__name__
        arg_parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
        call_str = f"{name}({', '.join(arg_parts)})"

        if self.on_api_call:
            self.on_api_call(f"  >> {call_str}")

        try:
            result = await func(self, *args, **kwargs)
            if self.on_api_call and isinstance(result, dict):
                self.on_api_call(f"  << {result}")
            return result
        except httpx.ConnectError:
            raise DeviceError(f"Cannot connect to device at {self.base_url} — is it running?")
        except httpx.TimeoutException:
            raise DeviceError(f"Device at {self.base_url} timed out")
        except httpx.HTTPStatusError as e:
            raise DeviceError(f"Device returned error: {e.response.status_code}")
    return wrapper


class FkiosClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._screen_rect: list[dict] | None = None  # cached screen corners (handles)
        self._calib_table: dict | None = None  # acceleration correction table
        self.on_api_call: callable | None = None  # optional log callback

    async def close(self):
        await self.http.aclose()

    async def fetch_calibration(self):
        """Fetch screen handles + calibration table from the device server.

        The device web UI stores these when the user drags corner handles
        and runs calibration. phingr-cli needs them for accurate coordinate mapping.
        """
        try:
            # Fetch handles (screen corner positions)
            r = await self.http.get("/api/calib/handles")
            data = r.json()
            if data.get("handles"):
                self._screen_rect = data["handles"]
                logger.info(f"Fetched handles from device: {self._screen_rect}")

            # Fetch calibration table (acceleration correction)
            r = await self.http.get("/api/calib/table")
            data = r.json()
            if data.get("table"):
                self._calib_table = data["table"]
                logger.info(f"Fetched calibration table: "
                            f"X={len(self._calib_table.get('tableX', []))} points, "
                            f"Y={len(self._calib_table.get('tableY', []))} points")
        except Exception as e:
            logger.warning(f"Failed to fetch calibration: {e}")

    def _correct_coord(self, desired: float, table: list[dict]) -> float:
        """Inverse lookup on calibration table.

        Matches perspective.js correctCoord() — given a desired screen position,
        returns the value to send so the cursor lands at the desired position
        (compensating for mobile pointer acceleration).
        """
        if not table or len(table) < 2:
            return desired

        for i in range(len(table) - 1):
            a, b = table[i], table[i + 1]
            if desired >= a["actual"] and desired <= b["actual"]:
                denom = b["actual"] - a["actual"]
                t = (desired - a["actual"]) / denom if denom > 0.001 else 0
                return a["intended"] + t * (b["intended"] - a["intended"])

        # Extrapolate beyond last point
        last = table[-1]
        if last["actual"] > 0.001:
            return desired * (last["intended"] / last["actual"])
        return desired

    def camera_to_screen(self, cx: float, cy: float) -> tuple[float, float]:
        """Transform coordinates from camera-frame space to phone-screen space.

        Uses bilinear inverse mapping (same as phingr-device web UI's
        mapToScreen / perspective.js) to handle camera perspective distortion.
        """
        if not self._screen_rect:
            return cx, cy

        # Screen corners: TL, TR, BR, BL
        quad = self._screen_rect

        # Bilinear inverse: find (u, v) in [0,1] such that
        # Q(u,v) = (1-u)(1-v)*TL + u(1-v)*TR + u*v*BR + (1-u)*v*BL = (cx, cy)
        # Newton's method iteration (matches perspective.js mapToScreen)
        u, v = 0.5, 0.5
        for _ in range(20):
            qx = ((1-u)*(1-v)*quad[0]["x"] + u*(1-v)*quad[1]["x"] +
                  u*v*quad[2]["x"] + (1-u)*v*quad[3]["x"])
            qy = ((1-u)*(1-v)*quad[0]["y"] + u*(1-v)*quad[1]["y"] +
                  u*v*quad[2]["y"] + (1-u)*v*quad[3]["y"])

            ex = cx - qx
            ey = cy - qy
            if abs(ex) < 0.0001 and abs(ey) < 0.0001:
                break

            # Jacobian
            dxdu = (-(1-v)*quad[0]["x"] + (1-v)*quad[1]["x"] +
                    v*quad[2]["x"] - v*quad[3]["x"])
            dxdv = (-(1-u)*quad[0]["x"] - u*quad[1]["x"] +
                    u*quad[2]["x"] + (1-u)*quad[3]["x"])
            dydu = (-(1-v)*quad[0]["y"] + (1-v)*quad[1]["y"] +
                    v*quad[2]["y"] - v*quad[3]["y"])
            dydv = (-(1-u)*quad[0]["y"] - u*quad[1]["y"] +
                    u*quad[2]["y"] + (1-u)*quad[3]["y"])

            det = dxdu * dydv - dxdv * dydu
            if abs(det) < 1e-10:
                break

            u += (dydv * ex - dxdv * ey) / det
            v += (dxdu * ey - dydu * ex) / det

        u = max(0.0, min(1.0, u))
        v = max(0.0, min(1.0, v))

        # Apply calibration correction (acceleration compensation)
        if self._calib_table:
            u_corrected = self._correct_coord(u, self._calib_table.get("tableX", []))
            v_corrected = self._correct_coord(v, self._calib_table.get("tableY", []))
            logger.info(f"camera_to_screen: ({cx:.4f}, {cy:.4f}) → bilinear=({u:.4f}, {v:.4f}) → corrected=({u_corrected:.4f}, {v_corrected:.4f})")
            return (u_corrected, v_corrected)

        logger.info(f"camera_to_screen: ({cx:.4f}, {cy:.4f}) → ({u:.4f}, {v:.4f}) [no calib table]")
        return (u, v)

    async def detect_screen(self) -> list[dict] | None:
        """Detect phone screen region in camera frame. Returns corners (TL, TR, BR, BL)
        as normalized 0-1 coordinates, or None if detection fails."""
        try:
            r = await self.http.post("/api/camera/detect_screen", json={})
            data = r.json()
            if data.get("ok") and data.get("candidates"):
                self._screen_rect = data["candidates"][0]["corners"]
                logger.info(f"Screen detected: {self._screen_rect}")
                return self._screen_rect
        except Exception as e:
            logger.warning(f"Screen detection failed: {e}")
        return None

    def _crop_to_screen(self, jpeg_bytes: bytes) -> bytes:
        """Crop a full camera frame to just the phone screen using cached screen rect."""
        if not self._screen_rect:
            return jpeg_bytes

        img = Image.open(io.BytesIO(jpeg_bytes))
        w, h = img.size

        # Get bounding box from the 4 corners (TL, TR, BR, BL)
        corners = self._screen_rect
        xs = [c["x"] * w for c in corners]
        ys = [c["y"] * h for c in corners]

        left = max(0, int(min(xs)))
        top = max(0, int(min(ys)))
        right = min(w, int(max(xs)))
        bottom = min(h, int(max(ys)))

        if right <= left or bottom <= top:
            return jpeg_bytes

        cropped = img.crop((left, top, right, bottom))

        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    @_handle_device_errors
    async def screenshot(self, crop: bool = True) -> bytes:
        """Capture screenshot, optionally cropped to detected screen region."""
        r = await self.http.get("/api/screenshot")
        r.raise_for_status()
        raw = r.content

        if crop and self._screen_rect:
            return self._crop_to_screen(raw)
        return raw

    @_handle_device_errors
    async def screenshot_raw(self) -> bytes:
        """Capture full uncropped screenshot (no moiré removal)."""
        r = await self.http.get("/api/screenshot")
        r.raise_for_status()
        return r.content

    @_handle_device_errors
    async def tap(self, x: float, y: float, duration_ms: int = 50) -> dict:
        r = await self.http.post("/api/tap", json={"x": x, "y": y, "duration_ms": duration_ms})
        return r.json()

    @_handle_device_errors
    async def swipe(self, x0: float, y0: float, x1: float, y1: float,
                    duration_ms: int = 300, steps: int = 20) -> dict:
        r = await self.http.post("/api/swipe", json={
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "duration_ms": duration_ms, "steps": steps,
        })
        return r.json()

    @_handle_device_errors
    async def type_text(self, text: str, delay_ms: int = 30) -> dict:
        r = await self.http.post("/api/keyboard/type", json={"text": text, "delay_ms": delay_ms})
        return r.json()

    @_handle_device_errors
    async def key(self, key: str, modifiers: list[str] | None = None, duration_ms: int = 50) -> dict:
        payload = {"key": key, "duration_ms": duration_ms}
        if modifiers:
            payload["modifiers"] = modifiers
        r = await self.http.post("/api/keyboard/key", json=payload)
        return r.json()

    @_handle_device_errors
    async def hotkey(self, name: str) -> dict:
        r = await self.http.post("/api/keyboard/hotkey", json={"name": name})
        return r.json()

    @_handle_device_errors
    async def mouse_click(self, button: int = 1, duration_ms: int = 50) -> dict:
        r = await self.http.post("/api/mouse/click", json={"button": button, "duration_ms": duration_ms})
        return r.json()

    @_handle_device_errors
    async def mouse_move(self, dx: int = 0, dy: int = 0) -> dict:
        r = await self.http.post("/api/mouse/move", json={"dx": dx, "dy": dy})
        return r.json()

    @_handle_device_errors
    async def mouse_scroll(self, dy: int = 0, steps: int = 20) -> dict:
        r = await self.http.post("/api/mouse/scroll", json={"dy": dy, "steps": steps})
        return r.json()

