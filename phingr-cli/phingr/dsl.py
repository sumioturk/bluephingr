"""YAML DSL parser and command classes for phingr-cli.

Element finding via template matching (OpenCV) or OCR (Tesseract).
Coordinates can be explicit, template-matched, or text-matched.
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

import yaml

DSL_VERSION = "1.2"


# ── Execution context ────────────────────────────────────────────────────

@dataclass
class ExecutionContext:
    phingr: object  # FkiosClient
    matcher: object | None  # TemplateMatcher
    log: Callable[[str], None]
    stop_requested: Callable[[], bool]
    set_annotated: Callable[[bytes], None] | None = None
    last_found: dict | None = None  # cache: {"name": str, "coords": (x,y), "time": float}


class CommandError(Exception):
    pass


# ── Swipe direction mappings ─────────────────────────────────────────────

SWIPE_COORDS = {
    "up":    {"x0": 0.5, "y0": 0.7, "x1": 0.5, "y1": 0.3},
    "down":  {"x0": 0.5, "y0": 0.3, "x1": 0.5, "y1": 0.7},
    "left":  {"x0": 0.7, "y0": 0.5, "x1": 0.3, "y1": 0.5},
    "right": {"x0": 0.3, "y0": 0.5, "x1": 0.7, "y1": 0.5},
}

HOTKEY_NAMES = {"home", "app_switch", "spotlight", "screenshot", "close_app",
                "select_all", "copy", "paste", "cut", "undo", "redo"}


# ── Command base ─────────────────────────────────────────────────────────

class Command(ABC):
    @abstractmethod
    async def execute(self, ctx: ExecutionContext) -> None: ...

    @abstractmethod
    def __str__(self) -> str: ...


# ── Tap ──────────────────────────────────────────────────────────────────

def _is_coordinates(val: str) -> bool:
    """Check if a string looks like coordinates (e.g. '0.5, 0.3')."""
    return bool(re.match(r"^\s*[\d.]+\s*,\s*[\d.]+\s*$", val))


def _parse_element_expr(target: str) -> tuple[str, list[str]]:
    """Parse element expression.

    "Settings"              → ("single", ["Settings"])
    "(Settings|Prefs)"      → ("or", ["Settings", "Prefs"])
    "(Settings, Prefs)"     → ("or", ["Settings", "Prefs"])
    "[Bluetooth, Wi-Fi]"    → ("and", ["Bluetooth", "Wi-Fi"])
    """
    import re
    target = target.strip()
    if target.startswith("(") and target.endswith(")"):
        # Accept both | and , as separators inside ()
        parts = [p.strip() for p in re.split(r"[|,]", target[1:-1])]
        return ("or", [p for p in parts if p])
    if target.startswith("[") and target.endswith("]"):
        parts = [p.strip() for p in target[1:-1].split(",")]
        return ("and", [p for p in parts if p])
    return ("single", [target])


async def _resolve_coords(ctx: ExecutionContext, target: str,
                          x: float | None, y: float | None,
                          tap_offset: tuple[float, float] | None = None,
                          threshold: float | None = None,
                          match_mode: str | None = None) -> tuple[float, float]:
    """Resolve tap target to coordinates.

    Priority: direct coords → template match → OmniParser
    """
    if x is not None and y is not None:
        return x, y

    import time as _time

    # Check cache
    if not tap_offset and ctx.last_found and ctx.last_found["name"] == target:
        age = _time.time() - ctx.last_found["time"]
        if age < 3.0:
            sx, sy = ctx.last_found["screen_coords"]
            ctx.log(f'  Using cached match for "{target}" ({age:.1f}s ago) at ({sx:.4f}, {sy:.4f})')
            ctx.last_found = None
            return sx, sy

    img = await ctx.phingr.screenshot(crop=False)

    # Parse element expression: (A|B) = OR, [A, B] = AND
    mode, elements = _parse_element_expr(target)

    if mode == "or":
        # OR: try each, return first match
        ctx.log(f'  Finding any of: {elements}')
        if ctx.matcher:
            for elem in elements:
                coords, annotated = ctx.matcher.find_and_annotate(img, elem, threshold=threshold, tap_offset_override=tap_offset, match_mode=match_mode)
                if ctx.set_annotated:
                    ctx.set_annotated(annotated)
                if coords:
                    sx, sy = ctx.phingr.camera_to_screen(coords[0], coords[1])
                    ctx.log(f'  Found "{elem}": camera=({coords[0]:.4f}, {coords[1]:.4f}) → screen=({sx:.4f}, {sy:.4f})')
                    return sx, sy
        raise CommandError(f'None of {elements} found — register templates first.')

    elif mode == "and":
        # AND: all must be visible, tap the first one
        ctx.log(f'  Finding all of: {elements}')
        if ctx.matcher:
            first_coords = None
            for elem in elements:
                coords = ctx.matcher.find(img, elem)
                if not coords:
                    raise CommandError(f'AND condition failed: "{elem}" not found')
                ctx.log(f'  "{elem}" found at ({coords[0]:.4f}, {coords[1]:.4f})')
                if first_coords is None:
                    first_coords = coords
            if first_coords:
                # Re-run with annotate for the first element
                coords, annotated = ctx.matcher.find_and_annotate(img, elements[0], tap_offset_override=tap_offset)
                if ctx.set_annotated:
                    ctx.set_annotated(annotated)
                sx, sy = ctx.phingr.camera_to_screen(first_coords[0], first_coords[1])
                ctx.log(f'  All found. Tapping "{elements[0]}" → screen=({sx:.4f}, {sy:.4f})')
                return sx, sy
        raise CommandError(f'Cannot check AND condition — no template matcher.')

    else:
        # Single element — try template match
        ctx.log(f'  Finding: "{target}"')
        if ctx.matcher:
            coords, annotated = ctx.matcher.find_and_annotate(img, target, threshold=threshold, tap_offset_override=tap_offset, match_mode=match_mode)
            if ctx.set_annotated:
                ctx.set_annotated(annotated)
            if coords:
                sx, sy = ctx.phingr.camera_to_screen(coords[0], coords[1])
                ctx.log(f"  Matched: camera=({coords[0]:.4f}, {coords[1]:.4f}) → screen=({sx:.4f}, {sy:.4f})")
                return sx, sy

    raise CommandError(
        f'Cannot find "{target}" — register a template or use text: matching.'
    )


async def _resolve_text(ctx: ExecutionContext, text: str) -> tuple[float, float]:
    """Find text on screen using OCR and return screen coordinates."""
    img = await ctx.phingr.screenshot(crop=False)
    ctx.log(f'  OCR finding: "{text}"')

    if ctx.matcher:
        coords, annotated = ctx.matcher.find_text_and_annotate(img, text)
        if ctx.set_annotated:
            ctx.set_annotated(annotated)
        if coords:
            sx, sy = ctx.phingr.camera_to_screen(coords[0], coords[1])
            ctx.log(f'  OCR found: camera=({coords[0]:.4f}, {coords[1]:.4f}) → screen=({sx:.4f}, {sy:.4f})')
            return sx, sy

    raise CommandError(f'Text "{text}" not found on screen (OCR)')


def _normalize_element_expr(val) -> str:
    """Normalize an element expression — handle YAML parsing a list instead of string.

    YAML: element: [A, B]  → Python list ['A', 'B']  → "[A, B]" (AND)
    YAML: element: "[A, B]" → string "[A, B]"        → unchanged
    """
    if isinstance(val, list):
        return "[" + ", ".join(str(v) for v in val) + "]"
    return str(val) if val else ""


# Backward-compat alias
_normalize_surrounding = _normalize_element_expr


async def _check_surrounding(ctx: ExecutionContext, surrounding: str, img: bytes) -> bool:
    """Check if surrounding context elements are present.

    surrounding uses the same AND/OR syntax:
        "[BT_title, BT_icon]"  → AND: all must be visible
        "(BT_title, BT_icon)"  → OR: any must be visible
        "BT_title"             → single: must be visible
    """
    if not surrounding or not ctx.matcher:
        return True

    mode, elements = _parse_element_expr(surrounding)

    if mode == "or":
        for elem in elements:
            if ctx.matcher.find(img, elem):
                ctx.log(f'  Surrounding OR: "{elem}" found')
                return True
        ctx.log(f'  Surrounding OR: none of {elements} found')
        return False

    elif mode == "and":
        for elem in elements:
            if not ctx.matcher.find(img, elem):
                ctx.log(f'  Surrounding AND: "{elem}" not found')
                return False
        ctx.log(f'  Surrounding AND: all of {elements} found')
        return True

    else:
        found = ctx.matcher.find(img, elements[0]) is not None
        ctx.log(f'  Surrounding: "{elements[0]}" {"found" if found else "not found"}')
        return found


@dataclass
class TapOn(Command):
    target: str = ""  # template name
    text: str = ""    # OCR text to find
    x: float | None = None
    y: float | None = None
    offset: tuple[float, float] | None = None
    surrounding: str = ""
    threshold: float | None = None  # override match score threshold
    match_mode: str | None = None  # "normal" (default), "edge", "both"
    duration_ms: int = 50

    async def execute(self, ctx: ExecutionContext) -> None:
        if self.surrounding:
            img = await ctx.phingr.screenshot(crop=False)
            if not await _check_surrounding(ctx, self.surrounding, img):
                raise CommandError(
                    f'Surrounding context not met for "{self.target or self.text}": {self.surrounding}'
                )
        if self.text:
            rx, ry = await _resolve_text(ctx, self.text)
        else:
            rx, ry = await _resolve_coords(ctx, self.target, self.x, self.y,
                                            tap_offset=self.offset,
                                            threshold=self.threshold,
                                            match_mode=self.match_mode)
        ctx.log(f"  Tapping at ({rx:.4f}, {ry:.4f})")
        await ctx.phingr.tap(rx, ry, self.duration_ms)
        ctx.log(f"  Tap sent")

    def __str__(self):
        if self.x is not None:
            return f"tapOn: ({self.x}, {self.y})"
        if self.text:
            return f'tapOn: text="{self.text}"'
        off = f" offset=({self.offset[0]}, {self.offset[1]})" if self.offset else ""
        sur = f' surrounding={self.surrounding}' if self.surrounding else ""
        return f'tapOn: "{self.target}"{off}{sur}'


@dataclass
class LongPressOn(Command):
    target: str = ""
    x: float | None = None
    y: float | None = None
    surrounding: str = ""

    async def execute(self, ctx: ExecutionContext) -> None:
        if self.surrounding:
            img = await ctx.phingr.screenshot(crop=False)
            if not await _check_surrounding(ctx, self.surrounding, img):
                raise CommandError(f'Surrounding not met for "{self.target}": {self.surrounding}')
        rx, ry = await _resolve_coords(ctx, self.target, self.x, self.y)
        await ctx.phingr.tap(rx, ry, duration_ms=1000)

    def __str__(self):
        if self.x is not None:
            return f"longPressOn: ({self.x}, {self.y})"
        sur = f' surrounding={self.surrounding}' if self.surrounding else ""
        return f'longPressOn: "{self.target}"{sur}'


@dataclass
class DoubleTapOn(Command):
    target: str = ""
    x: float | None = None
    y: float | None = None
    surrounding: str = ""

    async def execute(self, ctx: ExecutionContext) -> None:
        if self.surrounding:
            img = await ctx.phingr.screenshot(crop=False)
            if not await _check_surrounding(ctx, self.surrounding, img):
                raise CommandError(f'Surrounding not met for "{self.target}": {self.surrounding}')
        rx, ry = await _resolve_coords(ctx, self.target, self.x, self.y)
        await ctx.phingr.tap(rx, ry)
        await asyncio.sleep(0.1)
        await ctx.phingr.tap(rx, ry)

    def __str__(self):
        if self.x is not None:
            return f"doubleTapOn: ({self.x}, {self.y})"
        sur = f' surrounding={self.surrounding}' if self.surrounding else ""
        return f'doubleTapOn: "{self.target}"{sur}'


# ── Text / Keys ──────────────────────────────────────────────────────────

@dataclass
class InputText(Command):
    text: str

    async def execute(self, ctx: ExecutionContext) -> None:
        await ctx.phingr.type_text(self.text)

    def __str__(self): return f'inputText: "{self.text}"'


@dataclass
class PressKey(Command):
    key: str

    async def execute(self, ctx: ExecutionContext) -> None:
        if self.key.lower() in HOTKEY_NAMES:
            await ctx.phingr.hotkey(self.key.lower())
        else:
            await ctx.phingr.key(self.key.lower())

    def __str__(self): return f"pressKey: {self.key}"


# ── Swipe ────────────────────────────────────────────────────────────────

@dataclass
class Swipe(Command):
    direction: str = ""
    times: int = 1
    start: tuple[float, float] | None = None
    end: tuple[float, float] | None = None

    async def execute(self, ctx: ExecutionContext) -> None:
        if self.start and self.end:
            for i in range(self.times):
                await ctx.phingr.swipe(self.start[0], self.start[1],
                                      self.end[0], self.end[1])
                if i < self.times - 1:
                    await asyncio.sleep(0.3)
        else:
            coords = SWIPE_COORDS.get(self.direction.lower(), SWIPE_COORDS["down"])
            for i in range(self.times):
                await ctx.phingr.swipe(**coords)
                if i < self.times - 1:
                    await asyncio.sleep(0.3)

    def __str__(self):
        if self.start and self.end:
            return f"swipe: ({self.start[0]},{self.start[1]}) -> ({self.end[0]},{self.end[1]})"
        t = f" x{self.times}" if self.times > 1 else ""
        return f"swipe: {self.direction}{t}"


# ── Wait ─────────────────────────────────────────────────────────────────

@dataclass
class Wait(Command):
    seconds: float

    async def execute(self, ctx: ExecutionContext) -> None:
        await asyncio.sleep(self.seconds)

    def __str__(self): return f"wait: {self.seconds}s"


@dataclass
class Click(Command):
    """Click at current cursor position — no movement."""
    button: int = 1
    duration_ms: int = 50

    async def execute(self, ctx: ExecutionContext) -> None:
        await ctx.phingr.mouse_click(button=self.button, duration_ms=self.duration_ms)

    def __str__(self): return "click"


# ── Scroll/Swipe Until Found ──────────────────────────────────────────────

@dataclass
class SwipeUntilFound(Command):
    """Swipe repeatedly until template matching finds (or loses) the element."""
    element: str
    direction: str = "UP"
    max_swipes: int = 10
    until_gone: bool = False  # if True, swipe until element disappears

    async def execute(self, ctx: ExecutionContext) -> None:
        if not ctx.matcher:
            raise CommandError(f'swipeUntilFound requires registered templates')
        swipe = SWIPE_COORDS.get(self.direction.lower(), SWIPE_COORDS["up"])
        mode, elements = _parse_element_expr(self.element)

        for i in range(self.max_swipes):
            if ctx.stop_requested():
                raise CommandError("Stopped by user")
            img = await ctx.phingr.screenshot(crop=False)

            found = self._check_found(ctx, img, mode, elements)

            if self.until_gone:
                # Inverse: swipe until element DISAPPEARS
                if not found:
                    ctx.log(f'  "{self.element}" gone after {i} swipe(s)')
                    return
            else:
                # Normal: swipe until element APPEARS
                if found:
                    ctx.log(f'  "{self.element}" found after {i} swipe(s)')
                    return

            ctx.log(f"  Swipe {i+1}/{self.max_swipes}...")
            await ctx.phingr.swipe(**swipe)
            await asyncio.sleep(0.5)

        action = "disappear" if self.until_gone else "appear"
        raise CommandError(f'swipeUntilFound: "{self.element}" did not {action} after {self.max_swipes} swipes')

    def _check_found(self, ctx, img, mode, elements) -> bool:
        """Check if element(s) are found. Returns True if match condition is met."""
        import time as _time

        if mode == "or":
            for elem in elements:
                coords, annotated = ctx.matcher.find_and_annotate(img, elem)
                if ctx.set_annotated:
                    ctx.set_annotated(annotated)
                if coords:
                    sx, sy = ctx.phingr.camera_to_screen(coords[0], coords[1])
                    ctx.last_found = {"name": elem, "screen_coords": (sx, sy), "time": _time.time()}
                    return True
            return False

        elif mode == "and":
            first_coords = None
            for elem in elements:
                coords = ctx.matcher.find(img, elem)
                if not coords:
                    return False
                if first_coords is None:
                    first_coords = coords
            if first_coords:
                sx, sy = ctx.phingr.camera_to_screen(first_coords[0], first_coords[1])
                ctx.last_found = {"name": elements[0], "screen_coords": (sx, sy), "time": _time.time()}
            return True

        else:
            coords, annotated = ctx.matcher.find_and_annotate(img, self.element)
            if ctx.set_annotated:
                ctx.set_annotated(annotated)
            if coords:
                sx, sy = ctx.phingr.camera_to_screen(coords[0], coords[1])
                ctx.last_found = {"name": self.element, "screen_coords": (sx, sy), "time": _time.time()}
                return True
            return False

    def __str__(self):
        gone = " untilGone" if self.until_gone else ""
        return f'swipeUntilFound: "{self.element}" ({self.direction}){gone}'


# ── Import ───────────────────────────────────────────────────────────────

@dataclass
class Import(Command):
    """Import and execute commands from another flow file."""
    flow_name: str
    _commands: list[Command] | None = None  # resolved at parse time

    async def execute(self, ctx: ExecutionContext) -> None:
        if not self._commands:
            raise CommandError(f'Import "{self.flow_name}" has no resolved commands')
        for cmd in self._commands:
            if ctx.stop_requested():
                raise CommandError("Stopped by user")
            await cmd.execute(ctx)
            await asyncio.sleep(0.3)

    def __str__(self): return f'import: "{self.flow_name}"'


# ── Repeat ───────────────────────────────────────────────────────────────

@dataclass
class Repeat(Command):
    action: list[Command]
    times: int

    async def execute(self, ctx: ExecutionContext) -> None:
        for i in range(self.times):
            if ctx.stop_requested():
                raise CommandError("Stopped by user")
            ctx.log(f"  Repeat {i+1}/{self.times}")
            for cmd in self.action:
                await cmd.execute(ctx)
                await asyncio.sleep(0.3)

    def __str__(self): return f"repeat: {self.times} times"


# ── Flow ─────────────────────────────────────────────────────────────────

@dataclass
class Flow:
    name: str
    device_url: str
    commands: list[Command]


# ── YAML Parser ──────────────────────────────────────────────────────────

def _parse_point(val) -> tuple[float, float]:
    """Parse "0.5, 0.3" or "0.5 0.3" into (0.5, 0.3)."""
    s = str(val).strip()
    # Split by comma, or by space if no comma
    parts = s.split(",") if "," in s else s.split()
    if len(parts) != 2:
        raise ValueError(f"Expected two numbers, got: {val}")
    return (float(parts[0].strip()), float(parts[1].strip()))


def _parse_command(raw: dict) -> Command:
    """Parse a single YAML dict into a Command."""

    if "tapOn" in raw:
        val = raw["tapOn"]
        if isinstance(val, dict):
            if "point" in val:
                x, y = _parse_point(val["point"])
                return TapOn(x=x, y=y)
            if "text" in val:
                return TapOn(text=val["text"],
                             surrounding=_normalize_surrounding(val.get("surrounding", "")),
                             threshold=float(val["threshold"]) if "threshold" in val else None)
            if "element" in val:
                offset = None
                if "offset" in val:
                    ox, oy = _parse_point(val["offset"])
                    offset = (ox, oy)
                return TapOn(target=_normalize_element_expr(val["element"]), offset=offset,
                             surrounding=_normalize_surrounding(val.get("surrounding", "")),
                             threshold=float(val["threshold"]) if "threshold" in val else None,
                             match_mode=str(val["matchMode"]) if "matchMode" in val else None)
        if isinstance(val, list):
            return TapOn(target=_normalize_element_expr(val))
        if isinstance(val, str):
            if _is_coordinates(val):
                x, y = _parse_point(val)
                return TapOn(x=x, y=y)
            return TapOn(target=val)
        raise ValueError(f"tapOn: invalid value: {val}")

    if "longPressOn" in raw:
        val = raw["longPressOn"]
        if isinstance(val, dict):
            if "point" in val:
                x, y = _parse_point(val["point"])
                return LongPressOn(x=x, y=y)
            if "element" in val:
                return LongPressOn(target=_normalize_element_expr(val["element"]),
                                   surrounding=str(val.get("surrounding", "")))
        if isinstance(val, str):
            if _is_coordinates(val):
                x, y = _parse_point(val)
                return LongPressOn(x=x, y=y)
            return LongPressOn(target=val)
        raise ValueError(f"longPressOn: invalid value: {val}")

    if "doubleTapOn" in raw:
        val = raw["doubleTapOn"]
        if isinstance(val, dict):
            if "point" in val:
                x, y = _parse_point(val["point"])
                return DoubleTapOn(x=x, y=y)
            if "element" in val:
                return DoubleTapOn(target=_normalize_element_expr(val["element"]),
                                   surrounding=str(val.get("surrounding", "")))
        if isinstance(val, str):
            if _is_coordinates(val):
                x, y = _parse_point(val)
                return DoubleTapOn(x=x, y=y)
            return DoubleTapOn(target=val)
        raise ValueError(f"doubleTapOn: invalid value: {val}")

    if "inputText" in raw:
        return InputText(text=str(raw["inputText"]))

    if "pressKey" in raw:
        return PressKey(key=str(raw["pressKey"]))

    if "swipe" in raw:
        val = raw["swipe"]
        if isinstance(val, str):
            return Swipe(direction=val)
        if "start" in val and "end" in val:
            sp = _parse_point(val["start"])
            ep = _parse_point(val["end"])
            return Swipe(start=sp, end=ep, times=int(val.get("times", 1)))
        return Swipe(
            direction=val.get("direction", "DOWN"),
            times=int(val.get("times", 1)),
        )

    if "swipeUntilFound" in raw:
        val = raw["swipeUntilFound"]
        return SwipeUntilFound(
            element=_normalize_element_expr(val["element"]),
            direction=val.get("direction", "UP"),
            max_swipes=int(val.get("maxSwipes", 10)),
            until_gone=bool(val.get("untilGone", False)),
        )

    if "swipeUntilGone" in raw:
        val = raw["swipeUntilGone"]
        return SwipeUntilFound(
            element=_normalize_element_expr(val["element"]),
            direction=val.get("direction", "UP"),
            max_swipes=int(val.get("maxSwipes", 10)),
            until_gone=True,
        )

    if "wait" in raw:
        return Wait(seconds=float(raw["wait"]))

    if "click" in raw:
        val = raw["click"]
        if isinstance(val, dict):
            return Click(button=int(val.get("button", 1)),
                         duration_ms=int(val.get("duration_ms", 50)))
        return Click()

    if "repeat" in raw:
        val = raw["repeat"]
        sub_cmds = [_parse_command(c) for c in val["action"]]
        return Repeat(action=sub_cmds, times=int(val.get("times", 1)))

    if "import" in raw:
        return Import(flow_name=str(raw["import"]))

    raise ValueError(f"Unknown command: {raw}")


def parse_flow(yaml_text: str, flows_dir: str | None = None) -> Flow:
    """Parse a YAML flow file into a Flow object.

    Args:
        yaml_text: YAML content
        flows_dir: directory to resolve imports from (optional)
    """
    from pathlib import Path

    docs = list(yaml.safe_load_all(yaml_text))
    if len(docs) < 2:
        raise ValueError("Flow must have frontmatter (name, device) separated by --- from commands")

    header = docs[0] or {}
    commands_raw = docs[1] or []

    if not isinstance(commands_raw, list):
        raise ValueError("Commands section must be a list")

    name = header.get("name", "Untitled")
    device_url = header.get("device", "")

    commands = [_parse_command(c) for c in commands_raw]

    # Resolve imports
    if flows_dir:
        flows_path = Path(flows_dir)
        for cmd in commands:
            if isinstance(cmd, Import):
                import_path = flows_path / f"{cmd.flow_name}.yaml"
                if not import_path.exists():
                    raise ValueError(f'Import "{cmd.flow_name}" not found at {import_path}')
                imported = parse_flow(import_path.read_text(), flows_dir=flows_dir)
                cmd._commands = imported.commands

    return Flow(name=name, device_url=device_url, commands=commands)
