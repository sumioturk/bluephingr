"""phingr — Python library for mobile UI automation.

Single entry point: PhingrSession. Handles both device actions
(tap, swipe, find) and server management (flows, templates, runs).

Usage:
    import asyncio
    from phingr import PhingrSession

    async def main():
        async with PhingrSession("http://cli:8800", "http://device:8080") as s:
            await s.press_key("home")
            if await s.exists("settings_icon"):
                await s.tap_on("settings_icon")

    asyncio.run(main())
"""

from .flow_builder import PhingrSession, RunResult

__all__ = ["PhingrSession", "RunResult"]
