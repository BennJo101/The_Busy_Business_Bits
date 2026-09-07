"""The Boss's Desk.

The Busy Business Bits gate anything destructive behind the Boss's approval,
and that is the one moment in the whole app that needs a person. This puts it
on a screen you can reach: the Bit, what it wants, and two buttons.

It talks to the app over the USB lead it is already plugged into - one JSON
object per line, no wifi, no credentials, no configuration.

    in    {"t":"room","in":["Boss","Coder"],"who":"Coder","say":"..."}
          {"t":"ask","id":"7","bit":"Reaper","tool":"delete_paths","detail":"..."}
          {"t":"clear","id":"7"}
    out   {"t":"hello","dev":"bits-desk","v":1}
          {"t":"rule","id":"7","ok":true}
"""
import json
import select
import sys
import time
from machine import Pin

import tft as T
import touch as TC

# the roster's own colours, straight off the sprite cards
PALETTE = {
    "Boss": (0x5c, 0x7f, 0xd6), "Coder": (0x4f, 0xc0, 0x6a),
    "Courier": (0x6c, 0x8f, 0xe0), "Investigator": (0x4f, 0xc0, 0x6a),
    "Reaper": (0xe0, 0x68, 0x7a), "Secretary": (0xe0, 0x68, 0x7a),
    "Wizard": (0x7b, 0x7f, 0xd6), "Ghost": (0x9a, 0xa6, 0xb8),
    "Librarian": (0xc8, 0xa2, 0x4a),
}


def wrap(text, cols):
    """Break a line to fit, on spaces where it can."""
    out, line = [], ""
    for word in str(text).split():
        if len(word) > cols:                       # a path with no spaces in it
            while word:
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:cols])
                word = word[cols:]
            continue
        if len(line) + len(word) + (1 if line else 0) > cols:
            out.append(line)
            line = word
        else:
            line = (line + " " + word) if line else word
    if line:
        out.append(line)
    return out


class Desk:
    def __init__(self):
        self.d = T.TFT()
        self.t = TC.Touch()
        self.led = {c: Pin(p, Pin.OUT, value=1)      # active low
                    for c, p in (("r", 4), ("g", 16), ("b", 17))}
        d = self.d
        self.INK = d.rgb(26, 17, 22)
        self.PAPER = d.rgb(216, 207, 192)
        self.GOLD = d.rgb(232, 217, 184)
        self.DARK = d.rgb(102, 57, 49)
        self.DIM = d.rgb(122, 111, 99)
        self.GREEN = d.rgb(58, 168, 96)
        self.RED = d.rgb(192, 58, 74)
        self.ask = None                 # the approval on screen, if any
        self.room = {"in": [], "who": "", "say": ""}
        self.dirty = True
        self.flash_until = 0
        self.pulse = 0

    def lamp(self, r=False, g=False, b=False):
        self.led["r"].value(0 if r else 1)
        self.led["g"].value(0 if g else 1)
        self.led["b"].value(0 if b else 1)

    def colour_of(self, name):
        return self.d.rgb(*PALETTE.get(name, (200, 190, 175)))

    def draw(self):
        self.dirty = False
        if self.ask:
            self.draw_ask()
        else:
            self.draw_idle()

    def header(self, text, colour, ink):
        self.d.fill(0, 0, T.W, 26, colour)
        self.d.text(text[:26], 8, 9, ink, colour)

    def draw_idle(self):
        d = self.d
        d.clear(self.INK)
        self.header("THE BUSY BUSINESS BITS", self.DARK, self.GOLD)
        here = self.room.get("in") or []
        d.text("in the room" if here else "nobody in the room", 8, 38,
               self.DIM, self.INK)
        x = 8
        for name in here[:6]:
            if x + 8 * len(name) + 10 > T.W:
                break
            x += d.text(name, x, 56, self.colour_of(name), self.INK) + 14
        d.fill(8, 84, T.W - 16, 1, d.rgb(60, 45, 52))
        who, say = self.room.get("who") or "", self.room.get("say") or ""
        if who:
            d.text(who + ":", 8, 96, self.colour_of(who), self.INK)
        y = 116
        for line in wrap(say, 38)[:5]:
            d.text(line, 8, y, self.PAPER, self.INK)
            y += 14
        d.text("nothing needs you", 8, T.H - 18, self.DIM, self.INK)

    def draw_ask(self):
        d, a = self.d, self.ask
        bit = a.get("bit", "A Bit")
        d.clear(self.INK)
        self.header(bit.upper() + " WANTS TO", self.colour_of(bit), self.INK)
        d.text(str(a.get("tool", "?"))[:19], 8, 40, self.GOLD, self.INK, 2)
        y = 68
        for line in wrap(a.get("detail", ""), 38)[:4]:
            d.text(line, 8, y, self.PAPER, self.INK)
            y += 14
        d.text("your call", 8, 132, self.DIM, self.INK)
        self.buttons()

    def buttons(self, hit=None):
        d = self.d
        for x, w, colour, label, key in (
                (0, 158, self.RED, "REFUSE", "no"),
                (162, 158, self.GREEN, "APPROVE", "yes")):
            on = (hit == key)
            c = self.GOLD if on else colour
            d.fill(x, 152, w, 88, c)
            d.text(label, x + (w - 8 * len(label) * 2) // 2, 186,
                   self.INK if on else self.PAPER, c, 2)

    def flash(self, ok):
        self.buttons("yes" if ok else "no")
        self.lamp(g=ok, r=not ok)
        self.flash_until = time.ticks_add(time.ticks_ms(), 700)

    def send(self, obj):
        print(json.dumps(obj))

    def handle(self, msg):
        kind = msg.get("t")
        if kind == "room":
            self.room = {"in": msg.get("in") or [], "who": msg.get("who") or "",
                         "say": msg.get("say") or ""}
            if not self.ask:
                self.dirty = True
        elif kind == "ask":
            self.ask = msg
            self.dirty = True
        elif kind == "clear":
            if self.ask and (msg.get("id") is None
                             or msg.get("id") == self.ask.get("id")):
                self.ask = None
                self.lamp()
                self.dirty = True
        elif kind == "ping":
            self.send({"t": "hello", "dev": "bits-desk", "v": 1})

    def rule(self, ok):
        a, self.ask = self.ask, None
        self.flash(ok)
        self.send({"t": "rule", "id": a.get("id"), "ok": bool(ok)})

    def run(self):
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        buf = ""
        self.send({"t": "hello", "dev": "bits-desk", "v": 1})
        while True:
            while poll.poll(0):
                ch = sys.stdin.read(1)
                if ch is None:
                    break
                if ch == "\n":
                    line, buf = buf.strip(), ""
                    if line:
                        try:
                            self.handle(json.loads(line))
                        except Exception:
                            pass          # a half-line is not worth a crash
                else:
                    buf += ch
                    if len(buf) > 900:    # never grow without bound
                        buf = ""
            if self.flash_until:
                if time.ticks_diff(time.ticks_ms(), self.flash_until) > 0:
                    self.flash_until = 0
                    self.lamp()
                    self.dirty = True
            elif self.ask:
                # a slow amber pulse: something is waiting on you
                p = (time.ticks_ms() // 500) % 2
                if p != self.pulse:
                    self.pulse = p
                    self.lamp(r=True, g=bool(p))
            if self.dirty:
                self.draw()
            hit = self.t.get()
            if hit and self.ask and not self.flash_until and hit[1] > 145:
                self.rule(hit[0] > 160)
            time.sleep_ms(20)
