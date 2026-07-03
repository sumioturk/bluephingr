"""config.py — user-editable settings for the phingr Pico relay controller.

Edit this file on the device (Thonny, or `mpremote fs cp`) to match your setup.
This is the single source of truth: WiFi networks, hostname, and relay wiring.
"""

# ── WiFi ────────────────────────────────────────────────────────────────────
# Networks are tried in order; the first one that connects wins. Add as many
# (ssid, password) pairs as you like — home, lab, phone hotspot, etc.
WIFI_NETWORKS = [
    ("MySSID",     "password1"),
    ("BackupSSID", "password2"),
]

# Seconds to wait for each network before moving on to the next.
WIFI_TIMEOUT_S = 10

# ── Hostname / mDNS ─────────────────────────────────────────────────────────
# Reachable as "<HOSTNAME>.local" on the LAN (mirrors the RPi's phingr-XXXX.local).
# Must be set before the WiFi interface is activated (see wifi.py).
HOSTNAME = "phingr-pico"

# ── Relays ──────────────────────────────────────────────────────────────────
# NOTE: these are Pico **GP** pin numbers (see the Pico 2 W pinout), NOT the
# Broadcom BCM numbers used by the RPi version. GP17/27/22/23 are convenient
# general-purpose outputs; change to match your wiring.
RELAY_PINS = [17, 27, 22, 23]
RELAY_NAMES = ["Relay 1", "Relay 2", "Relay 3", "Relay 4"]

# True  -> relay energizes when the GPIO is driven HIGH (3.3V).
# False -> relay energizes on LOW (0V), typical of cheap optocoupler modules.
RELAY_ACTIVE_HIGH = True

# ── HTTP server ─────────────────────────────────────────────────────────────
HTTP_PORT = 8080
