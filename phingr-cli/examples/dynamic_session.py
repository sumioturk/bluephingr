#!/usr/bin/env python3
"""Dynamic flow example — Python branches based on what's on screen.

PhingrSession executes actions immediately so Python can react to
the result (unlike a static YAML flow).

Usage:
    python dynamic_session.py
"""

import asyncio
from phingr import PhingrSession


async def toggle_bluetooth():
    async with PhingrSession(
        server_url="http://localhost:8800",
        device_url="http://phingr-e825.local:8080",
    ) as s:
        await s.press_key("home")
        await s.wait(1)

        # Swipe until Settings is visible (try left first, then right)
        settings = await s.find("settings_icon")
        if not settings:
            print("Settings not on this page — swiping left")
            await s.swipe_until_found("settings_icon", direction="LEFT", max_swipes=5)

        await s.tap_on("settings_icon")
        await s.wait(1)

        # Find Bluetooth section
        await s.swipe_until_found("bt_header", direction="DOWN", max_swipes=3)

        # Check current toggle state, then act accordingly
        if await s.exists("bt_toggle_on"):
            print("Bluetooth is ON — turning OFF")
            await s.tap_on("bt_toggle_on", offset=(0.85, 0.5))
        elif await s.exists("bt_toggle_off"):
            print("Bluetooth is OFF — turning ON")
            await s.tap_on("bt_toggle_off", offset=(0.85, 0.5))
        else:
            print("Could not find BT toggle")
            return

        await s.wait(2)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(toggle_bluetooth())
