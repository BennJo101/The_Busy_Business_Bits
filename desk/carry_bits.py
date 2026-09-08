"""Carry the Busy Business Bits on the desk unit's SD card.

    python desk/carry_bits.py --load          put this project onto the card
    python desk/carry_bits.py --unload DIR    copy the project off, onto this PC
    python desk/carry_bits.py --list          what the card is carrying
    python desk/carry_bits.py --payload ZIP   put the handover bundle on it

The board is not a USB drive - it is an ESP32 on a serial port - so the files
go through it a chunk at a time. That is about 8KB/s, which makes a full copy
of the project a few minutes; it runs with a progress bar at both ends, the
board's own screen included.

Needs only pyserial, on purpose: the point of the card is a computer that does
not have the project on it yet.
"""
import argparse
import ast
import base64
import hashlib
import os
import subprocess
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("this needs pyserial:  pip install pyserial")

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
ROOT = "/sd/BusyBusinessBits"            # the app
VAULT_ROOT = "/sd/BusyBusinessBitsVault"  # the Bits' own notes, and Obsidian's
VAULT_LOCAL = os.path.join(os.path.expanduser("~"), "Busy Business Bits Vault")
PAYLOAD = "/sd/bits.zip"                 # what the board's own web page serves
CHUNK = 4096          # base64 of this is 5.5KB, and the wire is the
                      # limit - fewer round trips is the only lever
CH340 = (0x1A86, 0x7523)

# What travels. The sprites are most of it and the whole point - a Bit with no
# art is a name in a list. Settings and state are deliberately not here: they
# live in the user's home directory and belong to the machine, not the card.
CARRY_DIRS = ("The Bits", "docs", "desk", "Preview")
CARRY_FILES = ("busy_business_bits.py", "bits_core.py", "bits_tools.py",
               "bits_ambient.py", "bits_desk.py", "selftest.py",
               "requirements.txt", "README.md", "LICENSE",
               "Run The Bits.bat", "Demo The Bits.bat")
SKIP_SUFFIX = (".pyc",)
SKIP_PARTS = ("__pycache__", ".git", ".venv", "factory-backup.bin")


def guess_port():
    for p in list_ports.comports():
        if (p.vid, p.pid) == CH340:
            return p.device
    for p in list_ports.comports():
        if p.vid is not None:
            return p.device
    return ""


class Board:
    """The raw REPL. Bulk transfer goes through here rather than the desk's own
    JSON protocol - same wire, without a line of JSON and a per-character parse
    around every kilobyte."""

    def __init__(self, port, bare=False):
        self.s = serial.Serial()
        self.s.port = port
        self.s.baudrate = 115200
        self.s.timeout = 0.05       # polled, not waited on - see run()
        self.s.dtr = False
        self.s.rts = False
        self.s.open()
        time.sleep(0.2)
        self._bare() if bare else self._raw()

    def _bare(self):
        """Take the REPL before main.py has imported anything.

        On boot the desk unit imports itself, the screen driver, the touch
        panel and the radio, and compiling desk.py alone wants twenty-odd
        kilobytes. Interrupting after all that leaves about 75KB free, which
        is not enough to run a file server and hold a socket buffer as well:
        a 35MB payload died a fifth of the way in, every time, and the board
        closed the connection without saying why.

        Interrupting during the boot instead leaves 164KB. Nothing is lost by
        it - the desk is going to be restarted afterwards anyway.
        """
        self.s.dtr = False
        self.s.rts = True               # hold in reset
        time.sleep(0.2)
        self.s.rts = False              # and let it boot
        end = time.time() + 3.0
        while time.time() < end:        # interrupt it before it gets going
            self.s.write(b"\x03")
            time.sleep(0.02)
        time.sleep(0.4)
        self.s.reset_input_buffer()
        self._raw()

    def _hard_reset(self):
        """Bring the board back when it has stopped making sense.

        RTS is wired to its reset pin and DTR to the boot pin, which is how
        esptool restarts it - so there is always a way back from a board left
        talking at a baud rate nobody remembers choosing.
        """
        self.s.dtr = False          # boot normally, not into the bootloader
        self.s.rts = True           # hold it in reset
        time.sleep(0.2)
        self.s.rts = False
        time.sleep(2.0)
        self.s.reset_input_buffer()

    def _raw(self):
        want = b"raw REPL; CTRL-B to exit\r\n>"
        for attempt in range(5):
            self.s.write(b"\r\x03\x03")
            time.sleep(0.3)
            self.s.reset_input_buffer()
            self.s.write(b"\r\x01")
            buf, t0 = b"", time.time()
            while time.time() - t0 < 2.5:
                buf += self.s.read(self.s.in_waiting or 1)
                if want in buf:
                    return
            time.sleep(0.4 + attempt * 0.4)
            if attempt == 2:        # talking past each other; start it over
                self._hard_reset()
        raise SystemExit("the board never offered a raw REPL - is it plugged in?")

    def run(self, code, timeout=30.0):
        """Run code on the board and wait for both end markers.

        The waiting is done by read_until, in the OS, rather than by a Python
        loop that blocks for the whole port timeout on every empty poll. That
        one detail was the transfer rate: 1.7KB/s of a possible 11.
        """
        self.s.write(code.encode() + b"\x04")
        buf, t0 = b"", time.time()
        while buf.count(b"\x04") < 2 and time.time() - t0 < timeout:
            got = self.s.read_until(b"\x04")
            if got:
                buf += got
        if buf.count(b"\x04") < 2:
            raise SystemExit("the board stopped answering")
        body = buf.split(b"OK", 1)[-1]
        out, _, rest = body.partition(b"\x04")
        err = rest.partition(b"\x04")[0].decode("utf-8", "replace").strip()
        if err:
            raise SystemExit("the board said:\n" + err)
        return out.decode("utf-8", "replace")

    def restart(self):
        self.s.write(b"\x02")
        time.sleep(0.3)
        self.s.write(b"\x04")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def vault_files(where):
    """The vault as (relative path, absolute path, size).

    `.obsidian` travels: it is the difference between a folder of markdown and
    a vault that opens with the right accent colour and the graph already on.
    Its workspace file does not - that is where *this* machine had its panes.
    """
    out = []
    for here, dirs, files in os.walk(where):
        dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
        for f in files:
            if f in ("workspace.json", "workspace-mobile.json") or f.endswith(
                    SKIP_SUFFIX):
                continue
            full = os.path.join(here, f)
            rel = os.path.relpath(full, where).replace("\\", "/")
            out.append((rel, full, os.path.getsize(full)))
    return sorted(out)


