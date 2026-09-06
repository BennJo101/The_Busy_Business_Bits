"""
The Busy Business Bits - the ambient layer.

Tools let a Bit answer when spoken to. This is what lets one speak first.

Each watcher owns a cheap check and belongs to exactly one Bit, the same way a
tool does. A watcher returns a Nudge when something has actually changed, and
nothing at all the rest of the time - which is almost always. The hard part is
not noticing things; it's staying quiet, because a character that comments on
everything gets muted within a day.

Four rules hold the whole layer together:

1.  Only summoned Bits speak. If the Coder isn't on screen he doesn't interrupt.
2.  Nothing fires twice. Every nudge carries a key, and a key is only ever
    used once - persisted, so it survives a restart.
3.  One voice at a time. A global cooldown means two watchers going off together
    still produce one line, not a pile-up.
4.  Quiet by default on first run. A watcher's first poll records the world as
    it is rather than announcing all of it.
"""

import hashlib
import os
import re
import time
from datetime import datetime

import bits_tools as T

STATE = os.path.join(T.STATE_DIR, "ambient.json")

# Minimum gap between any two ambient lines, whichever Bit they come from. The
# room should feel occasionally alive, not chatty.
GLOBAL_COOLDOWN = 90


class Nudge:
    """One thing worth saying, and who says it."""

    def __init__(self, bit, text, key, tag=""):
        self.bit = bit          # which Bit speaks
        self.text = text        # the stage direction it reacts to
        self.key = key          # dedupe key; used once, ever
        self.tag = tag          # short label for the console


class Watcher:
    bit = ""
    interval = 60               # seconds between checks
    label = ""

    def __init__(self, store):
        self.store = store      # shared, persisted dict
        self.last = 0.0

    def due(self, now):
        return (now - self.last) >= self.interval

    def poll(self):             # -> Nudge | None
        raise NotImplementedError

    # -- small helpers for subclasses ---------------------------------------
    def mem(self, key, default=None):
        return self.store.setdefault("watchers", {}).setdefault(
            self.__class__.__name__, {}).get(key, default)

    def remember(self, key, value):
        self.store.setdefault("watchers", {}).setdefault(
            self.__class__.__name__, {})[key] = value


# ---------------------------------------------------------------------------
# The Coder - the clipboard. The smallest feature here and the most useful.
# ---------------------------------------------------------------------------
ERROR_SIGNS = (
    r"Traceback \(most recent call last\)",
    r"\b[A-Z]\w*(Error|Exception)\b\s*:",
    r'^\s*File ".+", line \d+',
    r"^\s+at [\w.$<>]+\(",                       # JS / Java stack frames
    r"\berror\b\s*(CS|TS|C)\d{2,}",              # compiler codes
    r"^\s*\w+\.\w+Exception\b",
    r"panic:|segmentation fault|core dumped",
    r"npm ERR!|fatal:|error\[E\d+\]",            # npm, git, rust
)
ERROR_RX = [re.compile(p, re.M | re.I) for p in ERROR_SIGNS]


class ClipboardWatcher(Watcher):
    """Fires when what you just copied looks like something that went wrong.

    Deliberately narrow. It ignores every ordinary copy - it has to, or the
    Coder would talk over you all day.
    """

    bit = "The Coder"
    interval = 3
    label = "clipboard"

    def poll(self):
        text = T.run_tool(self.bit, "read_clipboard", {})
        if not text or len(text) < 40 or text.startswith(("clipboard is empty",
                                                          "no clipboard access")):
            return None
        key = "clip:" + hashlib.md5(text.encode("utf-8", "replace")).hexdigest()
        if key == self.mem("last"):
            return None
        self.remember("last", key)
        if not any(rx.search(text) for rx in ERROR_RX):
            return None
        first = self._headline(text)
        return Nudge(
            self.bit,
            "You glance at what was just copied to the clipboard and it's an "
            "error:\n\n%s\n\nSay in one or two sentences what's actually wrong. "
            "Use your tools to check the file if it names one. Don't paste the "
            "error back." % text[:1800],
            key, tag="caught: %s" % first[:60])

    @staticmethod
    def _headline(text):
        for line in reversed(text.strip().splitlines()):
            if re.match(r"^\s*[A-Z]\w*(Error|Exception)\b", line):
                return line.strip()
        return text.strip().splitlines()[0][:60]


