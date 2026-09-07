"""The desk unit - the Boss's gate, on a screen you can reach.

An ESP32-2432S028 ("cheap yellow display") on the USB lead becomes a physical
approval gate: when a Bit queues something destructive, the little screen lights
up with who wants what, and two buttons settle it. The rest of the time it shows
the room.

Optional in exactly the way the watchers are - no board plugged in, no pyserial
installed, and the app is unchanged.

The board speaks one JSON object per line over the USB serial it is already
plugged into. No wifi, so no credentials, no network, nothing to configure.
"""
import json
import subprocess
import sys
import threading
import time
import os

try:
    import serial
    from serial.tools import list_ports
    SERIAL_OK = True
except Exception:                                                 # noqa: BLE001
    serial = None
    SERIAL_OK = False

BAUD = 115200
DEVICE = "bits-desk"
RETRY_SECS = 4.0


CH340 = (0x1A86, 0x7523)


def _ports():
    """Ports worth saying hello to, the CH340 this board uses first.

    USB only. A PC has serial ports that are not sockets on the back of it -
    an Intel AMT console, a legacy COM1 - and opening those every few seconds
    to ask whether they are a games console is not a good way to behave.
    """
    if not SERIAL_OK:
        return []
    found = [p for p in list_ports.comports() if p.vid is not None]
    found.sort(key=lambda p: 0 if (p.vid, p.pid) == CH340 else 1)
    return [p.device for p in found]


class Desk:
    """The board, if it is there. Every method is safe when it isn't."""

    def __init__(self, on_rule=None, on_note=None, on_start=None):
        self.on_rule = on_rule          # (approval_id, approved) -> None
        self.on_note = on_note          # (text) -> None, for the console
        self.on_start = on_start        # () -> None, the START button
        self.port = ""
        self.ser = None
        self.on = False
        self.carrying = 0               # files the board's SD card is holding
        self._waits = {}                # radio calls waiting on an answer
        self._seq = 0
        self._last_room = None
        self._last_ask = None
        self._lock = threading.Lock()

    # -- connecting ---------------------------------------------------------
    def start(self):
        if not SERIAL_OK or self.on:
            return False
        self.on = True
        threading.Thread(target=self._work, daemon=True).start()
        return True

    def stop(self):
        self.on = False
        self._shut()

    def _shut(self):
        with self._lock:
            s, self.ser = self.ser, None
            self.port = ""
        if s:
            try:
                s.close()
            except Exception:                                     # noqa: BLE001
                pass

    def _open(self, port):
        """Open without touching DTR/RTS - those are wired to the ESP32's reset
        and boot pins, and asserting them reboots the board on every connect."""
        s = serial.Serial()
        s.port = port
        s.baudrate = BAUD
        s.timeout = 0.3
        s.dtr = False
        s.rts = False
        s.open()
        return s

    def _find(self):
        """Say hello to each port until something says hello back."""
        for port in _ports():
            s = None
            try:
                s = self._open(port)
                time.sleep(0.2)
                s.reset_input_buffer()
                s.write(b'{"t":"ping"}\n')
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    line = s.readline()
                    if not line:
                        continue
                    if DEVICE.encode() in line:
                        try:
                            self.carrying = int(json.loads(line.decode(
                                "utf-8", "replace")).get("carrying") or 0)
                        except Exception:                         # noqa: BLE001
                            self.carrying = 0
                        return s, port
            except Exception:                                     # noqa: BLE001
                pass
            if s:
                try:
                    s.close()
                except Exception:                                 # noqa: BLE001
                    pass
        return None, ""

    # -- the loop -----------------------------------------------------------
    def _work(self):
        while self.on:
            s, port = self._find()
            if not s:
                time.sleep(RETRY_SECS)
                continue
            with self._lock:
                self.ser, self.port = s, port
            # forget what it was showing: it has just booted, and the app
            # will assert the whole state again on its next tick
            self._last_room = self._last_ask = None
            if self.carrying:
                self.note("the desk is on %s, carrying the Bits - %d files. "
                          "desk/carry_bits.py --unload DIR takes them off."
                          % (port, self.carrying))
            else:
                self.note("the desk is on %s." % port)
            try:
                while self.on:
                    line = s.readline()
                    if not line:
                        continue
                    self._line(line)
            except Exception:                                     # noqa: BLE001
                pass
            self._shut()
            if self.on:
                self.note("the desk was unplugged.")
                time.sleep(RETRY_SECS)

    def _line(self, raw):
        try:
            msg = json.loads(raw.decode("utf-8", "replace").strip())
        except Exception:                                         # noqa: BLE001
            return                          # the boot banner, mostly
        kind = msg.get("t")
        if kind == "radio":
            wait = self._waits.get(msg.get("id"))
            if wait:
                wait[1] = msg
                wait[0].set()
        elif kind == "start":
            self._last_ask = None
            if self.on_start:
                self.on_start()
        elif kind == "rule":
            self._last_ask = None          # it has cleared its own screen
            if self.on_rule:
                self.on_rule(msg.get("id"), bool(msg.get("ok")))

    # -- talking to it ------------------------------------------------------
    def send(self, obj):
        with self._lock:
            s = self.ser
        if not s:
            return False
        try:
            s.write((json.dumps(obj) + "\n").encode())
            return True
        except Exception:                                         # noqa: BLE001
            return False

    def here(self):
        return bool(self.ser)

    def radio(self, do, timeout=40.0, **args):
        """Ask the board to use its own WiFi or Bluetooth, and wait.

        Called from a Bit's worker thread, which is already blocked on its own
        turn - so blocking here costs nothing that wasn't already being waited
        on. Returns the board's answer, or a dict saying why not.
        """
        if not self.here():
            return {"ok": False, "error": "no desk unit plugged in"}
        with self._lock:
            self._seq += 1
            call_id = self._seq
        gate = [threading.Event(), None]
        self._waits[call_id] = gate
        try:
            if not self.send({"t": "radio", "id": call_id, "do": do,
                              "args": args}):
                return {"ok": False, "error": "the desk unit stopped listening"}
            if not gate[0].wait(timeout):
                return {"ok": False, "error": "the desk unit didn't answer in "
                                              "%ds" % int(timeout)}
            msg = gate[1] or {}
            if not msg.get("ok"):
                return {"ok": False, "error": msg.get("error", "it wouldn't say")}
            return {"ok": True, "out": msg.get("out")}
        finally:
            self._waits.pop(call_id, None)

    def note(self, text):
        if self.on_note:
            try:
                self.on_note(text)
            except Exception:                                     # noqa: BLE001
                pass

    def room(self, present, who="", say=""):
        """Who is on screen and the last thing said. Sent only when it changes -
        the board redraws on every message and a redraw is 60ms of SPI."""
        state = (tuple(present), who, say)
        if state == self._last_room:
            return
        self._last_room = state
        self.send({"t": "room", "in": list(present), "who": who,
                   "say": (say or "")[:160]})

    def ask(self, item):
        """Put an approval on the screen.

        Idempotent, like `room`: the app asserts what should be showing on a
        tick and this sends only when that changes, so a reconnect redraws and
        a quiet second costs nothing.
        """
        if item.get("id") == self._last_ask:
            return True
        self._last_ask = item.get("id")
        self._last_room = None
        return self.send({"t": "ask", "id": item.get("id"),
                          "bit": item.get("bit", "").replace("The ", ""),
                          "tool": item.get("tool", ""),
                          "detail": _detail(item)})

    def clear(self, approval_id=None):
        if self._last_ask is None:
            return True
        self._last_ask = None
        self._last_room = None
        return self.send({"t": "clear", "id": approval_id})


