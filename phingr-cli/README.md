# phingr-cli — Mobile UI Automation

YAML DSL + Python library for mobile UI automation via phingr-device. Uses **OpenCV template matching** to find UI elements by pixel pattern, and optional **OCR** (Tesseract) for text-based element finding.

## Quick Start

### Web UI

```bash
cd phingr-cli
bash setup.sh run    # http://localhost:8800
```

OCR text matching (`tapOn: {text: "Bluetooth"}`) requires Tesseract — installed automatically by `setup.sh`.

### Python Library

```bash
pip install -e .
```

```python
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
```

## How It Works

1. **Register templates**: Crop UI elements from device screenshots in the web UI
2. **Write flows**: YAML DSL referencing templates by name
3. **Execute**: Template matching finds elements (~10ms), taps at the matched position

```
YAML Flow → DSL Engine → phingr-device (RPi) → Phone
                │
                ├─ tapOn: "0.5, 0.3"     → coordinates (instant)
                ├─ tapOn: "Settings"     → template match (~10ms)
                └─ tapOn: {text: "BT"}   → OCR text match (~500ms)
```

### Template Matching

- **Dual matching**: grayscale + Canny edge detection (configurable per-template: `normal`, `edge`, or `both`)
- **Multi-scale**: matches at 0.8x to 1.2x scale to handle camera distance variations
- **Per-template metadata**: `threshold` (match score, default 0.8), `match_mode`, `tap_offset`

## DSL Reference (v1.2)

### Flow Header

```yaml
name: My Flow
device: http://phingr-device:8080
---
```

### Tap

```yaml
# By template name
- tapOn: "Settings"

# By OCR text
- tapOn:
    text: "Bluetooth"

# With tap offset (0,0=top-left, 0.5,0.5=center, 1,1=bottom-right)
- tapOn:
    element: "toggle"
    offset: "0.9, 0.5"

# With surrounding context (disambiguate repeated elements)
- tapOn:
    element: "toggle"
    surrounding: "[BT_title, BT_icon]"    # AND: all must be visible
- tapOn:
    element: "toggle"
    surrounding: "(WiFi_label, BT_label)" # OR: any confirms
- tapOn:
    text: "Bluetooth"
    surrounding: "settings_header"

# By coordinates
- tapOn: "0.5, 0.3"
- tapOn:
    point: "0.5, 0.3"
```

### Long Press / Double Tap

```yaml
- longPressOn: "App_icon"
- longPressOn:
    element: "app_icon"
    surrounding: "app_label"

- doubleTapOn: "Photo"
- doubleTapOn: "0.5, 0.3"
```

### Swipe

```yaml
- swipe: UP
- swipe:
    direction: DOWN
    times: 5
- swipe:
    start: "0.5, 0.7"
    end: "0.5, 0.3"
```

### Swipe Until Found / Gone

```yaml
# Swipe until element appears
- swipeUntilFound:
    element: "Settings"
    direction: LEFT
    maxSwipes: 10

# Swipe until element disappears
- swipeUntilGone:
    element: "Loading_spinner"
    direction: DOWN
    maxSwipes: 20
```

### Text Input & Keys

```yaml
- inputText: "hello world"
- pressKey: enter
- pressKey: home
```

Available keys: `enter`, `space`, `backspace`, `tab`, `escape`, `up`, `down`, `left`, `right`, `delete`

Hotkeys: `home`, `app_switch`, `spotlight`, `screenshot`, `close_app`, `select_all`, `copy`, `paste`, `cut`, `undo`, `redo`

### Click (no movement)

```yaml
# Click at current cursor position without moving
- click
```

### Wait & Repeat

```yaml
- wait: 2

- repeat:
    times: 3
    action:
      - swipe: DOWN
      - wait: 0.5
```

### Import Flows

```yaml
- import: "reset-home"
- import: "navigate-to-settings"
```

### AND/OR Element Expressions

```yaml
# OR — tap whichever is found first
- tapOn: "(Settings|Preferences|Gear_icon)"

# AND — all must be visible, taps first
- tapOn: "[BT_icon, BT_label]"

# Works in swipeUntilFound/Gone too
- swipeUntilFound:
    element: "(Settings|Preferences)"
    direction: LEFT
```

### Notes

- **Three ways to find elements**: template (`element:`), OCR (`text:`), coordinates (`point:`)
- **Coordinates** accept `"0.5, 0.3"` and `"0.5 0.3"`
- **`()`** = OR, **`[]`** = AND
- **`surrounding`** checks context before acting
- **`import`** inlines another flow's commands
- **`offset`** controls tap position within bounding box