# ---------------------------------------------------------------------------
# The Courier - what just landed
# ---------------------------------------------------------------------------
class DownloadsWatcher(Watcher):
    bit = "The Courier"
    interval = 90
    label = "downloads"

    def poll(self):
        folder = T.DOWNLOADS
        if not os.path.isdir(folder):
            return None
        try:
            now_set = {e.name for e in os.scandir(folder)
                       if e.is_file() and not e.name.startswith(".")
                       and not e.name.endswith((".crdownload", ".part", ".tmp"))}
        except Exception:
            return None
        seen = set(self.mem("seen") or [])
        if not self.mem("seen"):
            self.remember("seen", sorted(now_set))     # first run: just look
            return None
        new = sorted(now_set - seen)
        if not new:
            if len(now_set) != len(seen):
                self.remember("seen", sorted(now_set))
            return None
        self.remember("seen", sorted(now_set))
        key = "dl:" + hashlib.md5("|".join(new).encode()).hexdigest()
        filed = [(n, T._classify(n)) for n in new]
        known = [n for n, d in filed if d]
        return Nudge(
            self.bit,
            "%d new file%s just landed in Downloads: %s. %s Offer to file them - "
            "one short sentence." % (
                len(new), "" if len(new) == 1 else "s", ", ".join(new[:5]),
                ("You have a filing rule for %d of them." % len(known)) if known
                else "None of them match a filing rule yet."),
            key, tag="%d new in Downloads" % len(new))


# ---------------------------------------------------------------------------
# The Secretary - time and commitments
# ---------------------------------------------------------------------------
class BriefWatcher(Watcher):
    """The morning brief, once a day, the first time you're actually at the desk."""

    bit = "The Secretary"
    interval = 120
    label = "brief"

    def poll(self):
        today = datetime.now().date().isoformat()
        if self.mem("last_brief") == today:
            return None
        if datetime.now().hour < 5:
            return None
        self.remember("last_brief", today)
        brief = T.run_tool(self.bit, "morning_brief", {})
        if "overdue: 0" in brief and "due today: 0" in brief:
            return None                                 # nothing worth saying
        return Nudge(
            self.bit,
            "It's the start of the day. Here is what's on the list:\n\n%s\n\n"
            "Give the shape of the day in one or two sentences. Lead with what's "
            "overdue if anything is." % brief,
            "brief:" + today, tag="morning brief")


class DueWatcher(Watcher):
    """Something falls due, or has gone past due, during the day."""

    bit = "The Secretary"
    interval = 900
    label = "due"

    def poll(self):
        listing = T.run_tool(self.bit, "tasks_list", {})
        hot = [l for l in listing.splitlines() if "OVERDUE" in l or "TODAY" in l]
        if not hot:
            return None
        key = "due:" + datetime.now().date().isoformat() + ":" + \
            hashlib.md5("|".join(hot).encode()).hexdigest()
        if key == self.mem("last"):
            return None
        self.remember("last", key)
        return Nudge(
            self.bit,
            "These are due now or already late:\n\n%s\n\nRemind him once, "
            "briefly, without nagging." % "\n".join(hot[:6]),
            key, tag="%d due or overdue" % len(hot))


# ---------------------------------------------------------------------------
# The Boss - things waiting on him
# ---------------------------------------------------------------------------
class ApprovalWatcher(Watcher):
    bit = "The Boss"
    interval = 60
    label = "approvals"

    def poll(self):
        pending = [i for i in T._approvals()["items"] if i["state"] == "pending"]
        if not pending:
            return None
        ids = ",".join(i["id"] for i in pending)
        key = "appr:" + ids
        if key == self.mem("last"):
            return None
        self.remember("last", key)
        return Nudge(
            self.bit,
            "%d action%s queued for your approval:\n\n%s\n\nSay what's waiting "
            "and ask whether to let it through. Do not approve anything yet." % (
                len(pending), "" if len(pending) == 1 else "s",
                "\n".join("%s  %s wants %s" % (i["id"], i["bit"], i["summary"])
                          for i in pending[:5])),
            key, tag="%d awaiting approval" % len(pending))


