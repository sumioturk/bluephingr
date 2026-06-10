# phingr — Fingertip Kit

Edge-only mobile remote control for automated testing. A Raspberry Pi Zero 2W
acts as USB HID mouse + keyboard and captures the device screen via CSI camera.
Everything runs on the Pi — no host PC or mobile app needed.

## Architecture

```
┌──────────┐  USB HID     ┌──────────────────┐
│ Phone    │◄────────────│ RPi Zero 2W      │
│ Device   │  mouse+kbd   │                  │
│          │              │  web_server.py   │──── HTTP :8080
│  screen  │◄──camera────│  (HID + camera   │     (API + UI)
└──────────┘  (CSI/IMX519)│   + calibration) │
                          └──────────────────┘
```

## Quick Start

```bash
git clone --depth=1 https://github.com/sumioturk/phingr.git
sudo bash phingr/rpi/setup/bootstrap.sh
# reboot if prompted, then re-run
```

That's it. One command handles everything.

## Manual Setup

```bash
# Install dependencies
sudo apt install -y python3-picamera2 python3-opencv tesseract-ocr
pip install aiohttp pytesseract

# Enable USB gadget (one-time, then reboot)
echo 'dtoverlay=dwc2,dr_mode=peripheral' | sudo tee -a /boot/firmware/config.txt
echo 'dwc2' | sudo tee -a /etc/modules
echo 'libcomposite' | sudo tee -a /etc/modules
sudo reboot

# Configure HID gadget (mouse + keyboard)
sudo bash rpi/setup/setup_gadget.sh

# Start the web server
sudo python3 rpi/server/web_server.py
```

### Mobile Device

1. Connect to RPi via USB cable (data port, not power)
2. Enable AssistiveTouch: Settings > Accessibility > Touch > AssistiveTouch
3. Enable Full Keyboard Access: Settings > Accessibility > Keyboards > Full Keyboard Access
4. (Optional) Set hot corners for Home, App Switch, etc.

### Access

Open `http://<rpi-ip>:8080` in a browser for the web UI with live camera
preview and control buttons. Or use the JSON API directly.

## API

### Mouse
```bash
curl -X POST http://rpi:8080/api/mouse/click
curl -X POST http://rpi:8080/api/mouse/move -d '{"dx":50,"dy":0}'
curl -X POST http://rpi:8080/api/mouse/move_to -d '{"x":0.5,"y":0.5}'
curl -X POST http://rpi:8080/api/mouse/scroll -d '{"dy":-200}'
curl -X POST http://rpi:8080/api/mouse/reset
curl -X POST http://rpi:8080/api/mouse/corner -d '{"corner":"top_right"}'
```

### Keyboard
```bash
curl -X POST http://rpi:8080/api/keyboard/key -d '{"key":"a"}'
curl -X POST http://rpi:8080/api/keyboard/key -d '{"key":"h","modifiers":["cmd"]}'
curl -X POST http://rpi:8080/api/keyboard/hotkey -d '{"name":"home"}'
curl -X POST http://rpi:8080/api/keyboard/type -d '{"text":"hello world"}'
```

### Tap & Swipe
```bash
curl -X POST http://rpi:8080/api/tap -d '{"x":0.5,"y":0.3}'
curl -X POST http://rpi:8080/api/swipe -d '{"x0":0.5,"y0":0.7,"x1":0.5,"y1":0.3}'
```

### Camera & Calibration
```bash
curl http://rpi:8080/api/screenshot > screen.jpg
curl -X POST http://rpi:8080/api/camera/focus
curl -X POST http://rpi:8080/api/camera/autofocus
curl -X POST http://rpi:8080/api/camera/detect_screen
curl http://rpi:8080/api/calib/handles
curl http://rpi:8080/api/calib/table
```

