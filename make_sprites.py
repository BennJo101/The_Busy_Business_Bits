#!/usr/bin/env python3
"""
Sprite builder for the Bits that have no hand-drawn art yet.
=============================================================
Everything is authored on the same 64x64 cell grid the existing cards use,
rendered at 16px per cell to 1024x1024, so the frame, palette, title font and
timings match the rest of the roster exactly.

    python make_sprites.py            # write Ghost + Librarian sprites
    python make_sprites.py --preview  # just the two still cards, for a look

Edit the CHARACTER grids near the bottom and re-run; nothing else needs to
change. Sprite discovery is by filename, so the app picks them up on restart.
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CELL = 16
GRID = 64
SIZE = GRID * CELL

# --- palette, sampled straight off the existing cards -----------------------
OUT = (63, 36, 54)          # outermost pixel ring
FRAME = (102, 57, 49)       # dark wooden frame
RAIL = (138, 111, 48)       # gold inner rail
SKY = (151, 169, 179)
GROUND = (142, 151, 74)
SHADOW = (94, 120, 49)      # the darker grass under a character
BLACK = (0, 0, 0)

PAL = {
    ".": None,              # transparent - leave the backdrop alone
    "O": BLACK,
    "W": (221, 231, 216),   # ghost linen
    "S": (170, 184, 176),   # its shading
    "K": (47, 47, 47),      # eye sockets
    "F": (238, 195, 154),   # skin
    "f": (216, 150, 122),   # skin shadow
    "H": (201, 154, 62),    # hair - dark blonde, between Coder and Secretary
    "h": (150, 112, 42),    # hair shadow
    "C": (78, 111, 120),    # cardigan
    "c": (58, 84, 92),      # cardigan ribbing
    "N": (42, 58, 107),     # spectacle rims, borrowed from the Coder
    "G": (201, 217, 224),   # lens
    "M": (218, 87, 99),     # mouth
    # the desk, measured cell-for-cell off the Secretary's
    "E": (72, 29, 25),      # desk edge
    "d": (102, 57, 49),     # desk frame
    "D": (138, 111, 48),    # desk front panel
    "L": (88, 86, 82),      # desk leg
    # books on the desk
    "R": (145, 46, 52),
    "r": (46, 90, 145),
    "q": (46, 122, 74),
    "P": (232, 226, 207),   # pages
}

# ---------------------------------------------------------------------------
# Title font, lifted cell-for-cell off the existing cards. The name is set in
# the large face; the word "The" above it is a smaller one.
# ---------------------------------------------------------------------------
def _g(*rows):
    return [[c == "#" for c in r] for r in rows]


SMALL = {
    "T": _g("######", "######", "..##..", "..##..", "..##..", "..##..", "..##.."),
    "h": _g("##...", "##...", "####.", "#####", "##.##", "##.##", "##.##", "#...."),
    "e": _g(".#####", "##..##", "######", "##....", "#####.", "######"),
}

LARGE = {
    # --- extracted ---------------------------------------------------------
    "B": _g("####.", "#####", "##.##", "##.##", "####.", "##.##",
            "##..#", "##..#", "#####", "####."),
    "R": _g("##...", "####.", "##.##", "##.##", "#####", "###..",
            "###..", "#.##.", "#..##", "....#"),
    "a": _g(".##..", "#..#.", "#..#.", "#..##", ".####", "....#"),
    "e": _g(".###", "#..#", "####", "#...", "####", "#..."),
    "o": _g(".####.", "######", "##..##", "##..##", "##..##", "######", ".####."),
    "p": _g("#.##.", "#####", "##..#", "##..#", "#####", "####.",
            "#.#..", "#....", "#....", "#...."),
    "r": _g("#.##", "##..", "##..", "##..", "##..", "#..."),
    "s": _g(".#####", "###.##", "##....", ".####.", "....##", "##.###", "#####."),
    # --- authored to match: these letters appear in no existing name -------
    "G": _g(".####", "#####", "##..#", "##...", "##...", "##.##",
            "##.##", "##..#", "#####", ".###."),
    "L": _g("##...", "##...", "##...", "##...", "##...", "##...",
            "##...", "##...", "#####", "#####"),
    "b": _g("##...", "##...", "##...", "##...", "####.", "#####",
            "##..#", "##..#", "#####", "####."),
    "h": _g("##...", "##...", "##...", "##...", "####.", "#####",
            "##.##", "##.##", "##.##", "##.##"),
    "i": _g("##", "##", "..", "##", "##", "##", "##", "##"),
    "n": _g("#.##.", "#####", "##..#", "##..#", "##..#", "##..#"),
    "t": _g(".##.", ".##.", "####", ".##.", ".##.", ".##.", ".##.", "..##"),
}

THE_ROW, THE_X = 4, 5       # "The" sits top-left, as on every other card
NAME_BASELINE = 24          # bottom row of the large capitals


def horizon_row(c):
    """The hand-wobbled skyline: a step up at either edge."""
    return 47 if (c < 9 or c > 54) else 48


# ---------------------------------------------------------------------------
def blank_card():
    """A card with frame, sky and ground, and nothing else on it."""
    g = [[SKY] * GRID for _ in range(GRID)]
    for r in range(GRID):
        for c in range(GRID):
            edge = min(r, c, GRID - 1 - r, GRID - 1 - c)
            if edge == 0:
                g[r][c] = OUT
            elif edge in (1, 2):
                g[r][c] = FRAME
            elif edge == 3:
                g[r][c] = RAIL
            elif r > horizon_row(c):
                g[r][c] = GROUND
            elif r == horizon_row(c):
                g[r][c] = BLACK
    return g


def draw_text(g, glyphs, text, x, baseline, rgb, gap=1):
    for ch in text:
        bm = glyphs[ch]
        h, w = len(bm), len(bm[0])
        top = baseline - h + 1
        for r in range(h):
            for c in range(w):
                if bm[r][c]:
                    g[top + r][x + c] = rgb
        x += w + gap
    return x


def text_width(glyphs, text, gap=1):
    return sum(len(glyphs[c][0]) for c in text) + gap * (len(text) - 1)


def stamp(g, art, x0, y0):
    """Paint a character grid over the card, honouring transparency."""
    for r, row in enumerate(art):
        for c, key in enumerate(row):
            rgb = PAL.get(key)
            if rgb is not None and 0 <= y0 + r < GRID and 0 <= x0 + c < GRID:
                g[y0 + r][x0 + c] = rgb


def ellipse_shadow(g, cx, row, half):
    for c in range(cx - half, cx + half + 1):
        if 4 <= c < 60 and g[row][c] == GROUND:
            g[row][c] = SHADOW


def render(g):
    im = Image.new("RGB", (SIZE, SIZE))
    px = im.load()
    for r in range(GRID):
        for c in range(GRID):
            rgb = g[r][c]
            for dy in range(CELL):
                for dx in range(CELL):
                    px[c * CELL + dx, r * CELL + dy] = rgb
    return im


def card(name_text, colour, art, x0, y0, shadow=None):
    g = blank_card()
    draw_text(g, SMALL, "The", THE_X, THE_ROW + 7, BLACK)
    w = text_width(LARGE, name_text)
    draw_text(g, LARGE, name_text, 32 - w // 2, NAME_BASELINE, colour)
    if shadow:
        ellipse_shadow(g, *shadow)
    stamp(g, art, x0, y0)
    return g


def save_gif(path, grids, duration):
    frames = [render(g) for g in grids]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=duration, loop=0, disposal=2, optimize=False)


# ===========================================================================
# THE GHOST - a floating sheet, so it bobs instead of walking.
# 18 cells wide: the body sits in the middle 16, leaving a column each side
# for the arms to reach into when it flourishes.
# ===========================================================================
GHOST_INK = (74, 85, 120)   # deeper than the roster grey, which vanishes on sky


def ghost_art(mouth=0, arms=0, tail=0):
    art = [
        "......OOOOOO......",
        "....OOWWWWWWOO....",
        "...OWWWWWWWWWWO...",
        "..OWWWWWWWWWWWWO..",
        ".OWWWWWWWWWWWWWWO.",
        ".OWWWWWWWWWWWWWWO.",
        ".OWWWWWWWWWWWWWWO.",
        ".OWKKKWWWWWWKKKWO.",
        ".OWKKKWWWWWWKKKWO.",
        ".OWKKKWWWWWWKKKWO.",
        ".OWWWWWWWWWWWWWWO.",
        ".OWWWWWWWWWWWWWWO.",
    ]
    if arms:
        # the linen bulges out a cell either side - little stubby arms
        art[10] = art[11] = "O" + "W" * 16 + "O"
    if mouth == 1:
        art.append(".OWWWWWKKKKWWWWWO.")
    elif mouth == 2:
        art.append(".OWWWWKKKKKKWWWWO.")
    else:
        art.append(".OWWWWWWSSWWWWWWO.")
    art += [
        ".OWWWWWKKKKWWWWWO." if mouth else ".OWWWWWWWWWWWWWWO.",
        ".OWWWWWWWWWWWWWWO.",
        ".OWSWWWWWWWWWWSWO.",
        ".OWSWWWWWWWWWWSWO.",
        ".OWWWWWWWWWWWWWWO.",
        ".OWWWWWWWWWWWWWWO.",
    ]
    tails = [
        [".OWWOOWWWWWWOOWWO.", ".OWO..OWWWWO..OWO.", "..O....OOOO....O.."],
        [".OWWWWOOWWOOWWWWO.", ".OWWWO..OO..OWWWO.", "..OOO........OOO.."],
        [".OWOOWWWWWWWWOOWO.", ".OO..OWWWWWWO..OO.", ".......OOOO......."],
    ]
    return art + tails[tail % len(tails)]


GHOST_X, GHOST_Y = 23, 24


def ghost_card(bob=0, mouth=0, arms=0, tail=0):
    return card("Ghost", GHOST_INK, ghost_art(mouth, arms, tail),
                GHOST_X, GHOST_Y + bob, shadow=(32, 53, 5 - bob))


# ===========================================================================
# THE LIBRARIAN - stands on the ground, book in hand
# ===========================================================================
LIB_INK = (200, 162, 74)    # the roster gold, which reads fine on sky

# The desk, traced cell-for-cell off the Secretary's so they match: 34 wide,
# top edge on row 44, legs down to the grass.
# Same footprint and height as the Secretary's so the roster still lines up,
# but paneled into three bays with a return slot in the middle one - a lending
# counter rather than an office desk.
DESK = [
    "OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO",
    "OEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEO",
    ".OOdddDDDDDDDDDDDDDDDDDDDDdddOO...",
    "..OddDDDDDDDddDDDDDDddDDDDDDDddO..",
    "..OddDDDDDDDddOOOOOOddDDDDDDDddO..",
    "..OddDDDDDDDddDDDDDDddDDDDDDDddO..",
    "..OdddDDDDDDddDDDDDDddDDDDDDdddO..",
    ".OOddddddddddddddddddddddddddddOO.",
    ".OEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEO.",
    "..OLOOOOOOOOOOOOOOOOOOOOOOOOOOLO..",
    "..OLO........................OLO..",
    "..OOO........................OOO..",
]
DESK_X, DESK_Y = 15, 44

BOOKS = [                       # a stack where the Secretary keeps her mug
    ".OOOOOO.",
    ".ORRRRO.",
    ".OOOOOO.",
    ".OrrrrO.",
    ".OOOOOO.",
    ".OqqqqO.",
]
BOOKS_X, BOOKS_Y = 40, 38

OPEN_BOOK = [                   # what she is reading, lying on the desk
    "..OOOOOO..",
    ".OPPPOPPPO",
    ".OOOOOOOOO",
]
OPEN_BOOK_X, OPEN_BOOK_Y = 27, 41

# Every pose here is sampled off the hand-drawn Bits rather than invented. The
# snap is not one pose held and bobbed - that reads as a fist pump. Checking the
# Boss's and the Secretary's frames end to end, it is three distinct beats:
#
#   1. the wind-up   hand rises, fingers CURLED into a small fist
#   2. the snap      hand flicks OPEN and DROPS, and two spark marks appear
#                    above it - the sparks are what make it read as a snap
#                    rather than a wave
#   3. the release   hand stays open and lowers back down
#
# It is deliberately asymmetric. Rising curled and falling open is the whole
# gesture; loop it symmetrically and the character just pumps their fist.
HAND_CURL = [
    "..OOO....",
    ".OFFO....",
    ".OFOFO...",     # the notch, then the thumb
    ".OFFO....",
]
HAND_OPEN = [
    ".OOOO....",
    ".OFFFO...",     # fingers flicked out flat
    "..OOFFO..",
]
SPARKS = [
    "..O..O...",
    "...O.O...",
]
CURL_TOP = {0: 5, 1: 3, 2: 0}       # wind-up heights
OPEN_TOP = {0: 6, 1: 4, 2: 3}       # the open hand always sits lower
ARM_W, ARM_H = 9, 10


def arm_art(pose="curl", lift=2, sparks=False):
    """One frame of the arm: hand pose, how high it is, and the snap sparks.

    The sleeve is drawn from wherever the hand ends down to the shoulder, so it
    can never come up short - that gap is what made the first version look like
    a floating hand.
    """
    g = [list("." * ARM_W) for _ in range(ARM_H)]
    hand = HAND_OPEN if pose == "open" else HAND_CURL
    top = (OPEN_TOP if pose == "open" else CURL_TOP)[lift]
    for i, row in enumerate(hand):
        for x, ch in enumerate(row):
            if ch != ".":
                g[top + i][x] = ch
    first = top + len(hand)
    n = ARM_H - first
    # start the sleeve directly under that pose's wrist, or it reads as two
    # separate pieces; the open hand's wrist sits two cells further right
    start = 3 if pose == "open" else 1
    for j in range(n):
        r = first + j
        x = start + round((j / max(1, n - 1)) * (3 - start))
        body = "c" if j == 0 and n > 1 else "C"     # ribbed cuff under the wrist
        g[r][x] = "O"
        if r >= ARM_H - 2:                          # merge into the torso: the
            for c in range(x + 1, ARM_W - 1):       # overlap is what reads as
                g[r][c] = "C"                       # attached
        else:
            g[r][x + 1] = g[r][x + 2] = body
            g[r][x + 3] = "O"
    if sparks:
        for i, row in enumerate(SPARKS):
            for x, ch in enumerate(row):
                if ch != "." and top - 3 + i >= 0:
                    g[top - 3 + i][x] = ch
    return ["".join(r) for r in g]


# The choreography, beat for beat off the Secretary's twelve frames.
SNAP_SCRIPT = [
    ("curl", 0, False),     # rising
    ("curl", 1, False),
    ("curl", 2, False),     # wind-up, held
    ("curl", 2, False),
    ("open", 2, True),      # THE SNAP - flicks open, sparks
    ("open", 1, False),     # release
    ("open", 1, False),
    ("open", 0, False),     # lowering
    ("open", 0, False),
    ("curl", 0, False),     # back to rest
]

ARM_X, ARM_Y = 20, 33


def librarian_art(mouth=0, blink=0):
    """Head and shoulders - the desk hides her from the waist down."""
    # two separate lenses joined by a bridge - a full-width bar of rim just
    # reads as a visor at this size
    eyes = "NGKNNKGN" if not blink else "NOONNOON"
    art = [
        "....OOOOOO....",
        "..OOHHHHHHOO..",
        ".OHHHHHHHHHHO.",
        ".OHHhhHHhhHHO.",
        ".OHFFFFFFFFHO.",
        ".OHFFFFFFFFHO.",
        ".OHNNNFFNNNHO.",     # tops of the two lenses, skin between them
        ".OH" + eyes + "HO.",
    ]
    art.append(".OHFFFFFFFFHO.")
    if mouth == 1:
        art.append(".OHFFFMMFFFHO.")
    elif mouth == 2:
        art.append(".OHFFMMMMFFHO.")
    else:
        art.append(".OHFFFfFFFFHO.")
    art += [
        "..OHFFFFFFHO..",
        "...OOFFFFOO...",
        # shoulders and a cream collar over the cardigan
        "..OCCWWWWCCO..",
        ".OCCCWWWWCCCO.",
        ".OCcCCWWCCcCO.",
        "OCcCCCCCCCCcCO",
        "OCcCCCCCCCCcCO",
    ]
    return art


LIB_X, LIB_Y = 25, 28


def librarian_card(mouth=0, arm=None, book=0, blink=0, breath=0):
    """arm: None, or (pose, lift, sparks) - see arm_art."""
    g = blank_card()
    draw_text(g, SMALL, "The", THE_X, THE_ROW + 7, BLACK)
    w = text_width(LARGE, "Librarian")
    draw_text(g, LARGE, "Librarian", 32 - w // 2, NAME_BASELINE, LIB_INK)
    # she settles a row as she breathes; the desk swallows the extra row
    stamp(g, librarian_art(mouth, blink), LIB_X, LIB_Y + breath)
    if arm:
        stamp(g, arm_art(*arm), ARM_X, ARM_Y + breath)
    stamp(g, BOOKS, BOOKS_X, BOOKS_Y)
    if book:
        stamp(g, OPEN_BOOK, OPEN_BOOK_X, OPEN_BOOK_Y - (book - 1))
    stamp(g, DESK, DESK_X, DESK_Y)
    ellipse_shadow(g, 32, 56, 16)
    return g


# ===========================================================================
BITS_OUT = {
    "The Ghost": ("The Ghost Files", "Ghost"),
    "The Librarian": ("The Librarian Files", "Librarian"),
}


def states_for(which):
    """(filename suffix, [frames], duration) per animation state."""
    if which == "Ghost":
        bob = [0, 0, 1, 2, 2, 2, 1, 0]
        return [
            ("idle_loop", [ghost_card(bob[i], 0, 0, i % 3) for i in range(8)], 330),
            ("talk_loop", [ghost_card(bob[i % 8], 1 + i % 2, 0, i % 3)
                           for i in range(6)], 330),
            ("snap_loop", [ghost_card(bob[i % 8], 0, 1, i % 3)
                           for i in range(12)], 160),
            ("snap_talk_loop", [ghost_card(bob[i % 8], 1 + i % 2, 1, i % 3)
                                for i in range(12)], 160),
            ("haunt_loop", [ghost_card(bob[i], 0, i % 2, i % 3)
                            for i in range(8)], 330),
        ]
    blink = [0, 0, 0, 0, 0, 1, 0, 0]
    br = [0, 0, 1, 1, 1, 1, 0, 0]       # every frame must differ from the last,
    br2 = [0, 1] * 6                    # or Pillow folds them into one long one
    return [
        ("idle_loop", [librarian_card(0, 0, 0, blink[i], br[i])
                       for i in range(8)], 330),
        ("talk_loop", [librarian_card(1 + i % 2, 0, 0, 0, br[i])
                       for i in range(6)], 330),
        # the arm carries the motion now, so the body can breathe calmly under it
        ("snap_loop", [librarian_card(0, SNAP_SCRIPT[i], 0, blink[i % 8], br[i % 8])
                       for i in range(len(SNAP_SCRIPT))], 160),
        ("snap_talk_loop", [librarian_card(1 + i % 2, SNAP_SCRIPT[i], 0, 0, br[i % 8])
                            for i in range(len(SNAP_SCRIPT))], 160),
        # shelving: she reaches for the book rather than snapping
        ("shelve_loop", [librarian_card(0, ("open", i % 2, False), 1, blink[i], br[i])
                         for i in range(8)], 330),
    ]


def main():
    preview = "--preview" in sys.argv
    for full, (folder, short) in BITS_OUT.items():
        d = os.path.join(HERE, "The Bits", folder, "GIFs and PNG")
        os.makedirs(d, exist_ok=True)
        still = ghost_card() if short == "Ghost" else librarian_card()
        p = os.path.join(d, "%s.png" % full)
        render(still).save(p)
        print("  %s" % os.path.relpath(p, HERE))
        if preview:
            continue
        for suffix, grids, dur in states_for(short):
            p = os.path.join(d, "%s_%s.gif" % (short, suffix))
            save_gif(p, grids, dur)
            print("  %s  (%d frames, %dms)"
                  % (os.path.relpath(p, HERE), len(grids), dur))


if __name__ == "__main__":
    main()
