"""FastAPI route definitions for phingr-cli."""

import asyncio
import io
import json
import logging
import time
import zipfile

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, Response

from . import config
from .dsl import parse_flow, DSL_VERSION
from .engine import Engine
from .phingr_client import FkiosClient
from .template_matcher import TemplateMatcher

logger = logging.getLogger("phingr-cli")

router = APIRouter(prefix="/api")

# ---- Shared state ----

_runs: dict[str, dict] = {}  # run_id → {engine, filename, started_at}
_run_counter = 0
_device_clients: dict[str, FkiosClient] = {}
_matcher = TemplateMatcher(config.DATA_DIR / "templates")


def get_device_client(device_url: str) -> FkiosClient:
    if device_url not in _device_clients:
        _device_clients[device_url] = FkiosClient(base_url=device_url)
    return _device_clients[device_url]


# ---- Flows CRUD ----

@router.get("/flows")
async def list_flows():
    flows = []
    if config.FLOWS_DIR.exists():
        for f in sorted(config.FLOWS_DIR.glob("*.yaml")):
            try:
                flow = parse_flow(f.read_text(), flows_dir=str(config.FLOWS_DIR))
                flows.append({
                    "filename": f.stem,
                    "name": flow.name,
                    "device_url": flow.device_url,
                    "command_count": len(flow.commands),
                })
            except Exception as e:
                flows.append({
                    "filename": f.stem,
                    "name": f"(parse error: {e})",
                    "device_url": "",
                    "command_count": 0,
                })
    return JSONResponse(flows)


@router.get("/flows/{filename}")
async def get_flow(filename: str):
    path = config.FLOWS_DIR / f"{filename}.yaml"
    if not path.exists():
        raise HTTPException(404, "Flow not found")
    return Response(content=path.read_text(), media_type="text/yaml")


@router.put("/flows/{filename}")
async def save_flow(filename: str, request: Request):
    body = await request.body()
    yaml_text = body.decode("utf-8")
    try:
        flow = parse_flow(yaml_text, flows_dir=str(config.FLOWS_DIR))
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    path = config.FLOWS_DIR / f"{filename}.yaml"
    path.write_text(yaml_text)
    return JSONResponse({"ok": True, "name": flow.name, "command_count": len(flow.commands)})


@router.delete("/flows/{filename}")
async def delete_flow(filename: str):
    path = config.FLOWS_DIR / f"{filename}.yaml"
    if not path.exists():
        raise HTTPException(404, "Flow not found")
    path.unlink()
    return JSONResponse({"ok": True})