### External Relays
Four general-purpose relays driven from the Pi's GPIO header (power-cycle the
phone, toggle a charger, switch a camera light, etc.).
```bash
curl http://rpi:8080/api/relay                              # state of all 4
curl -X POST http://rpi:8080/api/relay -d '{"index":0,"on":true}'   # relay 1 ON
curl -X POST http://rpi:8080/api/relay -d '{"index":0,"on":false}'  # relay 1 OFF
curl -X POST http://rpi:8080/api/relay -d '{"index":2,"toggle":true}' # toggle relay 3
```
Relays 1-4 map to BCM GPIO `17, 27, 22, 23`. Polarity is set by
`RELAY_ACTIVE_HIGH` in `web_server.py`: `True` (default) energizes the relay
when the GPIO is driven HIGH (3.3V); set it `False` for the cheap optocoupler
boards that trigger on LOW (0V). If you measure GPIO↔GND, ON should read ~3.3V
and OFF ~0V with the default. If `gpiozero` / GPIO is unavailable the API still
works in a simulated state so the web UI is usable off-device.

#### Wiring (per relay channel)

Powering a 12V load through one relay channel, using a separate 12V adapter for
the load (the Pi only drives the relay's `IN` pin — it does **not** power the
load):

```
12V adapter (+) ──┬──────────────▶ DC+
                  └──────────────▶ COM        (DC+ and COM bridged)
12V adapter (−) ──┬──────────────▶ DC−
Pi GND ───────────┘                            (Pi GND tied to DC−)
Pi GPIO ─────────────────────────▶ IN          (17/27/22/23 → channel 1-4)
NO ──────────────────────────────▶ load (+)
DC− ─────────────────────────────▶ load (−)
```

| Relay board | Connect to |
|-------------|------------|
| `DC+`       | 12V adapter (+) |
| `COM`       | 12V adapter (+) — bridged to `DC+` |
| `DC−`       | 12V adapter (−) **and** Pi `GND` (common ground) |
| `IN`        | Pi GPIO (BCM 17/27/22/23 for relay 1-4) |
| `NO`        | load (+) |
| load (−)    | `DC−` |

Notes:
- The Pi `GND` must share a common ground with the adapter's `DC−`, otherwise
  the relay's `IN` signal has no reference and the channel won't switch.
- `NO` (normally open) means the load is **off** until the relay is energized.
  Use `NC` (normally closed) instead if you need the load on by default.
- Keep the load's 12V power on its own adapter — never back-feed it into the
  Pi's 5V rail.

## Hardware

- Raspberry Pi Zero 2W
- Arducam IMX519 16MP AF camera (or RPi Camera v3) + mini CSI cable
- USB data cable (micro-USB to Lightning/USB-C)
- (Optional) 4-channel relay module wired to BCM GPIO 17/27/22/23

Camera exposure is locked to 1/60s (16667us) to match typical phone screen refresh rates, eliminating moire banding in captured images.

## Project Structure

```
rpi/
├── setup/                  # Installation and configuration
│   ├── bootstrap.sh        # One-shot full setup (run this first)
│   ├── setup_gadget.sh     # USB HID gadget config (mouse + keyboard)
│   ├── teardown_gadget.sh  # Remove USB gadget
│   ├── requirements.txt    # Python dependencies
│   ├── phingr-web.service    # systemd: web server
│   ├── phingr-touch.service  # systemd: TCP HID server (legacy)
│   ├── phingr-capture.service# systemd: TCP camera streamer (legacy)
│   └── phingr-updater.service# systemd: auto-updater
├── server/                 # Runtime services
│   ├── web_server.py       # All-in-one edge server (HID + camera + vision + web UI)
│   ├── touch_server.py     # Standalone TCP HID server (headless use)
│   ├── capture_server.py   # Standalone TCP camera streamer
│   └── updater.py          # Auto-update from GitHub
└── util/                   # Test and debug scripts
    ├── test_mouse.py
    ├── test_keyboard.py
    ├── test_keyboard_led.py
    ├── test_scroll.py
    ├── test_camera.py
    └── ...
```
