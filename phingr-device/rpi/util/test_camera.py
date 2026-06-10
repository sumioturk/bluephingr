#!/usr/bin/env python3
"""test_camera.py — Quick test for the Pi CSI camera.

Captures a single frame and saves it as test_capture.jpg.
Use this to verify the camera works and focus is correct before
running the capture server.

Usage:
    python3 rpi/util/test_camera.py
    python3 rpi/util/test_camera.py --width 1920 --height 1080
"""

import argparse
import time


def main():
    parser = argparse.ArgumentParser(description="Test Pi CSI camera")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--output", default="test_capture.jpg")
    args = parser.parse_args()

    from picamera2 import Picamera2
    from libcamera import controls

    cam = Picamera2()
    config = cam.create_still_configuration(
        main={"size": (args.width, args.height), "format": "RGB888"},
    )
    cam.configure(config)
    cam.start()

    # Enable autofocus
    try:
        cam.set_controls({
            "AfMode": controls.AfModeEnum.Continuous,
            "AfSpeed": controls.AfSpeedEnum.Fast,
        })
        print("Autofocus enabled")
    except Exception as e:
        print(f"Autofocus not available: {e}")

    print("Waiting for auto-exposure and focus to settle ...")
    time.sleep(2)

    print(f"Capturing {args.width}x{args.height} ...")
    cam.capture_file(args.output)
    print(f"Saved to {args.output}")

    cam.stop()
    cam.close()


if __name__ == "__main__":
    main()
