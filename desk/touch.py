"""XPT2046 resistive touch, on its own SPI bus on the CYD.

Deliberately coarse. Nothing on this screen is smaller than a third of it, so
a rough calibration is all it needs and nobody has to tap crosshairs.
"""
from machine import Pin, SoftSPI
import json
import time

# what the panel reads at the edges - the usual spread for this screen, and
# what it falls back to when nobody has calibrated this particular one
DEFAULT = {"x_min": 300, "x_max": 3800, "y_min": 300, "y_max": 3800}
CAL_PATH = "/touch.json"


def load_cal():
    """The numbers for this panel, if it has ever been calibrated."""
    try:
        with open(CAL_PATH) as f:
            got = json.load(f)
        if all(k in got for k in DEFAULT) and got["x_max"] != got["x_min"] \
                and got["y_max"] != got["y_min"]:
            return got
    except Exception:
        pass
    return dict(DEFAULT)


def save_cal(cal):
    with open(CAL_PATH, "w") as f:
        json.dump(cal, f)


class Touch:
    def __init__(self, w=320, h=240):
        self.w, self.h = w, h
        self.cal = load_cal()
        self.cs = Pin(33, Pin.OUT, value=1)
        self.irq = Pin(36, Pin.IN)
        # Bit-banged on purpose. The panel is read at 1MHz, which needs no
        # hardware bus at all, and it leaves VSPI free for the SD card - which
        # wants that bus on its own pins and cannot share.
        self.spi = SoftSPI(baudrate=1000000, polarity=0, phase=0,
                           sck=Pin(25), mosi=Pin(32), miso=Pin(39))
        self.last = 0

    def _read(self, cmd):
        self.cs.value(0)
        self.spi.write(bytes((cmd,)))
        raw = self.spi.read(2)
        self.cs.value(1)
        return ((raw[0] << 8) | raw[1]) >> 3        # 12 bits, left aligned

    def raw(self):
        """(x, y) as the panel sees it, or None if nothing is touching it."""
        if self.irq.value():
            return None
        xs, ys = [], []
        for _ in range(5):
            xs.append(self._read(0xD0))
            ys.append(self._read(0x90))
        if self.irq.value():                        # let go mid-read
            return None
        xs.sort()
        ys.sort()
        x, y = xs[2], ys[2]                         # median of five
        if x < 100 or y < 100 or x > 4000 or y > 4000:
            return None
        return x, y

    def get(self, debounce_ms=180):
        """A screen position, once per press. None the rest of the time."""
        r = self.raw()
        if not r:
            return None
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last) < debounce_ms:
            return None
        self.last = now
        rx, ry = r
        # In this rotation the panel's axes are the screen's the other way
        # round: its y runs along the screen's x, and its x runs DOWN the
        # screen. Measured, after a flipped sign here put every press on the
        # buttons up in the header instead, where nothing was listening.
        return self.to_screen(rx, ry)

    def to_screen(self, rx, ry):
        """Panel reading to screen position, through this panel's numbers."""
        c = self.cal
        x = int((ry - c["y_min"]) * self.w / (c["y_max"] - c["y_min"]))
        y = int((rx - c["x_min"]) * self.h / (c["x_max"] - c["x_min"]))
        return max(0, min(self.w - 1, x)), max(0, min(self.h - 1, y))

    def press(self, seconds=20):
        """Wait for one press and return what the panel read, raw.

        Waits for a clean release afterwards, so a finger held for a moment is
        one press rather than several. Calibration is three presses long and
        counting them wrong quietly ruins the result.
        """
        end = time.ticks_add(time.ticks_ms(), int(seconds * 1000))
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            r = self.raw()
            if r:
                clear = 0
                while clear < 8 and time.ticks_diff(end, time.ticks_ms()) > 0:
                    clear = clear + 1 if self.raw() is None else 0
                    time.sleep_ms(25)
                self.last = time.ticks_ms()
                return r
            time.sleep_ms(20)
        return None

    def calibrate(self, at, readings):
        """Work out this panel's numbers from presses at known places.

        `at` is [(sx, sy), ...] where the targets were drawn and `readings`
        what the panel said. Two points decide a straight line each way; a
        third is used only to check the line, because a calibration that is
        quietly wrong is worse than one that refuses.
        """
        if len(at) < 2 or len(at) != len(readings):
            return None
        (x1, y1), (x2, y2) = at[0], at[1]
        (rx1, ry1), (rx2, ry2) = readings[0], readings[1]
        if x2 == x1 or y2 == y1:
            return None
        # the screen's x comes from the panel's y, and the other way about
        per_x = (ry2 - ry1) / float(x2 - x1)
        per_y = (rx2 - rx1) / float(y2 - y1)
        if not per_x or not per_y:
            return None
        cal = {"y_min": int(ry1 - x1 * per_x),
               "y_max": int(ry1 - x1 * per_x + per_x * self.w),
               "x_min": int(rx1 - y1 * per_y),
               "x_max": int(rx1 - y1 * per_y + per_y * self.h)}
        if cal["x_max"] == cal["x_min"] or cal["y_max"] == cal["y_min"]:
            return None
        return cal

    def check(self, cal, at, readings, slack=24):
        """How far off each press would be under `cal`, in screen pixels."""
        was, self.cal = self.cal, cal
        try:
            off = []
            for (sx, sy), (rx, ry) in zip(at, readings):
                gx, gy = self.to_screen(rx, ry)
                off.append(max(abs(gx - sx), abs(gy - sy)))
        finally:
            self.cal = was
        return off, all(o <= slack for o in off)

    def adopt(self, cal):
        self.cal = cal
        save_cal(cal)