def local_files():
    """What to send, as (relative path, absolute path, size)."""
    out = []
    for name in CARRY_FILES:
        full = os.path.join(PROJECT, name)
        if os.path.isfile(full):
            out.append((name.replace("\\", "/"), full, os.path.getsize(full)))
    for folder in CARRY_DIRS:
        base = os.path.join(PROJECT, folder)
        for here, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for f in files:
                if f.endswith(SKIP_SUFFIX) or f in SKIP_PARTS:
                    continue
                full = os.path.join(here, f)
                rel = os.path.relpath(full, PROJECT).replace("\\", "/")
                out.append((rel, full, os.path.getsize(full)))
    return sorted(out)


def bar(done, total, width=28):
    n = int(width * done / total) if total else width
    pct = 100 * done // total if total else 100
    return "[%s%s] %3d%%" % ("=" * n, " " * (width - n), pct)


UI = """
import tft as T
try:
    _d
except NameError:
    _d = T.TFT()
    _ink = _d.rgb(26,17,22); _paper = _d.rgb(216,207,192)
    _gold = _d.rgb(232,217,184); _dark = _d.rgb(102,57,49)
    _green = _d.rgb(58,168,96)
def carry_ui(title, line, done, total):
    _d.fill(0, 0, 320, 26, _dark)
    _d.text(title[:26], 8, 9, _gold, _dark)
    _d.fill(0, 26, 320, 214, _ink)
    _d.text(line, 8, 60, _paper, _ink)
    pct = int(done * 100 / total) if total else 100
    _d.frame(20, 110, 280, 30, _gold, 2)
    _d.fill(23, 113, int(274 * pct / 100), 24, _green)
    _d.text('%d%%  %d of %d KB' % (pct, done // 1024, total // 1024),
            20, 156, _paper, _ink)
"""


def screen(b, title, line, done, total):
    """The same progress, on the board's own screen."""
    try:
        b.run("carry_ui(%r, %r, %d, %d)" % (title, line[-26:], done, total),
              timeout=10)
    except SystemExit:
        pass                              # a screen is not worth failing over


def mounted(b):
    b.run("import carrier, ubinascii")
    if b.run("print(carrier.mount())").strip() != "True":
        raise SystemExit("no SD card in the board.")
    return int(b.run("print(carrier.free_mb())").strip() or 0)


