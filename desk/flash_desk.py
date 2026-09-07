"""Put the desk unit's firmware on an ESP32-2432S028.

    python desk/flash_desk.py              upload the four board files
    python desk/flash_desk.py --micropython PATH.bin   erase, flash, upload
    python desk/flash_desk.py --port COM7  say which port, if it guesses wrong

The board needs MicroPython on it once; after that this only copies files, so
changing the screen is a two-second round trip rather than a rebuild.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ("tft.py", "touch.py", "carrier.py", "radio.py", "netserve.py",
         "desk.py", "main.py")

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("this needs pyserial:  pip install pyserial esptool")


def guess_port():
    for p in list_ports.comports():
        if (p.vid, p.pid) == (0x1A86, 0x7523):        # the CH340 on this board
            return p.device
    for p in list_ports.comports():
        if "USB" in (p.description or "").upper():
            return p.device
    return ""


class Board:
    """Just enough of the raw REPL to copy files in."""

    def __init__(self, port):
        self.s = serial.Serial()
        self.s.port = port
        self.s.baudrate = 115200
        self.s.timeout = 0.3
        self.s.dtr = False
        self.s.rts = False
        self.s.open()
        time.sleep(0.2)
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

    def run(self, code, timeout=25.0):
        self.s.write(code.encode() + b"\x04")
        buf, t0 = b"", time.time()
        while buf.count(b"\x04") < 2 and time.time() - t0 < timeout:
            buf += self.s.read(self.s.in_waiting or 1)
        body = buf.split(b"OK", 1)[-1]
        out, _, rest = body.partition(b"\x04")
        return out.decode("utf-8", "replace"), rest.partition(b"\x04")[0].decode(
            "utf-8", "replace")

    def put(self, name, data):
        self.run("f = open(%r, 'wb')" % name)
        for i in range(0, len(data), 384):
            self.run("f.write(%r)" % data[i:i + 384])
        self.run("f.close()")
        got, _ = self.run("import os; print(os.stat(%r)[6])" % name)
        return int(got.strip() or 0)

    def restart(self):
        self.s.write(b"\x02")
        time.sleep(0.3)
        self.s.write(b"\x04")           # soft reset, so main.py runs

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="")
    ap.add_argument("--micropython", default="",
                    help="path to an ESP32 MicroPython .bin to erase and flash first")
    args = ap.parse_args()

    port = args.port or guess_port()
    if not port:
        sys.exit("no board found. Plug it in, or pass --port COM7.")
    print("board on %s" % port)

    if args.micropython:
        for step in (["erase-flash"],
                     ["write-flash", "0x1000", args.micropython]):
            cmd = [sys.executable, "-m", "esptool", "--port", port,
                   "--baud", "921600"] + step
            print("  " + " ".join(step))
            if subprocess.call(cmd) != 0:
                sys.exit("esptool failed")
        time.sleep(2)

    b = Board(port)
    try:
        for name in FILES:
            with open(os.path.join(HERE, name), "rb") as f:
                data = f.read()
            print("  %-10s %5d bytes" % (name, b.put(name, data)))
        b.restart()
    finally:
        b.close()
    print("done - the desk is running.")


if __name__ == "__main__":
    main()
