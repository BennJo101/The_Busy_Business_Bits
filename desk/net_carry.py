"""Move the card's contents over the board's WiFi instead of its serial line.

    python desk/net_carry.py --ssid NAME --password SECRET --unload DIR
    python desk/net_carry.py --ssid NAME --password SECRET --speed

Serial on this board is about 8KB/s and cannot be raised: asking for a faster
baud does move it - 460800 lands on 500000 - but sustained data corrupts at
every rate above 115200, which is the UART's clock divider rather than the USB
side. WiFi is the way round it, and it is the same board.

The password is used to join the board to the network and is not written
anywhere. Pass it on the command line yourself if you would rather it did not
pass through anyone else.
"""
import argparse
import os
import socket
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import carry_bits as c                    # noqa: E402

PORT = 8266
ROOTS = {"app": "/sd/BusyBusinessBits", "vault": "/sd/BusyBusinessBitsVault",
         "portable": "/sd/BitsPortable"}


def join(b, ssid, password, seconds=40):
    """Put the board on the network and hand back its address.

    The access point comes up with the board and stays up, so by the time we
    get here it is already broadcasting and already serving its own web page.
    Leaving it running through a transfer means two radios sharing one aerial
    and two server threads sharing 140KB of heap, and the far end simply stops
    reading partway through a 35MB send. So it is stood down first - this is a
    deliberate maintenance action, and a power cycle brings it back.
    """
    b.run("import radio")
    try:
        b.run("import portal\nportal.stop_ap()", timeout=20)
    except SystemExit:
        pass                          # not running, which is just as good
    got = b.run("print(radio.connect(%r, %r, %d))" % (ssid, password, seconds),
                timeout=seconds + 25).strip()
    if "'connected': True" not in got and '"connected": true' not in got.lower():
        raise SystemExit("the board wouldn't join: %s" % got[:200])
    ip = b.run("print(radio.status()['ip'])").strip()
    return ip


def start_server(b):
    """Leave the file server running on the board, in the background."""
    b.run("import netserve, _thread, carrier\ncarrier.mount()")
    b.run("_thread.start_new_thread(netserve.serve, ())")
    time.sleep(1.0)


class Net:
    def __init__(self, ip, port=PORT, timeout=20):
        self.s = socket.create_connection((ip, port), timeout=timeout)

    def _reply(self):
        head = self._exact(4)
        return self._exact(struct.unpack("<I", head)[0])

    def _exact(self, n):
        out = b""
        while len(out) < n:
            chunk = self.s.recv(min(65536, n - len(out)))
            if not chunk:
                raise IOError("the board hung up")
            out += chunk
        return out

    def list(self, root):
        self.s.sendall(("LIST %s\n" % root).encode())
        body = self._reply().decode("utf-8", "replace")
        out = []
        for line in body.splitlines():
            if "\t" in line:
                p, _, n = line.partition("\t")
                out.append((p, int(n)))
        return out

    def get(self, path):
        self.s.sendall(("GET %s\n" % path).encode())
        return self._reply()

    def size(self, path):
        self.s.sendall(("SIZE %s\n" % path).encode())
        try:
            return int(self._reply() or b"0")
        except ValueError:
            return 0

    def put(self, path, local, on_progress=None):
        """Send a file to the card. Returns the sha256 the board saw.

        The board hashes as it writes, so what comes back is what actually
        landed on the card rather than what we believe we sent.
        """
        size = os.path.getsize(local)
        self.s.sendall(("PUT %s %d\n" % (path, size)).encode())
        sent = 0
        with open(local, "rb") as f:
            while True:
                block = f.read(65536)
                if not block:
                    break
                self.s.sendall(block)
                sent += len(block)
                if on_progress:
                    on_progress(sent, size)
        return self._reply().decode("utf-8", "replace")

    def close(self):
        try:
            self.s.sendall(b"BYE\n")
            self.s.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssid", required=True)
    ap.add_argument("--password", default="")
    ap.add_argument("--unload", metavar="DIR")
    ap.add_argument("--payload", metavar="ZIP",
                    help="send the handover bundle to the card over WiFi")
    ap.add_argument("--what", default="app", choices=sorted(ROOTS))
    ap.add_argument("--speed", action="store_true",
                    help="just measure how fast it goes")
    ap.add_argument("--port", default="")
    args = ap.parse_args()

    b = c.Board(args.port or c.guess_port())
    try:
        print("putting the board on %s ..." % args.ssid)
        ip = join(b, args.ssid, args.password)
        print("  it is %s" % ip)
        print("starting the file server on it ...")
        start_server(b)
    finally:
        b.close()                          # let go of the serial port entirely

    root = ROOTS[args.what]
    n = Net(ip)
    try:
        if args.payload:
            if not os.path.isfile(args.payload):
                sys.exit("no such file: %s" % args.payload)
            size = os.path.getsize(args.payload)
            here = c.local_sha(args.payload)
            print("sending %.1f MB over WiFi" % (size / 1048576.0))
            t0 = time.time()

            def tick(sent, total):
                dt = max(time.time() - t0, 0.001)
                sys.stdout.write("\r  %s %6.0f KB/s"
                                 % (c.bar(sent, total), sent / 1024.0 / dt))
                sys.stdout.flush()

            there = n.put(c.PAYLOAD, args.payload, tick)
            dt = time.time() - t0
            print("\r  %s  %.0fs, %.0f KB/s%s"
                  % (c.bar(size, size), dt, size / 1024.0 / max(dt, 0.1),
                     " " * 16))
            if there != here:
                sys.exit("what landed does not match:\n  here %s\n  card %s"
                         % (here, there))
            print("sha256 matches: %s" % here)
            print("the wire would have taken %.0f minutes." % (size / 7800.0 / 60))
            return
        files = n.list(root)
        total = sum(s for _, s in files)
        print("%d files, %.1f MB on the card" % (len(files), total / 1048576.0))
        if args.speed:
            files = sorted(files, key=lambda f: -f[1])[:6]
            got, t0 = 0, time.time()
            for rel, size in files:
                got += len(n.get(root + "/" + rel))
            dt = time.time() - t0
            print("pulled %.1f MB in %.1fs  =  %.0f KB/s over WiFi"
                  % (got / 1048576.0, dt, got / 1024.0 / dt))
            print("serial does 8 KB/s, so that is %.0f times faster"
                  % (got / 1024.0 / dt / 8))
            return
        if not args.unload:
            return
        got, t0 = 0, time.time()
        for rel, size in sorted(files):
            dest = os.path.join(args.unload, *rel.split("/"))
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as f:
                f.write(n.get(root + "/" + rel))
            got += size
            sys.stdout.write("\r  %s %s" % (c.bar(got, total), rel[-34:].ljust(34)))
            sys.stdout.flush()
        dt = time.time() - t0
        print("\r  %s  %.0fs, %.0f KB/s%s"
              % (c.bar(total, total), dt, got / 1024.0 / max(dt, 0.1), " " * 20))
    finally:
        n.close()


if __name__ == "__main__":
    main()
