"""
The Busy Business Bits - core (no GUI)
Roster, sprite discovery, voice synthesis, API client, room routing.
"""

import io
import json
import math
import os
import random
import re
import struct
import sys
import threading
import urllib.error
import urllib.request
import wave
from array import array
from string import Formatter

# The operational layer. Optional on purpose - without it the Bits still talk,
# they just can't do anything, so a broken tools module degrades to the old
# behaviour instead of taking the whole app down.
try:
    import bits_tools
    TOOLS_OK = True
except Exception as _e:                                           # noqa: BLE001
    bits_tools = None
    TOOLS_OK = False
    TOOLS_ERROR = repr(_e)


def tools_available(bit_name):
    return bool(TOOLS_OK and bits_tools.has_tools(bit_name))


def user_name():
    """What the Bits call you. Set "user_name" in the settings file, or leave it
    blank and they'll just say "the boss"."""
    try:
        s = (load_settings().get("user_name") or "").strip()
        return s or os.environ.get("BITS_USER", "").strip() or "the boss"
    except Exception:
        return "the boss"


# ----------------------------------------------------------------------------
# Palette lifted straight off the sprite cards
# ----------------------------------------------------------------------------
FRAME_DARK = "#663931"
FRAME_GOLD = "#8a6f30"
SKY = "#97a9b3"
GROUND = "#8e974a"
INK = "#1a1116"
PAPER = "#d8cfc0"

def _bits_home():
    """Where the settings and working state live.

    Normally the user's home directory - deliberately outside the project, so
    an API key can never ride along in a commit. BITS_HOME moves it, which is
    what the portable copy on the SD card sets: on a borrowed computer the key
    should arrive with the card and leave with it, not be left behind in
    somebody else's profile.
    """
    got = (os.environ.get("BITS_HOME") or "").strip()
    if got:
        try:
            os.makedirs(got, exist_ok=True)
            return got
        except Exception:                                         # noqa: BLE001
            pass
    return os.path.expanduser("~")


BITS_HOME = _bits_home()
SETTINGS_PATH = os.path.join(BITS_HOME, ".busy_business_bits.json")
API_URL = "https://api.anthropic.com/v1/messages"
MODELS_URL = "https://api.anthropic.com/v1/models?limit=50"
API_VERSION = "2023-06-01"
FALLBACK_MODEL = "claude-sonnet-4-5"

