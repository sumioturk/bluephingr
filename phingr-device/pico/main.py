"""main.py — phingr Pico relay controller entrypoint.

Runs automatically on boot (MicroPython executes main.py after boot.py).
Brings up WiFi, initializes the relays, then serves the HTTP API.
"""

import asyncio
import sys

import config
import relays
import server
import wifi


def _main():
    print("=" * 44)
    print(" phingr relay controller — Pico 2 W")
    print("=" * 44)

    relays.init()

    ip = wifi.connect()
    if ip is None:
        # Keep serving anyway on any interface we might have; relay control
        # still works locally, and this makes failures visible over serial.
        print("WARNING: no WiFi — HTTP server may be unreachable")

    asyncio.run(server.run())


try:
    _main()
except KeyboardInterrupt:
    print("stopped")
except Exception as e:
    # Print the traceback so it's visible over the USB serial console / Thonny.
    sys.print_exception(e)
    raise
