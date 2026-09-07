"""
The Busy Business Bits - the operational layer.

This is what turns the Bits from a room of talking sprites into nine things that
actually do work on the machine. Every tool here is real: it touches the disk,
the registry, the clipboard, the network or the task file.

Design rules, in order of importance:

1.  One Bit, one verb. A tool belongs to exactly the Bit whose verb it is. If two
    Bits could own it, it's split wrong. `BITS_TOOLS` at the bottom is the map.
2.  Nothing destructive, outbound or executable happens unattended. Those tiers
    don't run when called - they queue an approval that the Boss (and you) must
    clear. See the Gate.
3.  Stdlib only. No new dependencies on top of Pillow. Where a nicety would need
    a package (xlsx, pdf), there's a minimal reader here instead, and it says so
    honestly when it can't cope.
4.  Tool results are read aloud by a character in one to three sentences, so they
    come back SHORT. Anything long is written to a report file and the Bit is
    handed the path.
"""

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from datetime import datetime, timedelta

WINDOWS = sys.platform.startswith("win")


def _user_name():
    """What the Bits call the person they work for. Read from the same settings
    file the app uses, so nothing personal is baked into the source."""
    try:
        with open(os.path.join(os.path.expanduser("~"),
                               ".busy_business_bits.json"), encoding="utf-8") as f:
            n = (json.load(f).get("user_name") or "").strip()
        if n:
            return n
    except Exception:
        pass
    return os.environ.get("BITS_USER", "").strip() or "the boss"


USER = _user_name()

# ----------------------------------------------------------------------------
# Where things live
#
# State sits outside the vault, next to the settings file, for the same reason
# the API key does - it should never ride along with an Obsidian sync. Reports
# are the exception: they're useful notes, so they land in the project.
# ----------------------------------------------------------------------------
HOME = os.path.expanduser("~")
# State follows the settings: BITS_HOME moves both, so the portable copy keeps
# its tasks, index and approvals on the card. HOME itself stays the real one -
# the Reaper audits the machine you are actually sitting at.
STATE_DIR = os.path.join((os.environ.get("BITS_HOME") or "").strip() or HOME,
                         ".busy_business_bits")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
def _vault_root():
    """Where the Bits keep their notes.

    Normally the Obsidian vault this project sits inside. But the desk unit
    carries a vault of its own on its SD card, and a board taken to another
    machine should bring the Bits' notes with it - so a setting or an
    environment variable can point them at that one instead.
    """
    got = os.environ.get("BITS_VAULT", "").strip()
    if not got:
        try:
            with open(os.path.join(HOME, ".busy_business_bits.json"),
                      encoding="utf-8") as f:
                got = (json.load(f).get("vault") or "").strip()
        except Exception:                                         # noqa: BLE001
            got = ""
    return got if got and os.path.isdir(got) else os.path.dirname(PROJECT_ROOT)


VAULT_ROOT = _vault_root()

# A Bit that finds forty things writes them to a file and says the verdict out
# loud. Those land in the vault when the Bits have one of their own - the desk
# unit's card carries a vault with a Reports folder in it - and beside the
# project when they don't.
REPORTS_DIR = (os.path.join(VAULT_ROOT, "Reports")
               if os.path.isdir(os.path.join(VAULT_ROOT, "Reports"))
               else os.path.join(PROJECT_ROOT, "Bit Reports"))
DOWNLOADS = os.path.join(HOME, "Downloads")
DESKTOP = os.path.join(HOME, "Desktop")

TASKS_PATH = os.path.join(STATE_DIR, "tasks.json")
INDEX_PATH = os.path.join(STATE_DIR, "index.json")
GHOST_PATH = os.path.join(STATE_DIR, "ghosts.json")
APPROVALS_PATH = os.path.join(STATE_DIR, "approvals.json")
METRICS_PATH = os.path.join(STATE_DIR, "metrics.json")
SEEN_PATH = os.path.join(STATE_DIR, "seen.json")
FILINGS_PATH = os.path.join(STATE_DIR, "filings.json")
SCOPES_PATH = os.path.join(STATE_DIR, "scopes.json")

MAX_RESULT = 3000          # tool output ceiling; longer goes to a report file


def _ensure_dirs():
    for d in (STATE_DIR, REPORTS_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default() if callable(default) else default


def _save(path, obj):
    _ensure_dirs()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _ago(ts):
    """Human 'how long since', from an iso string or epoch float."""
    try:
        t = datetime.fromtimestamp(ts) if isinstance(ts, (int, float)) \
            else datetime.fromisoformat(ts)
    except Exception:
        return "?"
    d = (datetime.now() - t).days
    if d < 1:
        return "today"
    if d == 1:
        return "yesterday"
    if d < 30:
        return "%dd" % d
    if d < 365:
        return "%dmo" % (d // 30)
    return "%.1fy" % (d / 365.0)


def _size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.0f%s" % (n, unit) if unit == "B" else "%.1f%s" % (n, unit)
        n /= 1024.0


def report(title, body, bit=""):
    """Park long output in a file and hand back a one-line pointer.

    A Bit speaks in three sentences; a disk audit is four hundred lines. This is
    how the two coexist - the Bit gets the headline and the path, you get the
    detail when you want it.
    """
    _ensure_dirs()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    name = "%s-%s.md" % (datetime.now().strftime("%Y%m%d-%H%M"), slug)
    path = os.path.join(REPORTS_DIR, name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# %s\n\n*%s%s*\n\n%s\n" % (
                title, _now(), (" - " + bit) if bit else "", body))
        return path
    except Exception:
        return ""


def _clip(text, limit=MAX_RESULT, title="output", bit=""):
    """Keep a tool result speakable; overflow becomes a report."""
    if len(text) <= limit:
        return text
    path = report(title, text, bit)
    head = text[:limit].rsplit("\n", 1)[0]
    if path:
        return head + "\n\n[...truncated. Full report: %s]" % path
    return head + "\n\n[...truncated]"


def _run(cmd, timeout=25, shell=False):
    """Run a command quietly. Returns (rc, output)."""
    flags = 0x08000000 if WINDOWS else 0        # CREATE_NO_WINDOW
    try:
        p = subprocess.run(
            cmd, shell=shell, timeout=timeout, creationflags=flags,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -1, "timed out after %ds" % timeout
    except Exception as e:
        return -1, repr(e)


def _ps(script, timeout=25):
    """Run a PowerShell snippet. The only sane way at Windows internals."""
    if not WINDOWS:
        return -1, "not Windows"
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=timeout)


# ----------------------------------------------------------------------------
# The clipboard, without a process per look.
#
# The Coder's watcher checks the clipboard every three seconds, and it used to
# do it by starting a PowerShell - twelve hundred process launches an hour on a
# machine whose whole job is to sit quietly in the corner. The clipboard is a
# pair of calls in user32, so make them.
#
# GetClipboardSequenceNumber is the cheap half: it changes only when somebody
# copies something, so the usual answer costs one call and no clipboard lock at
# all. Opening the clipboard is the expensive and rude half - it can fail
# outright, because whichever application copied last may still be holding it.
# ----------------------------------------------------------------------------
CF_UNICODETEXT = 13
_clip_last = [None, None]        # sequence number, and the text it went with


def _clip_seq():
    if not WINDOWS:
        return None
    try:
        import ctypes
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:             # noqa: BLE001
        return None


def _clip_text():
    """Whatever text is on the clipboard, or None. Never raises."""
    if not WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.OpenClipboard.argtypes = [wintypes.HWND]
        u32.GetClipboardData.restype = wintypes.HANDLE
        k32.GlobalLock.argtypes = [wintypes.HANDLE]
        k32.GlobalLock.restype = ctypes.c_void_p
        # Without this the handle is passed as a C int, and a 64-bit handle
        # does not fit one: "int too long to convert", raised on the way out
        # of a read that had already worked.
        k32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        # the owner may still have it; a few tries over a fifth of a second is
        # long enough to be polite and short enough not to stall the watcher
        for _ in range(5):
            if u32.OpenClipboard(None):
                break
            time.sleep(0.04)
        else:
            return None
        try:
            handle = u32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""                      # something is on it, not text
            p = k32.GlobalLock(handle)
            if not p:
                return None
            try:
                return ctypes.wstring_at(p)
            finally:
                k32.GlobalUnlock(handle)
        finally:
            u32.CloseClipboard()
    except Exception:             # noqa: BLE001
        return None


# ----------------------------------------------------------------------------
# Scope - "any device I place them on"
#
# A Bit's working folder is set by where you put it. Drop the Reaper on a folder
# window and the audit is about that folder. Until then, each has a sane default.
# ----------------------------------------------------------------------------
DEFAULT_SCOPE = {
    "The Coder": PROJECT_ROOT,
    "The Courier": DOWNLOADS,
    "The Librarian": VAULT_ROOT,
    "The Reaper": HOME,
    "The Ghost": VAULT_ROOT,
    "The Investigator": PROJECT_ROOT,
    "The Secretary": VAULT_ROOT,
    "The Boss": PROJECT_ROOT,
    "The Wizard": PROJECT_ROOT,
}


def scope_of(bit):
    s = _load(SCOPES_PATH, {})
    p = s.get(bit) or DEFAULT_SCOPE.get(bit) or PROJECT_ROOT
    return p if os.path.isdir(p) else PROJECT_ROOT


def set_scope(bit, path):
    if not os.path.isdir(path):
        return False
    s = _load(SCOPES_PATH, {})
    s[bit] = os.path.abspath(path)
    _save(SCOPES_PATH, s)
    return True


def _resolve(bit, path):
    """Interpret a path argument against the Bit's scope."""
    if not path:
        return scope_of(bit)
    path = os.path.expanduser(path.strip().strip('"'))
    if not os.path.isabs(path):
        path = os.path.join(scope_of(bit), path)
    return os.path.abspath(path)


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".obsidian",
             "AppData", "$RECYCLE.BIN", "System Volume Information", ".cache"}


