"""Where do presses actually land?

    python desk/touch_probe.py

The panel is read through a rough calibration and is known to land lower than
things are drawn. Every region on the idle screen is smaller than the third of
the screen that calibration was called good enough for, so the only honest way
to know a region is reachable is to press it and be told where it landed.

The board draws the three bands, labelled, in the same places the idle screen
puts them. Press each one in turn - top, middle, bottom. Nothing is acted on:
the desk is not running while this is, so pressing START starts nothing.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import carry_bits as c                                        # noqa: E402

SECONDS = 60
WANT = 3

# name, top, bottom - exactly what desk.press() uses
REGIONS = [
    ("the room / transcript", 84, 138),
    ("the hand-over strip", 138, 172),
    ("START", 172, 240),
]

PROBE = """
import tft, touch, time
d = tft.TFT()
t = touch.Touch()
ink = d.rgb(26, 17, 22)
gold = d.rgb(232, 217, 184)
paper = d.rgb(216, 207, 192)
d.clear(ink)
d.fill(0, 0, 320, 26, d.rgb(102, 57, 49))
d.text('WHERE DOES IT LAND?', 8, 9, gold, d.rgb(102, 57, 49))
d.text('press each band, top to bottom', 8, 40, paper, ink)
d.fill(0, 84, 320, 53, d.rgb(38, 52, 44))
d.text('1  the room', 8, 104, gold, d.rgb(38, 52, 44))
d.fill(0, 138, 320, 33, d.rgb(42, 30, 36))
d.text('2  hand over', 8, 148, gold, d.rgb(42, 30, 36))
d.fill(0, 172, 320, 68, d.rgb(60, 45, 52))
d.text('3  START', 8, 198, gold, d.rgb(60, 45, 52))
got = []
end = time.ticks_add(time.ticks_ms(), %d)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    hit = t.get()
    if hit:
        got.append(hit)
        # One reading per finger. The panel keeps reporting while it is held,
        # and the debounce is shorter than a deliberate press, so without
        # waiting for a clean release one press arrives as two and every
        # reading after it belongs to the press before.
        d.fill(300, 0, 20, 26, d.rgb(58, 168, 96))
        clear = 0
        while clear < 8 and time.ticks_diff(end, time.ticks_ms()) > 0:
            clear = clear + 1 if t.raw() is None else 0
            time.sleep_ms(25)
        d.fill(300, 0, 20, 26, d.rgb(102, 57, 49))
        if len(got) >= %d:
            break
    time.sleep_ms(20)
print(repr(got))
""" % (SECONDS * 1000, WANT)


def landed(y):
    for name, top, bottom in REGIONS:
        if top < y <= bottom:
            return name
    return "nothing at all"


def main():
    b = c.Board(c.guess_port())
    print("the board is showing three bands. Press them top to bottom.")
    print("(the desk is stopped - nothing you press will act on anything)")
    print()
    try:
        out = b.run(PROBE, timeout=SECONDS + 40).strip()
    finally:
        pass
    try:
        hits = eval(out.splitlines()[-1])                      # noqa: S307
    except Exception:
        hits = []
    wrong = 0
    for i, (name, top, bottom) in enumerate(REGIONS):
        if i >= len(hits):
            print("   %d  %-24s no press registered" % (i + 1, name))
            wrong += 1
            continue
        x, y = hits[i]
        where = landed(y)
        ok = where == name
        print("   %d  %-24s read x=%3d y=%3d -> %-22s %s"
              % (i + 1, name, x, y, where,
                 "OK" if ok else "MISSED (wanted %d-%d)" % (top, bottom)))
        if not ok:
            wrong += 1
    b._hard_reset()
    b.close()
    print()
    print("the board has restarted and is a desk unit again.")
    if wrong:
        print("%d of %d landed somewhere else - the bands need moving."
              % (wrong, len(REGIONS)))
    else:
        print("all %d landed where they were aimed." % len(REGIONS))
    return hits


if __name__ == "__main__":
    main()
