# Cursor Calibration

## The Problem

The Raspberry Pi controls the iPhone via a **relative USB HID mouse** — it can only send "move 5 pixels right" reports, not "move cursor to (375, 500)." Two issues make absolute positioning hard:

1. **pointer acceleration** — Small, slow HID movements get amplified less than large, fast ones. At 5px steps the relationship is roughly linear, but at 127px steps mobile applies heavy acceleration, making distance unpredictable.

2. **Unknown screen dimensions** — Different iPhones have different resolutions, and the system doesn't know the actual cursor-travel distance in HID units.

## The Solution: Reset + Move

To move to an absolute position, phingr:

1. **Resets to origin** — sends 200 reports of (-5, -5) to slam the cursor into the top-left corner
2. **Waits 100ms** for mobile to settle
3. **Moves to target** in small 5px steps (where acceleration is predictable)

But this still requires knowing: "how many 5px HID steps = full screen width?"

## Known Issue: Auto-Rotate

auto-rotate affects the HID coordinate system. When the phone rotates, the cursor's X and Y axes rotate with it. This means:

- **Reset goes to the wrong corner** — `_reset_to_origin()` sends (-5, -5) to reach the top-left, but if the phone is rotated 180 degrees, the cursor slams into the bottom-right instead.
- **Calibration values become invalid** — screen width and height swap when rotating between portrait and landscape.
- **Tap coordinates land in wrong positions** — a tap at (0.5, 0.3) maps to a completely different location after rotation.

**Workaround:** Lock the phone orientation before calibrating. On iOS/Android: Settings > Display & Brightness > disable auto-rotate (or use the Control Center orientation lock toggle). Recalibrate if the phone rotates.

## The Calibration Flow

1. **Lock phone orientation** — ensure auto-rotate is disabled before calibrating.
2. **`POST /api/calib/move`** — Backend resets cursor to origin, then sends a known number of HID units (default 500) along one axis (x or y).
3. **User observes** where the cursor actually landed on the phone screen.
4. **User marks the position** in the web UI (clicks on the camera feed where the cursor is).
5. **`POST /api/calib/set`** — User reports the cursor landed at e.g. 60% of screen width (`landed=0.6`). Backend computes:
   ```
   real_screen_width = units / landed = 500 / 0.6 = 833 HID units
   ```
6. Repeat for the y-axis.
7. **Validation** — calibration should not be accepted if the cursor landed at less than 95% of the screen width or height. If it did, the test units value is too large and the cursor hit the edge before travelling the full distance, giving an inaccurate measurement. Reduce `units` and recalibrate.

After calibration, `move_to(x=0.5, y=0.5)` means "reset to origin, then move 416 units right and 667 units down" — and it lands in the center.

## API Reference

| Endpoint | Purpose |
|----------|---------|
| `POST /api/calib/move` | Reset to origin, then move `units` along `axis` ("x" or "y") |
| `POST /api/calib/set` | Record where cursor landed (`landed` 0-1), compute real screen size |
| `POST /api/calib/get` | Return current `screen_w`, `screen_h`, `calib_units` |
| `POST /api/configure` | Manually set `screen_w` and `screen_h` (skip calibration) |

## For phingr-cli

The phingr device API's `tap(x, y)` with normalized 0-1 coordinates handles calibration internally. phingr-cli sends `{"x": 0.5, "y": 0.3}` and the device layer translates it using stored calibration values. The LLM never needs to think about HID units — it works entirely in normalized screen coordinates.