def carried(b):
    n, size = [int(x) for x in b.run("print('%d %d' % carrier.total())").split()]
    return n, size


def short_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()[:16]


def already_there(b, card_root):
    """What the card already holds, as {path: (size, short sha)}.

    Reading and hashing the whole card is about fifteen seconds; sending it all
    again is seven minutes. So a reload asks first.
    """
    try:
        got = ast.literal_eval(
            b.run("print(repr(carrier.digests(%r)))" % card_root,
                  timeout=300).strip())
    except Exception:                                   # noqa: BLE001
        return {}
    return {rel: (size, h) for rel, size, h in got}


def push_tree(b, files, card_root, title, known=None):
    """Send a tree to the card, drawing the same bar here and on the board."""
    total = sum(n for _, _, n in files)
    b.run("carrier.mkdirs(%r)" % card_root)
    known = known or {}
    sent, t0, made, skipped = 0, time.time(), set(), 0
    for rel, full, size in files:
        if known.get(rel) == (size, short_sha(full)):
            sent += size                       # already on the card, untouched
            skipped += 1
            continue
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if folder and folder not in made:
            b.run("carrier.mkdirs(%r)" % (card_root + "/" + folder))
            made.add(folder)
        b.run("f = open(%r, 'wb')" % (card_root + "/" + rel))
        with open(full, "rb") as fh:
            while True:
                block = fh.read(CHUNK)
                if not block:
                    break
                b.run("f.write(ubinascii.a2b_base64(%r))"
                      % base64.b64encode(block).decode(), timeout=30)
                sent += len(block)
                sys.stdout.write("\r  %s %s" % (bar(sent, total),
                                                rel[-34:].ljust(34)))
                sys.stdout.flush()
        b.run("f.close()")
        screen(b, title, rel, sent, total)
    dt = time.time() - t0
    print("\r  %s  %.0fs%s%s"
          % (bar(total, total), dt,
             ", %d already there" % skipped if skipped else "",
             " " * 26))
    return sent


def pull_tree(b, card_root, target, title):
    """Copy a tree off the card. Returns the files it brought."""
    listing = b.run("print(repr(carrier.walk(%r)))" % card_root, timeout=90).strip()
    # literal_eval, not eval: this is a listing off a device, and a listing is
    # data even when it arrives looking like Python
    files = sorted(ast.literal_eval(listing))
    if not files:
        return []
    total = sum(n for _, n in files)
    got, t0 = 0, time.time()
    for rel, size in files:
        dest = os.path.join(target, *rel.split("/"))
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        b.run("f = open(%r, 'rb')" % (card_root + "/" + rel))
        with open(dest, "wb") as out:
            while True:
                b64 = b.run(
                    "print(ubinascii.b2a_base64(f.read(%d)).decode(), end='')"
                    % CHUNK, timeout=30).strip()
                block = base64.b64decode(b64) if b64 else b""
                if not block:
                    break
                out.write(block)
                got += len(block)
                sys.stdout.write("\r  %s %s" % (bar(got, total),
                                                rel[-34:].ljust(34)))
                sys.stdout.flush()
        b.run("f.close()")
        screen(b, title, rel, got, total)
    dt = time.time() - t0
    print("\r  %s  %.0fs, %.1f KB/s%s"
          % (bar(total, total), dt, got / 1024.0 / max(dt, 1), " " * 20))
    return files


def find_obsidian():
    """A local Obsidian to open the vault with, if there is one.

    Obsidian itself does not travel on the card: it is 290MB, and at the speed
    this link runs that is eleven and a half hours. The vault is kilobytes and
    goes in seconds; the app is a thing you install once per machine, or drop
    on the card with a card reader for a machine that has none.
    """
    for p in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe"),
              os.path.expandvars(r"%PROGRAMFILES%\Obsidian\Obsidian.exe")):
        if os.path.isfile(p):
            return p
    return ""