@router.post("/flows/{filename}/validate")
async def validate_flow(filename: str):
    path = config.FLOWS_DIR / f"{filename}.yaml"
    if not path.exists():
        raise HTTPException(404, "Flow not found")
    try:
        flow = parse_flow(path.read_text(), flows_dir=str(config.FLOWS_DIR))
        return JSONResponse({
            "ok": True,
            "name": flow.name,
            "device_url": flow.device_url,
            "command_count": len(flow.commands),
            "commands": [str(c) for c in flow.commands],
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


# ---- Export / Import ----

@router.get("/export-all")
async def export_all():
    """Export all flows + all templates as a single zip bundle."""
    templates_dir = config.DATA_DIR / "templates"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # All flows
        flow_count = 0
        if config.FLOWS_DIR.exists():
            for f in config.FLOWS_DIR.glob("*.yaml"):
                zf.write(f, f"flows/{f.name}")
                flow_count += 1

        # All templates
        template_count = 0
        if templates_dir.exists():
            meta_path = templates_dir / "templates.json"
            if meta_path.exists():
                zf.write(meta_path, "templates/templates.json")
            for img in templates_dir.glob("*.png"):
                zf.write(img, f"templates/{img.name}")
                template_count += 1
            for img in templates_dir.glob("*.jpg"):
                zf.write(img, f"templates/{img.name}")
                template_count += 1

        # Calibration data (handles + acceleration table)
        calib = {}
        # Try to get from connected device client
        for client in _device_clients.values():
            if client._screen_rect:
                calib["handles"] = client._screen_rect
            if client._calib_table:
                calib["table"] = client._calib_table
            break
        # Fallback: local screen_rect.json
        if not calib.get("handles"):
            rect_file = config.DATA_DIR / "screen_rect.json"
            if rect_file.exists():
                calib["handles"] = json.loads(rect_file.read_text())
        if calib:
            zf.writestr("calibration.json", json.dumps(calib, indent=2))

        # Metadata
        zf.writestr("meta.json", json.dumps({
            "dsl_version": DSL_VERSION,
            "flows": flow_count,
            "templates": template_count,
            "has_calibration": bool(calib),
        }, indent=2))

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="phingr-export.zip"'},
    )


@router.post("/import-all")
async def import_all(file: UploadFile = File(...)):
    """Import all flows + templates from a zip bundle."""
    data = await file.read()
    templates_dir = config.DATA_DIR / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    config.FLOWS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        flow_count = 0
        template_count = 0

        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            for entry in zf.namelist():
                # Flows
                if entry.startswith("flows/") and entry.endswith(".yaml"):
                    fname = entry.split("/", 1)[1]
                    if fname:
                        (config.FLOWS_DIR / fname).write_bytes(zf.read(entry))
                        flow_count += 1

                # Template metadata
                elif entry == "templates/templates.json":
                    meta_path = templates_dir / "templates.json"
                    existing = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                    bundle_meta = json.loads(zf.read(entry).decode("utf-8"))
                    existing.update(bundle_meta)
                    meta_path.write_text(json.dumps(existing, indent=2))

                # Template images
                elif entry.startswith("templates/"):
                    fname = entry.split("/", 1)[1]
                    if fname:
                        (templates_dir / fname).write_bytes(zf.read(entry))
                        template_count += 1

                # Calibration data
                elif entry == "calibration.json":
                    calib = json.loads(zf.read(entry).decode("utf-8"))
                    # Save locally
                    calib_file = config.DATA_DIR / "calibration.json"
                    calib_file.write_text(json.dumps(calib, indent=2))
                    if calib.get("handles"):
                        rect_file = config.DATA_DIR / "screen_rect.json"
                        rect_file.write_text(json.dumps(calib["handles"]))
                    # Apply to connected clients + push to device
                    for client in _device_clients.values():
                        if calib.get("handles"):
                            client._screen_rect = calib["handles"]
                            try:
                                await client.http.post("/api/calib/handles",
                                    json={"handles": calib["handles"]})
                            except Exception:
                                pass
                        if calib.get("table"):
                            client._calib_table = calib["table"]
                            try:
                                await client.http.post("/api/calib/table",
                                    json=calib["table"])
                            except Exception:
                                pass

                # Legacy single-flow format (flow.yaml at root)
                elif entry == "flow.yaml":
                    flow_name = file.filename.replace(".zip", "") if file.filename else "imported"
                    (config.FLOWS_DIR / f"{flow_name}.yaml").write_bytes(zf.read(entry))
                    flow_count += 1

        has_calib = (config.DATA_DIR / "calibration.json").exists()
        return JSONResponse({
            "ok": True,
            "flows_imported": flow_count,
            "templates_imported": template_count,
            "calibration_restored": has_calib,
        })
    except Exception as e:
        raise HTTPException(400, f"Import failed: {e}")


# ---- Runs ----

@router.get("/runs")
async def list_runs():
    result = []
    for run_id, entry in sorted(_runs.items(), key=lambda x: x[1]["started_at"], reverse=True):
        engine = entry["engine"]
        result.append({
            "run_id": run_id,
            "filename": entry["filename"],
            "flow_name": engine.flow.name,
            "status": engine.status,
            "current_command": engine.current_command,
            "total_commands": len(engine.flow.commands),
            "started_at": entry["started_at"],
        })
    return JSONResponse(result)


@router.post("/flows/{filename}/run")
async def run_flow(filename: str):
    global _run_counter
    path = config.FLOWS_DIR / f"{filename}.yaml"
    if not path.exists():
        raise HTTPException(404, "Flow not found")

    # Only one flow at a time
    for rid, entry in _runs.items():
        if entry["engine"].running:
            raise HTTPException(409, f"Flow already running: {entry['engine'].flow.name} ({rid})")
    _expire_session_if_idle()
    if _active_session is not None:
        raise HTTPException(409, f"Interactive session active: {_active_session['session_id']}")

    flow = parse_flow(path.read_text(), flows_dir=str(config.FLOWS_DIR))
    device_url = flow.device_url or config.PHINGR_DEVICE_URL
    client = get_device_client(device_url)

    _run_counter += 1
    run_id = f"{filename}_{_run_counter}"

    engine = Engine(flow=flow, phingr=client)
    _runs[run_id] = {
        "engine": engine,
        "filename": filename,
        "started_at": time.time(),
    }

    task = asyncio.create_task(engine.run())
    task.add_done_callback(lambda t: _on_run_done(t, run_id))
    return JSONResponse({"ok": True, "run_id": run_id, "flow": flow.name})


def _on_run_done(task: asyncio.Task, run_id: str):
    if task.cancelled():
        logger.warning(f"Run {run_id} cancelled")
    elif task.exception():
        logger.exception(f"Run {run_id} failed", exc_info=task.exception())


@router.get("/runs/{run_id}/status")
async def run_status(run_id: str):
    entry = _runs.get(run_id)
    if not entry:
        raise HTTPException(404, "Run not found")

    async def event_stream():
        engine = entry["engine"]
        while True:
            status = engine.get_status()
            yield f"data: {json.dumps(status.model_dump())}\n\n"
            if status.status in ("success", "failed"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/annotated")
async def run_annotated(run_id: str):
    entry = _runs.get(run_id)
    if not entry or not entry["engine"].last_annotated:
        raise HTTPException(404, "No annotated screenshot")
    return Response(content=entry["engine"].last_annotated, media_type="image/jpeg")


@router.post("/runs/{run_id}/stop")
async def run_stop(run_id: str):
    entry = _runs.get(run_id)
    if not entry:
        return JSONResponse({"ok": True, "message": "Run not found"})
    entry["engine"].stop()
    return JSONResponse({"ok": True})


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    if run_id in _runs:
        e = _runs[run_id]["engine"]
        if e.running:
            e.stop()
        del _runs[run_id]
    return JSONResponse({"ok": True})


# Back-compat: old /flows/{filename}/run/* endpoints
@router.get("/flows/{filename}/run/status")
async def run_status_compat(filename: str):
    for rid, e in reversed(list(_runs.items())):
        if e["filename"] == filename:
            return await run_status(rid)
    raise HTTPException(404, "No run for this flow")

@router.get("/flows/{filename}/run/annotated")
async def run_annotated_compat(filename: str):
    for rid, e in reversed(list(_runs.items())):
        if e["filename"] == filename:
            return await run_annotated(rid)
    raise HTTPException(404, "No annotated screenshot")

@router.post("/flows/{filename}/run/stop")
async def run_stop_compat(filename: str):
    for rid, e in reversed(list(_runs.items())):
        if e["filename"] == filename and e["engine"].running:
            return await run_stop(rid)
    return JSONResponse({"ok": True})


# ---- Device proxy ----

@router.get("/device/resolve")
async def resolve_device_url(url: str = ""):
    """Resolve .local hostnames to IP for clients that lack mDNS (e.g. Android)."""
    import socket
    from urllib.parse import urlparse, urlunparse
    device_url = url or config.PHINGR_DEVICE_URL
    parsed = urlparse(device_url)
    try:
        ip = socket.gethostbyname(parsed.hostname)
        resolved = urlunparse(parsed._replace(netloc=f"{ip}:{parsed.port}" if parsed.port else ip))
        return JSONResponse({"ok": True, "url": resolved})
    except socket.gaierror:
        return JSONResponse({"ok": True, "url": device_url})


# ---- Interactive Session API ----
# For dynamic Python scripts that branch based on UI state.
# Sessions share the "one flow at a time" lock with regular runs.
# Sessions auto-expire after SESSION_IDLE_TIMEOUT seconds of inactivity
# so a crashed client doesn't hold the lock forever.

SESSION_IDLE_TIMEOUT = 30.0  # seconds — auto-unlock if no activity

_active_session: dict | None = None  # {session_id, device_url, started_at, last_activity}


def _expire_session_if_idle():
    """Clear the session if it has been idle longer than SESSION_IDLE_TIMEOUT."""
    global _active_session
    if _active_session is None:
        return
    idle = time.time() - _active_session["last_activity"]
    if idle > SESSION_IDLE_TIMEOUT:
        logger.warning(
            f"Session {_active_session['session_id']} expired after "
            f"{idle:.0f}s idle (timeout {SESSION_IDLE_TIMEOUT}s)"
        )
        _active_session = None


def _touch_session():
    """Update the last_activity timestamp for the current session."""
    if _active_session is not None:
        _active_session["last_activity"] = time.time()


def _session_is_active() -> bool:
    _expire_session_if_idle()
    return _active_session is not None


def _get_session_context(device_url: str):
    """Build an ExecutionContext for one-shot session calls."""
    from .dsl import ExecutionContext
    client = get_device_client(device_url)
    return ExecutionContext(
        phingr=client,
        matcher=_matcher,
        log=lambda m: None,
        stop_requested=lambda: False,
    )


@router.post("/session/start")
async def session_start(request: Request):
    """Acquire the execution lock for an interactive session.

    Body: {device_url?: str, name?: str}
    Returns: {ok: bool, session_id: str} or 409 if another flow/session is running
    """
    global _active_session
    body = await request.json() if await request.body() else {}
    device_url = body.get("device_url") or config.PHINGR_DEVICE_URL
    name = body.get("name", "session")

    # Expire stale session (crashed client)
    _expire_session_if_idle()

    # Check if any flow is running
    for rid, entry in _runs.items():
        if entry["engine"].running:
            raise HTTPException(409, f"Flow already running: {entry['engine'].flow.name} ({rid})")

    # Check if another session is active
    if _active_session is not None:
        raise HTTPException(409, f"Session already active: {_active_session['session_id']}")

    import uuid
    now = time.time()
    session_id = f"session_{uuid.uuid4().hex[:8]}"
    _active_session = {
        "session_id": session_id,
        "device_url": device_url,
        "name": name,
        "started_at": now,
        "last_activity": now,
    }
    logger.info(f"Session started: {session_id} ({name}) — timeout {SESSION_IDLE_TIMEOUT}s")
    return JSONResponse({"ok": True, "session_id": session_id,
                          "idle_timeout": SESSION_IDLE_TIMEOUT})


@router.post("/session/end")
async def session_end(request: Request):
    """Release the execution lock."""
    global _active_session
    body = await request.json() if await request.body() else {}
    session_id = body.get("session_id")
    if _active_session and session_id and _active_session["session_id"] != session_id:
        raise HTTPException(403, f"Session mismatch: {session_id}")
    if _active_session:
        logger.info(f"Session ended: {_active_session['session_id']}")
    _active_session = None
    return JSONResponse({"ok": True})


@router.post("/session/device_call")
async def session_device_call(request: Request):
    """Call any method on the FkiosClient (low-level device access).

    Body: {method: str, args?: list, kwargs?: dict,
           device_url?: str, session_id?: str}
    Returns: {ok: bool, result?: any}

    Allowed methods: key, hotkey, type_text, mouse_click, mouse_move,
    mouse_scroll, tap, swipe, detect_screen, fetch_calibration
    """
    ALLOWED = {
        "key", "hotkey", "type_text", "mouse_click", "mouse_move",
        "mouse_scroll", "tap", "swipe", "detect_screen", "fetch_calibration",
    }
    body = await request.json()
    _check_session(body)
    method = body.get("method", "")
    if method not in ALLOWED:
        raise HTTPException(400, f"Method not allowed: {method}")

    device_url = body.get("device_url") or config.PHINGR_DEVICE_URL
    client = get_device_client(device_url)
    args = body.get("args") or []
    kwargs = body.get("kwargs") or {}

    fn = getattr(client, method, None)
    if fn is None:
        raise HTTPException(400, f"Unknown method: {method}")

    try:
        result = await fn(*args, **kwargs)
        # Bytes aren't JSON-serializable — return length instead
        if isinstance(result, bytes):
            result = {"bytes": len(result)}
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=400)


@router.post("/session/heartbeat")
async def session_heartbeat(request: Request):
    """Keep the current session alive. Updates last_activity."""
    body = await request.json() if await request.body() else {}
    _expire_session_if_idle()
    if _active_session is None:
        raise HTTPException(410, "Session expired or ended")
    sid = body.get("session_id")
    if sid and sid != _active_session["session_id"]:
        raise HTTPException(403, "Session ID mismatch")
    _touch_session()
    return JSONResponse({"ok": True})


@router.get("/session/status")
async def session_status():
    """Get current active session info."""
    _expire_session_if_idle()
    if _active_session is None:
        return JSONResponse({"active": False})
    now = time.time()
    return JSONResponse({
        "active": True,
        **_active_session,
        "idle_seconds": round(now - _active_session["last_activity"], 1),
        "idle_timeout": SESSION_IDLE_TIMEOUT,
    })


def _check_session(body: dict):
    """Validate the session_id in a request body and update last_activity.

    Raises 403 if mismatched. Auto-expires stale sessions.
    """
    _expire_session_if_idle()
    if _active_session is None:
        return  # allow lockless session calls (backward compat)
    sid = body.get("session_id")
    if sid and sid != _active_session["session_id"]:
        raise HTTPException(403, "Session ID mismatch")
    _touch_session()


@router.post("/session/find")
async def session_find(request: Request):
    """Find an element or text on the current screen. Returns bbox or null.

    Body: {element?: str, text?: str, threshold?: float,
           device_url?: str, session_id?: str}
    Provide either `element` (template match) or `text` (OCR).
    Returns: {ok, found, x, y, x1, y1, x2, y2, score}
             where (x, y) is the tap/center point in screen coords
             and (x1,y1)-(x2,y2) is the bounding box in screen coords
    """
    body = await request.json()
    _check_session(body)
    element = body.get("element", "")
    text = body.get("text", "")
    threshold = body.get("threshold")
    device_url = body.get("device_url") or config.PHINGR_DEVICE_URL

    if not element and not text:
        raise HTTPException(400, "Must provide either 'element' or 'text'")

    client = get_device_client(device_url)
    if not client._screen_rect:
        await client.fetch_calibration()

    try:
        img = await client.screenshot(crop=False)
    except Exception as e:
        raise HTTPException(503, f"Device unreachable: {e}")

    if not _matcher:
        return JSONResponse({"ok": False, "error": "no matcher"})

    # Template match gives full bbox; OCR currently only returns point
    if element:
        bbox = _matcher.find_bbox(img, element, threshold=threshold)
        if bbox is None:
            return JSONResponse({"ok": True, "found": False})
        # Map all four corners + center to screen coords
        sx1, sy1 = client.camera_to_screen(bbox["x1"], bbox["y1"])
        sx2, sy2 = client.camera_to_screen(bbox["x2"], bbox["y2"])
        sx, sy = client.camera_to_screen(bbox["cx"], bbox["cy"])
        return JSONResponse({
            "ok": True, "found": True,
            "x": sx, "y": sy,
            "x1": sx1, "y1": sy1, "x2": sx2, "y2": sy2,
            "score": bbox["score"],
        })
    else:
        all_matches = _matcher.find_all_text_bbox(img, text)
        if not all_matches:
            return JSONResponse({"ok": True, "found": False, "matches": []})
        out = []
        for bbox in all_matches:
            sx1, sy1 = client.camera_to_screen(bbox["x1"], bbox["y1"])
            sx2, sy2 = client.camera_to_screen(bbox["x2"], bbox["y2"])
            sx, sy = client.camera_to_screen(bbox["cx"], bbox["cy"])
            out.append({
                "x": sx, "y": sy,
                "x1": sx1, "y1": sy1, "x2": sx2, "y2": sy2,
                "score": round(bbox["conf"] / 100.0, 3),
                "text": bbox["text"],
                "conf": bbox["conf"],
            })
        # Also echo the best (first) match at top level for convenience
        best = out[0]
        return JSONResponse({
            "ok": True, "found": True,
            "matches": out,
            **best,
        })


@router.post("/session/exec")
async def session_exec(request: Request):
    """Execute a single command immediately. Returns success or error.

    Body: {command: dict, device_url?: str}
    where `command` is a single DSL command dict, e.g. {"tapOn": "Settings"}
    """
    from .dsl import _parse_command, CommandError
    body = await request.json()
    _check_session(body)
    cmd_dict = body.get("command", {})
    device_url = body.get("device_url") or config.PHINGR_DEVICE_URL

    ctx = _get_session_context(device_url)
    if not ctx.phingr._screen_rect:
        await ctx.phingr.fetch_calibration()

    try:
        cmd = _parse_command(cmd_dict)
        await cmd.execute(ctx)
        return JSONResponse({"ok": True})
    except CommandError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)


