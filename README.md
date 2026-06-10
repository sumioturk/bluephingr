# 👻 phingr — Phantom Finger Remote

**Control your iPhone like a ghost is tapping it.**

Edge-only iPhone remote control and test automation via USB HID. A Raspberry Pi emulates a mouse + keyboard and watches the screen through a camera — no app install, no jailbreak, no cloud, no XCTest. iOS 14+ supported (Android is not — its HID stack rejects the descriptor format used here).

### YAML flows via the web editor

Register UI elements by cropping them from a live camera view, write a declarative YAML flow, and hit Run. The web UI shows the device screen in real time with template-match overlays on every tap.

![phingr YAML flow demo](demo-yaml.gif)

### Dynamic Python scripts with `PhingrSession`

For scripts that need to branch on what's actually on screen, use the async Python API. `find()` returns a bounding box + score, `exists()` returns a bool — write any control flow Python allows.

![phingr Python session demo](demo-py.gif)

## Two Ways to Use phingr

### Option 1: Device Only — Bring Your Own Automation

Use **phingr-device** as a headless mobile control API and build automation with your preferred framework.

```
Your Test Framework (Appium, Mobly, pytest, etc.)
        │
        │ HTTP API
        ▼
┌──────────────────┐         USB HID        ┌──────────┐
│ phingr-device    │─── mouse + keyboard ──▶│  Phone   │
│ (RPi :8080)      │◀── camera capture ─────│          │
│                  │                        └──────────┘
│ POST /api/tap    │
│ POST /api/swipe  │
│ GET  /api/screenshot
│ POST /api/keyboard/type
│ ...              │
└──────────────────┘
```

**You get:** A simple HTTP API for tap, swipe, type, screenshot, calibration. No UI automation framework — just raw device control. Build your own logic on top.

**Best for:** Teams with existing test infrastructure, custom frameworks, or specific language requirements.

```bash
# Setup
sudo bash phingr-device/rpi/setup/bootstrap.sh

# Use from any language
curl -X POST http://phingr-device:8080/api/tap -d '{"x": 0.5, "y": 0.3}'
curl http://phingr-device:8080/api/screenshot -o screen.jpg
```

### Option 2: Device + CLI — Template Matching with YAML DSL

Use **phingr-cli** with **phingr-device** for a complete automation solution with visual element detection.

```
┌──────────────────────────────────────┐
│ phingr-cli (Mac/PC :8800)            │
│                                      │
│  YAML DSL:        Template Matching: │
│  - tapOn: "Settings"  → OpenCV finds │
│  - swipeUntilFound     element by    │
│  - text: "Bluetooth"   pixel pattern │
│  - import, repeat...   (~10ms)       │
│                                      │
│  Web UI:                             │
│  - Flow editor with DSL reference    │
│  - Template registration (drag crop) │
│  - Live execution monitoring         │
│                                      │
│  Python Library:                     │
│  from phingr import PhingrSession    │
└──────────────┬───────────────────────┘
               │ HTTP
               ▼
┌──────────────────┐       USB HID      ┌──────────┐
│ phingr-device    │────────────────────▶│  Phone   │
│ (RPi :8080)      │                     └──────────┘
└──────────────────┘
```

**You get:** Visual element detection via template matching, a Maestro-inspired YAML DSL, a web UI for template registration, and a Python library for programmatic use.

**Best for:** Teams wanting quick automation without writing code, visual regression testing, or cross-device test portability.

```bash
# Setup device
sudo bash phingr-device/rpi/setup/bootstrap.sh

# Setup CLI
cd phingr-cli && bash setup.sh run  # http://localhost:8800
```

```yaml
# flows/open-bluetooth.yaml
name: Open Bluetooth
device: http://phingr-device:8080
---
- pressKey: home
- wait: 1
- swipeUntilFound:
    element: "Settings"
    direction: LEFT
- tapOn: "Settings"
- tapOn: "Bluetooth"
```

```python
# Or use Python
import asyncio
from phingr import PhingrSession

async def main():
    async with PhingrSession(
        server_url="http://localhost:8800",
        device_url="http://phingr-device:8080",
    ) as s:
        await s.press_key("home")
        if await s.exists("Settings"):
            await s.tap_on("Settings")

asyncio.run(main())
```

## Projects

| Directory | What | Port |
|-----------|------|------|
| [`phingr-device/`](phingr-device/) | RPi USB HID controller + camera + HTTP API | 8080 |
| [`phingr-cli/`](phingr-cli/) | YAML DSL engine + web UI + Python library | 8800 |
| [`phingr-web/`](phingr-web/) | Project website | — |

## Device Setup (Required)

Before using phingr, configure the phone. See [phingr-device README](phingr-device/README.md#mobile-device) for detailed steps per OS.

1. **Lock screen auto-rotation**
2. **Enable external pointer support** (iOS: AssistiveTouch + Full Keyboard Access)
3. **Connect phone to RPi** via USB data cable
4. **Calibrate** in the phingr-device web UI (adjust corner handles, run calibration)

## Documentation

- [phingr-cli README](phingr-cli/README.md) — full DSL reference, Python API, web UI docs
- [phingr-device README](phingr-device/README.md) — device setup, HTTP API reference
- [Calibration Guide](phingr-device/docs/calibration.md) — HID cursor calibration
- [HID Notes](phingr-device/docs/ios-hid-notes.md) — USB HID implementation details
- [Third-Party Licenses](THIRD_PARTY_LICENSES.md) — open-source attribution
