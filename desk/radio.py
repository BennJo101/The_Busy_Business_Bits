"""The board's own radios, lent to the Bits.

An ESP32 has WiFi and Bluetooth; the computer it is plugged into has its own.
These are the board's - a separate radio on a separate network, which is the
point of the toggle: what the Investigator fetches can go out over the board
rather than over the machine you are sitting at.

Everything here is written to answer in one call and never to block the desk
for longer than it says it will. A scan that takes four seconds says so on the
screen first, because a frozen screen looks broken.
"""
import time

import network

_wlan = None
_ble = None
_seen = {}

AUTH = {0: "open", 1: "WEP", 2: "WPA", 3: "WPA2", 4: "WPA/WPA2",
        5: "WPA2-ENT", 6: "WPA3", 7: "WPA2/WPA3"}


def wlan(on=True):
    global _wlan
    if _wlan is None:
        _wlan = network.WLAN(network.STA_IF)
    if on and not _wlan.active():
        _wlan.active(True)
        time.sleep_ms(300)
    return _wlan


def scan(limit=14):
    """Networks the board can hear, strongest first."""
    w = wlan()
    out = []
    for net in w.scan():
        ssid = net[0].decode("utf-8", "replace") if isinstance(net[0], bytes) \
            else str(net[0])
        out.append({"ssid": ssid or "(hidden)", "rssi": net[3],
                    "channel": net[2], "security": AUTH.get(net[4], "?")})
    out.sort(key=lambda n: -n["rssi"])
    return out[:limit]


def status():
    w = wlan(False)
    if not w.active():
        return {"on": False, "connected": False}
    try:
        ip, mask, gw, dns = w.ifconfig()
    except Exception:
        ip = gw = dns = ""
    ssid = ""
    try:
        ssid = w.config("essid")
    except Exception:
        pass
    return {"on": True, "connected": bool(w.isconnected()), "ssid": ssid,
            "ip": ip, "gateway": gw, "dns": dns,
            "rssi": w.status("rssi") if w.isconnected() else None}


def heard(ssid):
    """The network by that name as the board actually heard it.

    Matched without case: an SSID is case sensitive on the wire, but a person
    typing "Pretty Fly For A WiFi" for a network called "...Wifi" has not made
    a meaningful mistake, and joining with the spelling off the scan works.
    """
    want = str(ssid).strip().lower()
    try:
        nets = scan(40)
    except Exception:
        return None
    for net in nets:
        if net["ssid"].lower() == want:
            return net
    return None


def connect(ssid, password="", seconds=18):
    """Join a network. Returns the status either way, and never raises.

    The interface is taken down and brought back up first. Calling connect on
    a station that has been scanning is what gets you 'Wifi Internal State
    Error', which is a true thing to say about the driver and no use at all to
    anyone reading it.
    """
    if not ssid:
        return {"on": True, "connected": False, "error": "no network named"}
    try:
        w = wlan()
        w.active(False)                  # a clean state, or the driver objects
        time.sleep_ms(400)
        w.active(True)
        time.sleep_ms(400)
    except Exception as e:
        return {"on": False, "connected": False,
                "error": "the radio wouldn't start (%s)"
                         % (e.args[0] if e.args else repr(e))}
    # only now is a scan worth believing - a station left mid-connect from a
    # previous attempt hears nothing at all
    net = heard(ssid)
    if not net:
        near = ", ".join(n["ssid"] for n in (scan(6) or [])[:4])
        return {"on": True, "connected": False,
                "error": "the board can't hear a network called %s. It can hear: %s"
                         % (ssid, near or "nothing at all")}
    ssid = net["ssid"]                    # the spelling it actually heard
    how = net["security"]
    if how != "open" and not password:
        return {"on": True, "connected": False,
                "error": "%s is %s and no password was given" % (ssid, how)}
    try:
        w.connect(ssid, password)
    except Exception as e:
        return {"on": True, "connected": False,
                "error": "the radio wouldn't start on %s (%s)"
                         % (ssid, e.args[0] if e.args else repr(e))}
    end = time.ticks_add(time.ticks_ms(), int(seconds * 1000))
    while not w.isconnected() and time.ticks_diff(end, time.ticks_ms()) > 0:
        time.sleep_ms(250)
    got = status()
    if not got["connected"]:
        got["error"] = ("%s wouldn't have us - wrong password, or out of range"
                        % ssid)
    return got


def forget():
    w = wlan(False)
    if w.active():
        w.disconnect()
        w.active(False)
    return {"on": False, "connected": False}


# -- Bluetooth ---------------------------------------------------------------
def _name_from(adv):
    """The device's name out of its advertising data, if it gave one."""
    i = 0
    while i + 1 < len(adv):
        ln = adv[i]
        if ln == 0 or i + ln >= len(adv):
            break
        kind = adv[i + 1]
        if kind in (0x08, 0x09):                 # short and complete local name
            return bytes(adv[i + 2:i + 1 + ln]).decode("utf-8", "replace")
        i += ln + 1
    return ""


def bt_scan(seconds=4, limit=14):
    """What is advertising itself nearby."""
    import bluetooth
    global _ble, _seen
    _seen = {}
    if _ble is None:
        _ble = bluetooth.BLE()
    _ble.active(True)

    def handler(event, data):
        if event != 5:                           # _IRQ_SCAN_RESULT
            return
        addr_type, addr, adv_type, rssi, adv = data
        key = ":".join("%02x" % b for b in bytes(addr))
        was = _seen.get(key)
        name = _name_from(bytes(adv)) or (was or {}).get("name", "")
        if not was or rssi > was["rssi"]:
            _seen[key] = {"address": key, "name": name, "rssi": rssi}
        elif name and not was.get("name"):
            was["name"] = name

    _ble.irq(handler)
    _ble.gap_scan(int(seconds * 1000), 30000, 30000, True)
    end = time.ticks_add(time.ticks_ms(), int(seconds * 1000) + 700)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        time.sleep_ms(100)
    try:
        _ble.gap_scan(None)
        _ble.active(False)
    except Exception:
        pass
    out = sorted(_seen.values(), key=lambda d: -d["rssi"])
    return out[:limit]


# -- the web, over the board's radio -----------------------------------------
def get(url, limit=4000):
    """Fetch a page over the board's WiFi and hand back the text.

    Deliberately capped. The board has about 140k of RAM and the link back to
    the computer moves 7KB a second, so a whole page is neither storable nor
    worth sending; the Investigator gets the top of it, which is what it reads.
    """
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    w = wlan(False)
    if not w.active() or not w.isconnected():
        return {"ok": False, "error": "the board isn't on a network yet"}
    import requests
    r = None
    try:
        r = requests.get(url, headers={"User-Agent":
                                       "BusyBusinessBits/1.0 (desk unit)"})
        code = r.status_code
        ctype = ""
        try:
            ctype = r.headers.get("Content-Type", "")
        except Exception:
            pass
        text = r.text[:limit]
        return {"ok": True, "status": code, "type": ctype, "text": text,
                "url": url}
    except Exception as e:
        return {"ok": False, "error": "%s: %r" % (url, e)}
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
