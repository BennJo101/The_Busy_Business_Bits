"""The SD card: the board carries the Bits, and hands them to any computer.

The card is mounted on SPI host 2. Host 1 is the display - in this MicroPython
build machine.SPI(1) is VSPI, not HSPI, so the card has to be told slot=2 or it
collides with the screen and comes back ESP_ERR_INVALID_STATE. The touch panel
is bit-banged for the same reason: it was on the bus the card needs.
"""
import os
import machine

ROOT = "/sd/BusyBusinessBits"
_sd = None


def mount():
    """Mount the card if it isn't already. True when there is one."""
    global _sd
    try:
        os.listdir("/sd")
        return True                       # already there from an earlier call
    except Exception:
        pass
    try:
        _sd = machine.SDCard(slot=2, sck=machine.Pin(18), miso=machine.Pin(19),
                             mosi=machine.Pin(23), cs=machine.Pin(5),
                             freq=20000000)
        os.mount(_sd, "/sd")
        return True
    except Exception:
        _sd = None
        return False


def free_mb():
    try:
        v = os.statvfs("/sd")
        return v[0] * v[3] // 1048576
    except Exception:
        return 0


def _is_dir(path):
    try:
        return os.stat(path)[0] & 0x4000 != 0
    except Exception:
        return False


def walk(root=ROOT):
    """Every file under root as (path relative to root, size).

    Iterative rather than recursive: the depth is small but the stack on this
    board is smaller, and a folder of sprites is no place to find that out.
    """
    out = []
    stack = [root]
    while stack:
        here = stack.pop()
        try:
            names = os.listdir(here)
        except Exception:
            continue
        for name in names:
            full = here + "/" + name
            if _is_dir(full):
                stack.append(full)
            else:
                try:
                    out.append((full[len(root) + 1:], os.stat(full)[6]))
                except Exception:
                    pass
    return out


def total(root=ROOT):
    """(files, bytes) waiting on the card."""
    got = walk(root)
    return len(got), sum(n for _, n in got)


def mkdirs(path):
    """Make a folder and everything above it. Quiet if it already exists."""
    parts = path.split("/")
    made = ""
    for p in parts:
        if not p:
            continue
        made += "/" + p
        try:
            os.mkdir(made)
        except Exception:
            pass


def rm_tree(path):
    """Delete a folder and everything in it. Only ever called on ROOT."""
    if not path.startswith("/sd/") or len(path) < 6:
        return False                      # never anywhere but the card
    stack, dirs = [path], []
    while stack:
        here = stack.pop()
        dirs.append(here)
        try:
            names = os.listdir(here)
        except Exception:
            continue
        for name in names:
            full = here + "/" + name
            if _is_dir(full):
                stack.append(full)
            else:
                try:
                    os.remove(full)
                except Exception:
                    pass
    for d in reversed(dirs):
        try:
            os.rmdir(d)
        except Exception:
            pass
    return True


def digests(root=ROOT):
    """(path, size, short sha256) for everything under root.

    So a reload can send only what actually changed. Reading the whole card is
    a few seconds at 390KB/s; sending it again is seven minutes at 7KB/s, so
    this pays for itself the first time one file moves.
    """
    try:
        import hashlib
    except ImportError:
        import uhashlib as hashlib
    import ubinascii
    out = []
    for rel, size in walk(root):
        h = hashlib.sha256()
        f = open(root + "/" + rel, "rb")
        try:
            while True:
                block = f.read(4096)
                if not block:
                    break
                h.update(block)
        finally:
            f.close()
        out.append((rel, size, ubinascii.hexlify(h.digest()).decode()[:16]))
    return out
