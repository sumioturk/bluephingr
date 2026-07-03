# phingr relay controller — Raspberry Pi Pico 2 W

A stripped-down version of the [`phingr-device/rpi`](../rpi) firmware for the
**Raspberry Pi Pico 2 W** microcontroller. It keeps only three things:

1. **HTTP API to control relays** — same `/api/relay` contract as the RPi
   [`web_server.py`](../rpi/server/web_server.py), so existing clients work unchanged.
2. **WiFi** — connects to the first reachable network from a pre-specified list.
3. **`<hostname>.local`** — a configurable mDNS name, mirroring the RPi's `phingr-XXXX.local`.

There is **no** camera, USB-HID, or libimobiledevice — those are intentionally out of scope.

## Files

| File | Purpose |
|------|---------|
| `config.py`  | Single source of truth: WiFi networks, hostname, relay pins/names, port |
| `wifi.py`    | Sets hostname + mDNS, tries each network in order |
| `relays.py`  | `machine.Pin` relay control (port of the RPi `relay_*` functions) |
| `server.py`  | Minimal `asyncio` HTTP server: `GET/POST /api/relay`, `GET /` |
| `main.py`    | Entrypoint — runs on boot |
| `index.html` | Small browser UI with a toggle button per relay |

## Setup

1. **Flash MicroPython** for the Pico 2 W (RP2350) — download the
   `RPI_PICO2_W` UF2 from <https://micropython.org/download/RPI_PICO2_W/> and copy
   it onto the device in BOOTSEL mode.

2. **Copy the files** to the device root. With
   [`mpremote`](https://docs.micropython.org/en/latest/reference/mpremote.html):
   ```sh
   cd phingr-device/pico
   mpremote fs cp config.py relays.py wifi.py server.py main.py index.html :
   ```
   (Or drag them in with [Thonny](https://thonny.org/).)

3. **Edit `config.py`** — set your real WiFi SSIDs/passwords, the `HOSTNAME`,
   and the `RELAY_PINS` to match your wiring.

4. **Reset the Pico.** Watch the serial console (`mpremote` with no args, or
   Thonny). You should see the connected SSID, the assigned IP, and the
   `<HOSTNAME>.local` URL.

## API

Identical to the RPi version:

```sh
# List all relays and their state
curl http://phingr-pico.local:8080/api/relay
# -> {"ok": true, "available": true, "relays": [{"index":0,"name":"Relay 1","on":false}, ...]}

# Turn relay 0 on
curl -X POST http://phingr-pico.local:8080/api/relay -d '{"index":0,"on":true}'
# -> {"ok": true, "index": 0, "on": true}

# Turn it off
curl -X POST http://phingr-pico.local:8080/api/relay -d '{"index":0,"on":false}'

# Toggle relay 2
curl -X POST http://phingr-pico.local:8080/api/relay -d '{"index":2,"toggle":true}'
```

Or open `http://phingr-pico.local:8080/` in a browser for the toggle UI.

## Notes & caveats

- **Pin numbering:** `RELAY_PINS` are Pico **GP** numbers (see the Pico 2 W pinout),
  **not** the Broadcom BCM numbers used by the RPi version. The default
  `[17, 27, 22, 23]` are convenient general-purpose outputs; change to match your board.
- **`RELAY_ACTIVE_HIGH`:** set `False` for the common optocoupler relay modules that
  energize on LOW.
- **mDNS:** the RP2 MicroPython port has an mDNS responder built into lwIP, so
  `<HOSTNAME>.local` normally resolves. If it doesn't on your build/network, use the
  IP address printed on the serial console instead — that always works.
- **WiFi range/power:** relay control still works locally even if WiFi fails to
  connect; the failure is printed to the serial console.
