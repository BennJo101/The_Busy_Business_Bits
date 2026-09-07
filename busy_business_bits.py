#!/usr/bin/env python3
"""
The Busy Business Bits
======================
Pixel-art assistants that live in borderless, always-on-top windows on your
desktop. Summon them from the Wizard's console, talk to them in the text box
under their frame, and let them talk to each other.

Requires: Python 3.8+, Pillow.       Run:  python busy_business_bits.py
"""

import math
import os
import queue
import random
import re
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:                    # needs HERE on the path first
    import bits_ambient  # noqa: E402
except Exception:        # noqa: BLE001
    bits_ambient = None

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
LOG = os.path.join(HERE, "bits_install_log.txt")


def _run(args, log):
    """Run a subprocess quietly, appending everything it says to `log`."""
    log.write("\n$ " + " ".join(args) + "\n")
    log.flush()
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=NO_WINDOW, timeout=600)
        log.write(p.stdout.decode("utf-8", "replace"))
        log.flush()
        return p.returncode
    except Exception as e:  # noqa: BLE001
        log.write("!! %r\n" % (e,))
        log.flush()
        return 1


def ensure_deps():
    """Install Pillow if it's missing, showing progress, then re-exec cleanly."""
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("BITS_BOOTSTRAPPED"):
        _fatal("Pillow still isn't importable after installing it.\n\n"
               "See:\n%s" % LOG)

    win = tk.Tk()
    win.title("The Busy Business Bits")
    win.configure(bg="#663931")
    win.geometry("420x150")
    win.resizable(False, False)
    tk.Label(win, text="THE BUSY BUSINESS BITS", bg="#663931", fg="#e8d9b8",
             font=("Consolas", 12, "bold")).pack(pady=(24, 6))
    msg = tk.Label(win, text="Installing Pillow (one-time)...", bg="#663931",
                   fg="#d8cfc0", font=("Consolas", 9))
    msg.pack()
    sub = tk.Label(win, text=os.path.basename(sys.executable), bg="#663931",
                   fg="#a2907f", font=("Consolas", 8))
    sub.pack(pady=(4, 0))
    win.update()

    with open(LOG, "w", encoding="utf-8") as log:
        log.write("python: %s\n" % sys.executable)
        log.write("version: %s\n" % sys.version.replace("\n", " "))
        _run([sys.executable, "-m", "ensurepip", "--upgrade"], log)
        ok = False
        for extra in ([], ["--user"], ["--break-system-packages"]):
            msg.configure(text="Installing Pillow%s..." %
                          ((" " + " ".join(extra)) if extra else ""))
            win.update()
            rc = _run([sys.executable, "-m", "pip", "install",
                       "--disable-pip-version-check", "--no-input",
                       "Pillow"] + extra, log)
            if rc == 0:
                ok = True
                break

    win.destroy()
    if not ok:
        _fatal("Couldn't install Pillow automatically.\n\n"
               "Open a Command Prompt and run:\n\n"
               "    \"%s\" -m pip install Pillow\n\n"
               "Details were written to:\n%s" % (sys.executable, LOG))

    # a fresh interpreter is the only reliable way to pick up a just-installed
    # package (--user site dirs aren't on sys.path in this process)
    os.environ["BITS_BOOTSTRAPPED"] = "1"
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])


def _fatal(text):
    try:
        import tkinter.messagebox as mb
        r = tk.Tk()
        r.withdraw()
        mb.showerror("The Busy Business Bits", text)
    except Exception:
        print(text)
    sys.exit(1)


ensure_deps()

from PIL import Image, ImageSequence, ImageTk  # noqa: E402

from bits_core import (  # noqa: E402
    BITS, PARTY_BEAT, SHORT, FRAME_DARK, FRAME_GOLD, SKY, GROUND, INK, PAPER,
    ApiError, Konami, Speaker, ask_bit, available_bits, discover_sprites,
    find_addressees, list_models, load_settings, pick_default_model,
    route, save_settings, synth_song, synth_voice,
)
# already imported (or already failed to import) inside bits_core, so take its
# copy rather than risk a second, differently-configured module object
from bits_core import bits_tools  # noqa: E402

CARD = 260          # rendered sprite size, px
CHAT_H = 7          # transcript rows
MAX_CHAIN = 3       # how far a Bit-to-Bit conversation may cascade
HOST = "The Wizard"  # runs the console; never gets a window of his own
BOSS = "The Boss"    # holds the gate, so he gets fetched when one is hit


# ---------------------------------------------------------------------------
def make_dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


class Animator:
    """Plays a GIF into a Label, honouring per-frame durations. NEAREST scaling."""

    _cache = {}

    def __init__(self, widget, size):
        self.widget = widget
        self.size = size
        self.frames = []
        self.durations = []
        self.i = 0
        self.job = None
        self.path = None

    @classmethod
    def _load(cls, path, size):
        key = (path, size)
        if key in cls._cache:
            return cls._cache[key]
        frames, durations = [], []
        with Image.open(path) as im:
            for fr in ImageSequence.Iterator(im):
                f = fr.convert("RGBA").resize((size, size), Image.NEAREST)
                frames.append(ImageTk.PhotoImage(f))
                durations.append(max(40, int(fr.info.get("duration", 100) or 100)))
        cls._cache[key] = (frames, durations)
        return frames, durations

    _peaks = {}

    def total_ms(self, path):
        """How long this state runs end to end. The Wizard's cast is 49 frames;
        anything that wants to wait for it has to ask rather than guess."""
        try:
            _, durations = self._load(path, self.size)
            return sum(durations)
        except Exception:
            return 0

    @classmethod
    def peak_ms(cls, path):
        """When this state's effect is at its brightest, in ms from the start.

        Found by looking for colours the sprite never wears at rest - the
        Wizard's sparkles are a yellow that appears nowhere in his idle frame -
        and taking the frame where there is most of it. Measured rather than
        written down, so redrawing the cast moves the cue with it.

        Returns 0 when a state has no such effect, e.g. a plain idle loop.
        """
        if path in cls._peaks:
            return cls._peaks[path]
        out = 0
        try:
            frames = []
            with Image.open(path) as im:
                for fr in ImageSequence.Iterator(im):
                    ms = max(40, int(fr.info.get("duration", 100) or 100))
                    frames.append((ms, fr.convert("RGB").getcolors(1 << 20) or []))
            if frames:
                at_rest = {c for _, c in frames[0][1]}
                tally = {}
                for i, (_, cols) in enumerate(frames):
                    for n, c in cols:
                        if c not in at_rest:
                            tally.setdefault(c, {})[i] = n
                if tally:
                    # the colour with the most pixels across the run is the
                    # effect itself, not a stray dither pixel
                    col = max(tally, key=lambda c: sum(tally[c].values()))
                    hit = max(tally[col], key=lambda i: tally[col][i])
                    # up to, not through - the cue wants to land as the
                    # brightest frame is drawn, not as it leaves
                    out = sum(ms for ms, _ in frames[:hit])
        except Exception:
            out = 0
        cls._peaks[path] = out
        return out

    def play(self, path, restart=False):
        # restart=True replays a state that's already on screen - the Wizard's
        # snap has to fire again even if he's mid-snap from the last summon
        if not path or (path == self.path and not restart):
            return
        self.path = path
        try:
            self.frames, self.durations = self._load(path, self.size)
        except Exception:
            return
        # cancel the running frame loop first - otherwise every state change
        # leaves another _tick chain scheduled and the sprite speeds up by one
        # multiple per switch until it's an unreadable blur
        self.stop()
        self.i = 0
        self._tick()

    def _tick(self):
        if not self.frames:
            return
        self.widget.configure(image=self.frames[self.i])
        d = self.durations[self.i]
        self.i = (self.i + 1) % len(self.frames)
        self.job = self.widget.after(d, self._tick)

    def stop(self):
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except Exception:
                pass
            self.job = None