def do_load(b, wipe, vault_dir):
    files = local_files()
    vfiles = vault_files(vault_dir) if os.path.isdir(vault_dir) else []
    total = sum(n for _, _, n in files) + sum(n for _, _, n in vfiles)
    free = mounted(b)
    print("carrying %d files, %.1f MB (card has %d MB free)"
          % (len(files) + len(vfiles), total / 1048576.0, free))
    if free * 1048576 < total * 1.1:
        raise SystemExit("not enough room on the card.")
    app_known, vault_known = {}, {}
    if wipe:
        print("clearing the old copy...")
        b.run("print(carrier.rm_tree(%r))" % ROOT, timeout=180)
        b.run("print(carrier.rm_tree(%r))" % VAULT_ROOT, timeout=180)
    else:
        print("checking what the card already has...")
        app_known = already_there(b, ROOT)
        vault_known = already_there(b, VAULT_ROOT)
    b.run(UI)
    print("the app:")
    push_tree(b, files, ROOT, "LOADING THE BITS", app_known)
    if vfiles:
        print("the vault:")
        push_tree(b, vfiles, VAULT_ROOT, "LOADING THE VAULT", vault_known)
    else:
        print("no vault at %s - build one with desk/make_vault.py" % vault_dir)
    n, size = carried(b)
    print("the card is carrying %d files, %.1f MB" % (n, size / 1048576.0))
    screen(b, "THE BITS ARE ABOARD", "%d files" % n, 1, 1)


def do_unload(b, target, open_it):
    mounted(b)
    b.run(UI)
    print("the app:")
    files = pull_tree(b, ROOT, target, "HANDING THEM OVER")
    if not files:
        raise SystemExit("the card isn't carrying anything yet - try --load.")
    vault = os.path.join(target, "Vault")
    print("the vault:")
    vfiles = pull_tree(b, VAULT_ROOT, vault, "HANDING OVER THE VAULT")
    if not vfiles:
        print("  (the card has no vault on it)")
    print("\nthe Bits are on this computer:  %s" % os.path.abspath(target))
    print("   python selftest.py     checks they arrived intact")
    print("   Demo The Bits.bat      canned lines, no API key needed")
    if vfiles:
        print("\ntheir vault came too:  %s" % os.path.abspath(vault))
        print("   point them at it with:  set BITS_VAULT=%s"
              % os.path.abspath(vault))
        print('   or put "vault": "%s" in ~/.busy_business_bits.json'
              % os.path.abspath(vault).replace("\\", "\\\\"))
        exe = find_obsidian()
        if open_it and exe:
            print("   opening it in Obsidian...")
            subprocess.Popen([exe, "obsidian://open?path=%s"
                              % os.path.abspath(vault)])
        elif open_it:
            print("   no Obsidian on this machine to open it with.")
    screen(b, "HANDED OVER", os.path.basename(target) or "done", 1, 1)


def do_list(b):
    free = mounted(b)
    n, size = carried(b)
    v = ast.literal_eval(b.run("print(repr(carrier.walk(%r)))" % VAULT_ROOT,
                               timeout=90).strip())
    print("the card is carrying:")
    print("   the app    %4d files, %6.1f MB" % (n, size / 1048576.0))
    print("   the vault  %4d files, %6.1f KB" % (len(v), sum(s for _, s in v) / 1024.0))
    print("   %d MB free" % free)
    if v:
        for rel, sz in sorted(v)[:8]:
            print("      %6d  Vault/%s" % (sz, rel))
        if len(v) > 8:
            print("      ... and %d more" % (len(v) - 8))


def board_sha(b, dest, upto):
    """The sha256 of the first `upto` bytes of a file on the card.

    Done on the board because the alternative is reading 35MB back down a wire
    that manages 7.7KB/s. The board reads its own card at about 390KB/s, so
    this is a minute and a half against two hours.
    """
    code = ("try:\n"
            "    import uhashlib as _h\n"
            "except ImportError:\n"
            "    import hashlib as _h\n"
            "import ubinascii\n"
            "_x = _h.sha256()\n"
            "_left = %d\n"
            "_f = open(%r, 'rb')\n"
            "while _left > 0:\n"
            "    _b = _f.read(4096 if _left > 4096 else _left)\n"
            "    if not _b:\n"
            "        break\n"
            "    _left -= len(_b)\n"
            "    _x.update(_b)\n"
            "_f.close()\n"
            "print(ubinascii.hexlify(_x.digest()).decode())" % (upto, dest))
    return b.run(code, timeout=900).strip()


def local_sha(path, upto=None):
    h = hashlib.sha256()
    left = os.path.getsize(path) if upto is None else upto
    with open(path, "rb") as f:
        while left > 0:
            block = f.read(65536 if left > 65536 else left)
            if not block:
                break
            left -= len(block)
            h.update(block)
    return h.hexdigest()


