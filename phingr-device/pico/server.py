"""server.py — minimal asyncio HTTP server for relay control.

No aiohttp on the Pico, so this parses HTTP requests off the stream directly.
Exposes the same /api/relay contract as the RPi web_server.py plus a small UI.
"""

import asyncio
import json
import os

import config
import relays

_CORS = (
    "Access-Control-Allow-Origin: *\r\n"
    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
    "Access-Control-Allow-Headers: Content-Type\r\n"
)


async def _send(writer, status, body, content_type="application/json"):
    if isinstance(body, str):
        body = body.encode()
    header = (
        "HTTP/1.1 %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "%s"
        "\r\n" % (status, content_type, len(body), _CORS)
    )
    writer.write(header.encode())
    writer.write(body)
    await writer.drain()


async def _send_json(writer, obj, status="200 OK"):
    await _send(writer, status, json.dumps(obj))


def _handle_relay(method, body):
    """Return (obj, status) for /api/relay — logic ported from the RPi server."""
    if method == "GET":
        return {"ok": True, "available": relays.available(), "relays": relays.state()}, "200 OK"

    # POST: {"index": 0, "on": true} or {"index": 0, "toggle": true}
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "missing/invalid index"}, "400 Bad Request"

    if "toggle" in body:
        on = not relays.is_on(index)
    else:
        on = bool(body.get("on"))

    if not relays.set(index, on):
        return {"ok": False, "error": "invalid relay index"}, "400 Bad Request"
    return {"ok": True, "index": index, "on": on}, "200 OK"


async def _serve_index(writer):
    try:
        os.stat("index.html")
    except OSError:
        await _send(writer, "404 Not Found", "index.html not found", "text/plain")
        return
    with open("index.html", "rb") as f:
        await _send(writer, "200 OK", f.read(), "text/html")


async def _handle_client(reader, writer):
    try:
        request_line = await reader.readline()
        if not request_line:
            return
        try:
            method, path, _ = request_line.decode().split(" ", 2)
        except ValueError:
            await _send(writer, "400 Bad Request", "bad request", "text/plain")
            return

        # Drain headers, note Content-Length for the body.
        content_length = 0
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            lower = line.decode().lower()
            if lower.startswith("content-length:"):
                try:
                    content_length = int(lower.split(":", 1)[1].strip())
                except ValueError:
                    content_length = 0

        body = {}
        if content_length > 0:
            raw = await reader.readexactly(content_length)
            try:
                body = json.loads(raw)
            except Exception:
                body = {}

        # Strip any query string.
        path = path.split("?", 1)[0]

        if method == "OPTIONS":
            await _send(writer, "204 No Content", b"", "text/plain")
        elif path == "/api/relay":
            obj, status = _handle_relay(method, body)
            await _send_json(writer, obj, status)
        elif path == "/" and method == "GET":
            await _serve_index(writer)
        else:
            await _send_json(writer, {"error": "unknown: %s" % path}, "404 Not Found")
    except Exception as e:
        try:
            await _send_json(writer, {"ok": False, "error": str(e)}, "400 Bad Request")
        except Exception:
            pass
    finally:
        try:
            await writer.wait_closed()
        except Exception:
            try:
                writer.close()
            except Exception:
                pass


async def run():
    server = await asyncio.start_server(_handle_client, "0.0.0.0", config.HTTP_PORT)
    print("web server on http://0.0.0.0:%d" % config.HTTP_PORT)
    while True:
        await asyncio.sleep(3600)
