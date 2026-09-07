"""ILI9341 on the ESP32-2432S028 ("cheap yellow display").

No framebuffer for the whole screen - 320x240 at 16bpp is 150k and the board
has about 160k of RAM all in. Rectangles are streamed straight out, and text is
built in a small buffer the size of the line being drawn.
"""
from machine import Pin, SPI
import framebuf
import time

W, H = 320, 240

_INIT = (
    (0xEF, b"\x03\x80\x02"), (0xCF, b"\x00\xC1\x30"),
    (0xED, b"\x64\x03\x12\x81"), (0xE8, b"\x85\x00\x78"),
    (0xCB, b"\x39\x2C\x00\x34\x02"), (0xF7, b"\x20"), (0xEA, b"\x00\x00"),
    (0xC0, b"\x23"), (0xC1, b"\x10"), (0xC5, b"\x3E\x28"), (0xC7, b"\x86"),
    (0x36, b"\x28"), (0x3A, b"\x55"),
    (0xB1, b"\x00\x18"), (0xB6, b"\x08\x82\x27"), (0xF2, b"\x00"), (0x26, b"\x01"),
    (0xE0, b"\x0F\x31\x2B\x0C\x0E\x08\x4E\xF1\x37\x07\x10\x03\x0E\x09\x00"),
    (0xE1, b"\x00\x0E\x14\x03\x11\x07\x31\xC1\x48\x08\x0F\x0C\x31\x36\x0F"),
)


class TFT:
    def __init__(self, bgr=False):
        self.bl = Pin(21, Pin.OUT, value=1)
        self.cs = Pin(15, Pin.OUT, value=1)
        self.dc = Pin(2, Pin.OUT, value=0)
        self.spi = SPI(1, baudrate=40000000, polarity=0, phase=0,
                       sck=Pin(14), mosi=Pin(13), miso=Pin(12))
        self.bgr = bgr
        for c, d in _INIT:
            self.cmd(c, d)
        self.cmd(0x11)
        time.sleep_ms(120)
        self.cmd(0x29)
        time.sleep_ms(20)
        self._row = bytearray(W * 2)

    # -- wire ---------------------------------------------------------------
    def cmd(self, c, data=b""):
        self.cs.value(0)
        self.dc.value(0)
        self.spi.write(bytes((c,)))
        if data:
            self.dc.value(1)
            self.spi.write(data)
        self.cs.value(1)

    def window(self, x, y, w, h):
        x1, y1 = x + w - 1, y + h - 1
        self.cmd(0x2A, bytes((x >> 8, x & 255, x1 >> 8, x1 & 255)))
        self.cmd(0x2B, bytes((y >> 8, y & 255, y1 >> 8, y1 & 255)))
        self.cmd(0x2C)

    def backlight(self, on):
        self.bl.value(1 if on else 0)

    # -- colour -------------------------------------------------------------
    def rgb(self, r, g, b):
        """A 24-bit colour as this panel wants it on the wire."""
        if self.bgr:
            r, b = b, r
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    # -- drawing ------------------------------------------------------------
    def fill(self, x, y, w, h, colour):
        if w <= 0 or h <= 0:
            return
        self.window(x, y, w, h)
        row = bytes((colour >> 8, colour & 255)) * w
        self.cs.value(0)
        self.dc.value(1)
        for _ in range(h):
            self.spi.write(row)
        self.cs.value(1)

    def clear(self, colour=0):
        self.fill(0, 0, W, H, colour)

    def frame(self, x, y, w, h, colour, t=2):
        self.fill(x, y, w, t, colour)
        self.fill(x, y + h - t, w, t, colour)
        self.fill(x, y, t, h, colour)
        self.fill(x + w - t, y, t, h, colour)

    def blit(self, buf, x, y, w, h):
        self.window(x, y, w, h)
        self.cs.value(0)
        self.dc.value(1)
        self.spi.write(buf)
        self.cs.value(1)

    def text(self, s, x, y, fg, bg, scale=1):
        """8x8 built-in font, blown up. Returns the width drawn.

        framebuf keeps RGB565 the other way round from the wire, so the
        colours go in byte-swapped and come out right.
        """
        if not s:
            return 0
        cw, ch = 8 * len(s), 8
        mono = bytearray(cw * ch // 8)
        src = framebuf.FrameBuffer(mono, cw, ch, framebuf.MONO_HLSB)
        src.text(s, 0, 0, 1)
        ow, oh = cw * scale, ch * scale
        buf = bytearray(ow * oh * 2)
        dst = framebuf.FrameBuffer(buf, ow, oh, framebuf.RGB565)
        dst.fill(((bg & 255) << 8) | (bg >> 8))
        f = ((fg & 255) << 8) | (fg >> 8)
        for yy in range(ch):
            for xx in range(cw):
                if src.pixel(xx, yy):
                    if scale == 1:
                        dst.pixel(xx, yy, f)
                    else:
                        dst.fill_rect(xx * scale, yy * scale, scale, scale, f)
        self.blit(buf, x, y, ow, oh)
        return ow

    def centre(self, s, y, fg, bg, scale=1):
        return self.text(s, max(0, (W - 8 * len(s) * scale) // 2), y, fg, bg, scale)