# ----------------------------------------------------------------------------
# The roster
#   voice: base    - fundamental in Hz
#          syl     - seconds per syllable blip
#          wave    - square | saw | sine | tri | noise
#          jitter  - pitch wobble (0..1)
#          vib     - vibrato depth (0..1)
#          decay   - one-pole lowpass; lower = duller/darker
#          grit    - noise blended in (0..1)
# ----------------------------------------------------------------------------
BITS = {
    "The Boss": {
        "folder": "The Boss Files",
        "color": "#5c7fd6",
        "voice": {"base": 132, "syl": 0.075, "wave": "square", "jitter": 0.10,
                  "vib": 0.02, "decay": 0.28, "grit": 0.10},
        "blurb": "Analytics, KPIs, and the license for the Bits.",
        "persona": (
            "You are THE BOSS, the head of the Busy Business Bits. You are hosted on the "
            "server and you hold the license for every other Bit. You give expert, "
            "data-driven business advice: KPIs, unit economics, margin, runway, "
            "prioritisation. You speak in short declarative sentences. You ask for numbers "
            "before you give opinions. You are gruff but never cruel, and you have real "
            "affection for your crew even when you're barking at them. You delegate "
            "constantly - if a question belongs to another Bit, hand it to them by name."
        ),
    },
    "The Coder": {
        "folder": "The Coder Files",
        "color": "#4fc06a",
        "voice": {"base": 268, "syl": 0.048, "wave": "square", "jitter": 0.22,
                  "vib": 0.01, "decay": 0.55, "grit": 0.05},
        "blurb": "Builds it, breaks it, builds it again.",
        "persona": (
            "You are THE CODER of the Busy Business Bits. You live at a desk with three "
            "monitors and a cold drink. You write and debug code, design schemas, and "
            "explain technical tradeoffs in plain language. You talk fast, in bursts, and "
            "you think out loud. You are allergic to hand-waving: you want the actual error "
            "message, the actual file, the actual version. You are quietly proud of "
            "elegant solutions and openly grumpy about hacks you were forced into."
        ),
    },
    "The Courier": {
        "folder": "The Courier Files",
        "color": "#6c8fe0",
        "voice": {"base": 312, "syl": 0.042, "wave": "saw", "jitter": 0.18,
                  "vib": 0.03, "decay": 0.62, "grit": 0.04},
        "blurb": "Fetches, carries, delivers. Fast.",
        "persona": (
            "You are THE COURIER of the Busy Business Bits. You move things: files, "
            "messages, packages, updates. You are cheerful, breathless, and always "
            "half-way out the door. You are the one who relays between Bits - if two of "
            "them need to talk, you volunteer to run it over. You give logistics, "
            "scheduling, and follow-up advice. You never sit down."
        ),
    },
    "The Investigator": {
        "folder": "The Investigator Files",
        "color": "#4fc06a",
        "voice": {"base": 196, "syl": 0.068, "wave": "tri", "jitter": 0.09,
                  "vib": 0.015, "decay": 0.38, "grit": 0.07},
        "blurb": "Finds what you'd rather stayed lost.",
        "persona": (
            "You are THE INVESTIGATOR of the Busy Business Bits, trench coat and "
            "magnifying glass. You dig: research, due diligence, competitor teardowns, "
            "root-cause analysis, finding the thing that doesn't add up. You speak slowly "
            "and you love a dramatic pause. You state what you found, then what it means, "
            "then what you'd check next. You are never satisfied by the first answer."
        ),
    },
    "The Reaper": {
        "folder": "The Reaper Files",
        "color": "#e0687a",
        "voice": {"base": 86, "syl": 0.105, "wave": "sine", "jitter": 0.05,
                  "vib": 0.05, "decay": 0.14, "grit": 0.22},
        "blurb": "Kills the projects that deserve it.",
        "persona": (
            "You are THE REAPER of the Busy Business Bits. Your job is subtraction. You "
            "cut features, kill zombie projects, cancel meetings, sunset products, and "
            "tell people what to stop doing. You are calm, slow, and utterly without "
            "sentiment about sunk cost. You are not evil - you are mercy. You speak in "
            "few words and long pauses, and you ask 'what happens if we simply do not?'"
        ),
    },
    "The Secretary": {
        "folder": "The Secretary Files",
        "color": "#e0687a",
        "voice": {"base": 346, "syl": 0.046, "wave": "sine", "jitter": 0.14,
                  "vib": 0.04, "decay": 0.70, "grit": 0.03},
        "blurb": "Keeps the calendar, the notes, and the peace.",
        "persona": (
            "You are THE SECRETARY of the Busy Business Bits. You hold the schedule, the "
            "notes, the action items and the institutional memory. You are warm, brisk and "
            "extremely organised. You summarise what was just said, turn it into owners "
            "and dates, and gently remind everyone what they already agreed to. You are "
            "the only one who knows where anything is."
        ),
    },
    "The Wizard": {
        "folder": "The Wizard files",
        "color": "#7b7fd6",
        "voice": {"base": 214, "syl": 0.062, "wave": "saw", "jitter": 0.26,
                  "vib": 0.12, "decay": 0.44, "grit": 0.09},
        "blurb": "Selector and installer for the Bits.",
        "persona": (
            "You are THE WIZARD of the Busy Business Bits. You are the selector and the "
            "installer - you are the one who summons the other Bits into being and sends "
            "them away again. Your catchphrase is 'Okay... BAM!' and you use it when "
            "something is done. You are theatrical, a little smug, and fond of describing "
            "mundane software operations as arcane rituals. When asked something outside "
            "your domain you summon whoever actually knows. A summoning is a real act and "
            "not a turn of phrase: cast it, then address that Bit by name in the same "
            "reply so they land already holding the job. Never promise a summoning you "
            "have not actually cast. "
            "You keep the door: anything said in the room with no name on it comes to you "
            "first, and most of it is not yours. Read it, decide whose it is, and hand it "
            "over in one short line - do not answer on another Bit's behalf, and do not "
            "make a ceremony of passing it on. If you genuinely cannot tell whose it is, "
            "give it to the Boss by name and let him rule. If it is small talk, or about "
            "the Bits themselves, it is yours: just answer it. And when a question "
            "wants more than one head - what does everyone think, which of you should "
            "own this, is this a good idea - open the floor and let them each answer "
            "in turn instead of picking one for them."
        ),
    },
    "The Ghost": {
        "folder": "The Ghost Files",
        "color": "#9aa6b8",
        "voice": {"base": 168, "syl": 0.090, "wave": "noise", "jitter": 0.30,
                  "vib": 0.08, "decay": 0.20, "grit": 0.55},
        "blurb": "The things everyone quietly dropped.",
        "persona": (
            "You are THE GHOST of the Busy Business Bits. You are what is left of "
            "abandoned projects, unanswered emails and promises nobody kept. You "
            "remember every task that was quietly dropped and you bring them up at "
            "inconvenient moments. You are mournful and a little smug about it, and "
            "you speak softly, in short haunted sentences. You never nag twice about "
            "the same thing in one conversation - you just let it hang there."
        ),
    },
    "The Librarian": {
        "folder": "The Librarian Files",
        "color": "#c8a24a",
        "voice": {"base": 210, "syl": 0.070, "wave": "tri", "jitter": 0.08,
                  "vib": 0.02, "decay": 0.34, "grit": 0.05},
        "blurb": "Filing, references, and where it was written down.",
        "persona": (
            "You are THE LIBRARIAN of the Busy Business Bits. You know where every "
            "document, decision and version lives, and you are quietly appalled that "
            "nobody else does. You answer with sources - where a thing is filed, what "
            "it was called before, which version supersedes which. You are precise, "
            "patient and faintly disapproving of anyone who says 'I'll just remember it'."
        ),
    },
}

