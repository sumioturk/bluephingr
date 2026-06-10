#!/usr/bin/env python3
"""BT toggle stress test — 100 iterations with bbox logging.

Dynamic PhingrSession script that navigates to BT settings and
toggles the switch twice per iteration. Each find() call logs the
full match info: bbox, center point, and match score.

Usage:
    pip install -e /path/to/phingr-cli
    python bt_toggle_stress.py [--iterations 100]
"""

import argparse
import asyncio
import sys

from phingr import PhingrSession

SERVER_URL = "http://localhost:8800"
DEVICE_URL = "http://phingr-e825.local:8080"


def fmt_match(name: str, m: dict | None) -> str:
    """Format a find() result for logging."""
    if m is None:
        return f'  {name}: NOT FOUND'
    if "x1" in m:  # template match with bbox
        w = m["x2"] - m["x1"]
        h = m["y2"] - m["y1"]
        return (f'  {name}: center=({m["x"]:.3f}, {m["y"]:.3f}) '
                f'bbox=({m["x1"]:.3f}, {m["y1"]:.3f})-({m["x2"]:.3f}, {m["y2"]:.3f}) '
                f'{w:.3f}x{h:.3f} score={m.get("score", "?")}')
    # OCR or point-only match
    return f'  {name}: ({m["x"]:.3f}, {m["y"]:.3f})'


async def find_and_log(s: PhingrSession, name: str, **kwargs) -> dict | None:
    m = await s.find(name, **kwargs)
    print(fmt_match(name, m))
    return m


async def run_once(s: PhingrSession, i: int) -> bool:
    print(f"\n── Iteration {i} ──")

    await s.press_key("home")
    await s.wait(1)

    # Swipe right to reach photo widget
    await s.swipe_until_found("photo_widget", direction="RIGHT", max_swipes=4)
    if not await find_and_log(s, "photo_widget"):
        return False
    await s.wait(1)

    # Swipe left to find settings, verified by fit_icon context
    await s.swipe_until_found("settings_icon", direction="LEFT", max_swipes=4)
    settings = await find_and_log(s, "settings_icon")
    if not settings:
        return False
    if not await find_and_log(s, "fit_icon"):
        print("  fit_icon missing — wrong screen?")
        return False
    await s.wait(1)

    await s.tap_on("settings_icon")
    await s.wait(1)

    # Scroll to BT section
    await s.swipe_until_found("bt_header", direction="DOWN", max_swipes=2)
    if not await find_and_log(s, "bt_header"):
        return False
    await s.wait(1)

    # Find current toggle state
    on = await s.find("bt_toggle_on")
    off = await s.find("bt_toggle_off")
    print(fmt_match("bt_toggle_on", on))
    print(fmt_match("bt_toggle_off", off))
    text = await s.find_text("Bluetooth")
    if on is not None and text is not None:
        for t in text:
            print(f"intersect:{intersect(on, t)}")
    if off is not None and text is not None:
        for t in text:
            print(f"intersect:{intersect(off, t)}")

    if on:
        print("  → BT is ON, tapping to turn OFF")
        await s.tap_on("bt_toggle_on", offset=(0.85, 0.5))
    elif off:
        print("  → BT is OFF, tapping to turn ON")
        await s.tap_on("bt_toggle_off", offset=(0.85, 0.5))
    else:
        print("  → Neither toggle found")
        return False

    await s.wait(3)

    # Second toggle — use lower threshold since state just changed
    await s.tap_on(
        "(bt_toggle_on, bt_toggle_off)",
        offset=(0.85, 0.5),
        threshold=0.6,
    )
    return True


async def main(iterations: int):
    async with PhingrSession(
        server_url=SERVER_URL,
        device_url=DEVICE_URL,
        name="bt-toggle-stress",
    ) as s:
        passed = 0
        failed = 0
        for i in range(1, iterations + 1):
            try:
                ok = await run_once(s, i)
                if ok:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"  iter {i}: ERROR — {type(e).__name__}: {e}")
                failed += 1

        print(f"\n{'='*40}")
        print(f"Done: {passed} passed, {failed} failed out of {iterations}")
        print(f"{'='*40}")
        if failed > 0:
            sys.exit(1)

def intersect(bbox1, bbox2):
    """
    Determines if two bounding boxes intersect.
    Each bbox is a dict with keys: 'x1', 'y1', 'x2', 'y2'
    (Assumes x1 < x2 and y1 < y2)
    """
    # Check if bbox1 is to the right of bbox2 or vice versa
    if bbox1['x1'] >= bbox2['x2'] or bbox2['x1'] >= bbox1['x2']:
        return False

    # Check if bbox1 is below bbox2 or vice versa
    if bbox1['y1'] >= bbox2['y2'] or bbox2['y1'] >= bbox1['y2']:
        return False

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BT toggle stress test")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(main(args.iterations))
