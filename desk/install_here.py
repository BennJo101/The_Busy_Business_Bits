"""Install the Bits onto whatever computer the card has been plugged into.

    python install_here.py                 copy, register, start
    python install_here.py --with-obsidian bring Obsidian across too (290MB)
    python install_here.py --remove        undo all of it

Windows will not run anything by itself when a card is inserted - AutoRun was
switched off for removable media years ago and cannot be switched back on. So
this is the next best thing: one double-click of *Install on this computer*,
and after that the desk unit works on its own. Plug the board in, press START,
and the Bits come up, because the watcher is already running from login.

Nothing is written outside the user's own profile, and --remove takes it all
back out.
"""
import argparse
import os
import shutil
import subprocess
import sys

def _bundle_root():
    """The folder holding Python\ and App\ - the card's root.

    Found by walking up rather than counting levels: this file sits at
    <card>\App\desk\ on the card and at <project>\desk\ in the repo, and
    counting got the wrong one.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if all(os.path.isdir(os.path.join(here, d)) for d in ("Python", "App")):
            return here
        here = os.path.dirname(here)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


CARD = _bundle_root()
HOME = os.path.expanduser("~")
TARGET = os.path.join(os.environ.get("LOCALAPPDATA", HOME), "Busy Business Bits")
STARTUP = os.path.join(os.environ.get("APPDATA", HOME), "Microsoft", "Windows",
                       "Start Menu", "Programs", "Startup")
LAUNCHER = "Busy Business Bits.bat"

# Raw, and joined with os.path.join below: written as a plain string, the
# "\b" of "\bits_desk.py" is a backspace, and the launcher it wrote pointed at
# "Appits_desk.py".
# No BITS_HOME here on purpose. Keeping settings on the card is right when
# the Bits are *running from* it - the key arrives and leaves with the card.
# An install is the opposite: it commits to this machine, so it should use the
# machine's own settings and share them with anything already here. Setting it
# started a second, empty settings file beside a perfectly good one, and the
# Bits came up asking for an API key that was already on disk.
BOOT = r"""@echo off
rem Written by the installer. Delete this file to stop the Bits starting with
rem Windows, or run "Uninstall from this computer".
set "BITS_VAULT={vault}"
start "" "{pythonw}" "{watcher}"
"""


def size_of(path):
    return sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(path) for f in fs)


def copy(src, dst, label):
    if not os.path.isdir(src):
        return 0
    n = 0
    for here, dirs, files in os.walk(src):
        rel = os.path.relpath(here, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(here, f), os.path.join(out, f))
            n += 1
            if n % 200 == 0:
                sys.stdout.write("\r   %-14s %5d files" % (label, n))
                sys.stdout.flush()
    print("\r   %-14s %5d files%s" % (label, n, " " * 12))
    return n


def remove():
    boot = os.path.join(STARTUP, LAUNCHER)
    gone = []
    if os.path.isfile(boot):
        os.remove(boot)
        gone.append("the startup entry")
    if os.path.isdir(TARGET):
        keep = os.path.join(TARGET, "State")
        if os.path.isdir(keep):
            print("   leaving your settings and notes at %s" % keep)
            for name in os.listdir(TARGET):
                if name != "State":
                    p = os.path.join(TARGET, name)
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) \
                        else os.remove(p)
        else:
            shutil.rmtree(TARGET, ignore_errors=True)
        gone.append("the copy in %s" % TARGET)
    print("removed: %s" % (", ".join(gone) if gone else "nothing was installed"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-obsidian", action="store_true")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    args = ap.parse_args()
    if args.remove:
        return remove()

    if os.path.normcase(os.path.abspath(CARD)) == os.path.normcase(TARGET):
        sys.exit("this is already the installed copy - run the installer from "
                 "the card, not from %s" % TARGET)
    print("installing the Busy Business Bits")
    print("   from %s" % CARD)
    print("   to   %s" % TARGET)
    parts = [("Python", "the runtime"), ("App", "the app"), ("Vault", "the vault")]
    if args.with_obsidian:
        parts.append(("Obsidian", "Obsidian"))
    want = sum(size_of(os.path.join(CARD, p)) for p, _ in parts
               if os.path.isdir(os.path.join(CARD, p)))
    print("   %.0f MB" % (want / 1048576.0))
    os.makedirs(TARGET, exist_ok=True)
    for folder, label in parts:
        copy(os.path.join(CARD, folder), os.path.join(TARGET, folder), label)
    os.makedirs(os.path.join(TARGET, "State"), exist_ok=True)
    # settings that were on the card come across, so the key arrives with it
    card_state = os.path.join(CARD, "State")
    if os.path.isdir(card_state):
        for f in os.listdir(card_state):
            s = os.path.join(card_state, f)
            d = os.path.join(TARGET, "State", f)
            if not os.path.exists(d):
                shutil.copy2(s, d) if os.path.isfile(s) else shutil.copytree(s, d)

    os.makedirs(STARTUP, exist_ok=True)
    boot = os.path.join(STARTUP, LAUNCHER)
    with open(boot, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(BOOT.format(
            vault=os.path.join(TARGET, "Vault"),
            pythonw=os.path.join(TARGET, "Python", "pythonw.exe"),
            watcher=os.path.join(TARGET, "App", "bits_desk.py")))
    print("   registered at login: %s" % boot)

    if not args.no_start:
        env = dict(os.environ)
        env.pop("BITS_HOME", None)         # this machine's own settings
        env["BITS_VAULT"] = os.path.join(TARGET, "Vault")
        subprocess.Popen([os.path.join(TARGET, "Python", "pythonw.exe"),
                          os.path.join(TARGET, "App", "bits_desk.py")],
                         cwd=os.path.join(TARGET, "App"), env=env)
        print("   the watcher is running now")
    print()
    print("done. Plug the desk unit in and press START - the Bits will come up.")
    print("To undo:  Uninstall from this computer.bat  on the card")


if __name__ == "__main__":
    main()