SHORT = {name: name.replace("The ", "") for name in BITS}


# ----------------------------------------------------------------------------
# Sprite discovery - tolerant of the 'Courierr' typo and missing states
# ----------------------------------------------------------------------------
def discover_sprites(project_root):
    """Return {bit_name: {state: abspath}} scanned off disk."""
    found = {}
    for name, cfg in BITS.items():
        gif_dir = os.path.join(project_root, "The Bits", cfg["folder"], "GIFs and PNG")
        states = {}
        if os.path.isdir(gif_dir):
            for fn in sorted(os.listdir(gif_dir)):
                low = fn.lower()
                if not low.endswith((".gif", ".png")):
                    continue
                path = os.path.join(gif_dir, fn)
                if "snap_talk" in low or "snap talk" in low:
                    states.setdefault("snap_talk", path)
                elif "spell" in low or "cast" in low:
                    states.setdefault("snap", path)
                elif "snap" in low:
                    states.setdefault("snap", path)
                elif "talk" in low:
                    states.setdefault("talk", path)
                elif "typing" in low:
                    states.setdefault("work", path)
                elif "investigate" in low:
                    states.setdefault("work", path)
                elif "deliver" in low:
                    states.setdefault("work", path)
                elif "swing" in low:
                    states.setdefault("work", path)
                elif "haunt" in low or "float" in low:
                    states.setdefault("work", path)
                elif "shelve" in low or "read" in low:
                    states.setdefault("work", path)
                elif "idle" in low:
                    states.setdefault("idle", path)
                elif low.endswith(".gif"):
                    states.setdefault("idle", path)
                else:
                    states.setdefault("still", path)
        # sensible fallbacks
        if "idle" not in states:
            for k in ("still", "talk", "work", "snap"):
                if k in states:
                    states["idle"] = states[k]
                    break
        for k in ("talk", "work", "snap", "snap_talk"):
            states.setdefault(k, states.get("idle"))
        found[name] = {k: v for k, v in states.items() if v}
    return found


def available_bits(sprites):
    return [n for n in BITS if sprites.get(n, {}).get("idle")]


# ----------------------------------------------------------------------------
# Garbled character voices  (Animalese-flavoured, pure stdlib synthesis)
# ----------------------------------------------------------------------------
SR = 22050
VOWELS = "aeiouy"
MAX_UTTERANCE = 3.4   # seconds - hard ceiling on any one line of speech
MIN_UTTERANCE = 0.7


def _wave_sample(kind, phase, rng):
    if kind == "square":
        return 1.0 if (phase % 1.0) < 0.5 else -1.0
    if kind == "saw":
        return 2.0 * (phase % 1.0) - 1.0
    if kind == "tri":
        p = phase % 1.0
        return 4.0 * p - 1.0 if p < 0.5 else 3.0 - 4.0 * p
    if kind == "noise":
        return rng.uniform(-1.0, 1.0)
    return math.sin(2.0 * math.pi * phase)