@router.get("/device/screenshot")
async def device_screenshot(url: str = ""):
    device_url = url or config.PHINGR_DEVICE_URL
    client = get_device_client(device_url)
    try:
        img = await client.screenshot(crop=False)
    except Exception as e:
        raise HTTPException(503, f"Device unreachable: {e}")
    return Response(content=img, media_type="image/jpeg")


# ---- Device sync ----

@router.post("/device/sync-handles")
async def sync_handles(url: str = ""):
    device_url = url or config.PHINGR_DEVICE_URL
    client = get_device_client(device_url)
    if not client._screen_rect:
        await client.fetch_calibration()
    return JSONResponse({"ok": True, "has_rect": client._screen_rect is not None})


# ---- Screen Rect ----

@router.post("/device/screen-rect")
async def set_screen_rect(request: Request):
    body = await request.json()
    x1, y1 = float(body["x1"]), float(body["y1"])
    x2, y2 = float(body["x2"]), float(body["y2"])
    rect = [{"x": x1, "y": y1}, {"x": x2, "y": y1}, {"x": x2, "y": y2}, {"x": x1, "y": y2}]
    rect_file = config.DATA_DIR / "screen_rect.json"
    rect_file.write_text(json.dumps(rect))
    for client in _device_clients.values():
        client._screen_rect = rect
    return JSONResponse({"ok": True, "rect": rect})