def _detail(item):
    """The one line that has to carry the decision.

    Whatever the tool is actually about - the path, the command, the address -
    rather than the whole argument list, which never fits on a 40-column screen.
    """
    args = item.get("args") or {}
    for key in ("paths", "path", "cmd", "to", "url", "package", "name", "query"):
        if args.get(key):
            v = args[key]
            if isinstance(v, (list, tuple)):
                head = ", ".join(str(x) for x in v[:3])
                return head + (" (+%d more)" % (len(v) - 3) if len(v) > 3 else "")
            return str(v)
    return item.get("summary", "")


def watch():
    """Wait for START on the board, then start the Bits.

        python bits_desk.py

    For a computer the Bits are not running on yet - the board is plugged in,
    the screen says START, and pressing it brings them up. The watcher hands
    the port over as it goes: the app wants it for the gate, and two things
    cannot hold one serial port.
    """
    import os
    import subprocess
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    app = os.path.join(here, "busy_business_bits.py")
    if not os.path.isfile(app):
        sys.exit("busy_business_bits.py isn't next to this file.")

    pressed = threading.Event()
    desk = Desk(on_start=pressed.set,
                on_note=lambda t: print(t, flush=True))
    if not desk.start():
        sys.exit("this needs pyserial:  pip install pyserial")
    print("waiting for START on the desk unit. Ctrl-C to give up.",
          flush=True)
    try:
        while not pressed.wait(0.5):
            pass
    except KeyboardInterrupt:
        desk.stop()
        return
    print("starting the Bits...", flush=True)
    desk.stop()
    time.sleep(0.8)                 # let the port go before the app wants it
    subprocess.Popen([sys.executable, app], cwd=here)


if __name__ == "__main__":
    watch()