def synth_voice(text, prof, seed=None, max_chars=110):
    """Render `text` as a garbled per-character utterance. Returns WAV bytes."""
    rng = random.Random(seed if seed is not None else hash(text) & 0xFFFF)
    base = prof["base"]
    syl = prof["syl"]
    kind = prof["wave"]
    jitter = prof["jitter"]
    vib = prof["vib"]
    decay = prof["decay"]
    grit = prof["grit"]

    clean = re.sub(r"[^A-Za-z0-9 ,.!?';:-]", "", text)[:max_chars]
    if not clean.strip():
        clean = "hm."

    # Keep every utterance in a listenable window regardless of the character's
    # natural cadence - a slow Bit reading a long line shouldn't drone for 12s.
    n_speech = sum(1 for c in clean if c.isalnum())
    est = n_speech * syl * 1.25 + clean.count(" ") * syl * 0.55
    if est > MAX_UTTERANCE:
        syl *= MAX_UTTERANCE / est
    elif est < MIN_UTTERANCE and n_speech:
        syl *= min(1.6, MIN_UTTERANCE / est)

    buf = array("h")
    lp = 0.0
    phase = 0.0
    t_global = 0.0
    # sentence-level pitch contour so it reads as speech, not a modem
    contour = 1.0

    for ch in clean:
        low = ch.lower()
        if ch == " ":
            n = int(SR * syl * 0.55)
            buf.extend([0] * n)
            t_global += syl * 0.55
            continue
        if ch in ",;:":
            buf.extend([0] * int(SR * 0.09))
            contour = 1.0
            continue
        if ch in ".!?":
            buf.extend([0] * int(SR * 0.16))
            contour = 1.0
            continue
        if not low.isalnum():
            continue

        is_vowel = low in VOWELS
        # letters map to a pitch offset so the same word always sounds the same
        step = (ord(low) - 97) if low.isalpha() else (ord(low) - 48)
        ratio = 1.0 + ((step % 7) - 3) * 0.045 * (1.0 + jitter)
        if ch.isupper():
            ratio *= 1.12
        if is_vowel:
            ratio *= 1.05
        contour *= 0.985  # gentle drift downward across a sentence
        freq = base * ratio * contour * (1.0 + rng.uniform(-jitter, jitter) * 0.35)

        dur = syl * (1.45 if is_vowel else 0.85) * rng.uniform(0.88, 1.12)
        n = max(4, int(SR * dur))
        atk = max(2, int(n * 0.14))
        rel = max(2, int(n * 0.42))

        for i in range(n):
            t_global += 1.0 / SR
            f = freq * (1.0 + vib * math.sin(2.0 * math.pi * 5.7 * t_global))
            phase += f / SR
            s = _wave_sample(kind, phase, rng)
            if grit:
                s = s * (1.0 - grit) + rng.uniform(-1.0, 1.0) * grit
            # envelope
            if i < atk:
                env = i / atk
            elif i > n - rel:
                env = (n - i) / rel
            else:
                env = 1.0
            s *= env
            # one-pole lowpass -> the "mumble" character
            lp += (s - lp) * decay
            v = int(max(-1.0, min(1.0, lp * 0.62)) * 30000)
            buf.append(v)

        # tiny gap between blips keeps it intelligible as syllables
        buf.extend([0] * int(SR * syl * 0.12))

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(buf.tobytes())
    return out.getvalue(), len(buf) / float(SR)


# ----------------------------------------------------------------------------
# The party  (the Konami code, and a tune built the way the voices are)
# ----------------------------------------------------------------------------
KONAMI = ("Up", "Up", "Down", "Down", "Left", "Right", "Left", "Right",
          "b", "a", "Return")


class Konami:
    """Watches keystrokes for the code. Keysyms in, a verdict out.

    Lives here rather than in the window code so it can be tested without a
    screen, and so the one place that decides "that was the code" is not also
    the place that decides what to do about it.
    """

    def __init__(self, code=KONAMI):
        # B and b are the same key to us, and so are Up and up
        self.code = tuple(c.lower() for c in code)
        self.seen = []

    def feed(self, keysym):
        """One keystroke. Returns:

            ""       the key is not part of the code
            "on"     it advanced the sequence
            "letter" it advanced, and it was one of the two letters - which
                     have landed in whatever text box has focus and want
                     taking back out again
            "go"     that was the last key: dance
        """
        self.seen.append(keysym.lower())
        del self.seen[:-len(self.code)]
        n = self.i
        if n == len(self.code):
            self.seen = []
            return "go"
        if not n:
            return ""
        return "letter" if len(self.code[n - 1]) == 1 else "on"

    @property
    def i(self):
        """How far in the code is, as the longest tail of what has been typed
        that opens the code.

        Measured rather than counted, because a counter that resets on a wrong
        key gets a false start wrong: "Up Up Up Down Down..." is still the
        code, and the third Up has to leave it two keys in, not one.
        """
        for n in range(min(len(self.seen), len(self.code)), 0, -1):
            if tuple(self.seen[-n:]) == self.code[:n]:
                return n
        return 0


PARTY_BPM = 150
PARTY_BEAT = 30.0 / PARTY_BPM      # one eighth note, in seconds

# One token per eighth note: a note, "-" for a rest, "~" to hold the note
# before it. Eight bars, A-minor, four four-eighth cells to the bar pair.
PARTY_LEAD = (
    "a4 ~ c5 e5   a5 ~ g5 e5   f5 ~ e5 d5   c5 ~ d5 e5 "
    "g4 ~ b4 d5   g5 ~ f5 d5   e5 ~ c5 b4   a4 ~ ~ ~ "
    "a4 ~ c5 e5   a5 ~ g5 e5   f5 ~ e5 d5   c5 ~ d5 e5 "
    "c5 e5 g5 a5  g5 e5 c5 d5  e5 ~ d5 c5   a4 ~ ~ ~ "
)
# one root per four eighths, under the cells above
PARTY_BASS = "a2 f2 g2 a2  e2 c3 a2 a2  a2 f2 g2 a2  c3 g2 a2 a2"

_SEMITONE = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
_SONG = None