### Example

```yaml
name: Open Bluetooth Settings
device: http://phingr-device:8080
---
- import: "reset-home"
- swipeUntilFound:
    element: "(Settings|Gear_icon)"
    direction: LEFT
    maxSwipes: 10
- tapOn: "Settings"
- wait: 1
- swipeUntilFound:
    element: "Bluetooth"
    direction: UP
- tapOn: "Bluetooth"
```

## Python API

Single entry point: **`PhingrSession`**. Handles both device actions and server management.

### Interactive scripting (device actions — requires lock)

Use `async with` to acquire the execution lock, then execute actions immediately and branch on results:

```python
import asyncio
from phingr import PhingrSession

async def toggle_bluetooth():
    async with PhingrSession(
        server_url="http://localhost:8800",
        device_url="http://phingr-device:8080",
    ) as s:
        await s.press_key("home")
        await s.wait(1)

        # Find element, branch on result
        if not await s.exists("settings_icon"):
            await s.swipe_until_found("settings_icon", direction="LEFT")
        await s.tap_on("settings_icon")

        # Check current state and act accordingly
        if await s.exists("bt_toggle_on"):
            await s.tap_on("bt_toggle_on", offset=(0.85, 0.5))
        elif await s.exists("bt_toggle_off"):
            await s.tap_on("bt_toggle_off", offset=(0.85, 0.5))

asyncio.run(toggle_bluetooth())
```

While a session is active, YAML flow runs are blocked (409) and vice versa.

### Device action methods

```python
# Find / check existence (non-mutating)
# find()       → single best match dict, or None (template match: one template)
# find_text()  → list of matches, possibly empty (OCR: many text regions)
# Both match dicts have: x, y (center), x1, y1, x2, y2 (bbox), score (0-1).
# OCR matches also have: text (detected string), conf (raw OCR 0-100).

m = await s.find("settings_icon", threshold=0.8)     # → dict or None
if m:
    print(f"tap=({m['x']}, {m['y']}) bbox={m['x1']:.2f},{m['y1']:.2f}..{m['x2']:.2f},{m['y2']:.2f} score={m['score']}")

matches = await s.find_text("Bluetooth")             # → list[dict], sorted by conf desc
for t in matches:
    print(f"'{t['text']}' score={t['score']} at ({t['x']:.3f}, {t['y']:.3f})")

await s.exists("settings_icon")            # → bool (template)
await s.exists_text("Bluetooth")           # → bool (OCR — true if list non-empty)

# Wait helpers (poll with timeout)
await s.wait_for("settings_icon", timeout=10.0)     # → dict or None
await s.wait_for_text("Loading", timeout=5.0)       # → list[dict] (empty if not found)
await s.wait_until_gone("spinner", timeout=10.0)    # → bool

# Tap / click
await s.tap_on(element, offset=None, surrounding="", threshold=None)
await s.tap_text(text)
await s.tap(x, y)                          # direct coordinates
await s.click()                            # click at current cursor (no move)
await s.long_press(element, surrounding="")
await s.double_tap(element, surrounding="")

# Swipe
await s.swipe("UP", times=1)
await s.swipe_coords((0.5, 0.7), (0.5, 0.3))
await s.swipe_until_found(element, direction="UP", max_swipes=10)
await s.swipe_until_gone(element, direction="UP", max_swipes=10)

# Input
await s.input_text("hello")
await s.press_key("enter")
await s.key("c", modifiers=["cmd"])        # Cmd+C
await s.hotkey("home")                     # home, app_switch, copy, paste, etc.

# Low-level mouse (raw HID units)
await s.mouse_click(button=1)
await s.mouse_move(dx=50, dy=0)
await s.mouse_scroll(dy=-200)

# Other
await s.wait(2.0)
img = await s.screenshot()                 # → bytes (JPEG)
await s.detect_screen()                    # re-detect screen region
await s.fetch_calibration()                # reload handles + table
```

### Server management (no lock required)

These methods work on a plain `PhingrSession()` without `async with`:

