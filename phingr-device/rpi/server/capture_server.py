"""capture_server.py — Stream CSI camera frames over TCP.

Captures from the Pi CSI camera (e.g. Arducam IMX519) and streams
JPEG-encoded frames to the host PC. Uses the same wire format as the
ReplayKit source so the host capture client works unchanged.

Wire format (per frame):
    [4 bytes: big-endian uint32 payload length][payload: JPEG data]

Usage:
    sudo python3 rpi/capture_server.py
    sudo python3 rpi/capture_server.py --width 1280 --height 720 --fps 15
    sudo python3 rpi/capture_server.py --width 1920 --height 1080 --fps 10
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import struct
import time
from io import BytesIO

log = logging.getLogger("capture_server")

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7701


class CameraCapture:
    """Captures frames from the Pi CSI camera using picamera2."""

    def __init__(self, width: int = 1280, height: int = 720,
                 fps: int = 15, jpeg_quality: int = 70) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._jpeg_quality = jpeg_quality
        self._camera = None

    def start(self) -> None:
        from picamera2 import Picamera2
        from libcamera import controls

        self._camera = Picamera2()

        config = self._camera.create_still_configuration(
            main={"size": (self._width, self._height), "format": "RGB888"},
        )
        self._camera.configure(config)
        self._camera.start()

        # Enable autofocus (continuous) for close-range screen capture
        try:
            self._camera.set_controls({
                "AfMode": controls.AfModeEnum.Continuous,
                "AfSpeed": controls.AfSpeedEnum.Fast,
            })
            log.info("autofocus enabled (continuous)")
        except Exception as e:
            log.warning("autofocus not available: %s", e)

        # Let auto-exposure settle
        time.sleep(1)
        log.info("camera started: %dx%d @ %dfps, quality=%d",
                 self._width, self._height, self._fps, self._jpeg_quality)

    def stop(self) -> None:
        if self._camera:
            self._camera.stop()
            self._camera.close()
            self._camera = None

    def capture_jpeg(self) -> bytes:
        """Capture a single frame as JPEG bytes."""
        import cv2
        import numpy as np

        arr = self._camera.capture_array()
        # picamera2 returns RGB, OpenCV needs BGR
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        _, jpeg = cv2.imencode(".jpg", bgr,
                               [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
        return jpeg.tobytes()

    @property
    def frame_interval(self) -> float:
        return 1.0 / self._fps


class FrameStreamer:
    """Manages connected clients and streams frames to them."""

    def __init__(self, camera: CameraCapture) -> None:
        self._camera = camera
        self._clients: set[asyncio.StreamWriter] = set()
        self._lock = asyncio.Lock()

    async def add_client(self, writer: asyncio.StreamWriter) -> None:
        async with self._lock:
            self._clients.add(writer)
        addr = writer.get_extra_info("peername")
        log.info("client connected: %s (total: %d)",
                 addr, len(self._clients))

    async def remove_client(self, writer: asyncio.StreamWriter) -> None:
        async with self._lock:
            self._clients.discard(writer)
        addr = writer.get_extra_info("peername")
        log.info("client disconnected: %s (total: %d)",
                 addr, len(self._clients))

    async def stream_loop(self) -> None:
        """Continuously capture frames and send to all clients."""
        while True:
            if not self._clients:
                await asyncio.sleep(0.1)
                continue

            try:
                jpeg_data = await asyncio.get_event_loop().run_in_executor(
                    None, self._camera.capture_jpeg,
                )
            except Exception as e:
                log.error("capture error: %s", e)
                await asyncio.sleep(0.5)
                continue

            header = struct.pack(">I", len(jpeg_data))
            payload = header + jpeg_data

            async with self._lock:
                dead = []
                for writer in self._clients:
                    try:
                        writer.write(payload)
                        await writer.drain()
                    except (ConnectionError, BrokenPipeError, OSError):
                        dead.append(writer)
                for writer in dead:
                    self._clients.discard(writer)
                    try:
                        writer.close()
                    except Exception:
                        pass

            await asyncio.sleep(self._camera.frame_interval)


async def _client_handler(
    streamer: FrameStreamer,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    await streamer.add_client(writer)
    try:
        # Keep connection alive — client just reads frames
        while True:
            data = await reader.read(1024)
            if not data:
                break
    finally:
        await streamer.remove_client(writer)


async def main(width: int, height: int, fps: int, quality: int,
               port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    camera = CameraCapture(width, height, fps, quality)
    camera.start()

    streamer = FrameStreamer(camera)

    server = await asyncio.start_server(
        lambda r, w: _client_handler(streamer, r, w),
        LISTEN_HOST, port,
    )
    log.info("capture server listening on %s:%d", LISTEN_HOST, port)

    # Run frame streaming and server concurrently
    try:
        await asyncio.gather(
            server.serve_forever(),
            streamer.stream_loop(),
        )
    finally:
        camera.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="phingr capture server — stream Pi camera over TCP",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--quality", type=int, default=70,
                        help="JPEG quality 1-100 (default: 70)")
    parser.add_argument("--port", type=int, default=LISTEN_PORT)
    args = parser.parse_args()

    asyncio.run(main(args.width, args.height, args.fps, args.quality,
                     args.port))