def _walk(root, max_files=20000, skip_hidden=True):
    """Walk a tree without falling down the usual holes."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not (skip_hidden and d.startswith("."))]
        for fn in filenames:
            if skip_hidden and fn.startswith("."):
                continue
            yield os.path.join(dirpath, fn)
            n += 1
            if n >= max_files:
                return


# ----------------------------------------------------------------------------
# Tiers and the Gate
#
# The Boss holds the license, so the Boss holds the gate. Anything that destroys,
# sends or executes doesn't run when the Bit calls it - it queues here, and it
# stays queued until it's approved. That is the whole reason it's safe to leave
# these characters running on their own all day.
# ----------------------------------------------------------------------------
READ, WRITE, EXECUTE, SEND, DESTROY = "read", "write", "execute", "send", "destroy"
GATED = {EXECUTE, SEND, DESTROY}

# The app sets this so an approval fetches the Boss onto the screen instead of
# sitting in a file waiting to be noticed - a ruling can't happen off screen.
# Signature: fn(approval_dict) -> str, and what it returns is handed back to the
# Bit that queued it, so it knows he's coming and can put the case to him.
ON_APPROVAL_NEEDED = None


def _approvals():
    return _load(APPROVALS_PATH, {"seq": 0, "items": []})


def _put_approvals(a):
    _save(APPROVALS_PATH, a)


def request_approval(bit, tool_name, args, summary):
    a = _approvals()
    a["seq"] += 1
    item = {"id": "A%d" % a["seq"], "bit": bit, "tool": tool_name, "args": args,
            "summary": summary, "asked": _now(), "state": "pending"}
    a["items"].append(item)
    _put_approvals(a)
    note = ""
    if ON_APPROVAL_NEEDED:
        try:
            note = ON_APPROVAL_NEEDED(item) or ""
        except Exception:                                         # noqa: BLE001
            note = ""
    return item, note


def _find_approval(aid):
    a = _approvals()
    for it in a["items"]:
        if it["id"].lower() == str(aid).strip().lower():
            return a, it
    return a, None


# ----------------------------------------------------------------------------
# The registry
# ----------------------------------------------------------------------------
class Tool:
    def __init__(self, name, desc, props, required, tier, owner, fn):
        self.name, self.desc, self.props = name, desc, props
        self.required, self.tier, self.owner, self.fn = required, tier, owner, fn

    def schema(self):
        return {
            "name": self.name,
            "description": self.desc,
            "input_schema": {"type": "object", "properties": self.props,
                             "required": self.required},
        }


TOOLS = {}


def tool(name, desc, tier, owner, props=None, required=None):
    def deco(fn):
        TOOLS[name] = Tool(name, desc, props or {}, required or [], tier, owner, fn)
        return fn
    return deco


def _str(desc):
    return {"type": "string", "description": desc}


def _int(desc):
    return {"type": "integer", "description": desc}


def _bool(desc):
    return {"type": "boolean", "description": desc}


def tools_for(bit):
    """The tool schemas this Bit is allowed to call."""
    return [t.schema() for t in TOOLS.values() if t.owner == bit or t.owner == "*"]


def has_tools(bit):
    return any(t.owner == bit or t.owner == "*" for t in TOOLS.values())


def run_tool(bit, name, args):
    """Execute a tool for a Bit. Enforces ownership and the gate."""
    t = TOOLS.get(name)
    if t is None:
        return "no such tool: %s" % name
    if t.owner != "*" and t.owner != bit:
        return "that isn't your job - %s belongs to %s." % (name, t.owner)
    if t.tier in GATED and not args.get("_approved"):
        summary = _summarise_call(name, args)
        item, note = request_approval(bit, name, args, summary)
        return ("QUEUED FOR APPROVAL as %s: %s. Say it needs the Boss's nod "
                "before you can do it.%s"
                % (item["id"], summary, (" " + note) if note else ""))
    args = {k: v for k, v in args.items() if k != "_approved"}
    try:
        out = t.fn(bit, **args)
    except TypeError as e:
        return "bad arguments for %s: %s" % (name, e)
    except Exception as e:                                        # noqa: BLE001
        return "%s failed: %r" % (name, e)
    return _clip(str(out), title=name, bit=bit)


def _summarise_call(name, args):
    bits = ", ".join("%s=%s" % (k, str(v)[:60]) for k, v in args.items()
                     if not k.startswith("_"))
    return "%s(%s)" % (name, bits)


# ============================================================================
# SHARED - the small primitives every Bit needs to see the world
# ============================================================================
@tool("read_file", "Read a text file. Use before commenting on any file's contents.",
      READ, "*", {"path": _str("File path, absolute or relative to your scope."),
                  "max_lines": _int("Cap on lines returned. Default 300.")},
      ["path"])
def t_read_file(bit, path, max_lines=300):
    p = _resolve(bit, path)
    if not os.path.isfile(p):
        return "no file at %s" % p
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[:int(max_lines)]
    except Exception as e:
        return "can't read %s: %r" % (p, e)
    return "%s (%s)\n%s" % (p, _size(os.path.getsize(p)), "".join(lines))


@tool("list_dir", "List a folder: names, sizes, and when each was last touched.",
      READ, "*", {"path": _str("Folder path. Defaults to your scope.")}, [])
def t_list_dir(bit, path=""):
    p = _resolve(bit, path)
    if not os.path.isdir(p):
        return "no folder at %s" % p
    rows = []
    try:
        for e in sorted(os.scandir(p), key=lambda x: x.name.lower()):
            try:
                st = e.stat()
                rows.append("%-45s %8s  %s" % (
                    e.name[:45] + ("/" if e.is_dir() else ""),
                    "-" if e.is_dir() else _size(st.st_size), _ago(st.st_mtime)))
            except Exception:
                continue
    except Exception as e:
        return "can't list %s: %r" % (p, e)
    return "%s - %d entries\n%s" % (p, len(rows), "\n".join(rows))


@tool("find_files", "Find files by name pattern and/or text content, under a folder.",
      READ, "*", {"pattern": _str("Filename substring or glob-ish text, e.g. 'invoice'."),
                  "contains": _str("Optional text that must appear inside the file."),
                  "path": _str("Folder to search. Defaults to your scope.")},
      ["pattern"])
def t_find_files(bit, pattern, contains="", path=""):
    root = _resolve(bit, path)
    pat = pattern.lower().strip("*")
    hits = []
    for fp in _walk(root):
        if pat and pat not in os.path.basename(fp).lower():
            continue
        if contains:
            try:
                if os.path.getsize(fp) > 4_000_000:
                    continue
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    if contains.lower() not in f.read().lower():
                        continue
            except Exception:
                continue
        try:
            hits.append("%s  (%s, %s)" % (fp, _size(os.path.getsize(fp)),
                                          _ago(os.path.getmtime(fp))))
        except Exception:
            hits.append(fp)
        if len(hits) >= 60:
            break
    return "%d match(es) under %s\n%s" % (len(hits), root, "\n".join(hits)) \
        if hits else "nothing matching '%s' under %s" % (pattern, root)


@tool("set_my_scope", "Point yourself at a different folder. Your other tools then "
      "work on that folder until it's changed again.",
      WRITE, "*", {"path": _str("Folder to adopt as your working scope.")}, ["path"])
def t_set_scope(bit, path):
    p = _resolve(bit, path)
    return "scope is now %s" % p if set_scope(bit, p) else "no folder at %s" % p


# ============================================================================
# THE BOSS - measure. And the gate every other Bit passes through.
# ============================================================================
def _read_xlsx(path, max_rows=2000):
    """Minimal xlsx reader - a zip of XML, no openpyxl needed.

    Handles the common case: first sheet, shared strings, inline numbers. Enough
    to total a column of invoices, which is what it's actually for.
    """
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            shared = [re.sub(r"<[^>]+>", "", m)
                      for m in re.findall(r"<si>(.*?)</si>", xml, re.S)]
        sheets = [n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)]
        if not sheets:
            return []
        xml = z.read(sorted(sheets)[0]).decode("utf-8", "replace")
        rows = []
        for rm in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S)[:max_rows]:
            cells = []
            for cm in re.findall(r"<c([^>]*)>(.*?)</c>", rm, re.S):
                attrs, body = cm
                v = re.search(r"<v>(.*?)</v>", body, re.S)
                txt = v.group(1) if v else ""
                if 't="s"' in attrs and txt.isdigit() and int(txt) < len(shared):
                    txt = shared[int(txt)]
                elif 't="inlineStr"' in attrs:
                    txt = re.sub(r"<[^>]+>", "", body)
                cells.append(txt)
            rows.append(cells)
        return rows


def _read_table(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return _read_xlsx(path)
    if ext in (".csv", ".tsv", ".txt"):
        delim = "\t" if ext == ".tsv" else ","
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                delim = csv.Sniffer().sniff(sample, ",;\t|").delimiter
            except Exception:
                pass
            return [r for r in csv.reader(f, delimiter=delim)][:5000]
    return None


def _num(s):
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(s)))
    except Exception:
        return None


@tool("analyse_table", "Read a CSV or XLSX and work out what's in it: columns, row "
      "count, totals and averages for numeric columns, and the outliers.",
      READ, "The Boss", {"path": _str("Path to a .csv, .tsv or .xlsx file.")}, ["path"])
def t_analyse_table(bit, path):
    p = _resolve(bit, path)
    if not os.path.isfile(p):
        return "no file at %s" % p
    rows = _read_table(p)
    if not rows:
        return "%s isn't a table I can read (csv, tsv or xlsx)." % os.path.basename(p)
    header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    out = ["%s - %d columns, %d rows" % (os.path.basename(p), len(header), len(body))]
    for i, col in enumerate(header):
        vals = [_num(r[i]) for r in body if i < len(r)]
        vals = [v for v in vals if v is not None]
        if len(vals) < max(2, len(body) * 0.5):
            sample = {r[i] for r in body if i < len(r) and r[i].strip()}
            out.append("  %-22s text, %d distinct" % (col[:22], len(sample)))
            continue
        total, avg = sum(vals), sum(vals) / len(vals)
        hi, lo = max(vals), min(vals)
        spread = ""
        if len(vals) > 3:
            mean = avg
            sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            outliers = [v for v in vals if sd and abs(v - mean) > 2 * sd]
            if outliers:
                spread = "  outliers: %s" % ", ".join("%.2f" % o for o in outliers[:5])
        out.append("  %-22s total %.2f  avg %.2f  min %.2f  max %.2f%s"
                   % (col[:22], total, avg, lo, hi, spread))
    return "\n".join(out)


@tool("metrics_pulse", f"The numbers {USER} tracks, with the change since last time. "
      "Say nothing about the ones that barely moved.",
      READ, "The Boss", {}, [])
def t_pulse(bit):
    m = _load(METRICS_PATH, {"tracked": {}, "history": []})
    tracked = m.get("tracked") or {}
    if not tracked:
        return ("No metrics are being tracked yet. Ask what numbers matter, "
                "then record them with track_metric.")
    hist = m.get("history") or []
    prev = hist[-2] if len(hist) > 1 else {}
    lines = []
    for k, v in tracked.items():
        old = (prev.get("values") or {}).get(k)
        if old is None:
            lines.append("%s: %s (no prior reading)" % (k, v))
        else:
            d = _num(v) - _num(old) if _num(v) is not None and _num(old) is not None else None
            pct = (d / _num(old) * 100) if d is not None and _num(old) else None
            lines.append("%s: %s (%s%s)" % (
                k, v, ("+" if d and d > 0 else "") + ("%.2f" % d if d is not None else "?"),
                "" if pct is None else ", %+.1f%%" % pct))
    return "\n".join(lines)


@tool("track_metric", f"Record the current value of a number {USER} cares about. "
      "Building the history is what makes the pulse worth anything.",
      WRITE, "The Boss", {"name": _str("What the number is, e.g. 'monthly revenue'."),
                          "value": _str("The value now.")}, ["name", "value"])
def t_track(bit, name, value):
    m = _load(METRICS_PATH, {"tracked": {}, "history": []})
    m.setdefault("tracked", {})[name] = value
    m.setdefault("history", []).append({"at": _now(), "values": dict(m["tracked"])})
    m["history"] = m["history"][-200:]
    _save(METRICS_PATH, m)
    return "logged %s = %s" % (name, value)


@tool("pending_approvals", "Everything the other Bits are waiting on you to approve.",
      READ, "The Boss", {}, [])
def t_pending(bit):
    items = [i for i in _approvals()["items"] if i["state"] == "pending"]
    if not items:
        return "nothing waiting."
    return "\n".join("%s  %s wants: %s  (asked %s)"
                     % (i["id"], i["bit"], i["summary"], _ago(i["asked"]))
                     for i in items)


@tool("approve", f"Approve a queued action and let it run. Only do this when {USER} "
      "has actually said yes - you are the last thing between a Bit and the disk.",
      EXECUTE, "The Boss", {"id": _str("The approval id, e.g. A3.")}, ["id"])
def t_approve(bit, id):
    # The Boss rules on the gate when he is in the room; when he is not, it
    # goes to the desk unit's screen for a hand. Without this the Boss could
    # clear a gate he was not present for - a Bit asks, he agrees, and the work
    # runs with nobody having looked at it. Measured once at 178 files moved
    # eleven seconds after they were queued.
    here = present_bits()
    if here is not None and "The Boss" not in here:
        return ("the Boss isn't in the room. This one goes to the desk unit's "
                "screen for a hand - say so and stop, or ask the Wizard to "
                "summon him.")
    a, it = _find_approval(id)
    if not it:
        return "no approval called %s" % id
    if it["state"] != "pending":
        return "%s was already %s" % (id, it["state"])
    it["state"] = "approved"
    it["decided"] = _now()
    _put_approvals(a)
    args = dict(it["args"])
    args["_approved"] = True
    out = run_tool(it["bit"], it["tool"], args)
    it["result"] = out[:400]
    _put_approvals(a)
    return "approved %s. %s" % (id, out)


@tool("refuse", "Refuse a queued action. It doesn't run and the Bit is told why.",
      WRITE, "The Boss", {"id": _str("The approval id."),
                          "reason": _str("Why not.")}, ["id"])
def t_refuse(bit, id, reason=""):
    a, it = _find_approval(id)
    if not it:
        return "no approval called %s" % id
    it["state"] = "refused"
    it["reason"] = reason
    it["decided"] = _now()
    _put_approvals(a)
    return "refused %s%s" % (id, (" - " + reason) if reason else "")


# The Boss's approve tool is itself gated, which would deadlock. He is the gate,
# so his own two decisions run directly.
TOOLS["approve"].tier = WRITE


# ============================================================================
# THE CODER - build. The only Bit with a shell.
# ============================================================================
@tool("read_clipboard", f"Read what {USER} just copied. This is how you catch a "
      "traceback the moment it happens.",
      READ, "The Coder", {}, [])
def t_clipboard(bit):
    if WINDOWS:
        seq = _clip_seq()
        if seq is not None and seq == _clip_last[0]:
            text = _clip_last[1]               # nobody has copied since we looked
        else:
            text = _clip_text()
            if text is None:                   # someone else had it locked
                rc, out = _ps("Get-Clipboard -Raw", timeout=10)
                text = out if rc == 0 else ""
            elif seq is not None:
                _clip_last[0], _clip_last[1] = seq, text
        if text and text.strip():
            return text.strip()[:4000]
        return "clipboard is empty or not text."
    rc, out = _run(["xclip", "-o", "-selection", "clipboard"], timeout=10)
    return out.strip()[:4000] if rc == 0 else "no clipboard access on this platform."


@tool("git_status", "Branch, dirty files, staged work and how far ahead or behind "
      "the repo is.",
      READ, "The Coder", {"path": _str("Repo folder. Defaults to your scope.")}, [])
def t_git(bit, path=""):
    p = _resolve(bit, path)
    rc, out = _run(["git", "-C", p, "status", "--short", "--branch"], timeout=20)
    if rc != 0:
        return "not a git repo (or git missing): %s" % out.strip()[:200]
    rc2, log = _run(["git", "-C", p, "log", "-3", "--pretty=%h %ar  %s"], timeout=20)
    return "%s\n\nrecent:\n%s" % (out.strip(), log.strip())


@tool("check_python", "Syntax-check a Python file and report the first real error "
      "with its line number.",
      READ, "The Coder", {"path": _str("Path to a .py file.")}, ["path"])
def t_pycheck(bit, path):
    p = _resolve(bit, path)
    if not os.path.isfile(p):
        return "no file at %s" % p
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        compile(src, p, "exec")
    except SyntaxError as e:
        return "SyntaxError in %s line %s: %s\n    %s" % (
            os.path.basename(p), e.lineno, e.msg, (e.text or "").strip())
    except Exception as e:
        return "couldn't check: %r" % e
    n = len(src.splitlines())
    todo = len(re.findall(r"#\s*(TODO|FIXME|XXX)", src))
    return "%s parses clean. %d lines%s." % (
        os.path.basename(p), n, ", %d TODO/FIXME" % todo if todo else "")


@tool("repo_health", "What's unfinished here: uncommitted work and how long it's sat, "
      "plus anything that looks broken.",
      READ, "The Coder", {"path": _str("Repo or project folder.")}, [])
def t_health(bit, path=""):
    p = _resolve(bit, path)
    out = []
    rc, st = _run(["git", "-C", p, "status", "--porcelain"], timeout=20)
    if rc == 0:
        dirty = [l for l in st.splitlines() if l.strip()]
        if dirty:
            oldest, name = 0, ""
            for l in dirty:
                fp = os.path.join(p, l[3:].strip().strip('"'))
                try:
                    age = (time.time() - os.path.getmtime(fp)) / 86400
                    if age > oldest:
                        oldest, name = age, os.path.basename(fp)
                except Exception:
                    continue
            out.append("%d uncommitted file(s); oldest change %s (%.0f days) - %s"
                       % (len(dirty), name, oldest, name))
        else:
            out.append("working tree clean")
    for fp in _walk(p, max_files=4000):
        if fp.endswith(".py"):
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    compile(f.read(), fp, "exec")
            except SyntaxError as e:
                out.append("SYNTAX ERROR %s line %s: %s"
                           % (os.path.relpath(fp, p), e.lineno, e.msg))
            except Exception:
                pass
    return "\n".join(out) if out else "nothing to report."


@tool("run_shell", "Run a command. Queues for the Boss's approval first - always say "
      "what you're about to run before you call this.",
      EXECUTE, "The Coder", {"cmd": _str("The exact command line."),
                             "path": _str("Working folder. Defaults to your scope.")},
      ["cmd"])
def t_shell(bit, cmd, path=""):
    p = _resolve(bit, path)
    cwd = os.getcwd()
    try:
        os.chdir(p)
        rc, out = _run(cmd, timeout=90, shell=True)
    finally:
        try:
            os.chdir(cwd)
        except Exception:
            pass
    return "exit %d\n%s" % (rc, out.strip()[:2500] or "(no output)")


@tool("write_file", "Write or overwrite a file. Use for fixes and small tools you've "
      "already described. Queues for approval.",
      EXECUTE, "The Coder", {"path": _str("File to write."),
                             "content": _str("Full new contents.")},
      ["path", "content"])
def t_write(bit, path, content):
    p = _resolve(bit, path)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p):
            shutil.copy2(p, p + ".bak")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return "wrote %s (%d bytes)%s" % (
            p, len(content), ", previous kept as .bak" if os.path.exists(p + ".bak") else "")
    except Exception as e:
        return "couldn't write %s: %r" % (p, e)


# ============================================================================
# THE COURIER - move. The only Bit allowed off the machine.
# ============================================================================
FILING_RULES = [
    (r"invoice|receipt|billing|statement", "Invoices"),
    (r"contract|agreement|nda|terms|signed", "Contracts"),
    (r"quote|estimate|proposal|tender", "Quotes"),
    (r"\.(png|jpe?g|gif|webp|svg|bmp)$", "Images"),
    (r"\.(mp4|mov|avi|mkv|webm)$", "Video"),
    (r"\.(zip|7z|rar|tar|gz)$", "Archives"),
    (r"\.(exe|msi|dmg)$", "Installers"),
    (r"\.(pdf)$", "Documents"),
    (r"\.(docx?|odt|rtf|pages)$", "Documents"),
    (r"\.(xlsx?|csv|ods)$", "Spreadsheets"),
]


def _classify(name):
    low = name.lower()
    for pat, dest in FILING_RULES:
        if re.search(pat, low):
            return dest
    return ""


@tool("triage_downloads", "Look at what's landed in Downloads and work out where each "
      "thing belongs. Reports only - filing it needs approval.",
      READ, "The Courier", {"path": _str("Folder to triage. Defaults to Downloads."),
                            "days": _int("Only things touched in the last N days. 0 = all.")},
      [])
def t_triage(bit, path="", days=0):
    p = _resolve(bit, path or DOWNLOADS)
    if not os.path.isdir(p):
        return "no folder at %s" % p
    cutoff = time.time() - int(days) * 86400 if days else 0
    groups, unknown = {}, []
    for e in os.scandir(p):
        if e.is_dir() or e.name.startswith("."):
            continue
        try:
            st = e.stat()
        except Exception:
            continue
        if cutoff and st.st_mtime < cutoff:
            continue
        dest = _classify(e.name)
        row = "%s (%s, %s)" % (e.name, _size(st.st_size), _ago(st.st_mtime))
        if dest:
            groups.setdefault(dest, []).append(row)
        else:
            unknown.append(row)
    if not groups and not unknown:
        return "%s is clear." % p
    out = ["%s - %d filed by rule, %d unclassified"
           % (p, sum(len(v) for v in groups.values()), len(unknown))]
    for dest, rows in sorted(groups.items()):
        out.append("-> %s (%d): %s" % (dest, len(rows), "; ".join(rows[:6])))
    if unknown:
        out.append("-> no rule (%d): %s" % (len(unknown), "; ".join(unknown[:8])))
    return "\n".join(out)


@tool("file_by_rule", "Actually move what triage found into its folders. Queues for "
      "approval. Nothing is overwritten and nothing leaves the drive.",
      DESTROY, "The Courier",
      {"path": _str("Folder to file. Defaults to Downloads."),
       "into": _str("Parent folder for the destination folders. Defaults to the same folder.")},
      [])
def t_file_by_rule(bit, path="", into=""):
    p = _resolve(bit, path or DOWNLOADS)
    base = _resolve(bit, into) if into else p
    moved, skipped = [], 0
    # Every move is written down, in full, before anything is said about it.
    # The spoken answer is clipped and the approval record keeps only 400
    # characters of it - so without this there is no complete account of what
    # went where, and a filing run that shouldn't have happened cannot be
    # undone. That is not hypothetical: it has happened once.
    trail = []
    for e in list(os.scandir(p)):
        if e.is_dir() or e.name.startswith("."):
            continue
        dest = _classify(e.name)
        if not dest:
            skipped += 1
            continue
        d = os.path.join(base, dest)
        try:
            os.makedirs(d, exist_ok=True)
            target = os.path.join(d, e.name)
            if os.path.exists(target):
                stem, ext = os.path.splitext(e.name)
                target = os.path.join(d, "%s-%s%s" % (
                    stem, datetime.now().strftime("%Y%m%d"), ext))
            shutil.move(e.path, target)
            moved.append("%s -> %s" % (e.name, dest))
            trail.append([e.path, target])
        except Exception:
            skipped += 1
    if trail:
        runs = _load(FILINGS_PATH, {"runs": []})
        runs["runs"].append({"when": _now(), "from": p, "into": base,
                             "moves": trail})
        del runs["runs"][:-20]              # the last twenty runs is plenty
        _save(FILINGS_PATH, runs)
    return "moved %d, left %d where they were.%s\n%s" % (
        len(moved), skipped,
        "  Say undo_filing to put them back." if trail else "",
        "\n".join(moved[:40]))


@tool("undo_filing", "Put back what a filing run moved. Use it the moment something "
      "was filed that shouldn't have been - it only ever returns a file to where it "
      "came from, which is the safe direction, so it needs no one's approval.",
      WRITE, "The Courier",
      {"which": _int("How many runs back. 1 is the last one, the default.")}, [])
def t_undo_filing(bit, which=1):
    runs = _load(FILINGS_PATH, {"runs": []}).get("runs") or []
    if not runs:
        return "nothing has been filed by rule on this machine yet."
    i = len(runs) - max(1, int(which or 1))
    if i < 0:
        return "only %d filing run(s) are on record." % len(runs)
    run = runs[i]
    back, missing = 0, 0
    for src, dst in run.get("moves", []):
        if not os.path.isfile(dst) or os.path.exists(src):
            missing += 1               # gone, or something is in its place now
            continue
        try:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(dst, src)
            back += 1
        except Exception:              # noqa: BLE001
            missing += 1
    run["undone"] = _now()
    _save(FILINGS_PATH, {"runs": runs})
    return ("put %d file(s) back where they were, from the run at %s.%s"
            % (back, run.get("when", "?"),
               ("  %d could not be moved - already gone, or something is there "
                "now." % missing) if missing else ""))


@tool("deliver_file", "Send a file somewhere: another folder, another drive, or a "
      "path on another machine. Queues for approval.",
      SEND, "The Courier", {"path": _str("The file to move."),
                            "to": _str("Destination folder or full path."),
                            "copy": _bool("Copy instead of move. Default true.")},
      ["path", "to"])
def t_deliver(bit, path, to, copy=True):
    src = _resolve(bit, path)
    if not os.path.isfile(src):
        return "no file at %s" % src
    dst = os.path.expanduser(to)
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        (shutil.copy2 if copy else shutil.move)(src, dst)
        return "%s %s -> %s" % ("copied" if copy else "moved", os.path.basename(src), dst)
    except Exception as e:
        return "couldn't deliver: %r" % e


@tool("draft_email", f"Write an email and save it as a .eml draft {USER} can open and "
      "send. Drafting is free; sending is not your call.",
      WRITE, "The Courier", {"to": _str("Recipient address."),
                             "subject": _str("Subject line."),
                             "body": _str("Full message body."),
                             "attach": _str("Optional path to attach - noted in the draft.")},
      ["to", "subject", "body"])
def t_draft_email(bit, to, subject, body, attach=""):
    _ensure_dirs()
    fn = os.path.join(REPORTS_DIR, "%s-%s.eml" % (
        datetime.now().strftime("%Y%m%d-%H%M"),
        re.sub(r"[^a-z0-9]+", "-", subject.lower())[:40]))
    note = "\n\n[attachment intended: %s]" % attach if attach else ""
    try:
        with open(fn, "w", encoding="utf-8") as f:
            f.write("To: %s\nSubject: %s\nX-Drafted-By: The Courier\n\n%s%s\n"
                    % (to, subject, body, note))
        return "draft saved: %s" % fn
    except Exception as e:
        return "couldn't save draft: %r" % e


@tool("open_path", f"Open a file or folder in Windows so {USER} can see it.",
      EXECUTE, "The Courier", {"path": _str("What to open.")}, ["path"])
def t_open(bit, path):
    p = _resolve(bit, path)
    if not os.path.exists(p):
        return "nothing at %s" % p
    try:
        if WINDOWS:
            os.startfile(p)                                       # noqa: S606
        else:
            _run(["xdg-open", p], timeout=10)
        return "opened %s" % p
    except Exception as e:
        return "couldn't open: %r" % e


# ============================================================================
# THE INVESTIGATOR - dig. Points outward.
# ============================================================================
def _strip_html(html):
    html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", html).strip()


@tool("fetch_url", "Pull a web page down and read it. This is how you check a claim "
      "instead of repeating it.",
      READ, "The Investigator", {"url": _str("Full http(s) URL.")}, ["url"])
def t_fetch(bit, url):
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    if USE_BOARD_NET:
        return _fetch_over_board(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (BusyBusinessBits/1.0 The Investigator)"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            ctype = r.headers.get("content-type", "")
            raw = r.read(600_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return "%s returned %s" % (url, e.code)
    except Exception as e:
        return "couldn't reach %s: %r" % (url, e)
    text = raw if "json" in ctype or "text/plain" in ctype else _strip_html(raw)
    title = ""
    m = re.search(r"(?is)<title>(.*?)</title>", raw)
    if m:
        title = _strip_html(m.group(1))
    return "%s\n%s\n\n%s" % (url, title, text[:4000])


def _fetch_over_board(url):
    """The same fetch, but done by the board on its own network."""
    got = _radio("get", timeout=60, url=url, limit=4000)
    if not got.get("ok"):
        return ("the Bits are set to use the desk unit's radio and %s. Either "
                "put the board on a network, or turn that setting off to use "
                "this computer's connection."
                % got.get("error", "it wouldn't answer"))
    page = got.get("out") or {}
    if not page.get("ok"):
        return "over the board: %s" % page.get("error", "it wouldn't fetch")
    text = page.get("text") or ""
    if "json" not in (page.get("type") or "") and "text/plain" not in (
            page.get("type") or ""):
        text = _strip_html(text)
    return "%s  (over the board's radio, HTTP %s)\n\n%s" % (
        page.get("url", url), page.get("status"), text[:4000])


@tool("read_pdf", "Extract what text can be got out of a PDF. Scanned pages come back "
      "empty - say so rather than guessing at them.",
      READ, "The Investigator", {"path": _str("Path to a .pdf.")}, ["path"])
def t_pdf(bit, path):
    p = _resolve(bit, path)
    if not os.path.isfile(p):
        return "no file at %s" % p
    try:
        raw = open(p, "rb").read()
    except Exception as e:
        return "can't read: %r" % e
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S):
        blob = m.group(1)
        try:
            blob = zlib.decompress(blob)
        except Exception:
            pass
        for tm in re.finditer(rb"\((?:\\.|[^\\()])*\)", blob):
            s = tm.group(0)[1:-1]
            try:
                chunks.append(s.decode("utf-8", "replace"))
            except Exception:
                continue
        if sum(len(c) for c in chunks) > 20000:
            break
    text = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    if len(text) < 40:
        return ("%s has no extractable text - it's probably scanned images."
                % os.path.basename(p))
    return "%s\n\n%s" % (os.path.basename(p), text[:4000])


@tool("search_logs", "Hunt a pattern through log or text files under a folder and show "
      "the matching lines with context.",
      READ, "The Investigator",
      {"pattern": _str("Regex or plain text to look for."),
       "path": _str("Folder to search. Defaults to your scope."),
       "ext": _str("Limit to an extension, e.g. '.log'. Optional.")},
      ["pattern"])
def t_logs(bit, pattern, path="", ext=""):
    root = _resolve(bit, path)
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)
    hits = []
    for fp in _walk(root, max_files=6000):
        if ext and not fp.lower().endswith(ext.lower()):
            continue
        if not ext and os.path.splitext(fp)[1].lower() not in (
                ".log", ".txt", ".md", ".json", ".csv", ".py", ".yml", ".yaml", ""):
            continue
        try:
            if os.path.getsize(fp) > 8_000_000:
                continue
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for n, line in enumerate(f, 1):
                    if rx.search(line):
                        hits.append("%s:%d  %s" % (os.path.relpath(fp, root), n,
                                                   line.strip()[:200]))
                        if len(hits) >= 50:
                            break
        except Exception:
            continue
        if len(hits) >= 50:
            break
    return "%d hit(s) for '%s'\n%s" % (len(hits), pattern, "\n".join(hits)) \
        if hits else "no sign of '%s' under %s" % (pattern, root)


@tool("dossier", "Everything already on this machine about a name, company or client - "
      "before you go looking outside for more.",
      READ, "The Investigator", {"subject": _str("Name, company or client to look up.")},
      ["subject"])
def t_dossier(bit, subject):
    found = []
    for root in (VAULT_ROOT, DOWNLOADS, DESKTOP):
        if not os.path.isdir(root):
            continue
        for fp in _walk(root, max_files=8000):
            base = os.path.basename(fp).lower()
            if subject.lower() in base:
                found.append("filename: %s (%s)" % (fp, _ago(os.path.getmtime(fp))))
                continue
            if os.path.splitext(fp)[1].lower() in (".md", ".txt", ".csv", ".json"):
                try:
                    if os.path.getsize(fp) > 2_000_000:
                        continue
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        body = f.read()
                    if subject.lower() in body.lower():
                        i = body.lower().find(subject.lower())
                        found.append("mention: %s ... %s ..."
                                     % (fp, body[max(0, i - 90):i + 130].replace("\n", " ")))
                except Exception:
                    continue
            if len(found) >= 40:
                break
    return "%d reference(s) to '%s'\n%s" % (len(found), subject, "\n".join(found)) \
        if found else "nothing on this machine mentions '%s'." % subject


# ============================================================================
# THE REAPER - cut. Proposes; never acts alone.
# ============================================================================
@tool("disk_audit", "What's taking the space and what hasn't been touched in months. "
      "Sorted by how little it would be missed.",
      READ, "The Reaper", {"path": _str("Folder to audit. Defaults to your scope."),
                           "min_mb": _int("Ignore anything under this many MB. Default 50."),
                           "stale_days": _int("Count as stale after N days. Default 180.")},
      [])
def t_disk(bit, path="", min_mb=50, stale_days=180):
    root = _resolve(bit, path)
    cutoff = time.time() - int(stale_days) * 86400
    big, stale, total = [], [], 0
    for fp in _walk(root, max_files=60000):
        try:
            st = os.stat(fp)
        except Exception:
            continue
        total += st.st_size
        if st.st_size >= int(min_mb) * 1024 * 1024:
            big.append((st.st_size, st.st_mtime, fp))
        if st.st_mtime < cutoff and st.st_size > 5 * 1024 * 1024:
            stale.append((st.st_size, st.st_mtime, fp))
    big.sort(reverse=True)
    stale.sort(reverse=True)
    dead_bytes = sum(s for s, _, _ in stale)
    out = ["%s holds %s" % (root, _size(total)),
           "",
           "biggest:"]
    out += ["  %8s  %-6s  %s" % (_size(s), _ago(m), os.path.relpath(f, root))
            for s, m, f in big[:15]]
    out += ["", "untouched %d+ days (%s in total, %d files):" % (
        stale_days, _size(dead_bytes), len(stale))]
    out += ["  %8s  %-6s  %s" % (_size(s), _ago(m), os.path.relpath(f, root))
            for s, m, f in stale[:20]]
    return "\n".join(out)


@tool("find_duplicates", "Identical files kept in more than one place, and what "
      "clearing them would give back.",
      READ, "The Reaper", {"path": _str("Folder to check. Defaults to your scope."),
                           "min_kb": _int("Ignore files under this size. Default 100.")},
      [])
def t_dupes(bit, path="", min_kb=100):
    root = _resolve(bit, path)
    by_size = {}
    for fp in _walk(root, max_files=40000):
        try:
            s = os.path.getsize(fp)
        except Exception:
            continue
        if s < int(min_kb) * 1024:
            continue
        by_size.setdefault(s, []).append(fp)
    groups, reclaim = [], 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for fp in paths:
            try:
                h = hashlib.md5()
                with open(fp, "rb") as f:
                    while chunk := f.read(1 << 20):
                        h.update(chunk)
                by_hash.setdefault(h.hexdigest(), []).append(fp)
            except Exception:
                continue
        for dupes in by_hash.values():
            if len(dupes) > 1:
                groups.append((size, dupes))
                reclaim += size * (len(dupes) - 1)
    groups.sort(reverse=True)
    if not groups:
        return "no duplicates over %dKB under %s." % (min_kb, root)
    out = ["%d duplicate set(s) under %s - %s to reclaim"
           % (len(groups), root, _size(reclaim))]
    for size, dupes in groups[:15]:
        out.append("  %s x%d:" % (_size(size), len(dupes)))
        out += ["      " + os.path.relpath(d, root) for d in dupes[:4]]
    return "\n".join(out)


@tool("startup_items", "What launches at boot and is costing you your morning.",
      READ, "The Reaper", {}, [])
def t_startup(bit):
    rows = []
    if WINDOWS:
        try:
            import winreg
            for hive, hname in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                                (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
                try:
                    k = winreg.OpenKey(
                        hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")
                except Exception:
                    continue
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(k, i)
                        rows.append("%s  %-28s %s" % (hname, name[:28], str(val)[:90]))
                        i += 1
                    except OSError:
                        break
        except Exception as e:
            rows.append("registry unreadable: %r" % e)
    folder = os.path.join(HOME, "AppData", "Roaming", "Microsoft", "Windows",
                          "Start Menu", "Programs", "Startup")
    if os.path.isdir(folder):
        for e in os.scandir(folder):
            if not e.name.lower().endswith(".ini"):
                rows.append("FOLDER  %s" % e.name)
    return "%d startup entr(ies)\n%s" % (len(rows), "\n".join(rows)) if rows \
        else "nothing set to launch at boot."


@tool("stale_apps", "Installed programs that look abandoned. It's a heuristic off "
      "install dates and folder activity - say so, don't state it as fact.",
      READ, "The Reaper", {"days": _int("Consider stale after N days. Default 180.")}, [])
def t_stale_apps(bit, days=180):
    if not WINDOWS:
        return "only implemented on Windows."
    rows = []
    try:
        import winreg
        keys = [(winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_CURRENT_USER,
                 r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        cutoff = time.time() - int(days) * 86400
        for hive, sub in keys:
            try:
                root = winreg.OpenKey(hive, sub)
            except Exception:
                continue
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    name = winreg.EnumKey(root, i)
                    k = winreg.OpenKey(root, name)

                    def val(v):
                        try:
                            return winreg.QueryValueEx(k, v)[0]
                        except Exception:
                            return ""
                    disp = val("DisplayName")
                    if not disp:
                        continue
                    loc = val("InstallLocation")
                    size = val("EstimatedSize") or 0
                    last = 0
                    if loc and os.path.isdir(loc):
                        try:
                            last = max((os.path.getmtime(os.path.join(loc, f))
                                        for f in os.listdir(loc)[:60]), default=0)
                        except Exception:
                            last = 0
                    if last and last < cutoff:
                        rows.append("%-40s  quiet since %s  ~%s"
                                    % (str(disp)[:40], _ago(last),
                                       _size(int(size) * 1024) if size else "?"))
                except Exception:
                    continue
    except Exception as e:
        return "couldn't read the registry: %r" % e
    rows.sort()
    return ("%d program(s) show no activity in %d+ days (heuristic - folder mtimes):\n%s"
            % (len(rows), days, "\n".join(rows[:30]))) if rows \
        else "nothing obviously abandoned."


@tool("list_processes", "What's running now and what it's costing in memory.",
      READ, "The Reaper", {"top": _int("How many to show. Default 15.")}, [])
def t_procs(bit, top=15):
    if WINDOWS:
        rc, out = _ps(
            "Get-Process | Sort-Object WS -Descending | Select-Object -First %d "
            "Name,Id,@{n='MB';e={[math]::Round($_.WS/1MB)}} | Format-Table -AutoSize | Out-String"
            % int(top), timeout=25)
        return out.strip() if rc == 0 else "couldn't list processes: %s" % out[:200]
    rc, out = _run(["ps", "aux", "--sort=-rss"], timeout=20)
    return "\n".join(out.splitlines()[:int(top) + 1])


@tool("kill_process", "Stop a process that's hung. Queues for approval.",
      DESTROY, "The Reaper", {"pid": _int("Process id."),
                              "name": _str("Or the process name.")}, [])
def t_kill(bit, pid=0, name=""):
    if not pid and not name:
        return "give me a pid or a name."
    if WINDOWS:
        target = "-Id %d" % int(pid) if pid else "-Name '%s'" % name
        rc, out = _ps("Stop-Process %s -Force; 'stopped'" % target, timeout=20)
    else:
        rc, out = _run(["kill", "-9", str(pid)], timeout=10)
    return out.strip()[:300] if rc == 0 else "couldn't stop it: %s" % out[:200]


@tool("delete_paths", "Delete files. Queues for approval and always goes to the "
      "Recycle Bin route - a copy is kept unless told otherwise.",
      DESTROY, "The Reaper", {"paths": {"type": "array", "items": {"type": "string"},
                                        "description": "Full paths to remove."}},
      ["paths"])
def t_delete(bit, paths):
    graveyard = os.path.join(STATE_DIR, "graveyard",
                             datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(graveyard, exist_ok=True)
    done, failed = [], []
    for p in paths:
        p = os.path.expanduser(p)
        try:
            shutil.move(p, os.path.join(graveyard, os.path.basename(p)))
            done.append(os.path.basename(p))
        except Exception as e:
            failed.append("%s (%r)" % (os.path.basename(p), e))
    return "moved %d to %s%s" % (
        len(done), graveyard,
        ("; couldn't take: " + ", ".join(failed)) if failed else "")


# ============================================================================
# THE SECRETARY - schedule. The task file and the calendar are hers alone.
# ============================================================================
def _tasks():
    return _load(TASKS_PATH, {"seq": 0, "items": []})


@tool("tasks_list", "Everything outstanding, what's overdue and what's due today.",
      READ, "The Secretary", {"who": _str("Filter by owner. Optional."),
                              "include_done": _bool("Show completed too. Default false.")},
      [])
def t_tasks_list(bit, who="", include_done=False):
    t = _tasks()
    items = [i for i in t["items"] if include_done or i["state"] != "done"]
    if who:
        items = [i for i in items if who.lower() in (i.get("owner") or "").lower()]
    if not items:
        return "nothing outstanding."
    today = datetime.now().date()
    out = []
    for i in sorted(items, key=lambda x: x.get("due") or "9999"):
        due, flag = i.get("due") or "", ""
        if due:
            try:
                d = datetime.fromisoformat(due).date()
                flag = " OVERDUE" if d < today else (" TODAY" if d == today else "")
            except Exception:
                pass
        out.append("%s  %-52s %s%s%s" % (
            i["id"], i["text"][:52], i.get("owner") or "-",
            ("  due " + due) if due else "", flag))
    return "\n".join(out)


@tool("task_add", "Write down something that was agreed, with an owner and a date. "
      "If a date wasn't said, ask for one rather than inventing it.",
      WRITE, "The Secretary", {"text": _str("What needs doing."),
                               "owner": _str("Who owns it. Leave blank if it's the user's own."),
                               "due": _str("Due date as YYYY-MM-DD. Blank if genuinely unset."),
                               "source": _str("Where it came from - a meeting, a file.")},
      ["text"])
def t_task_add(bit, text, owner="", due="", source=""):
    t = _tasks()
    t["seq"] += 1
    t["items"].append({"id": "T%d" % t["seq"], "text": text,
                       "owner": owner or USER,
                       "due": due, "source": source, "state": "open",
                       "created": _now(), "touched": _now()})
    _save(TASKS_PATH, t)
    return "noted T%d: %s%s" % (t["seq"], text, (" - due " + due) if due else "")


@tool("task_done", "Close a task out.",
      WRITE, "The Secretary", {"id": _str("Task id, e.g. T4.")}, ["id"])
def t_task_done(bit, id):
    t = _tasks()
    for i in t["items"]:
        if i["id"].lower() == id.strip().lower():
            i["state"] = "done"
            i["touched"] = _now()
            _save(TASKS_PATH, t)
            return "closed %s: %s" % (i["id"], i["text"])
    return "no task called %s" % id


@tool("morning_brief", "The shape of today: what's due, what's overdue, what slipped, "
      "and what was promised and never closed.",
      READ, "The Secretary", {}, [])
def t_brief(bit):
    t = _tasks()
    today = datetime.now().date()
    overdue, due_today, soon = [], [], []
    for i in t["items"]:
        if i["state"] == "done":
            continue
        d = None
        try:
            d = datetime.fromisoformat(i["due"]).date() if i.get("due") else None
        except Exception:
            d = None
        if d is None:
            continue
        if d < today:
            overdue.append(i)
        elif d == today:
            due_today.append(i)
        elif d <= today + timedelta(days=3):
            soon.append(i)
    undated = [i for i in t["items"] if i["state"] != "done" and not i.get("due")]
    out = ["%s" % today.strftime("%A %d %B")]
    out.append("overdue: %d%s" % (len(overdue), (" - " + "; ".join(
        i["text"][:40] for i in overdue[:4])) if overdue else ""))
    out.append("due today: %d%s" % (len(due_today), (" - " + "; ".join(
        i["text"][:40] for i in due_today[:4])) if due_today else ""))
    out.append("next 3 days: %d" % len(soon))
    out.append("no date set: %d" % len(undated))
    return "\n".join(out)


@tool("end_of_day", "What was said today versus what actually closed.",
      READ, "The Secretary", {}, [])
def t_eod(bit):
    t = _tasks()
    today = datetime.now().date().isoformat()
    made = [i for i in t["items"] if (i.get("created") or "").startswith(today)]
    closed = [i for i in t["items"] if i["state"] == "done"
              and (i.get("touched") or "").startswith(today)]
    still = [i for i in t["items"] if i["state"] != "done"
             and (i.get("created") or "").startswith(today)]
    return ("today: %d new, %d closed, %d still open.\nstill open: %s"
            % (len(made), len(closed), len(still),
               "; ".join(i["text"][:50] for i in still[:6]) or "none"))


# ============================================================================
# THE GHOST - what was quietly dropped. Never the same thing twice.
# ============================================================================
def _ghosts():
    return _load(GHOST_PATH, {"surfaced": {}, "verdicts": {}})


@tool("stale_scan", "Find what stopped moving: notes, drafts, downloads and branches "
      "nobody has touched in a long time.",
      READ, "The Ghost", {"path": _str("Where to look. Defaults to your scope."),
                          "days": _int("Count as abandoned after N days. Default 60.")},
      [])
def t_stale(bit, path="", days=60):
    root = _resolve(bit, path)
    cutoff = time.time() - int(days) * 86400
    g = _ghosts()
    found = []
    for fp in _walk(root, max_files=20000):
        ext = os.path.splitext(fp)[1].lower()
        if ext not in (".md", ".txt", ".docx", ".doc", ".pdf", ".xlsx", ".csv", ".py"):
            continue
        try:
            m = os.path.getmtime(fp)
        except Exception:
            continue
        if m < cutoff:
            found.append((m, fp))
    found.sort()
    # never nag twice about the same thing
    fresh = [(m, f) for m, f in found if f not in g["surfaced"]]
    old_news = len(found) - len(fresh)
    if not fresh:
        return ("nothing new to haunt you with - %d already mentioned." % old_news)
    out = ["%d abandoned thing(s), %d already raised before:" % (len(fresh), old_news)]
    for m, f in fresh[:12]:
        out.append("  %-6s  %s" % (_ago(m), os.path.relpath(f, root)))
    return "\n".join(out)


@tool("mark_surfaced", "Record that you've raised something, so you never raise it "
      "twice in one conversation.",
      WRITE, "The Ghost", {"path": _str("What you just brought up.")}, ["path"])
def t_surfaced(bit, path):
    g = _ghosts()
    g["surfaced"][path] = _now()
    _save(GHOST_PATH, g)
    return "logged. You won't mention it again."


@tool("verdict", "Give an abandoned thing its ending: revive it (the Secretary "
      "schedules it), kill it (the Reaper takes it), or let it haunt.",
      WRITE, "The Ghost", {"path": _str("The thing."),
                           "call": _str("revive, kill or haunt."),
                           "note": _str("Why.")}, ["path", "call"])
def t_verdict(bit, path, call, note=""):
    call = call.lower().strip()
    if call not in ("revive", "kill", "haunt"):
        return "it's revive, kill or haunt. Nothing else."
    g = _ghosts()
    g["verdicts"][path] = {"call": call, "note": note, "at": _now()}
    g["surfaced"][path] = _now()
    _save(GHOST_PATH, g)
    if call == "revive":
        t_task_add("The Secretary", "Revive: %s" % os.path.basename(path),
                   owner=USER, source="The Ghost")
        return "revived. Secretary, it's on your list now."
    if call == "kill":
        return "marked for the Reaper. Reaper, it's yours."
    return "left to haunt. It'll be back."


@tool("open_loops", "Commitments with no closure - tasks rolling over, drafts never "
      "sent, things promised and never mentioned again.",
      READ, "The Ghost", {"days": _int("How long counts as rolling over. Default 21.")},
      [])
def t_loops(bit, days=21):
    t = _tasks()
    cutoff = datetime.now() - timedelta(days=int(days))
    rolling = []
    for i in t["items"]:
        if i["state"] == "done":
            continue
        try:
            if datetime.fromisoformat(i["created"]) < cutoff:
                rolling.append(i)
        except Exception:
            continue
    drafts = []
    if os.path.isdir(REPORTS_DIR):
        for e in os.scandir(REPORTS_DIR):
            if e.name.endswith(".eml") and (time.time() - e.stat().st_mtime) > 3 * 86400:
                drafts.append("%s (%s)" % (e.name, _ago(e.stat().st_mtime)))
    out = []
    if rolling:
        out.append("%d task(s) rolling over %d+ days:" % (len(rolling), days))
        out += ["  %s  %s (since %s)" % (i["id"], i["text"][:50], _ago(i["created"]))
                for i in rolling[:10]]
    if drafts:
        out.append("%d draft(s) written and never sent: %s"
                   % (len(drafts), "; ".join(drafts[:5])))
    return "\n".join(out) if out else "no open loops. Suspicious."


# ============================================================================
# THE LIBRARIAN - file. Points inward. Every answer comes with a path.
# ============================================================================
DOC_EXT = (".md", ".txt", ".pdf", ".docx", ".doc", ".xlsx", ".csv", ".pptx", ".rtf")


@tool("index_build", "Walk the vault and the drives and build the index. Everything "
      "else you do rests on this being current.",
      WRITE, "The Librarian", {"path": _str("Root to index. Defaults to the vault.")}, [])
def t_index(bit, path=""):
    root = _resolve(bit, path or VAULT_ROOT)
    idx = {"root": root, "built": _now(), "docs": []}
    for fp in _walk(root, max_files=40000):
        if os.path.splitext(fp)[1].lower() not in DOC_EXT:
            continue
        try:
            st = os.stat(fp)
        except Exception:
            continue
        idx["docs"].append({"path": fp, "name": os.path.basename(fp),
                            "size": st.st_size, "mtime": st.st_mtime})
    _save(INDEX_PATH, idx)
    return "indexed %d document(s) under %s." % (len(idx["docs"]), root)


@tool("index_search", "Find a document by name or by what's written in it. Always give "
      "the path back with the answer.",
      READ, "The Librarian", {"query": _str("What to look for."),
                              "content": _bool("Also search inside files. Slower. Default true.")},
      ["query"])
def t_index_search(bit, query, content=True):
    idx = _load(INDEX_PATH, None)
    if not idx:
        return "the index hasn't been built yet. Run index_build first."
    q = query.lower()
    by_name = [d for d in idx["docs"] if q in d["name"].lower()]
    out = ["by name (%d):" % len(by_name)]
    out += ["  %s  (%s, %s)" % (d["path"], _size(d["size"]), _ago(d["mtime"]))
            for d in sorted(by_name, key=lambda x: -x["mtime"])[:15]]
    if content:
        inside = []
        for d in idx["docs"]:
            if d["size"] > 2_000_000 or os.path.splitext(d["name"])[1].lower() \
                    not in (".md", ".txt", ".csv"):
                continue
            try:
                with open(d["path"], "r", encoding="utf-8", errors="ignore") as f:
                    body = f.read()
                if q in body.lower():
                    i = body.lower().find(q)
                    inside.append("  %s ... %s ..." % (
                        d["path"], body[max(0, i - 70):i + 110].replace("\n", " ")))
            except Exception:
                continue
            if len(inside) >= 15:
                break
        out.append("by content (%d):" % len(inside))
        out += inside
    return "\n".join(out)


@tool("file_document", "Put a document where it belongs, named the way everything else "
      "is named, and index it. Queues for approval because it moves the file.",
      DESTROY, "The Librarian",
      {"path": _str("The document to file."),
       "category": _str("Folder it belongs in, e.g. 'Contracts'."),
       "rename_to": _str("Optional new name, without the extension.")},
      ["path", "category"])
def t_file_doc(bit, path, category, rename_to=""):
    src = _resolve(bit, path)
    if not os.path.isfile(src):
        return "no file at %s" % src
    ext = os.path.splitext(src)[1]
    stem = rename_to or os.path.splitext(os.path.basename(src))[0]
    stem = re.sub(r"[^\w\s.-]", "", stem).strip().replace(" ", "-")
    dest_dir = os.path.join(VAULT_ROOT, category)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "%s-%s%s" % (
            datetime.now().strftime("%Y%m%d"), stem, ext))
        shutil.move(src, dest)
        return "filed: %s" % dest
    except Exception as e:
        return "couldn't file it: %r" % e


@tool("versions_of", "Every copy and draft of a document, newest first, so you can say "
      "which one is actually current.",
      READ, "The Librarian", {"name": _str("Document name or a distinctive part of it.")},
      ["name"])
def t_versions(bit, name):
    idx = _load(INDEX_PATH, None)
    docs = idx["docs"] if idx else [
        {"path": p, "name": os.path.basename(p), "size": os.path.getsize(p),
         "mtime": os.path.getmtime(p)}
        for p in _walk(VAULT_ROOT, max_files=20000)
        if os.path.splitext(p)[1].lower() in DOC_EXT]
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    hits = []
    for d in docs:
        stem = re.sub(r"[^a-z0-9]+", "", os.path.splitext(d["name"])[0].lower())
        stem = re.sub(r"(v\d+|final|draft|copy|\d{6,8})", "", stem)
        if key in stem or stem in key:
            hits.append(d)
    if not hits:
        return "no versions of '%s' anywhere." % name
    hits.sort(key=lambda d: -d["mtime"])
    out = ["%d version(s) of '%s' - newest first:" % (len(hits), name)]
    for i, d in enumerate(hits[:12]):
        tag = "  <- current" if i == 0 else ""
        out.append("  %-6s %8s  %s%s" % (_ago(d["mtime"]), _size(d["size"]),
                                         d["path"], tag))
    return "\n".join(out)


@tool("naming_check", "Documents that break the naming convention, and pairs that have "
      "quietly diverged into two versions of the same thing.",
      READ, "The Librarian", {"path": _str("Folder to check. Defaults to the vault.")}, [])
def t_naming(bit, path=""):
    root = _resolve(bit, path or VAULT_ROOT)
    bad, stems = [], {}
    for fp in _walk(root, max_files=20000):
        if os.path.splitext(fp)[1].lower() not in DOC_EXT:
            continue
        base = os.path.basename(fp)
        if re.search(r"(copy|final|FINAL|new|latest|\(\d\)|untitled)", base, re.I):
            bad.append(fp)
        stem = re.sub(r"[^a-z0-9]+", "",
                      re.sub(r"(v\d+|final|copy|draft|\d{6,8}|\(\d\))", "",
                             os.path.splitext(base)[0].lower()))
        if len(stem) > 4:
            stems.setdefault(stem, []).append(fp)
    diverged = {k: v for k, v in stems.items() if len(v) > 1}
    out = []
    if bad:
        out.append("%d file(s) named badly ('copy', 'final', 'untitled'):" % len(bad))
        out += ["  " + os.path.relpath(f, root) for f in bad[:12]]
    if diverged:
        out.append("%d document(s) exist in more than one version:" % len(diverged))
        for k, v in list(diverged.items())[:8]:
            out.append("  %s:" % k)
            out += ["      %-6s %s" % (_ago(os.path.getmtime(f)),
                                       os.path.relpath(f, root)) for f in v[:4]]
    return "\n".join(out) if out else "everything under %s is named properly." % root


# ============================================================================
# THE WIZARD - orchestrate. He runs the machine that runs the Bits.
# ============================================================================
# Summoning is the one verb of his that lives on screen rather than on disk, so
# it needs a way back to the window layer. The app sets these; when nothing does
# - bits_tools run on its own, or the selftest - the tools say so plainly rather
# than pretending the cast worked.
#
#   ON_STAGE(action, bit_name) -> str      action is "summon" or "dismiss"
#   STAGE_PRESENT() -> [bit_name, ...]     who is on the desktop right now
#   ON_FLOOR(names, question) -> str       give each of them a turn on one question
ON_STAGE = None
STAGE_PRESENT = None
ON_FLOOR = None

NO_STAGE = "the room isn't listening - there's no desktop to cast onto."


def _stage(action, name):
    if ON_STAGE is None:
        return NO_STAGE
    try:
        return ON_STAGE(action, name)
    except Exception as e:                                        # noqa: BLE001
        return "the cast failed: %r" % e


def present_bits():
    """Who is on screen, or None if nothing has told us."""
    if STAGE_PRESENT is None:
        return None
    try:
        return list(STAGE_PRESENT())
    except Exception:                                             # noqa: BLE001
        return None


def resolve_bit(name):
    """'coder', 'Coder', 'the coder' -> 'The Coder'. "" if there's no such Bit.

    Loose on purpose: this is fed by a spoken line, not by a form.
    """
    want = re.sub(r"^(the|@)\s*", "", str(name).strip().lower()).strip(" .,'\"")
    for full in DEFAULT_SCOPE:
        if want in (full.lower(), full.lower().replace("the ", "")):
            return full
    return ""


@tool("summon_bit", "Bring a Bit onto the desktop so it can answer for itself. Cast "
      "this whenever someone asks for a Bit by name, or asks for work that belongs to "
      "a Bit who isn't in the room yet - then address that Bit by name in the very "
      "same reply, so they pick the job up as they land.",
      WRITE, "The Wizard", {"name": _str("Which Bit, e.g. 'Coder' or 'The Reaper'.")},
      ["name"])
def t_summon(bit, name):
    who = resolve_bit(name)
    if not who:
        return "there is no Bit called '%s'. The roster is: %s" % (
            name, ", ".join(sorted(n.replace("The ", "") for n in DEFAULT_SCOPE)))
    if who == "The Wizard":
        return "you are the Wizard. You are the console - you're always here."
    here = present_bits()
    if here is not None and who in here:
        return "%s is already in the room. Just talk to them." % who
    return _stage("summon", who)


@tool("dismiss_bit", "Send a Bit back where it came from. Use it when its work is "
      "done and it's cluttering the desk, or when asked to.",
      WRITE, "The Wizard", {"name": _str("Which Bit, e.g. 'Coder'.")}, ["name"])
def t_dismiss(bit, name):
    who = resolve_bit(name)
    if not who:
        return "there is no Bit called '%s'." % name
    if who == "The Wizard":
        return "you can't dismiss yourself. You are the console."
    here = present_bits()
    if here is not None and who not in here:
        return "%s isn't here to dismiss." % who
    return _stage("dismiss", who)


def resolve_bits(who):
    """'Boss, the Coder and Reaper' -> ['The Boss', 'The Coder', 'The Reaper'].

    Blank means the whole roster. Fed by a spoken line, so it splits on commas,
    "and", slashes and plain spaces and takes whatever resolves.
    """
    if not str(who).strip():
        return [n for n in DEFAULT_SCOPE if n != "The Wizard"]
    out = []
    for part in re.split(r"[,/&]|\band\b|\s{2,}", str(who), flags=re.I):
        got = resolve_bit(part)
        if not got:                       # "Boss Coder Reaper" with no commas
            for word in part.split():
                w = resolve_bit(word)
                if w and w not in out:
                    out.append(w)
            continue
        if got not in out:
            out.append(got)
    return [n for n in out if n != "The Wizard"]


@tool("open_floor", "Put one question to the whole room and let every Bit answer it in "
      "its own turn. Cast this when you're asked what everyone thinks, or when a "
      "decision wants more heads than one - not for a job that plainly belongs to a "
      "single Bit. Anyone not in the room is summoned so they can speak, and each Bit "
      "may pass if it has nothing to add. The round IS the handoff: say your piece and "
      "stop, don't hand off to anyone afterwards.",
      WRITE, "The Wizard",
      {"question": _str("What is being put to the room, in one line."),
       "who": _str("Optional: who gets the floor, e.g. 'Boss, Coder, Reaper'. "
                   "Leave blank for the whole roster.")},
      ["question"])
def t_open_floor(bit, question, who=""):
    names = resolve_bits(who)
    if not names:
        return ("there is nobody called '%s'. The roster is: %s" % (
            who, ", ".join(sorted(n.replace("The ", "") for n in DEFAULT_SCOPE))))
    if ON_FLOOR is None:
        return NO_STAGE
    try:
        return ON_FLOOR(names, str(question).strip())
    except Exception as e:                                        # noqa: BLE001
        return "the floor wouldn't open: %r" % e


# ----------------------------------------------------------------------------
# THE BOARD'S RADIOS
#
# The desk unit has its own WiFi and Bluetooth, which are not the computer's.
# Seeing what is out there is the Investigator's job; wiring the board onto a
# network is the Wizard's, the same way installing anything else is.
#
#   ON_RADIO(do, **args) -> {"ok": bool, "out": ..., "error": str}
# ----------------------------------------------------------------------------
ON_RADIO = None
NO_RADIO = "there's no desk unit plugged in, so there's no radio to use."

# When this is on, anything the Bits pull off the web goes out over the desk
# unit's radio instead of the computer's. It does not quietly fall back: the
# whole reason to turn it on is that the traffic should not be on this machine's
# connection, and a silent fallback would be the one failure that matters.
USE_BOARD_NET = False


def _radio(do, **args):
    if ON_RADIO is None:
        return {"ok": False, "error": NO_RADIO}
    try:
        return ON_RADIO(do, **args)
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "error": "the desk unit: %r" % e}


def _bars(rssi):
    """Signal as something readable out loud, not a negative number."""
    try:
        rssi = int(rssi)
    except Exception:                                             # noqa: BLE001
        return "?"
    return ("strong" if rssi > -55 else "good" if rssi > -67 else
            "weak" if rssi > -80 else "barely there")


@tool("wifi_scan", "What wireless networks the desk unit can hear. This is the "
      "board's own radio, not the computer's - it hears what is around the board.",
      READ, "The Investigator", {}, [])
def t_wifi_scan(bit):
    got = _radio("scan")
    if not got.get("ok"):
        return got.get("error", "no answer from the desk unit")
    nets = got.get("out") or []
    if not nets:
        return "the board hears nothing at all."
    rows = ["%-22s %-10s ch%-3s %s" % (n["ssid"][:22], n["security"],
                                       n["channel"], _bars(n["rssi"]))
            for n in nets]
    return "%d network(s) the board can hear:\n%s" % (len(nets), "\n".join(rows))


@tool("bluetooth_scan", "What Bluetooth devices are advertising near the desk unit. "
      "Takes a few seconds and hears only things that are announcing themselves.",
      READ, "The Investigator",
      {"seconds": _int("How long to listen. Default 4, max 10.")}, [])
def t_bt_scan(bit, seconds=4):
    seconds = max(1, min(10, int(seconds or 4)))
    got = _radio("bt", timeout=seconds + 25, seconds=seconds)
    if not got.get("ok"):
        return got.get("error", "no answer from the desk unit")
    seen = got.get("out") or []
    if not seen:
        return "nothing nearby is advertising itself."
    rows = ["%-24s %s  %s" % (d.get("name") or "(no name)", d["address"],
                              _bars(d["rssi"])) for d in seen]
    return "%d Bluetooth device(s) near the board:\n%s" % (len(seen),
                                                           "\n".join(rows))


@tool("board_network", "Whether the desk unit is on a wireless network of its own, "
      "and what address it has. Check here before promising the Bits can reach "
      "anything through the board.",
      READ, "The Wizard", {}, [])
def t_board_net(bit):
    got = _radio("status")
    if not got.get("ok"):
        return got.get("error", "no answer from the desk unit")
    st = got.get("out") or {}
    if not st.get("on"):
        return "the board's radio is off."
    if not st.get("connected"):
        return "the board's radio is on but not joined to anything."
    return ("the board is on %s as %s (gateway %s, %s signal)."
            % (st.get("ssid") or "a network", st.get("ip"), st.get("gateway"),
               _bars(st.get("rssi"))))


@tool("board_join", "Put the desk unit onto a wireless network, so the Bits can reach "
      "the web over the board's radio instead of the computer's. Ask for the password "
      "rather than guessing it.",
      EXECUTE, "The Wizard",
      {"ssid": _str("The network name, exactly as wifi_scan gave it."),
       "password": _str("Its password. Leave blank for an open network.")},
      ["ssid"])
def t_board_join(bit, ssid, password=""):
    got = _radio("connect", timeout=45, ssid=ssid, password=password)
    if not got.get("ok"):
        return got.get("error", "no answer from the desk unit")
    st = got.get("out") or {}
    if not st.get("connected"):
        return "it wouldn't join %s. %s" % (ssid, st.get("error", ""))
    return "the board is on %s as %s." % (ssid, st.get("ip"))


@tool("board_leave", "Take the desk unit off its network and turn its radio off.",
      WRITE, "The Wizard", {}, [])
def t_board_leave(bit):
    got = _radio("forget")
    if not got.get("ok"):
        return got.get("error", "no answer from the desk unit")
    return "the board's radio is off."


ROUTINES = {
    "morning": ["The Secretary: morning_brief", "The Boss: metrics_pulse",
                "The Ghost: one abandoned thing"],
    "triage": ["The Courier: triage_downloads", "The Librarian: index_build",
               "The Reaper: what shouldn't have been kept"],
    "pre-meeting": ["The Secretary: agenda and last decisions",
                    "The Investigator: dossier", "The Librarian: relevant documents"],
    "end of day": ["The Secretary: end_of_day", "The Coder: repo_health",
                   "The Ghost: what slipped"],
    "reckoning": ["The Reaper: disk_audit and stale_apps", "The Ghost: open_loops",
                  "The Boss: approve or refuse each", "The Secretary: schedule survivors"],
    "ship it": ["The Coder: git_status", "The Librarian: file the artefacts",
                "The Courier: deliver", "The Secretary: log it done"],
}


@tool("list_routines", "The named sequences you can fire, and which Bits each one wakes.",
      READ, "The Wizard", {}, [])
def t_routines(bit):
    return "\n".join("%-12s %s" % (k, " -> ".join(v)) for k, v in ROUTINES.items())


@tool("run_routine", "Fire a routine. You announce it and hand off to the first Bit in "
      "the chain by name - that's what makes it run.",
      READ, "The Wizard", {"name": _str("Routine name, e.g. 'morning'.")}, ["name"])
def t_run_routine(bit, name):
    key = name.lower().strip()
    if key not in ROUTINES:
        return "no routine called '%s'. There's: %s" % (name, ", ".join(ROUTINES))
    steps = ROUTINES[key]
    return ("routine '%s': %s\nHand off to the first Bit by name now."
            % (key, " -> ".join(steps)))


@tool("system_state", "What the machine looks like right now - disk, uptime, memory. "
      "Useful before you promise anything.",
      READ, "The Wizard", {}, [])
def t_sysstate(bit):
    out = []
    try:
        total, used, free = shutil.disk_usage(os.path.splitdrive(HOME)[0] or "/")
        out.append("disk: %s free of %s (%.0f%% used)"
                   % (_size(free), _size(total), used / total * 100))
    except Exception:
        pass
    if WINDOWS:
        rc, o = _ps("$os=Get-CimInstance Win32_OperatingSystem; "
                    "'{0:N0} MB free of {1:N0} MB; up since {2}' -f "
                    "($os.FreePhysicalMemory/1KB),($os.TotalVisibleMemorySize/1KB),"
                    "$os.LastBootUpTime", timeout=20)
        if rc == 0 and o.strip():
            out.append("memory/uptime: " + o.strip())
    a = [i for i in _approvals()["items"] if i["state"] == "pending"]
    out.append("approvals pending: %d" % len(a))
    t = _tasks()
    out.append("tasks open: %d" % len([i for i in t["items"] if i["state"] != "done"]))
    return "\n".join(out)


@tool("bit_status", "Who is on the desktop right now, what each Bit is pointed at, "
      "and whether it has anything waiting. Check here before you summon anyone.",
      READ, "The Wizard", {}, [])
def t_bitstatus(bit):
    scopes = _load(SCOPES_PATH, {})
    here = present_bits()
    pend = {}
    for i in _approvals()["items"]:
        if i["state"] == "pending":
            pend[i["bit"]] = pend.get(i["bit"], 0) + 1
    rows = []
    for name in DEFAULT_SCOPE:
        n = len([t for t in TOOLS.values() if t.owner == name])
        if here is None or name == "The Wizard":
            where = "  "             # nothing is telling us, or he is the console
        else:
            where = "on" if name in here else "--"
        rows.append("%-3s %-18s %2d tools  scope: %-42s %s"
                    % (where, name, n,
                       (scopes.get(name) or DEFAULT_SCOPE[name])[:42],
                       ("%d pending" % pend[name]) if name in pend else ""))
    if here is not None:
        rows.append("('on' = in the room and can be spoken to; '--' = not summoned)")
    return "\n".join(rows)


@tool("install_package", "Install a Python package into the app's virtual environment. "
      "Queues for approval.",
      EXECUTE, "The Wizard", {"package": _str("Package name, e.g. 'openpyxl'.")},
      ["package"])
def t_install(bit, package):
    if not re.match(r"^[A-Za-z0-9_.\-\[\]=<>]+$", package):
        return "that isn't a package name."
    py = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(py):
        py = sys.executable
    rc, out = _run([py, "-m", "pip", "install", package], timeout=180)
    return "%s\n%s" % ("installed" if rc == 0 else "failed", out.strip()[-800:])


# ----------------------------------------------------------------------------
# Which Bit owns what - the map, derived from the registry so it can't drift
# ----------------------------------------------------------------------------
def ownership():
    out = {}
    for t in TOOLS.values():
        out.setdefault(t.owner, []).append((t.name, t.tier))
    return out


def describe():
    lines = []
    for owner, tools in sorted(ownership().items()):
        lines.append("%s (%d)" % (owner, len(tools)))
        for name, tier in sorted(tools):
            lines.append("    %-20s %s%s" % (name, tier,
                                             "  [gated]" if tier in GATED else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    _ensure_dirs()
    print(describe())
    print("\nstate: %s\nreports: %s" % (STATE_DIR, REPORTS_DIR))