# ---------------------------------------------------------------------------
class BitWindow(tk.Toplevel):
    """One Bit: borderless card + a text box underneath its frame."""

    def __init__(self, app, name, x, y):
        super().__init__(app.root)
        self.app = app
        self.name = name
        self.short = SHORT[name]
        self.states = app.sprites.get(name, {})
        self.speaking = False

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=FRAME_DARK)
        self.geometry("+%d+%d" % (x, y))

        wrap = tk.Frame(self, bg=FRAME_DARK, bd=0)
        wrap.pack(fill="both", expand=True)

        # --- the card itself (this is the "frame") -------------------------
        stage = tk.Frame(wrap, bg=FRAME_DARK, width=CARD, height=CARD)
        stage.pack()
        stage.pack_propagate(False)
        self.sprite = tk.Label(stage, bg=SKY, bd=0)
        self.sprite.pack()
        self.anim = Animator(self.sprite, CARD)
        # only the Wizard snaps when summoning - the Bit simply arrives, idling
        self.anim.play(self.states.get("idle"))

        for w in (self.sprite, stage, wrap):
            w.bind("<ButtonPress-1>", self._grab)
            w.bind("<B1-Motion>", self._drag)
        self.sprite.bind("<Button-3>", lambda e: self.app.dismiss(self.name))

        # --- close pip, sitting on the card's own border -------------------
        self.pip = tk.Label(stage, text="x", bg=FRAME_DARK, fg="#e8d9b8",
                            font=("Consolas", 9, "bold"), padx=4, cursor="hand2")
        self.pip.place(x=CARD - 18, y=3)
        self.pip.bind("<Button-1>", lambda e: self.app.dismiss(self.name))

        # --- the text box below the frame ----------------------------------
        panel = tk.Frame(wrap, bg=FRAME_GOLD, bd=0)
        panel.pack(fill="x", padx=6, pady=(0, 6))
        inner = tk.Frame(panel, bg=INK, bd=0)
        inner.pack(fill="both", expand=True, padx=3, pady=3)

        self.log = tk.Text(inner, height=CHAT_H, width=1, bg=INK, fg=PAPER,
                           insertbackground=PAPER, bd=0, wrap="word",
                           font=("Consolas", 9), padx=7, pady=6,
                           highlightthickness=0, state="disabled", cursor="arrow")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("me", foreground=BITS[name]["color"],
                               font=("Consolas", 9, "bold"))
        self.log.tag_configure("you", foreground="#8fd6c0",
                               font=("Consolas", 9, "bold"))
        self.log.tag_configure("other", foreground="#b9a98f",
                               font=("Consolas", 9, "bold"))
        self.log.tag_configure("body", foreground=PAPER)
        self.log.tag_configure("sys", foreground="#7a6f63",
                               font=("Consolas", 8, "italic"))

        row = tk.Frame(inner, bg=INK)
        row.pack(fill="x", padx=6, pady=(0, 6))
        self.entry = tk.Entry(row, bg="#241a20", fg=PAPER, insertbackground=PAPER,
                              bd=0, font=("Consolas", 9), highlightthickness=1,
                              highlightbackground="#3d2f34", highlightcolor=FRAME_GOLD)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 4))
        self.entry.bind("<Return>", self._send)
        self.entry.bind("<Button-1>", lambda e: self._focus())
        tk.Button(row, text="▶", bg=FRAME_GOLD, fg=INK, bd=0,
                  activebackground="#a8883a", font=("Consolas", 9, "bold"),
                  cursor="hand2", command=self._send).pack(side="left", ipadx=6)

        self.say_sys("summoned.")

    # -- dragging -----------------------------------------------------------
    def _grab(self, e):
        self._ox, self._oy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()
        self.lift()

    def _drag(self, e):
        self.geometry("+%d+%d" % (e.x_root - self._ox, e.y_root - self._oy))

    def _focus(self):
        try:
            self.focus_force()
            self.entry.focus_set()
        except Exception:
            pass

    # -- animation ----------------------------------------------------------
    def set_state(self, state):
        self.anim.play(self.states.get(state) or self.states.get("idle"))

    # -- transcript ---------------------------------------------------------
    def _append(self, who, tag, text, newline=True):
        self.log.configure(state="normal")
        if who:
            self.log.insert("end", who + "  ", tag)
        self.log.insert("end", text + ("\n" if newline else ""), "body")
        self.log.see("end")
        self.log.configure(state="disabled")

    def say_sys(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", "sys")
        self.log.see("end")
        self.log.configure(state="disabled")

    def heard(self, speaker, text):
        tag = "you" if speaker == "You" else "other"
        label = "You" if speaker == "You" else SHORT.get(speaker, speaker)
        self._append(label + ":", tag, text)

    def begin_line(self):
        self.log.configure(state="normal")
        self.log.insert("end", self.short + ":  ", "me")
        self.log.configure(state="disabled")

    def stream_char(self, c):
        self.log.configure(state="normal")
        self.log.insert("end", c, "body")
        self.log.see("end")
        self.log.configure(state="disabled")

    def end_line(self):
        self.log.configure(state="normal")
        self.log.insert("end", "\n", "body")
        self.log.see("end")
        self.log.configure(state="disabled")

    # -- input --------------------------------------------------------------
    def _send(self, _evt=None):
        if _evt is not None and self.app.party.pressed_return():
            return "break"          # that Enter finished the Konami code
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.app.user_says(text, to=self.name)

    def destroy(self):
        self.anim.stop()
        super().destroy()


# ---------------------------------------------------------------------------
class Console(tk.Frame):
    """The Wizard's console: selector / installer for the Bits."""

    def __init__(self, app, master):
        super().__init__(master, bg=FRAME_DARK)
        self.app = app
        self.pack(fill="both", expand=True)

        head = tk.Frame(self, bg=FRAME_DARK)
        head.pack(fill="x", padx=10, pady=(10, 4))
        title = tk.Label(head, text="THE BUSY BUSINESS BITS", bg=FRAME_DARK,
                         fg="#e8d9b8", font=("Consolas", 11, "bold"))
        title.pack(side="left")
        self.title = title      # the party flashes it on the beat

        # minimal chrome - the same pips the Bits' cards use, rightmost first
        self.pips = {}
        for txt, cmd in (("x", app.quit), ("□", app.toggle_max),
                         ("—", app.minimize)):
            pip = tk.Label(head, text=txt, bg=FRAME_DARK, fg="#e8d9b8",
                           font=("Consolas", 9, "bold"), padx=5, cursor="hand2")
            pip.pack(side="right")
            pip.bind("<Button-1>", lambda e, c=cmd: c())
            pip.bind("<Enter>", lambda e, p=pip: p.configure(fg=FRAME_GOLD))
            pip.bind("<Leave>", lambda e, p=pip: p.configure(fg="#e8d9b8"))
            self.pips[txt] = pip

        tk.Button(head, text="settings", bg=FRAME_GOLD, fg=INK, bd=0, cursor="hand2",
                  activebackground="#a8883a", font=("Consolas", 8, "bold"),
                  command=app.open_settings).pack(side="right", ipadx=6, padx=(0, 10))

        # drag the console by its bar, exactly like dragging a Bit by its card
        for wdg in (head, title):
            wdg.bind("<ButtonPress-1>", app._grab_root)
            wdg.bind("<B1-Motion>", app._drag_root)

        body = tk.Frame(self, bg=FRAME_DARK)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # roster ------------------------------------------------------------
        left = tk.Frame(body, bg=FRAME_GOLD)
        left.pack(side="left", fill="y")
        roster = tk.Frame(left, bg=INK)
        roster.pack(fill="both", expand=True, padx=3, pady=3)
        tk.Label(roster, text=" summon / dismiss ", bg=INK, fg="#7a6f63",
                 font=("Consolas", 8, "italic")).pack(anchor="w", padx=8, pady=(6, 2))

        self.buttons = {}
        for name in BITS:
            if name == HOST:
                continue        # the Wizard is the console - nothing to summon
            has_art = bool(app.sprites.get(name, {}).get("idle"))
            b = tk.Button(
                roster, text=("  " + SHORT[name]).ljust(16), anchor="w",
                bg=INK, fg=BITS[name]["color"] if has_art else "#4f4740",
                activebackground="#2b1f26", activeforeground=BITS[name]["color"],
                bd=0, font=("Consolas", 10, "bold"),
                cursor="hand2" if has_art else "arrow",
                state="normal" if has_art else "disabled",
                command=(lambda n=name: app.toggle(n)) if has_art else None,
            )
            b.pack(fill="x", padx=6, pady=1)
            if not has_art:
                tk.Label(roster, text="      sprites pending", bg=INK, fg="#3f3830",
                         font=("Consolas", 7, "italic")).pack(anchor="w", padx=6)
            self.buttons[name] = b

        tk.Frame(roster, bg="#2b1f26", height=1).pack(fill="x", padx=8, pady=6)
        tk.Button(roster, text="  dismiss all", anchor="w", bg=INK, fg="#8a7d70",
                  activebackground="#2b1f26", bd=0, font=("Consolas", 9),
                  cursor="hand2", command=app.dismiss_all).pack(fill="x", padx=6, pady=(0, 8))

        # wizard + room -------------------------------------------------------
        right = tk.Frame(body, bg=FRAME_DARK)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        wiz_states = app.sprites.get("The Wizard", {})
        stage = tk.Frame(right, bg=FRAME_DARK, width=180, height=180)
        stage.pack()
        stage.pack_propagate(False)
        self.wiz = tk.Label(stage, bg=SKY, bd=0)
        self.wiz.pack()
        self.wiz_anim = Animator(self.wiz, 180)
        self.wiz_anim.play(wiz_states.get("idle"))
        self._flourish_job = None

        rm = tk.Frame(right, bg=FRAME_GOLD)
        rm.pack(fill="both", expand=True, pady=(8, 0))
        inner = tk.Frame(rm, bg=INK)
        inner.pack(fill="both", expand=True, padx=3, pady=3)

        self.room = tk.Text(inner, height=8, width=34, bg=INK, fg=PAPER, bd=0,
                            wrap="word", font=("Consolas", 9), padx=7, pady=6,
                            highlightthickness=0, state="disabled", cursor="arrow")
        self.room.pack(fill="both", expand=True)
        self.room.tag_configure("you", foreground="#8fd6c0", font=("Consolas", 9, "bold"))
        self.room.tag_configure("sys", foreground="#7a6f63", font=("Consolas", 8, "italic"))
        self.room.tag_configure("body", foreground=PAPER)
        for name in BITS:
            self.room.tag_configure(name, foreground=BITS[name]["color"],
                                    font=("Consolas", 9, "bold"))

        row = tk.Frame(inner, bg=INK)
        row.pack(fill="x", padx=6, pady=(0, 6))
        self.entry = tk.Entry(row, bg="#241a20", fg=PAPER, insertbackground=PAPER,
                              bd=0, font=("Consolas", 9), highlightthickness=1,
                              highlightbackground="#3d2f34", highlightcolor=FRAME_GOLD)
        self.entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 4))
        self.entry.bind("<Return>", self._send)
        tk.Button(row, text="▶", bg=FRAME_GOLD, fg=INK, bd=0, cursor="hand2",
                  activebackground="#a8883a", font=("Consolas", 9, "bold"),
                  command=self._send).pack(side="left", ipadx=6)
        self.mic = tk.Button(row, text="mic", bg="#3d2f34", fg="#c9bcae", bd=0,
                             cursor="hand2", activebackground="#5a4149",
                             font=("Consolas", 8, "bold"), command=app.listen)
        self.mic.pack(side="left", ipadx=4, padx=(4, 0))

        self.status = tk.Label(right, text="", bg=FRAME_DARK, fg="#8a7d70",
                               font=("Consolas", 8), anchor="w")
        self.status.pack(fill="x", pady=(4, 0))

    def _send(self, _evt=None):
        if _evt is not None and self.app.party.pressed_return():
            return "break"          # that Enter finished the Konami code
        t = self.entry.get().strip()
        if not t:
            return
        self.entry.delete(0, "end")
        self.app.user_says(t, to=None)

    def room_line(self, speaker, text):
        self.room.configure(state="normal")
        if speaker == "You":
            self.room.insert("end", "You:  ", "you")
        else:
            # the tag must go in as a 1-tuple: Tcl parses a bare "The Boss"
            # as the two tags "The" and "Boss", and the colour is lost
            self.room.insert("end", SHORT.get(speaker, speaker) + ":  ", (speaker,))
        self.room.insert("end", text + "\n", "body")
        self.room.see("end")
        self.room.configure(state="disabled")

    def room_sys(self, text):
        self.room.configure(state="normal")
        self.room.insert("end", text + "\n", "sys")
        self.room.see("end")
        self.room.configure(state="disabled")

    def set_active(self, name, on):
        b = self.buttons.get(name)
        if b:
            b.configure(bg="#2b1f26" if on else INK,
                        text=(("> " if on else "  ") + SHORT[name]).ljust(16))

    def wizard_flourish(self, states):
        """The spell-cast snap, sparkles and all, then back to idle.

        Returns how long the cast runs, so the caller can hold anything that is
        meant to happen at the end of it. This used to settle back to idle after
        a flat 1100ms while the cast itself is 4900 - the sparkles never got on
        screen at all.
        """
        snap = states.get("snap")
        if not snap:
            return 0
        idle = states.get("idle")
        if self._flourish_job:
            try:
                self.after_cancel(self._flourish_job)
            except Exception:
                pass
        self.wiz_anim.play(snap, restart=True)
        full = self.wiz_anim.total_ms(snap) or 1100
        self._flourish_job = self.after(full, lambda: self._end_flourish(idle))
        # the cast plays out in full, but the cue a caller waits on is the
        # sparkle peak - the moment the spell actually lands
        return self.wiz_anim.peak_ms(snap) or full

    def _end_flourish(self, idle):
        self._flourish_job = None
        self.wiz_anim.play(idle)


