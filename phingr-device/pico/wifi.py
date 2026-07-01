"""wifi.py — connect the Pico 2 W to the first reachable pre-specified network.

Sets the hostname *before* activating the interface so the RP2 lwIP mDNS
responder advertises "<HOSTNAME>.local" (this replaces avahi on the full RPi).
"""

import time

import network

import config

_wlan = None


def connect():
    """Try each network in config.WIFI_NETWORKS in order.

    Returns the assigned IP string on success, or None if none connected.
    """
    global _wlan

    # Hostname must be set before the interface comes up for it to reach DHCP
    # and the mDNS responder.
    try:
        network.hostname(config.HOSTNAME)
    except Exception as e:
        print("could not set hostname:", e)

    _wlan = network.WLAN(network.STA_IF)
    _wlan.active(True)

    for ssid, password in config.WIFI_NETWORKS:
        print("connecting to %r ..." % ssid)
        try:
            _wlan.connect(ssid, password)
        except Exception as e:
            print("  connect() failed:", e)
            continue

        deadline = time.time() + config.WIFI_TIMEOUT_S
        while time.time() < deadline:
            if _wlan.isconnected():
                ip = _wlan.ifconfig()[0]
                print("  connected: %s  ->  http://%s.local:%d  (or http://%s:%d)" % (
                    ssid, config.HOSTNAME, config.HTTP_PORT, ip, config.HTTP_PORT))
                return ip
            time.sleep(0.5)

        print("  timed out on %r" % ssid)
        try:
            _wlan.disconnect()
        except Exception:
            pass

    print("could not connect to any configured network")
    return None


def isconnected():
    return _wlan is not None and _wlan.isconnected()
