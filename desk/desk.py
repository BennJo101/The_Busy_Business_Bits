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

import carrier
from portal import AP_NAME as P_NAME, AP_PASS as P_PASS
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


# The 8x8 font at scale 1, across a 320px screen with an 8px margin each side.
# Anything drawn wider than this runs off the edge or into whatever is drawn
# after it.
COLS = 38


def fits(left, right, cols=COLS):
    """Two labels on one line, guaranteed not to overlap."""
    keep = cols - (len(right) + 1 if right else 0)
    return left[:max(0, keep)], right


GAP = 14                  # pixels between two names on the same row


def name_rows(names, rows=3, width=320, margin=8, gap=GAP, cell=8):
    """The roster packed into rows that actually fit across the screen.

    The last row keeps a "+N" when there are more than will go, because a
    list that silently stops is worse than a short one: the whole point of
    showing who is in the room is knowing who is in the room.
    """
    out, row, x = [], [], margin
    space = width - margin
    for i, name in enumerate(names):
        need = cell * len(name)
        if row and x + need > space:
            out.append(row)
            if len(out) == rows:                    # no room for another line
                left = len(names) - i
                if left:
                    tail = "+%d" % left
                    while out[-1] and (margin + sum(cell * len(n) + gap
                                                    for n in out[-1])
                                       + cell * len(tail)) > space:
                        out[-1].pop()
                    out[-1].append(tail)
                return out
            row, x = [], margin
        row.append(name)
        x += need + gap
    if row:
        out.append(row)
    return out


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
        # The card is mounted once, here, and kept: the driver will not come
        # back a second time in one boot, and the screen wants to say what it
        # is carrying.
        self.carrying = 0
        if carrier.mount():
            try:
                self.carrying = carrier.total()[0]
            except Exception:
                self.carrying = 0
        self.ask = None                 # the approval on screen, if any
        # Two different things, deliberately. `live` is whether the access
        # point is broadcasting; `ap` is whether the screen is currently given
        # over to explaining it. Setting one from the other meant the board
        # could only offer to hand over while it was showing nothing else -
        # so the way to set up a new computer was to already know to press a
        # strip you could not see.
        self.ap = ""                    # the address, while that screen is up
        self.ap_live = ""               # the address, whenever it is running
        # The room as it has actually gone, not just its last line. The idle
        # screen has room for five lines of one speaker, which is enough to
        # see that something was said and not enough to read it.
        self.log = []                   # (who, said), oldest first
        self.chat = False               # the transcript, full screen
        self.top = 0                    # first line shown, while it is open
        self.room = {"in": [], "who": "", "say": ""}
        self.dirty = True
        self.flash_until = 0
        self.pulse = 0
        self.strip_top = 146   # set by draw_idle; the touch chain reads it
        # Setting a computer up is a thing that finishes. START is how the
        # board is told it has: nothing is listening for that press until
        # the Bits are installed and running on the far end.
        self.setup_done = False
        self._net = ("", "")   # (network, address), cached
        self._net_at = 0
        self.ticks = 0          # main-loop counter, so a stall is visible

    def lamp(self, r=False, g=False, b=False):
        self.led["r"].value(0 if r else 1)
        self.led["g"].value(0 if g else 1)
        self.led["b"].value(0 if b else 1)

    def colour_of(self, name):
        return self.d.rgb(*PALETTE.get(name, (200, 190, 175)))

    def station(self):
        """(network joined, address on it), or ("", "") if it has joined none.

        Cached for a few seconds: this is read while drawing, and the screen
        redraws on every message that arrives.
        """
        now = time.ticks_ms()
        if self._net_at and time.ticks_diff(now, self._net_at) < 5000:
            return self._net
        self._net_at = now
        try:
            import network
            w = network.WLAN(network.STA_IF)
            if w.active() and w.isconnected():
                try:
                    ssid = w.config("essid")
                except Exception:
                    ssid = ""
                self._net = (ssid, w.ifconfig()[0])
            else:
                self._net = ("", "")
        except Exception:
            self._net = ("", "")
        return self._net

    def station_ip(self):
        return self.station()[1]

    def joined(self, st=None):
        """The portal has just put the board on a network.

        Called from the web server's thread the moment somebody submits the
        form. Without it the screen went on showing the access point and the
        setup address for as long as it was left alone: the board knew it had
        moved and the person standing in front of it did not, which is the one
        moment they need the new address.
        """
        self._net_at = 0                 # forget what was cached
        try:
            self.station()               # and look it up now
        except Exception:
            pass
        self.dirty = True

    def draw(self):
        self.dirty = False
        if self.ap:
            self.draw_portal()
        elif self.ask:
            self.draw_ask()
        elif self.chat:
            self.draw_chat()
        else:
            self.draw_idle()

    def header(self, text, colour, ink):
        self.d.fill(0, 0, T.W, 26, colour)
        self.d.text(text[:26], 8, 9, ink, colour)

    ROWS = 13                 # lines of transcript that fit between the bars
    ROOM_ROWS = 3             # rows the roster may take before it says "+N"

    def lines(self):
        """The whole room, flattened to drawable lines.

        Each is (text, who) - who is "" for a continuation, so a speaker's
        name keeps its colour and the words stay readable.
        """
        out = []
        for who, said in self.log:
            out.append((who + ":", who))
            for line in wrap(said, 38):
                out.append((line, ""))
        return out

    def draw_chat(self):
        """The room, full screen, scrolled."""
        d = self.d
        d.clear(self.INK)
        rows = self.lines()
        self.header("THE ROOM  (%d-%d of %d)"
                    % (min(self.top + 1, len(rows)),
                       min(self.top + self.ROWS, len(rows)), len(rows)),
                    self.DARK, self.GOLD)
        if not rows:
            d.text("nothing has been said yet.", 8, 100, self.DIM, self.INK)
        y = 34
        for text, who in rows[self.top:self.top + self.ROWS]:
            d.text(text, 8, y, self.colour_of(who) if who else self.PAPER,
                   self.INK)
            y += 14
        bar = d.rgb(42, 30, 36)
        d.fill(0, 208, T.W, 32, bar)
        third = T.W // 3
        at_top, at_end = self.top <= 0, self.top + self.ROWS >= len(rows)
        d.text("up", 34, 218, self.DIM if at_top else self.GOLD, bar)
        d.text("close", third + 26, 218, self.GOLD, bar)
        d.text("down", 2 * third + 22, 218,
               self.DIM if at_end else self.GOLD, bar)
        d.fill(third, 208, 1, 32, self.INK)
        d.fill(2 * third, 208, 1, 32, self.INK)

    def strip_lines(self):
        """What the strip has to say, as (text, colour).

        All of it is about setting a computer up, so all of it stops at the
        first START: that press is somebody telling the board the machine in
        front of it is already running the Bits.
        """
        ssid, ip = self.station()
        if self.setup_done:
            out = []
        elif ip:
            # joined. The network and the address are what is wanted now; the
            # password is not, and putting it up once it is spent is just
            # leaving it on a screen.
            out = [("On: " + ssid, self.GOLD), ("IP: " + ip, self.PAPER)]
            if self.ap_live:
                out.append(("Setup: %s / %s" % (P_NAME, self.ap_live), self.DIM))
        elif self.ap_live:
            out = [("SSID: " + P_NAME, self.GOLD),
                   ("Password: " + P_PASS, self.PAPER),
                   ("Webpage: " + self.ap_live, self.PAPER)]
        else:
            out = []
        return [(t[:COLS], c) for t, c in out]

    # Where the strip begins. It is as tall as it needs to be, and a press has
    # to mean what it looks like it means - so this decides the touch boundary
    # too, rather than the two being written down separately and drifting.
    def strip_at(self):
        return {3: 126, 2: 140}.get(len(self.strip_lines()), 146)

    def draw_idle(self):
        d = self.d
        self.strip_top = self.strip_at()
        d.clear(self.INK)
        self.header("THE BUSY BUSINESS BITS", self.DARK, self.GOLD)
        here = self.room.get("in") or []
        d.text("in the room" if here else "nobody in the room", 8, 38,
               self.DIM, self.INK)
        # Every name, wrapped. It used to stop at six and then stop again at
        # the edge of the line, so with the whole roster in the room the board
        # showed two of them and no sign there were more - which is the one
        # moment the list is worth having.
        y = 56
        for row in name_rows(here, self.ROOM_ROWS):
            x = 8
            for name in row:
                x += d.text(name, x, y, self.colour_of(name), self.INK) + GAP
            y += 14
        if here:
            y += 2

        d.fill(8, y, T.W - 16, 1, d.rgb(60, 45, 52))
        y += 10
        who, say = self.room.get("who") or "", self.room.get("say") or ""
        if who:
            d.text(who + ":", 8, y, self.colour_of(who), self.INK)
            if self.log:
                # say so, because a region that does something when pressed
                # and looks exactly like one that does not is not a control
                note = "tap to read (%d)" % len(self.log)
                d.text(note, T.W - 8 * len(note) - 8, y, self.DIM, self.INK)
            y += 16
        # Whatever is left between the names and the strip. A crowded room
        # gets fewer lines of what was said, which is the right way round -
        # the transcript is a tap away and the roster is not.
        for line in wrap(say, COLS):
            if y > self.strip_top - 16:
                break
            d.text(line, 8, y, self.PAPER, self.INK)
            y += 14
        # A tappable strip of its own. The portal has to be reachable from
        # the board alone: the computer it is being handed to has no software
        # to ask for it with, which is the entire problem being solved.
        strip = d.rgb(42, 30, 36)
        d.fill(0, self.strip_top, T.W, 172 - self.strip_top, strip)
        # A bare computer needs the network, the password for it and the
        # address to open, and no two of those are any use without the third.
        # It has to be legible without pressing anything: the machine being
        # set up has no way of being told any of it.
        rows = self.strip_lines()
        if rows:
            y = self.strip_top + 3 + (6 if len(rows) == 2 else 0)
            for text, ink in rows:
                d.text(text, 8, y, ink, strip)
                y += 14
        else:
            # Both ends of one line, and they must not meet in the middle. The
            # right-hand label used to be placed as though it were always
            # seventeen characters wide, so a longer one began before the
            # left-hand one had finished and overwrote its tail: "hand over to
            # a new cocarrying101 files".
            right = ("%d files" % self.carrying) if self.carrying else ""
            left, right = fits("hand over to a new computer", right)
            d.text(left, 8, 150, self.GOLD, strip)
            if right:
                d.text(right, T.W - 8 * len(right) - 8, 150, self.DIM, strip)
        self.start_button()

    def start_button(self, hit=False):
        """The way in. Tapping it opens the Wizard on the computer."""
        d = self.d
        c = self.GOLD if hit else self.DARK
        d.fill(0, 174, T.W, 66, c)
        label = "START"
        d.text(label, (T.W - 8 * len(label) * 2) // 2, 198,
               self.INK if hit else self.GOLD, c, 2)

    def busy(self, what):
        """Say what the radio is doing. A four-second scan on a frozen screen
        looks like a crash; the same four seconds with a word on it does not."""
        d = self.d
        d.fill(0, 174, T.W, 66, self.INK)
        d.text(what[:34], 8, 198, self.GOLD, self.INK)

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
        """One flash of the ruling: green for yes, red for no, then out."""
        self.buttons("yes" if ok else "no")
        self.lamp(g=ok, r=not ok)
        self.flash_until = time.ticks_add(time.ticks_ms(), 700)

    def hello(self):
        """Who we are, and what we are carrying - so the app can say so."""
        return {"t": "hello", "dev": "bits-desk", "v": 1,
                "carrying": self.carrying}

    def send(self, obj):
        print(json.dumps(obj))

    def portal(self, on=True, show=True):
        """Become an access point, so a bare computer can be handed the Bits.

        The screen carries the instructions, because at this point the computer
        has no way to be told anything: it has a COM port it cannot use and no
        software to use it with. What it does have is wifi and a browser.
        """
        import portal as P
        if not on:
            P.stop_ap()
            self.ap = self.ap_live = ""
            self.dirty = True
            return
        if self.ap_live:                  # already broadcasting; just show it
            self.ap = self.ap_live if show else ""
            self.dirty = True
            return
        try:
            if show:
                self.busy("starting the access point...")
            self.ap_live = P.start_ap()
            import _thread
            _thread.start_new_thread(P.serve, (self.joined,))
        except Exception as e:
            self.ap = self.ap_live = ""
            if show:
                self.busy("no access point: %r" % e)
            return
        self.ap = self.ap_live if show else ""
        self.dirty = True

    def draw_portal(self):
        """What to type into a machine that has nothing on it."""
        d = self.d
        d.clear(self.INK)
        self.header("HANDING OVER THE BITS", self.DARK, self.GOLD)
        d.text("join this wifi:", 8, 40, self.DIM, self.INK)
        d.text(P_NAME, 8, 58, self.GOLD, self.INK, 2)
        d.text("password:  " + P_PASS, 8, 88, self.PAPER, self.INK)
        d.text("then open a browser at:", 8, 118, self.DIM, self.INK)
        d.text("http://" + self.ap, 8, 138, self.GOLD, self.INK, 2)
        d.fill(0, 174, T.W, 66, self.DARK)
        d.text("tap to stop", (T.W - 8 * 11) // 2, 200, self.GOLD, self.DARK)

    # Where the crosses go. Well inside the edges, because the panel is least
    # linear at its rim, and far apart, because a short baseline multiplies
    # every millimetre of thumb into pixels of error. The third is only
    # checked against, never fitted - it is how a bad calibration is caught
    # before it is kept.
    TARGETS = [(40, 40), (280, 200), (160, 120)]

    def cross(self, x, y, n, of):
        d = self.d
        d.clear(self.INK)
        self.header("CALIBRATING THE SCREEN", self.DARK, self.GOLD)
        d.text("press the middle of the cross", 8, 40, self.PAPER, self.INK)
        d.text("%d of %d" % (n, of), 8, 58, self.DIM, self.INK)
        d.fill(x - 12, y, 25, 1, self.GOLD)
        d.fill(x, y - 12, 1, 25, self.GOLD)
        d.fill(x - 2, y - 2, 5, 5, self.RED)

    def calibrate(self):
        """Three presses, and the panel knows where the screen is.

        Returns what to say about it. Nothing is kept unless the third press
        lands where the first two say it should: a calibration that is quietly
        wrong makes every button on this board miss, which is far worse than
        one that says it could not do it.
        """
        readings = []
        for i, (x, y) in enumerate(self.TARGETS):
            self.cross(x, y, i + 1, len(self.TARGETS))
            got = self.t.press(seconds=60)
            if not got:
                self.dirty = True
                return {"ok": False, "error": "nothing was pressed"}
            readings.append(got)
        cal = self.t.calibrate(self.TARGETS, readings)
        if not cal:
            self.dirty = True
            return {"ok": False, "error": "those presses do not make a screen"}
        off, good = self.t.check(cal, self.TARGETS, readings)
        if not good:
            self.dirty = True
            return {"ok": False, "error": "off by %s px - not kept" % max(off),
                    "off": off}
        self.t.adopt(cal)
        self.dirty = True
        return {"ok": True, "cal": cal, "off": off}

    def radio(self, msg):
        """Anything that needs the board's own WiFi or Bluetooth.

        Answered in one call with the id it came in with, because the computer
        blocks a Bit's turn waiting for it.
        """
        import radio as R
        do = msg.get("do") or ""
        args = msg.get("args") or {}
        self.busy({"scan": "scanning for networks...",
                   "bt": "listening for Bluetooth...",
                   "connect": "joining %s..." % args.get("ssid", ""),
                   "get": "fetching over the board..."}.get(do, do))
        try:
            if do == "scan":
                out = R.scan(int(args.get("limit", 14)))
            elif do == "status":
                out = R.status()
            elif do == "connect":
                out = R.connect(args.get("ssid", ""), args.get("password", ""),
                                int(args.get("seconds", 18)))
            elif do == "forget":
                out = R.forget()
            elif do == "bt":
                out = R.bt_scan(float(args.get("seconds", 4)),
                                int(args.get("limit", 14)))
            elif do == "get":
                out = R.get(args.get("url", ""), int(args.get("limit", 4000)))
            else:
                self.send({"t": "radio", "id": msg.get("id"), "ok": False,
                           "error": "no such radio call: %s" % do})
                self.dirty = True
                return
            self.send({"t": "radio", "id": msg.get("id"), "ok": True, "out": out})
        except Exception as e:
            self.send({"t": "radio", "id": msg.get("id"), "ok": False,
                       "error": repr(e)})
        self.dirty = True

    def handle(self, msg):
        kind = msg.get("t")
        if kind == "room":
            self.room = {"in": msg.get("in") or [], "who": msg.get("who") or "",
                         "say": msg.get("say") or ""}
            who, say = self.room["who"], self.room["say"]
            if who and say and (not self.log or self.log[-1] != (who, say)):
                self.log.append((who, say))
                # 40 turns is a few screens to scroll back through and about
                # six kilobytes. The board has a hundred and thirty free, and
                # a transcript is not what it should spend them on.
                del self.log[:-40]
                if self.chat and self.top >= len(self.lines()) - 1:
                    self.top = max(0, len(self.lines()) - self.ROWS)
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
        elif kind == "radio":
            self.radio(msg)
        elif kind == "portal":
            self.portal(bool(msg.get("on", True)))
        elif kind == "state":
            # what it thinks it is showing. Worth having: the difference
            # between "the touch panel is wrong" and "the screen is not the
            # one you think it is" cost an hour of guessing once.
            self.send({"t": "state", "ticks": self.ticks,
                       "ask": (self.ask or {}).get("id"),
                       "flash": bool(self.flash_until), "dirty": self.dirty,
                       "carrying": self.carrying, "in": self.room.get("in"),
                       # whether the access point is up, and whether the
                       # screen is currently given over to explaining it.
                       # Without the first, the only way to find out was to
                       # interrupt the desk and ask the radio - which reboots
                       # the board, which restarts the access point, so the
                       # question could not be asked without changing the
                       # answer.
                       "ap": self.ap_live, "ap_shown": bool(self.ap),
                       "chat": bool(self.chat), "top": self.top,
                       "said": len(self.log),
                       "irq": self.t.irq.value(), "raw": self.t.raw()})
            # deliberately not t.get(): that consumes the press and resets the
            # debounce, so asking what the screen sees would take the press
            # away from the loop that acts on it
        elif kind == "calibrate":
            out = self.calibrate()
            out["t"] = "calibrated"
            self.send(out)
        elif kind == "tap":
            # A press, sent down the wire. The screen has no other way of
            # being exercised without a thumb, and "does the transcript
            # scroll" is not a question worth answering by hand every time.
            try:
                self.press(int(msg.get("x", 0)), int(msg.get("y", 0)))
            except Exception:
                pass
        elif kind == "ping":
            self.send(self.hello())

    def rule(self, ok):
        a, self.ask = self.ask, None
        self.flash(ok)
        self.send({"t": "rule", "id": a.get("id"), "ok": bool(ok)})

    def press(self, x, y):
        """Act on a press at (x, y).

        Split out of the main loop so the same code answers the touch panel
        and a press sent down the wire, which is what makes the screen
        testable without a thumb.

        The order here has to agree with draw(): whatever is on the screen is
        what a press is about. An approval is drawn over the transcript, so it
        is ruled on before the transcript sees the press - otherwise the gate
        is visible and unanswerable, which is the worst of both.
        """
        if self.flash_until:
            return
        if self.ap and y > 168:
            self.portal(False)              # tap to stop handing over
        elif self.ask and y > 145:
            self.rule(x > 160)
        elif self.chat:
            # up / close / down along the bottom; anywhere above is a page
            # down, which is what a thumb does to a wall of text it is reading
            rows = len(self.lines())
            last = max(0, rows - self.ROWS)
            if y > 204:
                third = T.W // 3
                if x < third:
                    self.top = max(0, self.top - self.ROWS)
                elif x < 2 * third:
                    self.chat = False
                else:
                    self.top = min(last, self.top + self.ROWS)
            else:
                self.top = min(last, self.top + self.ROWS)
            self.dirty = True
        elif not self.ask and 84 < y <= self.strip_top:
            # the room, which the idle screen shows two lines of - enough to
            # see that something was said and not enough to read it
            self.chat = True
            self.top = max(0, len(self.lines()) - self.ROWS)
            self.dirty = True
        elif not self.ask and self.strip_top < y <= 172:
            self.portal(True)               # the strip above START
        elif not self.ask and y > 172:
            # anything below the header. There is nothing else to press on
            # this screen, and a resistive panel read through a rough
            # calibration lands lower than the bar is drawn.
            # Sent before the button is drawn: the computer should hear about
            # it first, the highlight can wait 28ms.
            self.send({"t": "start"})
            self.start_button(True)
            self.flash_until = time.ticks_add(time.ticks_ms(), 400)
            # START only means anything on a computer that already has the
            # Bits on it - something has to be listening for it. So pressing
            # it settles the question the access point was there to ask, and
            # the radio can go down. A power cycle brings it back, which is
            # the case that matters: a board carried to a bare machine.
            self.setup_done = True
            if self.ap_live:
                self.portal(False)

    def run(self):
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        buf = ""
        self.send(self.hello())
        # Broadcast from the moment it is powered, without taking the screen.
        # Setting up a computer is exactly when you cannot ask the board for
        # anything - it is the case where nothing else is working yet - so the
        # network has to already be there rather than be summoned first.
        try:
            self.portal(True, show=False)
        except Exception:
            pass                     # no radio is not a reason not to be a desk
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
                # yellow, on and off, for as long as it is waiting on you -
                # red and green together is the only yellow this lamp has
                p = (time.ticks_ms() // 450) % 2
                if p != self.pulse:
                    self.pulse = p
                    self.lamp(r=bool(p), g=bool(p))
            # The panel is read before the redraw, not after. A full idle
            # redraw is 195ms, and a tap that landed inside one was simply
            # missed - which is why START seemed to need pressing twice.
            self.ticks += 1
            hit = self.t.get()
            if self.dirty:
                self.draw()
            if hit:
                self.press(hit[0], hit[1])
            time.sleep_ms(20)