```python
s = PhingrSession("http://localhost:8800")

# Flows
await s.list_flows()
await s.get_flow("my-flow")
await s.save_flow("my-flow", yaml_content)
await s.delete_flow("my-flow")

# Run a saved flow by name (blocks until done)
result = await s.run_flow("my-flow", log_callback=print)
print(result.status)  # "success" or "failed"

# Templates
await s.list_templates()
img = await s.get_template_image("Settings")
await s.delete_template("Settings")

# Runs
await s.list_runs()
await s.get_run_status(run_id)
await s.stop_run(run_id)
await s.delete_run(run_id)

# Export / import (includes calibration)
zip_bytes = await s.export_all()
await s.import_all(zip_bytes)

await s.close()
```

### Mobly Integration Example

```python
from mobly import base_test, test_runner
from phingr import PhingrSession

class BluetoothTest(base_test.BaseTestClass):

    def test_open_bluetooth(self):
        import asyncio
        async def run():
            async with PhingrSession(
                server_url="http://phingr-cli:8800",
                device_url="http://phingr-device:8080",
            ) as s:
                await s.press_key("home")
                await s.wait(1)
                await s.swipe_until_found("Settings", direction="LEFT")
                await s.tap_on("Settings")
                await s.wait(1)
                await s.tap_on("Bluetooth")
                assert await s.exists("bt_header"), "Did not reach BT screen"
        asyncio.run(run())

if __name__ == "__main__":
    test_runner.main()
```

## Architecture

```
 ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
   LOCAL MACHINE
 │                                                        │
   ┌──────────────────────────────────────────────────┐
 │ │ phingr-cli (:8800)                                │  │
   │  app/dsl.py             YAML parser + commands    │
 │ │  app/engine.py          sequential executor       │  │
   │  app/template_matcher.py OpenCV + OCR matching    │
 │ │  app/phingr_client.py   device HTTP client        │  │
   │  app/static/            web UI                    │
 │ │  data/templates/        registered element crops  │  │
   │  data/flows/            saved YAML flows          │
 │ └───────────────────────────┬──────────────────────┘  │
                                │ HTTP
 └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
                                │
 ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
   RASPBERRY PI                 │
 │ ┌────────────────────────────▼─────────────────────┐  │
   │ phingr-device (:8080)                             │
 │ │ /api/tap, /api/swipe, /api/screenshot, etc.       │  │
   │ /api/calib/handles, /api/calib/table              │
 │ └──────────────────────────────────────────┬────────┘  │
                                               │ USB HID
 └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ┘
                                               ▼
                                      ┌──────────────┐
                                      │ Mobile Device│
                                      └──────────────┘
```

## Project Structure

```
phingr-cli/
├── setup.sh                  # Setup: venv + deps
├── requirements.txt          # Server deps (FastAPI, httpx, OpenCV, etc.)
├── pyproject.toml            # pip install -e . (library only)
├── app/                      # Web UI server
│   ├── server.py             # FastAPI entry point (:8800)
│   ├── api.py                # REST API (flows, runs, templates, device)
│   ├── config.py             # PHINGR_DEVICE_URL, PHINGR_DATA_DIR
│   ├── dsl.py                # YAML DSL parser + command classes
│   ├── engine.py             # Sequential command executor
│   ├── phingr_client.py      # Device HTTP client + coordinate mapping
│   ├── template_matcher.py   # OpenCV template matching + OCR
│   ├── flow_builder.py       # Python fluent API + runner
│   ├── models.py             # Pydantic models
│   └── static/               # Web UI (HTML/CSS/JS)
├── phingr/                   # Standalone Python package (pip installable)
│   ├── __init__.py            # from phingr import PhingrSession, RunResult
│   ├── dsl.py, engine.py, etc.
├── data/
│   ├── flows/                # Saved YAML flows
│   └── templates/            # Registered element crops + metadata
├── examples/                 # Example flows
└── util/                     # Test scripts
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PHINGR_DEVICE_URL` | `http://localhost:8080` | Device API URL |
| `PHINGR_DATA_DIR` | `./data` | Flows + templates directory |

## Web UI

Three tabs:

| Tab | Purpose |
|-----|---------|
| **Flows** | List/run/delete flows. Recent runs with status. Export all / import (includes calibration). |
| **Editor** | YAML editor with tree gutter, flow structure, DSL reference, template list |
| **Device & Templates** | Device control + template registration + flow execution overlay |

When a flow runs, the Device & Templates tab shows:
- **Run bar** at top: progress, status badge, stop button
- **Center panel**: annotated screenshots with template match rectangles
- **Right panel**: run log + template list

## Device Setup

See [phingr-device README](../phingr-device/README.md) and the [root README](../README.md#device-setup-required) for phone configuration and calibration instructions.