@router.get("/device/screen-rect")
async def get_screen_rect():
    rect_file = config.DATA_DIR / "screen_rect.json"
    if rect_file.exists():
        return JSONResponse({"ok": True, "rect": json.loads(rect_file.read_text())})
    return JSONResponse({"ok": True, "rect": None})


# ---- Templates ----

@router.get("/templates")
async def list_templates():
    return JSONResponse(_matcher.list_templates())

@router.get("/templates/{name}/image")
async def get_template_image(name: str):
    for ext in (".png", ".jpg"):
        path = _matcher.templates_dir / f"{name}{ext}"
        if path.exists():
            ct = "image/png" if ext == ".png" else "image/jpeg"
            return Response(content=path.read_bytes(), media_type=ct)
    raise HTTPException(404, "Template image not found")

@router.post("/templates/{name}")
async def save_template(name: str, request: Request):
    body = await request.json()
    device_url = body.get("device_url", config.PHINGR_DEVICE_URL)
    client = get_device_client(device_url)
    try:
        img = await client.screenshot(crop=False)
    except Exception as e:
        raise HTTPException(503, f"Device unreachable: {e}")
    tap_offset = (float(body.get("tap_offset_x", 0.5)), float(body.get("tap_offset_y", 0.5)))
    result = _matcher.save_template(
        name=name, image_bytes=img,
        x1=float(body["x1"]), y1=float(body["y1"]),
        x2=float(body["x2"]), y2=float(body["y2"]),
        tap_offset=tap_offset,
    )
    return JSONResponse({"ok": True, **result})

@router.delete("/templates/{name}")
async def delete_template(name: str):
    _matcher.delete_template(name)
    return JSONResponse({"ok": True})

@router.post("/templates/{name}/test")
async def test_template(name: str, request: Request):
    body = await request.json()
    device_url = body.get("device_url", config.PHINGR_DEVICE_URL)
    client = get_device_client(device_url)
    try:
        img = await client.screenshot(crop=False)
    except Exception as e:
        raise HTTPException(503, f"Device unreachable: {e}")
    coords, annotated_img = _matcher.find_and_annotate(img, name)
    if coords:
        return Response(content=annotated_img, media_type="image/jpeg",
                        headers={"X-Match-X": str(coords[0]), "X-Match-Y": str(coords[1])})
    return Response(content=annotated_img, media_type="image/jpeg",
                    headers={"X-Match-Found": "false"})
