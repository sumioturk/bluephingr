"""Python API for phingr — interactive session with server management.

PhingrSession is the single entry point for Python scripting:
- Execute actions immediately (tap, swipe, find, etc.)
- Branch on results (find / exists)
- Manage server state (list/save/delete flows, templates, runs)
- Export/import bundles

Usage:
    import asyncio
    from phingr import PhingrSession

    async def main():
        async with PhingrSession(
            server_url="http://localhost:8800",
            device_url="http://phingr-device:8080",
        ) as s:
            await s.press_key("home")
            if await s.exists("settings_icon"):
                await s.tap_on("settings_icon")

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class RunResult:
    """Result of a flow execution."""
    run_id: str = ""
    flow_name: str = ""
    status: str = "pending"  # pending, running, success, failed
    current_command: int = 0
    total_commands: int = 0
    log: list[str] = field(default_factory=list)
    started_at: float = 0.0


class PhingrSession:
    """Interactive API for phingr — actions, queries, and server management.

    Two modes:

    1. **Direct (no lock)** — for read-only/CRUD operations. No `async with`:
        s = PhingrSession("http://localhost:8800")
        flows = await s.list_flows()
        await s.close()

    2. **Context manager (with lock)** — for device actions. Acquires the
       single-execution lock so other flows/sessions are blocked:

        async with PhingrSession(server, device) as s:
            await s.press_key("home")
            if await s.exists("settings_icon"):
                await s.tap_on("settings_icon")

    Device actions (tap, swipe, find, etc.) require the lock (use `async with`).
    CRUD methods (list_flows, save_flow, etc.) work without the lock.
    """

    def __init__(self, server_url: str = "http://localhost:8800",
                 device_url: str = "http://localhost:8080",
                 name: str = "session"):
        self.server_url = server_url.rstrip("/")
        self.device_url = device_url
        self.name = name
        self.session_id: str | None = None
        self._http = None
        self._heartbeat_task: asyncio.Task | None = None

    def _client(self):
        if self._http is None:
            import httpx
            self._http = httpx.AsyncClient(base_url=self.server_url, timeout=60.0)
        return self._http

    async def start(self) -> str:
        """Acquire the execution lock. Raises if another flow/session is active."""
        r = await self._client().post("/api/session/start", json={
            "device_url": self.device_url,
            "name": self.name,
        })
        if r.status_code == 409:
            raise RuntimeError(f"Cannot start session: {r.json().get('detail', '')}")
        r.raise_for_status()
        data = r.json()
        self.session_id = data["session_id"]
        # Start heartbeat so the lock doesn't expire while the script is idle
        idle_timeout = data.get("idle_timeout", 30.0)
        interval = max(2.0, idle_timeout / 3)
        self._heartbeat_task = asyncio.create_task(self._heartbeat(interval))
        return self.session_id

    async def _heartbeat(self, interval: float):
        """Ping /session/heartbeat periodically to keep the lock alive."""
        try:
            while self.session_id is not None:
                await asyncio.sleep(interval)
                if self.session_id is None:
                    break
                try:
                    await self._client().post(
                        "/api/session/heartbeat",
                        json={"session_id": self.session_id},
                    )
                except Exception:
                    pass  # transient errors — try again next tick
        except asyncio.CancelledError:
            pass

    async def end(self):
        """Release the execution lock."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        if self.session_id:
            try:
                await self._client().post("/api/session/end",
                                          json={"session_id": self.session_id})
            except Exception:
                pass
            self.session_id = None

    async def close(self):
        await self.end()
        if self._http:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ─────────────────────────────────────────────────────────────────────
    # Device actions (require session lock)
    # ─────────────────────────────────────────────────────────────────────

    async def find(self, element: str, threshold: float | None = None) -> dict | None:
        """Find a template element. Returns match info dict or None.

        Returns dict with keys:
          x, y       — tap point (screen coords, normalized 0-1)
          x1, y1     — top-left of bounding box
          x2, y2     — bottom-right of bounding box
          score      — match confidence (0-1)
        """
        payload = {"element": element, "device_url": self.device_url,
                   "session_id": self.session_id}
        if threshold is not None:
            payload["threshold"] = threshold
        r = await self._client().post("/api/session/find", json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("found"):
            return {k: data[k] for k in data if k not in ("ok", "found")}
        return None

    async def find_text(self, text: str) -> list[dict]:
        """Find text via OCR. Returns list of matches (highest conf first).

        Each match dict has: x, y (center), x1, y1, x2, y2 (bbox),
        score (0-1, normalized from OCR conf), text (detected string),
        conf (raw OCR 0-100).

        Returns empty list if no matches found.
        """
        payload = {"text": text, "device_url": self.device_url,
                   "session_id": self.session_id}
        r = await self._client().post("/api/session/find", json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("matches", [])

    async def exists(self, element: str, threshold: float | None = None) -> bool:
        """Check if a template element is visible on current screen."""
        return await self.find(element, threshold) is not None

    async def exists_text(self, text: str) -> bool:
        """Check if text is visible on current screen (OCR)."""
        return bool(await self.find_text(text))

    async def wait_for(self, element: str, timeout: float = 10.0,
                       poll_interval: float = 0.5,
                       threshold: float | None = None) -> dict | None:
        """Poll until element is found or timeout. Returns match info or None."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = await self.find(element, threshold)
            if m:
                return m
            await asyncio.sleep(poll_interval)
        return None

    async def wait_for_text(self, text: str, timeout: float = 10.0,
                            poll_interval: float = 0.5) -> list[dict]:
        """Poll until text is found or timeout. Returns list of matches (possibly empty)."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            matches = await self.find_text(text)
            if matches:
                return matches
            await asyncio.sleep(poll_interval)
        return []

    async def wait_until_gone(self, element: str, timeout: float = 10.0,
                               poll_interval: float = 0.5,
                               threshold: float | None = None) -> bool:
        """Poll until element disappears or timeout. Returns True if gone."""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not await self.exists(element, threshold):
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def _exec(self, command: dict):
        r = await self._client().post("/api/session/exec", json={
            "command": command,
            "device_url": self.device_url,
            "session_id": self.session_id,
        })
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Command failed: {data.get('error', 'unknown')}")
        return data

    async def tap_on(self, element: str, offset: tuple[float, float] | None = None,
                     surrounding: str = "", threshold: float | None = None):
        val: dict = {"element": element}
        if offset:
            val["offset"] = f"{offset[0]}, {offset[1]}"
        if surrounding:
            val["surrounding"] = surrounding
        if threshold is not None:
            val["threshold"] = threshold
        await self._exec({"tapOn": val})

    async def tap_text(self, text: str, threshold: float | None = None):
        val: dict = {"text": text}
        if threshold is not None:
            val["threshold"] = threshold
        await self._exec({"tapOn": val})

    async def tap(self, x: float, y: float):
        """Tap at normalized screen coordinates (0-1)."""
        await self._exec({"tapOn": f"{x}, {y}"})

    async def click(self, button: int = 1):
        """Click at current cursor position (no movement)."""
        await self._exec({"click": {"button": button}})

    async def long_press(self, element: str, surrounding: str = ""):
        val: dict = {"element": element}
        if surrounding:
            val["surrounding"] = surrounding
        await self._exec({"longPressOn": val})

    async def double_tap(self, element: str, surrounding: str = ""):
        val: dict = {"element": element}
        if surrounding:
            val["surrounding"] = surrounding
        await self._exec({"doubleTapOn": val})

    async def swipe(self, direction: str, times: int = 1):
        await self._exec({"swipe": {"direction": direction, "times": times}})

    async def swipe_coords(self, start: tuple[float, float], end: tuple[float, float]):
        await self._exec({"swipe": {
            "start": f"{start[0]}, {start[1]}",
            "end": f"{end[0]}, {end[1]}",
        }})

    async def swipe_until_found(self, element: str, direction: str = "UP",
                                 max_swipes: int = 10):
        await self._exec({"swipeUntilFound": {
            "element": element,
            "direction": direction,
            "maxSwipes": max_swipes,
        }})

    async def swipe_until_gone(self, element: str, direction: str = "UP",
                                max_swipes: int = 10):
        await self._exec({"swipeUntilGone": {
            "element": element,
            "direction": direction,
            "maxSwipes": max_swipes,
        }})

    async def input_text(self, text: str):
        await self._exec({"inputText": text})

    async def press_key(self, key: str):
        await self._exec({"pressKey": key})

    async def wait(self, seconds: float):
        await self._exec({"wait": seconds})

    async def screenshot(self) -> bytes:
        """Get current device screenshot (JPEG bytes)."""
        r = await self._client().get(
            "/api/device/screenshot",
            params={"url": self.device_url},
        )
        r.raise_for_status()
        return r.content

    # ---- Low-level device access ----

    async def _device_call(self, method: str, *args, **kwargs) -> dict:
        r = await self._client().post("/api/session/device_call", json={
            "method": method,
            "args": list(args),
            "kwargs": kwargs,
            "device_url": self.device_url,
            "session_id": self.session_id,
        })
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"device_call({method}) failed: {data.get('error')}")
        return data.get("result")

    async def key(self, key: str, modifiers: list[str] | None = None, duration_ms: int = 50):
        """Press a single key with optional modifiers (e.g. ['cmd', 'shift'])."""
        await self._device_call("key", key, modifiers=modifiers, duration_ms=duration_ms)

    async def hotkey(self, name: str):
        """Press a named hotkey (home, app_switch, spotlight, copy, paste, ...)."""
        await self._device_call("hotkey", name)

    async def mouse_click(self, button: int = 1, duration_ms: int = 50):
        """Click at current cursor position."""
        await self._device_call("mouse_click", button=button, duration_ms=duration_ms)

    async def mouse_move(self, dx: int = 0, dy: int = 0):
        """Move cursor by a delta in raw HID units."""
        await self._device_call("mouse_move", dx=dx, dy=dy)

    async def mouse_scroll(self, dy: int = 0, steps: int = 20):
        """Scroll the mouse wheel (dy < 0 = down, dy > 0 = up)."""
        await self._device_call("mouse_scroll", dy=dy, steps=steps)

    async def detect_screen(self) -> list | None:
        """Re-detect the phone screen region via camera. Returns corners or None."""
        return await self._device_call("detect_screen")

    async def fetch_calibration(self):
        """Reload calibration (handles + table) from the device server."""
        await self._device_call("fetch_calibration")

    # ─────────────────────────────────────────────────────────────────────
    # Server management (no lock required)
    # ─────────────────────────────────────────────────────────────────────

    # ---- Flow CRUD ----

    async def list_flows(self) -> list[dict]:
        """List all flows on the server."""
        r = await self._client().get("/api/flows")
        r.raise_for_status()
        return r.json()

    async def get_flow(self, filename: str) -> str:
        """Get flow YAML content."""
        r = await self._client().get(f"/api/flows/{filename}")
        r.raise_for_status()
        return r.text

    async def save_flow(self, filename: str, yaml_content: str) -> dict:
        """Save a flow YAML to the server."""
        r = await self._client().put(
            f"/api/flows/{filename}",
            content=yaml_content,
            headers={"Content-Type": "text/yaml"},
        )
        r.raise_for_status()
        return r.json()

    async def delete_flow(self, filename: str):
        """Delete a flow."""
        r = await self._client().delete(f"/api/flows/{filename}")
        r.raise_for_status()

    # ---- Run saved flow (blocks until complete) ----

    async def run_flow(self, filename: str, poll_interval: float = 1.0,
                       log_callback=None) -> RunResult:
        """Run a saved flow by filename and wait for completion.

        Note: cannot be called from inside a session context (lock conflict).
        """
        if self.session_id is not None:
            raise RuntimeError(
                "run_flow cannot be called inside an active session "
                "(lock conflict). Call it outside `async with`."
            )
        r = await self._client().post(f"/api/flows/{filename}/run")
        if r.status_code == 409:
            raise RuntimeError(f"Flow already running: {r.json().get('detail', '')}")
        r.raise_for_status()
        run_id = r.json()["run_id"]

        # Poll until done
        while True:
            status = await self.get_run_status(run_id)
            if status is None:
                raise RuntimeError(f"Run {run_id} not found")
            if log_callback:
                log_callback(f"[{status.current_command+1}/{status.total_commands}] {status.status}")
            if status.status in ("success", "failed"):
                return status
            await asyncio.sleep(poll_interval)

    # ---- Run management ----

    async def list_runs(self) -> list[RunResult]:
        """List all runs from the server."""
        r = await self._client().get("/api/runs")
        r.raise_for_status()
        return [
            RunResult(
                run_id=run["run_id"],
                flow_name=run["flow_name"],
                status=run["status"],
                current_command=run["current_command"],
                total_commands=run["total_commands"],
                started_at=run["started_at"],
            )
            for run in r.json()
        ]

    async def get_run_status(self, run_id: str) -> RunResult | None:
        """Get current status of a run."""
        r = await self._client().get("/api/runs")
        r.raise_for_status()
        for run in r.json():
            if run["run_id"] == run_id:
                return RunResult(
                    run_id=run["run_id"],
                    flow_name=run["flow_name"],
                    status=run["status"],
                    current_command=run["current_command"],
                    total_commands=run["total_commands"],
                    started_at=run["started_at"],
                )
        return None

    async def stop_run(self, run_id: str) -> bool:
        """Stop a running flow."""
        r = await self._client().post(f"/api/runs/{run_id}/stop")
        return r.status_code == 200

    async def delete_run(self, run_id: str):
        """Delete a run from history."""
        r = await self._client().delete(f"/api/runs/{run_id}")
        r.raise_for_status()

    # ---- Template CRUD ----

    async def list_templates(self) -> list[dict]:
        """List registered templates."""
        r = await self._client().get("/api/templates")
        r.raise_for_status()
        return r.json()

    async def get_template_image(self, name: str) -> bytes:
        """Get template image bytes."""
        r = await self._client().get(f"/api/templates/{name}/image")
        r.raise_for_status()
        return r.content

    async def delete_template(self, name: str):
        """Delete a template."""
        r = await self._client().delete(f"/api/templates/{name}")
        r.raise_for_status()

    # ---- Export / Import ----

    async def export_all(self) -> bytes:
        """Export all flows + templates + calibration as zip bytes."""
        r = await self._client().get("/api/export-all")
        r.raise_for_status()
        return r.content

    async def import_all(self, zip_bytes: bytes, filename: str = "import.zip") -> dict:
        """Import flows + templates + calibration from zip bytes."""
        r = await self._client().post(
            "/api/import-all",
            files={"file": (filename, zip_bytes, "application/zip")},
        )
        r.raise_for_status()
        return r.json()
