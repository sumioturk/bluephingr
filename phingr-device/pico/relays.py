"""relays.py — GPIO relay control for the Pico 2 W.

MicroPython port of the RPi relay layer (relay_init/set/state in
phingr-device/rpi/server/web_server.py). Uses machine.Pin instead of gpiozero
and keeps the same JSON state shape so existing clients work unchanged.

asyncio on the Pico is single-threaded, so no locking is needed.
"""

from machine import Pin

import config

_relays = []                                   # list of machine.Pin outputs
_state = [False] * len(config.RELAY_PINS)      # tracked on/off per relay
_available = False


def init():
    """Set up the GPIO relay outputs. Degrades gracefully if a pin is bad."""
    global _relays, _available
    try:
        _relays = [Pin(pin, Pin.OUT) for pin in config.RELAY_PINS]
        # Drive every relay to the OFF state at startup.
        for i in range(len(_relays)):
            _write(i, False)
        _available = True
        print("relays ready on GP pins %s (active_%s)" % (
            config.RELAY_PINS, "high" if config.RELAY_ACTIVE_HIGH else "low"))
    except Exception as e:
        _relays = []
        _available = False
        print("relays not available:", e)


def _write(index, on):
    """Drive the physical pin, honoring RELAY_ACTIVE_HIGH."""
    level = 1 if on else 0
    if not config.RELAY_ACTIVE_HIGH:
        level = 1 - level
    _relays[index].value(level)


def available():
    return _available


def set(index, on):
    """Switch a single relay on/off. Returns True on success."""
    if index < 0 or index >= len(config.RELAY_PINS):
        return False
    on = bool(on)
    if _available and index < len(_relays):
        try:
            _write(index, on)
        except Exception as e:
            print("relay %d set failed: %s" % (index, e))
            return False
    _state[index] = on
    print("relay %d -> %s" % (index + 1, "ON" if on else "OFF"))
    return True


def is_on(index):
    """Current tracked state of a relay (False if index out of range)."""
    if 0 <= index < len(_state):
        return _state[index]
    return False


def state():
    """Return the current state of every relay (same shape as the RPi API)."""
    return [
        {"index": i, "name": config.RELAY_NAMES[i], "on": _state[i]}
        for i in range(len(config.RELAY_PINS))
    ]