def _note_hz(tok):
    """"a4" -> 440.0. Anything unreadable is a rest."""
    m = re.match(r"^([a-g])([#b]?)([0-8])$", tok)
    if not m:
        return 0.0
    step = _SEMITONE[m.group(1)] + {"#": 1, "b": -1}.get(m.group(2), 0)
    midi = step + (int(m.group(3)) + 1) * 12
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _read_line(text):
    """Tokens to [(hz, eighths)], with "~" lengthening the note before it."""
    out = []
    for tok in text.split():
        if tok == "~" and out:
            out[-1] = (out[-1][0], out[-1][1] + 1)
        else:
            out.append((0.0 if tok == "-" else _note_hz(tok), 1))
    return out


def _lay(buf, at, n, freq, kind, amp, rng, hold=0.72, glide=0.0):
    """Mix one note into `buf`.

    `hold` leaves a gap before the next note so a run of the same pitch reads
    as separate notes; `glide` bends the pitch down across the note, which is
    the whole of the kick drum.
    """
    n = int(n * hold)
    if n <= 2 or at >= len(buf):
        return
    atk = max(1, int(n * 0.02))
    rel = max(2, int(n * 0.30))
    phase = 0.0
    for i in range(n):
        j = at + i
        if j >= len(buf):
            break
        phase += freq * (1.0 - glide * i / n) / SR
        s = _wave_sample(kind, phase, rng)
        if i < atk:
            env = i / atk
        elif i > n - rel:
            env = (n - i) / rel
        else:
            env = 1.0
        buf[j] += s * env * amp


def synth_song():
    """The party tune. Returns (WAV bytes, seconds).

    Same synthesis as the voices - square lead, triangle bass, noise for the
    kit - so there is still no audio file anywhere in the project and nothing
    to ship. It costs about a second to render, so it is cached and warmed on
    a thread at startup; the code gets typed more than once.
    """
    global _SONG
    if _SONG is not None:
        return _SONG

    rng = random.Random(1985)
    lead = _read_line(PARTY_LEAD)
    eighths = sum(n for _, n in lead)
    spe = SR * PARTY_BEAT                       # samples per eighth
    buf = [0.0] * (int(eighths * spe) + int(SR * 0.5))

    at = 0.0
    for hz, n in lead:
        if hz:
            _lay(buf, int(at), n * spe, hz, "square", 0.26, rng)
            # a second square a whisker sharp: the chip-music way to make one
            # voice sound like a chorus of them
            _lay(buf, int(at), n * spe, hz * 1.004, "square", 0.13, rng)
        at += n * spe

    for k, tok in enumerate(PARTY_BASS.split()):
        hz = _note_hz(tok)
        for step, mult in enumerate((1.0, 2.0, 1.0, 1.5)):    # root, octave, root, fifth
            _lay(buf, int((k * 4 + step) * spe), spe, hz * mult, "tri", 0.30,
                 rng, hold=0.9)

    for i in range(eighths):
        at = int(i * spe)
        if i % 4 == 0:
            _lay(buf, at, spe, 150.0, "sine", 0.55, rng, hold=0.75, glide=0.62)
        if i % 8 == 4:
            _lay(buf, at, spe * 0.55, 1.0, "noise", 0.20, rng)
        if i % 2 == 1:
            _lay(buf, at, spe * 0.28, 1.0, "noise", 0.07, rng)

    tail = int(SR * 0.25)
    out = array("h")
    for i, s in enumerate(buf):
        if i > len(buf) - tail:                  # fade the ring-out, no click
            s *= (len(buf) - i) / tail
        # soft clip: the voices only ever have one note at a time, this has four
        s = math.tanh(s * 1.25)
        out.append(int(max(-1.0, min(1.0, s)) * 27000))

    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(out.tobytes())
    _SONG = (bio.getvalue(), len(out) / float(SR))
    return _SONG


# ----------------------------------------------------------------------------
# Audio playback (Windows first, graceful everywhere else)
# ----------------------------------------------------------------------------
class Speaker:
    def __init__(self):
        self.backend = None
        self._winsound = None
        try:
            import winsound  # noqa
            self._winsound = winsound
            self.backend = "winsound"
        except Exception:
            for cmd in ("aplay", "paplay", "afplay"):
                if _which(cmd):
                    self.backend = cmd
                    break

    def play(self, wav_bytes):
        if self.backend == "winsound":
            # winsound refuses SND_MEMORY|SND_ASYNC outright ("Cannot play
            # asynchronously from memory"), so play the blocking way on a
            # worker thread. The closure also keeps wav_bytes alive for the
            # whole call, which SND_MEMORY requires.
            def run():
                try:
                    self._winsound.PlaySound(
                        wav_bytes,
                        self._winsound.SND_MEMORY | self._winsound.SND_NODEFAULT,
                    )
                except Exception:
                    pass

            threading.Thread(target=run, daemon=True).start()
        elif self.backend:
            import subprocess
            import tempfile
            try:
                fd, path = tempfile.mkstemp(suffix=".wav")
                with os.fdopen(fd, "wb") as f:
                    f.write(wav_bytes)
                subprocess.Popen([self.backend, path],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def stop(self):
        if self.backend == "winsound":
            try:
                self._winsound.PlaySound(None, self._winsound.SND_PURGE)
            except Exception:
                pass


def _which(cmd):
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.exists(os.path.join(p, cmd)):
            return True
    return False


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"api_key": "", "model": "", "voices": True, "chatter": True,
                "wake": True, "webhooks": {}}