# ---------------------------------------------------------------------------
class Party:
    """Up Up Down Down Left Right Left Right B A Enter - and the room dances.

    The code is caught on the "all" bindtag, which fires after the widget that
    has focus has already had the keystroke. That is fine for the arrows, which
    only move a cursor, but the B and the A land as text in whichever box you
    were typing in, so they get taken back out; and the Enter would send the
    line, so the two `_send`s ask here first and stand down if the code just
    landed.
    """

    STEP_MS = int(PARTY_BEAT * 1000)     # one move per eighth note
    HOP = 16                             # how far off the ground a Bit gets
    SWAY = 11
    MOVES = ("snap_talk", "talk", "snap", "work")

    def __init__(self, app):
        self.app = app
        self.code = Konami()
        self.dancing = False
        self._home = {}                  # name -> where it stood before
        self._root_home = None

    def warm(self):
        """Render the tune up front. It costs about half a second, and lazily
        that half second is spent on the main thread with nine windows already
        bouncing."""
        threading.Thread(target=self._warm, daemon=True).start()

    @staticmethod
    def _warm():
        try:
            synth_song()
        except Exception:                                         # noqa: BLE001
            pass

    # -- the code -----------------------------------------------------------
    def key(self, e):
        """Every keystroke in the app, from `bind_all`."""
        try:
            verdict = self.code.feed(e.keysym)
        except Exception:                                         # noqa: BLE001
            return
        if verdict == "letter":
            self._unfeed(e)
        elif verdict == "go":
            self.start()

    def pressed_return(self):
        """Enter, from a text box that binds it before we ever see it.

        True means the code just completed, so the line must not be sent.
        """
        if self.code.feed("Return") != "go":
            return False
        self.start()
        return True

    def _unfeed(self, e):
        """Take the letter back out of the text box it landed in."""
        w = getattr(e, "widget", None)
        try:
            if isinstance(w, tk.Entry):
                i = w.index("insert")
                if i > 0 and w.get()[i - 1].lower() == e.keysym.lower():
                    w.delete(i - 1)
        except Exception:                                         # noqa: BLE001
            pass

    # -- the dance ----------------------------------------------------------
    def start(self):
        if self.dancing:
            return
        app = self.app
        dur = 12.0
        try:
            wav, dur = synth_song()
            if app.settings.get("voices", True):
                app.speaker.play(wav)
        except Exception:                                         # noqa: BLE001
            pass
        self.dancing = True
        self._home = {}
        self._root_home = None
        if not app._minimized and not app._restore_geom:
            try:
                app.root.update_idletasks()
                self._root_home = (app.root.winfo_x(), app.root.winfo_y())
            except Exception:                                     # noqa: BLE001
                pass
        who = len(app.windows)
        app.console.room_sys(
            "* * *  %s  * * *"
            % ("everybody dance" if who else "the Wizard dances alone"))
        self._step(0, max(1, int(dur * 1000 / self.STEP_MS)))

    def _step(self, i, steps):
        app = self.app
        if not self.dancing or i >= steps:
            self._settle()
            return
        try:
            for n, name in enumerate(list(app.windows)):
                w = app.windows.get(name)
                if not w or not w.winfo_exists():
                    continue
                # a Bit that arrives mid-song joins from wherever it landed
                x, y = self._home.setdefault(name, (w.winfo_x(), w.winfo_y()))
                # each card a step behind the last, so the room ripples rather
                # than jumping as one
                ph = i + n
                w.geometry("+%d+%d" % (
                    x + int(self.SWAY * math.sin(ph * math.pi / 4.0)),
                    y - (self.HOP if ph % 2 == 0 else 0)))
                if i % 4 == 0:
                    w.set_state(self.MOVES[(i // 4 + n) % len(self.MOVES)])
            if self._root_home:
                rx, ry = self._root_home
                app.root.geometry("+%d+%d" % (rx, ry - (0 if i % 2 else 6)))
            app.console.title.configure(fg=FRAME_GOLD if i % 2 else "#e8d9b8")
            if i % 24 == 0:         # his cast runs 4.9s; keep him casting
                app.console.wizard_flourish(app.sprites.get(HOST, {}))
        except tk.TclError:
            self.dancing = False
            return
        app.root.after(self.STEP_MS, lambda: self._step(i + 1, steps))

    def stop(self):
        self.dancing = False
        try:
            self.app.speaker.stop()
        except Exception:                                         # noqa: BLE001
            pass

    def _settle(self):
        was = self.dancing
        self.dancing = False
        for name, home in self._home.items():
            w = self.app.windows.get(name)
            if not w:
                continue
            try:
                w.geometry("+%d+%d" % home)
                w.set_state("idle")
            except Exception:                                     # noqa: BLE001
                pass
        self._home = {}
        try:
            if self._root_home:
                self.app.root.geometry("+%d+%d" % self._root_home)
            self.app.console.title.configure(fg="#e8d9b8")
            if was:
                self.app.console.room_sys("...and back to work.")
        except Exception:                                         # noqa: BLE001
            pass
        self._root_home = None


# ---------------------------------------------------------------------------
class App:
    def __init__(self, root, project_root):
        self.root = root
        self.project_root = project_root
        self.sprites = discover_sprites(project_root)
        self.settings = load_settings()
        self.speaker = Speaker()
        self.windows = {}
        self.room_log = []          # [(speaker, text)]
        self.turn_q = queue.Queue()  # (bit_name, depth, relay)
        self.busy = False
        self._slot = 0
        self.results = queue.Queue()
        self._pending = {}          # summoned, mid-cast, not yet on screen
        self._quiet_cast = set()    # cast by the Wizard mid-line; he'll say it himself
        self._on_arrival = {}       # lines to put up on a card that doesn't exist yet
        self._just_dismissed = set()   # don't fetch back what this exchange sent away
        self._queued = set()        # who already has a turn waiting, so nobody
                                    # is asked the same thing twice in one breath
        if bits_tools:
            # the Wizard's summon_bit / dismiss_bit reach the screen through here
            bits_tools.ON_STAGE = self._stage_request
            bits_tools.STAGE_PRESENT = self.present
            bits_tools.ON_APPROVAL_NEEDED = self._approval_raised
        try:
            self.ambient = bits_ambient.Ambient() if bits_ambient else None
        except Exception:                                         # noqa: BLE001
            self.ambient = None      # watchers are a luxury; never fatal

        root.title("The Busy Business Bits")
        root.configure(bg=FRAME_DARK)
        root.geometry("620x480")
        root.minsize(560, 440)
        root.overrideredirect(True)     # borderless, same as the Bits' cards
        self._restore_geom = None
        self._minimized = False
        root.bind("<Map>", self._on_map)
        self.party = Party(self)
        # the code has to be caught wherever the focus is - every card is its
        # own toplevel, and "all" is the only bindtag they share
        root.bind_all("<KeyPress>", self.party.key, add="+")
        self.console = Console(self, root)

        avail = [n for n in available_bits(self.sprites) if n != HOST]
        missing = [n for n in BITS if n != HOST and n not in avail]
        self.console.room_sys("%d Bits ready." % len(avail))
        if missing:
            self.console.room_sys("no sprites yet: " + ", ".join(SHORT[m] for m in missing))
        if not self.settings.get("api_key"):
            self.console.room_sys("no API key set - open settings to add one.")
        else:
            threading.Thread(target=self._refresh_models, daemon=True).start()

        self._pump()
        self._ambient_tick()
        self._warm_peaks()
        self.party.warm()
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # -- summoning ----------------------------------------------------------
    def toggle(self, name):
        if name in self.windows or name in self._pending:
            self.dismiss(name)
        else:
            self.summon(name)

    def summon(self, name, quiet=False):
        """`quiet` means the Wizard cast this one mid-sentence, so his own reply
        carries the BAM and _land shouldn't say it a second time."""
        self._just_dismissed.discard(name)      # asked for outright; that wins
        if (name == HOST or name in self.windows or name in self._pending
                or not self.sprites.get(name, {}).get("idle")):
            return
        if quiet:
            self._quiet_cast.add(name)
        n = self._slot
        self._slot += 1
        sx, sy = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        step = CARD + 30
        # start clear of the console so it never gets buried
        try:
            self.root.update_idletasks()
            left = self.root.winfo_x() + self.root.winfo_width() + 24
        except Exception:
            left = 660
        vstep = CARD + 190          # card + its text box + breathing room
        cols = max(1, (sx - left - 20) // step)
        rows = max(1, (sy - 60) // vstep)
        cell = n % (cols * rows)
        lap = n // (cols * rows)    # after a full grid, cascade diagonally
        x = left + (cell % cols) * step + lap * 26
        y = 30 + (cell // cols) * vstep + lap * 26
        x = min(x, max(20, sx - CARD - 20))
        y = min(y, max(20, sy - 200))
        # The Wizard casts first and the Bit arrives on the BAM at the end of
        # it - so the whole snap and its sparkles play out before anything
        # appears. The arrival is timed off the App rather than the console's
        # own settle-to-idle job, because a second summon cancels that job and
        # would otherwise strand the first Bit mid-cast, never arriving.
        self._pending[name] = (x, y)
        self.console.set_active(name, True)
        self.console.room_sys("The Wizard begins the summoning of %s..." % SHORT[name])
        cue = self.console.wizard_flourish(self.sprites.get("The Wizard", {}))
        self.root.after(max(0, cue), lambda: self._land(name))

    def _why_not_summon(self, name):
        """Why `name` can't be cast right now, or "" if it can."""
        if name == HOST or name not in BITS:
            return "%s isn't one of the Bits." % name
        if not self.sprites.get(name, {}).get("idle"):
            return ("%s has no sprites on disk yet - there's nothing to summon."
                    % SHORT[name])
        if name in self.windows:
            return "%s is already in the room." % name
        if name in self._pending:
            return "%s is already mid-cast and about to land." % name
        return ""

    def _stage_request(self, action, name):
        """The Wizard casting from inside a reply, rather than from the roster.

        Called on his worker thread, so it decides what it can from plain data
        and hands the window work to the main thread. What it returns is what
        he reads off the tool, so it has to be a sentence he can act on.
        """
        if name == HOST or name not in BITS:
            return "%s isn't one of the Bits." % name
        if action == "dismiss":
            if name not in self.windows and name not in self._pending:
                return "%s isn't here." % name
            self.root.after(0, lambda: self.dismiss(name))
            return "%s is on the way out." % name
        why = self._why_not_summon(name)
        if why:
            return why
        # he is mid-line, so let his own reply be the BAM rather than doubling it
        self.root.after(0, lambda: self.summon(name, quiet=True))
        return ("%s is arriving on the sparkle. Address them by name in this very "
                "reply and they'll pick it up as they land." % name)

    def _approval_raised(self, item):
        """A Bit has hit the gate. Fetch the Boss - a ruling can't happen off
        screen, and the Bit shouldn't have to say "ask him when you next see him".

        Called from the queuing Bit's worker thread, inside the gate itself, and
        what it returns lands in that Bit's tool result.
        """
        who = SHORT.get(item.get("bit", ""), item.get("bit", ""))
        line = "%s needs the Boss - %s" % (who, item.get("summary", ""))
        self.root.after(0, lambda: self.console.room_sys(line))
        if BOSS in self.windows or BOSS in self._pending:
            return "The Boss is here - put it to him by name and he can rule on it."
        why = self._why_not_summon(BOSS)
        if why:
            return why
        self.root.after(0, lambda: self.summon(BOSS, quiet=True))
        return ("The Wizard is fetching the Boss for this one - put the case to "
                "him by name in this very reply, so he has it as he lands.")

    def _land(self, name):
        """The BAM. Fires on the sparkle peak, with the cast still playing."""
        xy = self._pending.pop(name, None)
        if xy is None or name in self.windows:
            return                  # dismissed or cancelled mid-cast
        self.windows[name] = BitWindow(self, name, xy[0], xy[1])
        for speaker, line in self._on_arrival.pop(name, []):
            self.windows[name].heard(speaker, line)
        self.console.room_sys("Okay... BAM! %s is in." % SHORT[name])
        quiet = name in self._quiet_cast     # he cast this one mid-sentence
        self._quiet_cast.discard(name)
        if not quiet:
            self._speak_line("The Wizard", "Okay... BAM!", to_window=False)

    def dismiss(self, name):
        self._quiet_cast.discard(name)
        self._on_arrival.pop(name, None)
        self._just_dismissed.add(name)
        if name in self._pending:                 # still mid-cast; call it off
            self._pending.pop(name, None)
            self.console.set_active(name, False)
            self.console.room_sys("%s never arrived." % SHORT[name])
            return
        w = self.windows.pop(name, None)
        if w:
            w.destroy()
            self.console.set_active(name, False)
            self.console.room_sys("%s dismissed." % SHORT[name])
        if not self.windows:
            self._slot = 0

    def dismiss_all(self):
        for n in list(self.windows) + list(self._pending):
            self.dismiss(n)

    def present(self):
        return list(self.windows.keys())

    def addressable(self):
        """Everyone you can talk to: the summoned Bits, plus the ones still mid-
        cast - the Wizard hands off to those in the same breath as summoning
        them - plus the Wizard himself, who is always in the console even
        though he has no window."""
        return self.present() + list(self._pending) + [HOST]

    def reachable(self):
        """Everyone a request can land on, which is everyone the Wizard could
        fetch: the room, plus any Bit still in the roster with art on disk.

        Being off screen isn't the same as being unavailable - that's what the
        Wizard is for. A name that reaches nobody is a dropped request, and the
        chains the whole app is built on are nothing but names.
        """
        return [n for n in BITS
                if n in self.windows or n in self._pending or n == HOST
                or self.sprites.get(n, {}).get("idle")]

    def fetch(self, name):
        """Have the Wizard cast for `name` if that's what it takes to reach them.

        Quiet, because whoever asked for them is mid-sentence: the console still
        prints the BAM, but he doesn't say it over the top of them.

        Not for anyone this exchange just sent away. "Begone, Reaper" names the
        Reaper, and a rule that fetches whoever is named would have the Wizard
        undo his own dismissal in the sentence that announced it. Asking for
        them outright still works - that clears the block on the way through.
        """
        if name in self._just_dismissed:
            return
        if not self._why_not_summon(name):
            self.summon(name, quiet=True)

    # -- conversation -------------------------------------------------------
    def user_says(self, text, to=None):
        self.room_log.append(("You", text))
        self.console.room_line("You", text)
        if to:
            # typed into a Bit's own box - there is nothing to work out
            targets, relay = [to], False
        else:
            targets, relay = route(text, self.reachable(), HOST)
        # every Bit still *hears* the whole room - room_log is what gets sent to
        # the API - but a Bit's window only shows its own thread with you, so
        # only the Bits expected to answer echo your line
        for t in targets:
            self.fetch(t)
            self._put_to(t, text)
        for t in targets:
            self._enqueue(t, relay=relay)
        self._drain()

    def _put_to(self, name, text):
        """Your line, onto a Bit's card - or onto the pile waiting for one.

        A Bit summoned by the very line it is meant to answer has no card yet,
        so the question goes up as it lands. The Wizard has no card at all: the
        console is his, and it already has your line on it.
        """
        w = self.windows.get(name)
        if w:
            w.heard("You", text)
        elif name != HOST:
            self._on_arrival.setdefault(name, []).append(("You", text))

    def _enqueue(self, name, depth=0, relay=False):
        """`relay` means this turn is holding a line that has not reached its
        Bit yet - the front desk taking a message. The handoff at the end of it
        is the delivery, so it goes through even with chatter switched off."""
        self.turn_q.put((name, depth, relay))
        self._queued.add(name)

    def _warm_peaks(self):
        """Scan the Wizard's cast for its sparkle peak up front.

        It costs about 400ms, and doing it lazily would spend that on the main
        thread at the exact moment the first cast is meant to start playing.
        """
        snap = (self.sprites.get("The Wizard") or {}).get("snap")
        if not snap:
            return
        threading.Thread(target=Animator.peak_ms, args=(snap,), daemon=True).start()

    # -- ambient ------------------------------------------------------------
    def _ambient_tick(self):
        """Give the watchers a look at the world every few seconds.

        A nudge is delivered exactly like a spoken line, so everything
        downstream - the chain limit, the voice, the transcript - works on it
        unchanged. The Bit sees a stage direction rather than a line from you.
        """
        try:
            if (self.ambient and not self.busy
                    and self.settings.get("ambient", True)
                    and self.turn_q.empty()):
                n = self.ambient.poll(self.present())
                if n:
                    self.room_log.append(("(noticed)", n.text))
                    self.console.room_sys("%s %s" % (SHORT.get(n.bit, n.bit), n.tag))
                    self._enqueue(n.bit)
                    self._drain()
        except Exception:                                         # noqa: BLE001
            pass
        self.root.after(4000, self._ambient_tick)

    def webhook_for(self, name):
        """A Bit's own n8n webhook, or "" if it goes through the shared key."""
        return ((self.settings.get("webhooks") or {}).get(name) or "").strip()

    def _drain(self):
        if self.busy or self.turn_q.empty():
            return
        name, depth, relay = self.turn_q.get()
        self._queued.discard(name)
        w = self.windows.get(name)
        if w is None and name != HOST:
            if name in self._pending:
                # summoned a moment ago and still inside the Wizard's cast. Hold
                # the turn rather than dropping it - the handoff that comes with
                # a summoning is the whole point of him being able to summon.
                self._enqueue(name, depth, relay)
                self.root.after(200, self._drain)
                return
            self._drain()
            return
        webhook = self.webhook_for(name)
        key = self.settings.get("api_key", "")
        # a Bit on its own webhook doesn't need the shared key, so only the
        # ones still going through the shared key are blocked by a missing one
        if not webhook and not key:
            self.console.room_sys(
                "%s needs the API key or its own webhook - open settings."
                % SHORT[name])
            self._drain()
            return
        self.busy = True
        if w:                       # the Wizard has no card to put to work
            w.set_state("work")
        self.console.status.configure(text="%s is thinking..." % SHORT[name])
        snapshot = list(self.room_log)
        present = self.addressable()
        model = self.settings.get("model") or ""

        def note_tool(bit, tool_name, args):
            """A Bit reaching for a tool, echoed to the console so a ten-second
            pause reads as work rather than as the app having hung."""
            detail = ""
            for k in ("path", "cmd", "query", "url", "subject", "name", "pattern"):
                if args.get(k):
                    detail = " %s" % str(args[k])[:48]
                    break
            self.root.after(0, lambda: self.console.room_sys(
                "%s ... %s%s" % (SHORT.get(bit, bit), tool_name, detail)))

        def work():
            try:
                reply = ask_bit(key, model, name, snapshot, present, webhook,
                                on_tool=note_tool)
                self.results.put(("ok", name, depth, reply, relay))
            except ApiError as e:
                self.results.put(("err", name, depth, str(e), relay))
            except Exception as e:  # noqa: BLE001
                self.results.put(("err", name, depth, repr(e), relay))

        threading.Thread(target=work, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, name, depth, payload, relay = self.results.get_nowait()
                self.busy = False
                self.console.status.configure(text="")
                w = self.windows.get(name)
                if kind == "err":
                    if w:
                        w.set_state("idle")
                        w.say_sys("(" + payload + ")")
                    self.console.room_sys("%s: %s" % (SHORT[name], payload))
                    self.root.after(120, self._drain)
                    continue
                self._deliver(name, payload, depth, relay)
        except queue.Empty:
            if not self.busy and self.turn_q.empty():
                # the room has settled, so the goodbye that named someone is
                # over and done with - they can be called for again
                self._just_dismissed.clear()
        self.root.after(60, self._pump)

    def _deliver(self, name, text, depth, relay=False):
        text = " ".join(text.split())
        if not text:
            self.root.after(120, self._drain)
            return
        self.room_log.append((name, text))
        self.console.room_line(name, text)
        # Bit-to-Bit chatter shows in the console only - a Bit's own window
        # stays a clean one-to-one transcript, written by _speak_line below
        self._speak_line(name, text)

        # a handoff is only a handoff if it reaches someone, so a Bit naming
        # another has that one fetched. Only the first name in the line, and
        # only as deep as MAX_CHAIN, so a Bit reeling off the roster doesn't
        # fill the desktop with it
        # ...but not to someone already holding a turn. "Wizard, get me the
        # Coder" names them both, so the Coder is answering the request already
        # when the Wizard hands it to him - and would otherwise answer twice.
        # `relay` is the front desk passing your line on, which is delivery
        # rather than Bit-to-Bit chatter - switching chatter off must not leave
        # the Wizard as the only Bit who can ever answer the console. What the
        # Bit he hands to says next is chatter again, so the flag stops here.
        nxt = find_addressees(text, self.reachable(), exclude=(name,))
        if (nxt and depth < MAX_CHAIN and nxt[0] not in self._queued
                and (relay or self.settings.get("chatter", True))):
            self.fetch(nxt[0])
            if relay:
                # your line has only just found its Bit, so it goes up on their
                # card too - a transcript that opens with the answer reads as a
                # Bit muttering to itself
                you = next((t for who, t in reversed(self.room_log)
                            if who == "You"), "")
                if you:
                    self._put_to(nxt[0], you)
            self._enqueue(nxt[0], depth + 1)

    def _speak_line(self, name, text, to_window=True):
        w = self.windows.get(name) if to_window else None
        prof = BITS[name]["voice"]
        dur = 0.0
        if self.settings.get("voices", True):
            try:
                wav, dur = synth_voice(text, prof)
                self.speaker.play(wav)
            except Exception:
                dur = 0.0
        if not w:
            self.root.after(int(max(300, dur * 1000)) + 150, self._drain)
            return

        w.set_state("talk" if random.random() < 0.75 else "snap_talk")
        w.begin_line()
        chars = list(text)
        total = max(0.9, dur if dur else len(chars) * 0.035)
        step = max(8, int(total * 1000 / max(1, len(chars))))

        def tick(i=0):
            if i < len(chars):
                w.stream_char(chars[i])
                w.after(step, lambda: tick(i + 1))
            else:
                w.end_line()
                w.set_state("idle")
                self.root.after(250, self._drain)

        tick()

    # -- voice in -----------------------------------------------------------
    def listen(self):
        try:
            import speech_recognition as sr
        except ImportError:
            self.console.room_sys(
                "mic needs:  pip install SpeechRecognition pyaudio")
            return
        self.console.mic.configure(text="...", bg="#7a3b46")
        self.console.status.configure(text="listening...")

        def work():
            out = None
            err = None
            try:
                r = sr.Recognizer()
                with sr.Microphone() as src:
                    r.adjust_for_ambient_noise(src, duration=0.4)
                    audio = r.listen(src, timeout=6, phrase_time_limit=15)
                out = r.recognize_google(audio)
            except Exception as e:  # noqa: BLE001
                err = str(e) or e.__class__.__name__
            self.root.after(0, lambda: self._heard_voice(out, err))

        threading.Thread(target=work, daemon=True).start()

    def _heard_voice(self, text, err):
        self.console.mic.configure(text="mic", bg="#3d2f34")
        self.console.status.configure(text="")
        if text:
            self.user_says(text, to=None)
        else:
            self.console.room_sys("didn't catch that. (%s)" % (err or "silence"))

    # -- settings -----------------------------------------------------------
    def _refresh_models(self):
        try:
            ids = list_models(self.settings["api_key"])
        except Exception:
            return
        self.model_ids = ids
        if not self.settings.get("model") and ids:
            self.settings["model"] = pick_default_model(ids)
            save_settings(self.settings)
            self.root.after(0, lambda: self.console.room_sys(
                "model: " + self.settings["model"]))

    def open_settings(self):
        SettingsDialog(self)

    # -- window chrome ------------------------------------------------------
    def _grab_root(self, e):
        self._rx, self._ry = e.x_root, e.y_root
        self._rorigin = (self.root.winfo_x(), self.root.winfo_y())

    def _drag_root(self, e):
        x0, y0 = getattr(self, "_rorigin", (0, 0))
        self.root.geometry("+%d+%d" % (x0 + e.x_root - self._rx,
                                       y0 + e.y_root - self._ry))

    def minimize(self):
        # a borderless window has no taskbar button, so hand it back a real
        # frame for as long as it's minimised - otherwise it can't be restored
        self.root.overrideredirect(False)
        self.root.update()          # absorb the remap that itself triggers
        self.root.iconify()
        self._minimized = True      # armed only once we are really iconified

    def _on_map(self, e):
        if e.widget is self.root and self._minimized:
            self._minimized = False
            self.root.overrideredirect(True)
            self.root.lift()

    def _work_area(self):
        """Screen minus the taskbar, so maximising doesn't bury it."""
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                r = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(
                        0x0030, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
                    return r.left, r.top, r.right - r.left, r.bottom - r.top
            except Exception:
                pass
        return (0, 0, self.root.winfo_screenwidth(),
                self.root.winfo_screenheight())

    def toggle_max(self):
        if self._restore_geom:
            self.root.geometry(self._restore_geom)
            self._restore_geom = None
            return
        self._restore_geom = self.root.geometry()
        x, y, w, h = self._work_area()
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def quit(self):
        self.party.stop()
        self.speaker.stop()
        self.dismiss_all()
        self.root.destroy()


# ---------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Settings")
        self.configure(bg=FRAME_DARK)
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()

        pad = {"padx": 14, "pady": 6}
        tk.Label(self, text="Anthropic API key", bg=FRAME_DARK, fg="#e8d9b8",
                 font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", **pad)
        self.key = tk.Entry(self, width=46, show="•", bg="#241a20", fg=PAPER,
                            insertbackground=PAPER, bd=0, font=("Consolas", 9),
                            highlightthickness=1, highlightbackground="#3d2f34")
        self.key.grid(row=1, column=0, columnspan=2, sticky="we", padx=14, ipady=4)
        self.key.insert(0, app.settings.get("api_key", ""))

        tk.Label(self, text="stored in  ~/.busy_business_bits.json  on this PC only",
                 bg=FRAME_DARK, fg="#8a7d70", font=("Consolas", 7, "italic")
                 ).grid(row=2, column=0, columnspan=2, sticky="w", padx=14)

        tk.Label(self, text="Model", bg=FRAME_DARK, fg="#e8d9b8",
                 font=("Consolas", 9, "bold")).grid(row=3, column=0, sticky="w", **pad)
        self.model = ttk.Combobox(self, width=42, values=getattr(app, "model_ids", []))
        self.model.grid(row=4, column=0, columnspan=2, sticky="we", padx=14)
        self.model.set(app.settings.get("model", ""))
        tk.Button(self, text="fetch models", bg=FRAME_GOLD, fg=INK, bd=0,
                  font=("Consolas", 8, "bold"), cursor="hand2",
                  command=self._fetch).grid(row=5, column=0, sticky="w", padx=14, pady=(4, 0))

        self.voices = tk.BooleanVar(value=app.settings.get("voices", True))
        self.chatter = tk.BooleanVar(value=app.settings.get("chatter", True))
        self.ambient = tk.BooleanVar(value=app.settings.get("ambient", True))
        for i, (var, label) in enumerate([
            (self.voices, "garbled voices"),
            (self.chatter, "let Bits answer each other"),
            (self.ambient, "let Bits speak up on their own"),
        ]):
            tk.Checkbutton(self, text=label, variable=var, bg=FRAME_DARK, fg=PAPER,
                           selectcolor=INK, activebackground=FRAME_DARK,
                           activeforeground=PAPER, bd=0, font=("Consolas", 9),
                           highlightthickness=0).grid(row=6 + i, column=0, sticky="w",
                                                      padx=12, pady=2)

        # --- per-Bit n8n webhooks -------------------------------------------
        tk.Label(self, text="Per-Bit n8n webhooks", bg=FRAME_DARK, fg="#e8d9b8",
                 font=("Consolas", 9, "bold")).grid(row=9, column=0, sticky="w",
                                                    padx=14, pady=(12, 0))
        tk.Label(self, text="blank = use the shared API key above",
                 bg=FRAME_DARK, fg="#8a7d70", font=("Consolas", 7, "italic")
                 ).grid(row=10, column=0, columnspan=2, sticky="w", padx=14)

        hooks = tk.Frame(self, bg=FRAME_DARK)
        hooks.grid(row=11, column=0, columnspan=2, sticky="we", padx=14, pady=(4, 0))
        saved = app.settings.get("webhooks") or {}
        self.hooks = {}
        for i, name in enumerate(available_bits(app.sprites)):
            tk.Label(hooks, text=SHORT[name], bg=FRAME_DARK, fg=BITS[name]["color"],
                     font=("Consolas", 8, "bold"), width=12, anchor="w"
                     ).grid(row=i, column=0, sticky="w", pady=1)
            e = tk.Entry(hooks, width=38, bg="#241a20", fg=PAPER,
                         insertbackground=PAPER, bd=0, font=("Consolas", 8),
                         highlightthickness=1, highlightbackground="#3d2f34",
                         highlightcolor=FRAME_GOLD)
            e.grid(row=i, column=1, sticky="we", ipady=2, pady=1)
            e.insert(0, saved.get(name, ""))
            self.hooks[name] = e

        bar = tk.Frame(self, bg=FRAME_DARK)
        bar.grid(row=12, column=0, columnspan=2, sticky="e", padx=14, pady=12)
        tk.Button(bar, text="cancel", bg="#3d2f34", fg=PAPER, bd=0, cursor="hand2",
                  font=("Consolas", 9), command=self.destroy).pack(side="left", padx=4, ipadx=8)
        tk.Button(bar, text="save", bg=FRAME_GOLD, fg=INK, bd=0, cursor="hand2",
                  font=("Consolas", 9, "bold"), command=self._save).pack(side="left", ipadx=10)

        self.status = tk.Label(self, text="", bg=FRAME_DARK, fg="#8a7d70",
                               font=("Consolas", 8))
        self.status.grid(row=13, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 8))

    def _fetch(self):
        k = self.key.get().strip()
        if not k:
            self.status.configure(text="enter a key first")
            return
        self.status.configure(text="fetching...")

        def work():
            try:
                ids = list_models(k)
                self.after(0, lambda: self._got(ids))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: self.status.configure(text=str(e)[:60]))

        threading.Thread(target=work, daemon=True).start()

    def _got(self, ids):
        self.app.model_ids = ids
        self.model.configure(values=ids)
        if not self.model.get() and ids:
            self.model.set(pick_default_model(ids))
        self.status.configure(text="%d models" % len(ids))

    def _save(self):
        hooks = {}
        for name, e in self.hooks.items():
            url = e.get().strip()
            if not url:
                continue
            if not url.lower().startswith(("http://", "https://")):
                self.status.configure(text="%s: webhook must start with http"
                                           % SHORT[name])
                return          # keep the dialog open so it can be fixed
            hooks[name] = url

        s = self.app.settings
        s["api_key"] = self.key.get().strip()
        s["model"] = self.model.get().strip()
        s["voices"] = bool(self.voices.get())
        s["chatter"] = bool(self.chatter.get())
        s["ambient"] = bool(self.ambient.get())
        s["webhooks"] = hooks
        save_settings(s)
        if hooks:
            self.app.console.room_sys(
                "on their own webhook: " + ", ".join(SHORT[n] for n in hooks))
        self.app.console.room_sys("settings saved.")
        if s["api_key"] and not s["model"]:
            threading.Thread(target=self.app._refresh_models, daemon=True).start()
        self.destroy()


# ---------------------------------------------------------------------------
DEMO_LINES = {
    "The Boss": [
        "Numbers first. What's the burn and what's the margin?",
        "Coder, get me the export. Secretary, put it on Thursday.",
        "I don't want a plan, I want a number.",
    ],
    "The Coder": [
        "Give me the actual error, not the vibe of the error.",
        "That'll work, but we'll hate ourselves in six months.",
        "Boss, the schema drifted again. It's always the schema.",
    ],
    "The Courier": [
        "Already moving. Where's it going?",
        "Picked up, logged, delivered. Next!",
        "I'll run it over to the Secretary, she'll know.",
    ],
    "The Investigator": [
        "Something here doesn't add up. Give me an hour.",
        "The invoice says March. The bank says May. Interesting.",
        "I found it. You're not going to like where.",
    ],
    "The Reaper": [
        "What happens if we simply... do not?",
        "It's been dead since March. Let me make it official.",
        "Cut it. You'll feel better on Monday.",
    ],
    "The Secretary": [
        "Noted. That's you, by Thursday. I'll remind you Wednesday.",
        "You agreed to this in the last meeting, actually.",
        "I have it. Third drawer, filed under regrets.",
    ],
    "The Wizard": [
        "Okay... BAM!",
        "A simple incantation. Two clicks and a restart.",
        "Summoning is my department. Answers are theirs.",
    ],
    "The Ghost": [
        "You said you'd do that in March.",
        "I still have the email. Nobody replied to it.",
        "It's fine. It's all fine. It's been fine for a year.",
    ],
    "The Librarian": [
        "It's filed. You just called it something else.",
        "Version four supersedes it. You approved that.",
        "I can find it, but I'd rather you wrote it down.",
    ],
}


def demo_reply(_key, _model, name, room_log, present, _webhook=None,
                on_tool=None):
    """Canned lines - except the summoning, which is real even in demo mode.

    Asking for a Bit by name is the first thing anyone tries, and a demo that
    answered it with a canned quip would teach the wrong thing about the app.
    So the Wizard reads the last line, works out who it wants, and casts.
    """
    import time as _t
    _t.sleep(0.5)
    if name == HOST and bits_tools:
        said = next((t for who, t in reversed(room_log) if who != HOST), "")
        wants = find_addressees(said, [b for b in BITS if b != HOST])
        if wants:
            who = wants[0]
            away = re.search(r"dismiss|go away|send .{0,20}away|get rid of|"
                             r"off you go|be gone", said, re.I)
            call = "dismiss_bit" if away else "summon_bit"
            if on_tool:
                on_tool(HOST, call, {"name": SHORT[who]})
            out = bits_tools.run_tool(HOST, call, {"name": SHORT[who]})
            if not out.startswith(who):          # couldn't, and says why
                return "The stars refuse me. " + out
            if away:
                return "Begone, %s. Okay... BAM!" % SHORT[who]
            return "Okay... BAM! %s, you're up." % SHORT[who]
        # Nobody named, and every unaddressed line comes to him now - so the
        # handoff has to be canned too, or the demo is one Bit saying one quip
        # forever. The real Wizard reads the line and picks; this one has
        # nothing to read with, so it passes to whoever is already on screen.
        others = [b for b in (present or []) if b != HOST]
        if others:
            return "%s, this one's yours." % SHORT[others[0]]
    pool = DEMO_LINES.get(name) or ["Right."]
    return pool[len([1 for s, _ in room_log if s == name]) % len(pool)]


def voice_demo():
    """Play every Bit's garbled voice once, so you can tune them."""
    import time
    sp = Speaker()
    if not sp.backend:
        print("No audio backend found.")
        return
    for name, cfg in BITS.items():
        line = (DEMO_LINES.get(name) or ["Hello."])[0]
        wav, dur = synth_voice(line, cfg["voice"])
        print("%-17s %.2fs  %s" % (name, dur, line))
        sp.play(wav)
        time.sleep(dur + 0.45)


def song_demo():
    """Play the party tune once, for tuning - the sibling of --voices."""
    import time
    sp = Speaker()
    wav, dur = synth_song()
    if not sp.backend:
        print("No audio backend found.")
        return
    print("the party tune  %.2fs" % dur)
    sp.play(wav)
    time.sleep(dur + 0.3)


def main():
    if "--voices" in sys.argv:
        voice_demo()
        return
    if "--song" in sys.argv:
        song_demo()
        return
    make_dpi_aware()
    root = tk.Tk()
    project_root = HERE
    if not os.path.isdir(os.path.join(project_root, "The Bits")):
        # allow running from anywhere as long as the project sits alongside
        alt = os.path.join(HERE, "The Busy Business Bits Project")
        if os.path.isdir(os.path.join(alt, "The Bits")):
            project_root = alt
    app = App(root, project_root)
    if "--demo" in sys.argv:
        global ask_bit
        ask_bit = demo_reply
        app.demo = True
        app.settings["api_key"] = app.settings.get("api_key") or "demo"
        app.console.room_sys("DEMO MODE - canned lines, no API calls.")
    root.mainloop()


if __name__ == "__main__":
    main()
