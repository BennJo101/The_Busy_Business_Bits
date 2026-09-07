"""XPT2046 resistive touch, on its own SPI bus on the CYD.

Deliberately coarse. Nothing on this screen is smaller than a third of it, so
a rough calibration is all it needs and nobody has to tap crosshairs.
"""
from machine import Pin, SoftSPI
import time

# what the panel reads at the edges - the usual spread for this screen
X_MIN, X_MAX = 300, 3800
Y_MIN, Y_MAX = 300, 3800


class Touch:
    def __init__(self, w=320, h=240):
        self.w, self.h = w, h
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

    def get(self, debounce_ms=350):
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
        x = int((ry - Y_MIN) * self.w / (Y_MAX - Y_MIN))
        y = int((rx - X_MIN) * self.h / (X_MAX - X_MIN))
        return max(0, min(self.w - 1, x)), max(0, min(self.h - 1, y))