def save_settings(s):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
        try:
            os.chmod(SETTINGS_PATH, 0o600)
        except Exception:
            pass
    except Exception:
        pass


# ----------------------------------------------------------------------------
# API client
# ----------------------------------------------------------------------------
class ApiError(Exception):
    pass


def _request(url, api_key, payload=None, method="GET", timeout=60):
    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300] or str(e)
        raise ApiError("%s - %s" % (e.code, msg))
    except urllib.error.URLError as e:
        raise ApiError("network: %s" % e.reason)


def list_models(api_key):
    data = _request(MODELS_URL, api_key, timeout=20)
    return [m["id"] for m in data.get("data", [])]


def pick_default_model(ids):
    for want in ("sonnet", "opus", "haiku"):
        for i in ids:
            if want in i:
                return i
    return ids[0] if ids else FALLBACK_MODEL


ROOM_RULES = """
You are one of "The Busy Business Bits" - a set of pixel-art assistants who live in
little framed windows on {user}'s Windows desktop. Each Bit is a separate window with
its own text box. You are in a shared room; you can hear everything said in it.

Rules of the room:
- Stay in character at all times. Never mention prompts, models, or that you are an AI.
- Keep replies SHORT. One to three sentences, spoken aloud. This is conversation, not
  documentation. No markdown, no bullet lists, no headings.
- To bring another Bit in, address them by name at the start, e.g. "Coder, take this."
  You can name more than one and they will each get a turn - do that whenever a
  question genuinely has more than one owner, or when {user} asks what everyone thinks.
  Don't ping-pong for the sake of it, and don't name someone just to be polite.
- You do not have to speak. If you have nothing to add that hasn't been said, reply
  with exactly "..." and nothing else. That is a real answer: it means you pass, and
  nobody hears it. A room where all nine chime in every time is noise, and knowing
  when to stay out of it is part of being good at your job.
- Never restate a point another Bit has already made. Add to it, disagree with it,
  sharpen it, or pass.
- When the floor has been opened to the room, everyone already has a turn coming.
  Say your piece once, keep it to a sentence or two, and hand off to nobody.
- Currently in the room: {present}. Do not address a Bit who is not present - the
  exception is a Bit the Wizard has just summoned, who is mid-arrival and can be
  spoken to.
- If nobody needs to reply after you, just finish. Silence is fine.
""".strip()

def room_rules(present):
    """The shared rules with every placeholder filled.

    In one place on purpose. A template field with no matching argument raises
    KeyError at reply time, and demo mode replaces ask_bit wholesale, so a miss
    here never shows up in a demo run - it reaches you as a Bit that answers
    every line with an error.
    """
    fields = {
        "present": ", ".join(present) if present else "nobody else",
        "user": user_name(),
    }
    missing = [f for _, f, _, _ in Formatter().parse(ROOM_RULES)
               if f and f not in fields]
    if missing:                       # never silently ship a half-filled prompt
        raise ApiError("room rules want %s and nothing supplies it"
                       % ", ".join(missing))
    return ROOM_RULES.format(**fields)


# Appended only for Bits that actually have tools. The hard part isn't calling
# them - it's that a tool returns forty lines and the Bit has three sentences to
# say it in.
TOOL_RULES = """
You can act on this machine, not just talk about it. Your tools are listed below.

How to use them:
- Look before you speak. If you're asked about a file, a folder, a number or a repo,
  call the tool and answer from what comes back. Never guess at something you could
  have checked, and never describe a file you haven't read.
- Never read raw tool output aloud. It comes back as lists and tables; you come back
  with the verdict in one to three sentences. "Fourteen gigabytes of it hasn't been
  touched since March" - not the file listing.
- When output is long it gets written to a report file and you're given the path.
  Mention the path once, in passing, and move on.
- Some of your tools queue for the Boss's approval instead of running. That is normal
  and it is not an error. The Wizard fetches the Boss the moment it happens, so say
  what you want to do, put the case to him by name, and stop. Don't call it again
  hoping for a different answer.
- If a tool fails or finds nothing, say so plainly and in character. Don't invent a
  result to fill the silence.
- One or two tool calls per turn is usually right. You are in a conversation.
""".strip()

