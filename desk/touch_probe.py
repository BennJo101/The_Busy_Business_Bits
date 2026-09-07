"""Where do presses actually land?

    python desk/touch_probe.py

The panel is read through a rough calibration and is known to land lower than
things are drawn. Every region on the screen is smaller than the third of it
that calibration was called good enough for, so the only honest way to know a
region is reachable is to press it and see what the board says.

Press each thing the board asks for. Nothing is acted on - the desk is not
running while this is - so pressing START here starts nothing.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import carry_bits as c                                        # noqa: E402

# what is drawn where, on the idle screen
REGIONS = [
    ("the room / transcript", 84, 138),
    ("the hand-over strip", 138, 172),
    ("START", 172, 240),
]

ASK = [
    ("the middle of the room area, about a third down", "the room / transcript"),
    ("the hand-over strip, just above START", "the hand-over strip"),
    ("the START bar", "START"),
]

WATCH = """
import touch, time
t = touch.Touch()
got = []
end = time.ticks_add(time.ticks_ms(), %d)
while time.ticks_diff(end, time.ticks_ms()) > 0:
    hit = t.get()
    if hit:
        got.append(hit)
        if len(got) >= %d:
            break
    time.sleep_ms(20)
print(repr(got))
"""


def landed(y):
    for name, top, bottom in REGIONS:
        if top < y <= bottom:
            return name
    return "nothing (y=%d)" % y


def main():
    b = c.Board(c.guess_port())
    print("the desk is stopped while this runs - nothing you press will act.")
    print()
    bad = 0
    try:
        for prompt, want in ASK:
            print("PRESS %s" % prompt)
            print("   (you have 15 seconds)")
            out = b.run(WATCH % (15000, 1), timeout=40).strip()
            hits = eval(out) if out.startswith("[") else []      # noqa: S307
            if not hits:
                print("   nothing registered\n")
                bad += 1
                continue
            x, y = hits[0]
            where = landed(y)
            ok = where == want
            print("   read as x=%d y=%d  ->  %s  %s"
                  % (x, y, where, "OK" if ok else "WRONG - wanted " + want))
            print()
            if not ok:
                bad += 1
    finally:
        b._hard_reset()
        b.close()
    print("the board has been restarted and is a desk unit again.")
    if bad:
        print("%d of %d landed somewhere else. Tell Claude these numbers and "
              "the regions can be moved to match your thumb." % (bad, len(ASK)))
    else:
        print("all %d landed where they were aimed." % len(ASK))


if __name__ == "__main__":
    main()