# ---------------------------------------------------------------------------
# The Coder - work left sitting
# ---------------------------------------------------------------------------
class RepoWatcher(Watcher):
    bit = "The Coder"
    interval = 3600
    label = "repo"

    def poll(self):
        out = T.run_tool(self.bit, "repo_health", {})
        if "SYNTAX ERROR" not in out and "uncommitted" not in out:
            return None
        stale = re.search(r"oldest change .*?\((\d+) days\)", out)
        broken = "SYNTAX ERROR" in out
        if not broken and (not stale or int(stale.group(1)) < 2):
            return None                                  # today's work is fine
        key = "repo:" + hashlib.md5(out.encode()).hexdigest()
        if key == self.mem("last"):
            return None
        self.remember("last", key)
        return Nudge(
            self.bit,
            "The project you're watching:\n\n%s\n\nSay the one thing that most "
            "needs doing about it, in a sentence." % out[:900],
            key, tag="broken build" if broken else "uncommitted work")


# ---------------------------------------------------------------------------
# The Ghost - one abandoned thing, occasionally, never twice
# ---------------------------------------------------------------------------
class GhostWatcher(Watcher):
    bit = "The Ghost"
    interval = 2700
    label = "haunt"

    def poll(self):
        out = T.run_tool(self.bit, "stale_scan", {"days": 60})
        lines = [l.strip() for l in out.splitlines()
                 if l.startswith("  ") and l.strip()]
        if not lines:
            return None
        pick = lines[0]
        key = "ghost:" + hashlib.md5(pick.encode()).hexdigest()
        if key == self.mem("last"):
            return None
        self.remember("last", key)
        return Nudge(
            self.bit,
            "One thing that stopped moving and was never finished:\n\n%s\n\n"
            "Bring it up softly. One sentence. Then mark it surfaced so you "
            "never raise it again." % pick,
            key, tag="a ghost stirs")


WATCHERS = [ClipboardWatcher, DownloadsWatcher, BriefWatcher, DueWatcher,
            ApprovalWatcher, RepoWatcher, GhostWatcher]


# ---------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------
class Ambient:
    """Polls the watchers and hands back at most one thing to say."""

    def __init__(self):
        self.store = T._load(STATE, {"fired": [], "watchers": {}})
        self.watchers = [w(self.store) for w in WATCHERS]
        self.last_nudge = 0.0
        self._dirty = False

    def fired(self, key):
        return key in set(self.store.get("fired") or [])

    def mark(self, key):
        f = self.store.setdefault("fired", [])
        f.append(key)
        del f[:-500]                       # keep the tail, forget ancient keys
        self.save()

    def save(self):
        T._save(STATE, self.store)
        self._dirty = False

    def poll(self, present):
        """Return a Nudge for a summoned Bit, or None. Cheap enough to call
        every few seconds - most watchers aren't due and return immediately."""
        now = time.time()
        if now - self.last_nudge < GLOBAL_COOLDOWN:
            return None
        out = None
        for w in self.watchers:
            if w.bit not in present or not w.due(now):
                continue
            w.last = now
            self._dirty = True
            try:
                n = w.poll()
            except Exception:                                 # noqa: BLE001
                continue                     # a watcher must never take the app down
            if n and not self.fired(n.key):
                out = n
                break
        if out:
            self.mark(out.key)
            self.last_nudge = now
        elif self._dirty:
            self.save()
        return out

    def status(self):
        now = time.time()
        return "\n".join(
            "%-18s %-14s every %5ds  next in %5ds"
            % (w.bit, w.label, w.interval, max(0, w.interval - (now - w.last)))
            for w in self.watchers)


if __name__ == "__main__":
    a = Ambient()
    print(a.status())
    print("\npolling once with everyone present...\n")
    n = a.poll([w.bit for w in a.watchers])
    print("%s -> %s" % (n.bit, n.tag) if n else "nothing to say (correct most of the time)")