def resume_at(b, dest, local):
    """How much of the payload the card already holds, of ours.

    Thirty-five megabytes at 7.7KB/s is an hour and a quarter, and "the cable
    was nudged at minute seventy, start again" is not a recovery story. The
    card's copy is hashed and compared against the same prefix of ours, so a
    resume can only ever continue our own file - a different build, or a
    truncated write, falls back to sending the lot.
    """
    size = os.path.getsize(local)
    try:
        on_card = int(b.run("import os\n"
                            "try:\n"
                            "    print(os.stat(%r)[6])\n"
                            "except OSError:\n"
                            "    print(-1)" % dest, timeout=30).strip())
    except (SystemExit, ValueError):
        return 0
    if on_card <= 0 or on_card > size:
        return 0
    print("   the card already holds %.1f MB - checking it is ours"
          % (on_card / 1048576.0))
    if board_sha(b, dest, on_card) == local_sha(local, on_card):
        print("   it is: carrying on from there")
        return on_card
    print("   it is not - sending the whole thing")
    return 0


def do_payload(b, local, dest=None):
    """Put the handover payload on the card, resumably, and prove it arrived."""
    dest = dest or PAYLOAD
    if not os.path.isfile(local):
        raise SystemExit("no such file: %s" % local)
    free = mounted(b)
    size = os.path.getsize(local)
    want = size / 1048576.0
    print("sending %s  %.1f MB, %d MB free on the card"
          % (os.path.basename(local), want, free))
    start = resume_at(b, dest, local)
    if start >= size:
        print("   already complete")
    else:
        b.run("carrier.mkdirs(%r)" % dest.rsplit("/", 1)[0])
        b.run("import ubinascii")
        b.run("f = open(%r, %r)" % (dest, "ab" if start else "wb"))
        sent, t0, since = start, time.time(), 0
        with open(local, "rb") as fh:
            fh.seek(start)
            while True:
                block = fh.read(CHUNK)
                if not block:
                    break
                b.run("f.write(ubinascii.a2b_base64(%r))"
                      % base64.b64encode(block).decode(), timeout=60)
                sent += len(block)
                since += 1
                rate = (sent - start) / max(time.time() - t0, 0.001)
                left = (size - sent) / rate if rate else 0
                sys.stdout.write("\r  %s %5.1f KB/s  %d min left   "
                                 % (bar(sent, size), rate / 1024.0, left / 60))
                sys.stdout.flush()
                if since >= 40:             # the board's screen, now and then
                    screen(b, "Loading the Bits", os.path.basename(local),
                           sent, size)
                    since = 0
        b.run("f.close()")
        print("\r  %s  %.0f min%s"
              % (bar(size, size), (time.time() - t0) / 60, " " * 30))

    print("   verifying on the board")
    there, here = board_sha(b, dest, size), local_sha(local)
    screen(b, "Loading the Bits", "verified" if there == here else "MISMATCH",
           size, size)
    if there != here:
        raise SystemExit("the copy on the card does not match:\n"
                         "   here  %s\n   card  %s" % (here, there))
    print("   sha256 matches: %s" % here)
    print("done. The card can hand this to a computer that has nothing on it.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true",
                    help="copy this project and the vault onto the card")
    ap.add_argument("--unload", metavar="DIR",
                    help="copy them off the card into DIR")
    ap.add_argument("--list", action="store_true", help="what is on the card")
    ap.add_argument("--payload", metavar="ZIP",
                    help="put the handover bundle on the card as %s, "
                         "resuming if a part of it is already there" % PAYLOAD)
    ap.add_argument("--fresh", action="store_true",
                    help="with --load, clear the card's copy first")
    ap.add_argument("--vault", default=VAULT_LOCAL,
                    help="the vault to send (default: %s)" % VAULT_LOCAL)
    ap.add_argument("--open", action="store_true",
                    help="with --unload, open the vault in Obsidian afterwards")
    ap.add_argument("--port", default="")
    args = ap.parse_args()
    if not (args.load or args.unload or args.list or args.payload):
        ap.error("say what to do: --load, --unload DIR, --list, or --payload ZIP")

    port = args.port or guess_port()
    if not port:
        sys.exit("no board found. Plug it in, or pass --port COM7.")
    print("board on %s" % port)
    # A payload is 35MB through a file the board has to hold open; it
    # wants the memory the desk unit would otherwise be sitting on.
    b = Board(port, bare=bool(args.payload))
    try:
        if args.list:
            do_list(b)
        elif args.payload:
            do_payload(b, args.payload)
        elif args.load:
            do_load(b, args.fresh, args.vault)
        else:
            do_unload(b, args.unload, args.open)
    finally:
        b.restart()                        # back to being a desk unit
        b.close()


if __name__ == "__main__":
    main()
