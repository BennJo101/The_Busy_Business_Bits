"""Lay the card out so it serves both jobs.

    python desk/setup_card.py --drive E: --bundle PATH   put everything on it
    python desk/setup_card.py --drive E: --check         just look

The card has two customers and they never meet:

  \BitsPortable\            a whole environment for a card reader - Python,
                            Obsidian, the app, the vault. Plugged into any
                            computer, it runs without installing anything.
  \BusyBusinessBits\        the same project where the *board* looks for it,
  \BusyBusinessBitsVault\   for handing over down the serial line.

Both fit many times over, so there is no reason to choose. The important part
is the filesystem: **FAT32, not exFAT**. Windows is happy with either, but
MicroPython's SD driver is built without exFAT, so an exFAT card mounts on the
computer and not on the board - which quietly costs you half of what the card
is for.
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

CARD_APP = "BusyBusinessBits"
CARD_VAULT = "BusyBusinessBitsVault"
PORTABLE = "BitsPortable"
FAT = ("FAT32", "FAT", "FAT16")


def look(drive):
    """What the drive is, and whether it is safe to write to."""
    import subprocess
    ps = ("$v = Get-Volume -DriveLetter %s;"
          "$p = Get-Partition -DriveLetter %s -ErrorAction SilentlyContinue;"
          "$d = if ($p) { Get-Disk -Number $p.DiskNumber } else { $null };"
          "'{0}|{1}|{2}|{3}|{4}|{5}' -f $v.FileSystem, $v.Size, "
          "$v.SizeRemaining, $v.DriveType, $d.BusType, $d.Size"
          % (drive[0], drive[0]))
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    bits = (out.split("|") + [""] * 6)[:6]
    return {"fs": bits[0], "size": int(bits[1] or 0),
            "free": int(bits[2] or 0), "type": bits[3],
            "bus": bits[4], "disk": int(bits[5] or 0)}


def copy_tree(src, dst, label):
    n = tot = 0
    for here, dirs, files in os.walk(src):
        rel = os.path.relpath(here, src)
        out = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out, exist_ok=True)
        for f in files:
            s = os.path.join(here, f)
            shutil.copy2(s, os.path.join(out, f))
            n += 1
            tot += os.path.getsize(s)
            if n % 25 == 0:
                sys.stdout.write("\r  %-22s %5d files  %6.0f MB"
                                 % (label, n, tot / 1048576.0))
                sys.stdout.flush()
    print("\r  %-22s %5d files  %6.0f MB%s" % (label, n, tot / 1048576.0, " " * 8))
    return n, tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", required=True, help="the card's drive letter, e.g. E:")
    ap.add_argument("--bundle", default="", help="the portable bundle to copy")
    ap.add_argument("--vault", default=os.path.join(os.path.expanduser("~"),
                                                    "Busy Business Bits Vault"))
    ap.add_argument("--check", action="store_true", help="look, don't touch")
    ap.add_argument("--force", action="store_true",
                    help="write even if the drive looks wrong")
    args = ap.parse_args()

    drive = args.drive.rstrip("\/")
    if not drive.endswith(":"):
        drive += ":"
    root = drive + "\\"
    if not os.path.isdir(root):
        sys.exit("%s isn't there." % root)

    it = look(drive)
    print("%s  %s  %.1f GB (%.1f GB free)  %s on %s"
          % (drive, it["fs"] or "?", it["size"] / 1e9, it["free"] / 1e9,
             it["type"], it["bus"] or "?"))

    trouble = []
    if it["type"] != "Removable":
        trouble.append("it is not a removable drive - this looks like a disk, "
                       "not a card")
    if it["fs"] and it["fs"].upper() not in FAT:
        trouble.append("it is %s, and the board's SD driver reads FAT only - "
                       "it would mount here and not there. FAT32 is the one "
                       "both ends can read" % it["fs"])
    for t in trouble:
        print("  !! " + t)
    if args.check:
        return
    if trouble and not args.force:
        sys.exit("stopping. Fix that, or pass --force if you know better.")

    need = 0
    plan = []
    if args.bundle:
        if not os.path.isdir(args.bundle):
            sys.exit("no bundle at %s" % args.bundle)
        plan.append((args.bundle, os.path.join(root, PORTABLE), "the portable copy"))
    sys.path.insert(0, HERE)
    import carry_bits as c
    app = os.path.join(root, CARD_APP)
    vault = os.path.join(root, CARD_VAULT)
    for src, dst, label in plan:
        need += sum(os.path.getsize(os.path.join(r, f))
                    for r, _, fs in os.walk(src) for f in fs)
    need += sum(n for _, _, n in c.local_files())
    if os.path.isdir(args.vault):
        need += sum(n for _, _, n in c.vault_files(args.vault))
    if need > it["free"]:
        sys.exit("that wants %.0f MB and the card has %.0f MB free."
                 % (need / 1048576.0, it["free"] / 1048576.0))
    print("writing %.0f MB..." % (need / 1048576.0))

    for src, dst, label in plan:
        copy_tree(src, dst, label)
    # the board's copies, at the paths carrier.py looks for
    os.makedirs(app, exist_ok=True)
    n = tot = 0
    for rel, full, size in c.local_files():
        out = os.path.join(app, *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(full, out)
        n += 1
        tot += size
    print("  %-22s %5d files  %6.0f MB" % ("for the board", n, tot / 1048576.0))
    if os.path.isdir(args.vault):
        copy_tree(args.vault, vault, "the board's vault")

    print("\nthe card is ready. In a reader:")
    print("   %s%s\Start the Bits.bat" % (root, PORTABLE))
    print("   %s%s\Open the Vault.bat" % (root, PORTABLE))
    print("In the board: it carries the project as before.")


if __name__ == "__main__":
    main()