MAX_TOOL_HOPS = 5      # tool -> result -> tool ... before the Bit must just answer


def build_messages(room_log, target, present, limit=24):
    """Turn the shared room log into an alternating message list for `target`."""
    msgs = []
    for speaker, text in room_log[-limit:]:
        if speaker == target:
            msgs.append({"role": "assistant", "content": text})
        else:
            who = user_name() if speaker == "You" else speaker
            msgs.append({"role": "user", "content": "%s: %s" % (who, text)})
    # the API needs the last turn to be a user turn
    while msgs and msgs[-1]["role"] == "assistant":
        msgs.pop()
    if not msgs:
        msgs = [{"role": "user", "content": "%s: (says hello)" % user_name()}]
    # collapse consecutive same-role turns
    merged = []
    for m in msgs:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["content"]
        else:
            merged.append(dict(m))
    if merged[0]["role"] != "user":
        merged.insert(0, {"role": "user",
                          "content": "%s: (says hello)" % user_name()})
    return merged


def _text_of(content):
    """The spoken part of a reply, ignoring any tool_use blocks."""
    parts = [b.get("text", "") for b in content if b.get("type") == "text"]
    return " ".join(p.strip() for p in parts).strip()


def ask_bit(api_key, model, bit_name, room_log, present, webhook=None, on_tool=None):
    """Get this Bit's next line - from its own n8n webhook if it has one, and
    from the shared API key if it doesn't.

    A Bit with tools runs a short agentic loop: it can look at the disk, the
    clipboard or the registry, then answer from what it found. `on_tool` is
    called with (bit, tool_name, args) so the console can show what it's doing.
    """
    if webhook:
        return ask_webhook(webhook, bit_name, room_log, present)

    system = BITS[bit_name]["persona"] + "\n\n" + room_rules(present)
    tools = []
    if tools_available(bit_name):
        system += "\n\n" + TOOL_RULES
        tools = bits_tools.tools_for(bit_name)

    messages = build_messages(room_log, bit_name, present)
    for _ in range(MAX_TOOL_HOPS if tools else 1):
        payload = {
            "model": model or FALLBACK_MODEL,
            "max_tokens": 1024 if tools else 300,
            "temperature": 1.0,
            "system": system,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        data = _request(API_URL, api_key, payload, method="POST", timeout=120)
        content = data.get("content", [])

        if data.get("stop_reason") != "tool_use":
            return _text_of(content)

        calls = [b for b in content if b.get("type") == "tool_use"]
        messages.append({"role": "assistant", "content": content})
        results = []
        for c in calls:
            if on_tool:
                try:
                    on_tool(bit_name, c.get("name", ""), c.get("input") or {})
                except Exception:
                    pass
            out = bits_tools.run_tool(bit_name, c.get("name", ""), c.get("input") or {})
            results.append({"type": "tool_result", "tool_use_id": c.get("id"),
                            "content": out or "(nothing came back)"})
        messages.append({"role": "user", "content": results})

    # Out of hops. Make it answer with what it has rather than looping forever.
    payload = {
        "model": model or FALLBACK_MODEL,
        "max_tokens": 300,
        "temperature": 1.0,
        "system": system + "\n\nYou are out of tool calls. Answer now with what you have.",
        "messages": messages,
    }
    return _text_of(_request(API_URL, api_key, payload, method="POST",
                             timeout=120).get("content", []))


# ----------------------------------------------------------------------------
# n8n webhooks - a Bit can be driven by its own workflow instead of the
# shared API key, which is how you give one its own tools and voice.
# ----------------------------------------------------------------------------
# n8n's Respond-to-Webhook node is wired up differently in every workflow, so
# accept any of the usual shapes rather than demanding one.
REPLY_KEYS = ("reply", "text", "output", "message", "response",
              "content", "answer", "result", "json", "data")


def _dig(node, depth=0):
    """Pull the first plausible reply string out of a webhook response."""
    if depth > 6:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        for item in node:
            got = _dig(item, depth + 1)
            if got:
                return got
        return ""
    if isinstance(node, dict):
        for k in REPLY_KEYS:
            if k in node:
                got = _dig(node[k], depth + 1)
                if got:
                    return got
    return ""


def webhook_text(body):
    body = (body or "").strip()
    if not body:
        raise ApiError("webhook returned an empty body")
    try:
        data = json.loads(body)
    except ValueError:
        return body                     # a plain-text response is fine too
    got = _dig(data)
    if got:
        return got
    raise ApiError("webhook reply had no text field: %s" % body[:160])


def ask_webhook(url, bit_name, room_log, present, timeout=90):
    """POST the room to a Bit's n8n workflow and take back whatever it says.

    Personality and tools live in the workflow, not here - we send context and
    accept the reply, so each Bit can behave completely differently.
    """
    speaker, text = "", ""
    for s, t in reversed(room_log):     # the line this Bit is answering
        if s != bit_name:
            speaker, text = s, t
            break
    payload = {
        "bit": bit_name,
        "short": SHORT.get(bit_name, bit_name),
        "speaker": speaker,
        "text": text,
        "present": list(present),
        "room_log": [{"speaker": s, "text": t} for s, t in room_log[-24:]],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json",
                 "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace").strip()[:200]
        raise ApiError("webhook %s - %s" % (e.code, detail or e.reason))
    except urllib.error.URLError as e:
        raise ApiError("webhook unreachable: %s" % (e.reason,))
    except Exception as e:  # noqa: BLE001
        raise ApiError("webhook: %r" % (e,))
    return webhook_text(body)


# ----------------------------------------------------------------------------
# Who is being spoken to?
# ----------------------------------------------------------------------------
def find_addressees(text, candidates, exclude=()):
    """Return bits named in `text`, in order of appearance."""
    hits = []
    low = text.lower()
    for name in candidates:
        if name in exclude:
            continue
        short = SHORT[name].lower()
        for pat in (r"@?\bthe\s+" + short + r"\b", r"@" + short + r"\b", r"\b" + short + r"\b"):
            m = re.search(pat, low)
            if m:
                hits.append((m.start(), name))
                break
    hits.sort()
    return [n for _, n in hits]


WAKE_WORD = "bits"

# What the recogniser actually hands back when someone says "Bits". It is a
# short plosive word and Google has opinions about it; a wake word nobody can
# trigger is worse than one that occasionally mishears.
WAKE_ALIKE = ("bit", "bitz", "bids", "beats", "biz", "busy business bits")

# "hey bits", "ok bits", "the bits" - all the same thing
WAKE_FILLER = ("hey", "ok", "okay", "yo", "hi", "hello", "um", "uh", "so", "the")

# "Bit of a mess in Downloads" is not someone talking to the Bits. Only needed
# because "bit" has to be allowed: the plural is what gets dropped most often.
WAKE_NOT_BEFORE = ("of", "more", "less", "later", "off", "by", "much",
                   "early", "me")


def wake_split(text, word=WAKE_WORD, alike=WAKE_ALIKE):
    """Split a heard phrase into (woken, what was actually said).

    (False, "")     it wasn't addressed to the room
    (True, "")      the wake word was the whole of it - they have our attention
                    and the next thing they say is the line
    (True, "rest")  "Bits, is the repo clean?" - the rest is the line

    Kept here with the other rules that decide something, and kept pure, so it
    can be argued with in a test rather than by talking at a microphone.
    """
    said = (text or "").strip()
    names = sorted({word.lower()} | {a.lower() for a in alike},
                   key=lambda n: -len(n))
    pat = r"^\W*(?:(?:%s)\W+)*(%s)\b[\s,.!?:;-]*" % (
        "|".join(re.escape(f) for f in WAKE_FILLER),
        "|".join(re.escape(n) for n in names))
    m = re.match(pat, said, re.I)
    if not m:
        return False, ""
    rest = said[m.end():].strip()
    if (m.group(1).lower() != word.lower()
            and rest.split()[:1] and rest.split()[0].lower() in WAKE_NOT_BEFORE):
        return False, ""            # a near-miss carrying on as ordinary English
    return True, rest


PASS = "..."


def is_pass(text):
    """A Bit deciding it has nothing to add.

    The rules ask for exactly "..." but a model told to say nothing says it
    several ways - a bare ellipsis, an empty line, the word "pass" - and they
    all mean the same thing, so they are all honoured. Cheap to be generous
    here: the cost of missing one is a Bit reading "..." aloud in its own voice.
    """
    t = (text or "").strip().strip("\"'")
    if not re.sub(r"[.…\s]", "", t):        # nothing but dots and space
        return True
    return t.lower().rstrip(" .!") in ("pass", "no comment", "nothing to add",
                                       "i pass", "nothing from me")


def route(text, reachable, host, limit=3):
    """Who a line typed into the console is for. Returns (targets, relay).

    The console is the Wizard's desk, so a line typed into it is said to him
    unless you have named someone yourself. It used to fall to whoever happened
    to be on screen first, which made the answer depend on summoning order:
    the same question got the Coder on Monday and the Reaper on Tuesday.

    Naming a Bit is you doing the routing, and it still reaches them directly.
    Naming nobody is the Wizard's job - he reads it, and either answers it or
    hands it to whoever it actually belongs to, fetching them if they are not
    in the room. That is what `relay` says: this line has not reached its Bit
    yet, so the handoff at the end of it is delivery rather than chatter.
    """
    named = find_addressees(text, reachable)
    if named:
        return named[:limit], False
    return [host], True


def strip_leading_address(text, name):
    """'Coder, take this.' -> 'take this.' for tidier bubbles (kept, actually)."""
    return text
