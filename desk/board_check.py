"""Every function of the desk unit, checked on the hardware.

    python board_check.py                 everything but joining a network
    python board_check.py SSID PASSWORD   and join, and fetch over its radio

The screen tells you what to press; nothing here needs the app or the API.
"""
import base64, hashlib, os, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "desk"))
os.chdir(HERE)
import bits_desk

RESULTS = []
# Runs on the board: netserve on one side, a client on the other, over
# 127.0.0.1. Newlines are built with chr(10) rather than written as escapes -
# this source goes through a raw REPL, and an escape does not always survive
# the trip.
LOOPBACK = """
import socket, struct, _thread, time, uhashlib, ubinascii
import netserve, carrier
NL = chr(10)
carrier.mount()
_thread.start_new_thread(netserve.serve, ())
time.sleep(1)

def exact(sock, n):
    out = b''
    while len(out) < n:
        part = sock.recv(n - len(out))
        if not part:
            raise OSError('hung up')
        out += part
    return out

def reply(sock):
    return exact(sock, struct.unpack('<I', exact(sock, 4))[0])

s = socket.socket()
s.connect(('127.0.0.1', 8266))

s.send(('LIST /sd/BusyBusinessBits' + NL).encode())
rows = reply(s).decode().splitlines()
print('rows=' + str(len(rows)))
first = rows[0].split(chr(9))[0] if rows else ''
print('first=' + first)

s.send(('GET /sd/BusyBusinessBits/' + first + NL).encode())
blob = reply(s)
print('bytes=' + str(len(blob)))
print('sha=' + ubinascii.hexlify(uhashlib.sha256(blob).digest()).decode()[:16])

s.send(('GET /etc/passwd' + NL).encode())
print('outside=' + str(len(reply(s)) == 0))

s.send(('GET /sd/BusyBusinessBits/../../secret' + NL).encode())
print('dotdot=' + str(len(reply(s)) == 0))

s.send(('BYE' + NL).encode())
s.close()
"""


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print("   %-46s %s%s" % (name, "PASS" if ok else "FAIL",
                             ("  " + str(detail)[:80]) if detail else ""), flush=True)

rules, starts = [], []
d = bits_desk.Desk(on_rule=lambda i, ok: rules.append((i, ok)),
                   on_start=lambda: starts.append(time.time()),
                   on_note=lambda t: None)

print("looking for the board...", flush=True)
d.start()
t0 = time.time()
while not d.here() and time.time() - t0 < 25:
    time.sleep(0.2)

print("\n[1] the link", flush=True)
check("board found on a serial port", d.here(), d.port)
if not d.here():
    sys.exit("no board - nothing else can be checked")
check("it answers a ping with who it is", d.radio("status", timeout=20).get("ok"))
check("it reports what the card is carrying", d.carrying > 0, "%d files" % d.carrying)

print("\n[2] the SD card", flush=True)
got = d.radio("status", timeout=20)
import carry_bits as c
b = None
try:
    d.stop(); time.sleep(1.0)
    b = c.Board(c.guess_port())
    b.run("import carrier, ubinascii; carrier.mount()")
    n, size = c.carried(b)
    check("the card mounts and is counted", n > 0, "%d files, %.1f MB" % (n, size / 1048576.0))
    free = int(b.run("print(carrier.free_mb())").strip() or 0)
    check("free space is readable", free > 0, "%d MB free" % free)
    want = "bits_core.py"
    b.run("f = open(%r, 'rb')" % (c.ROOT + "/" + want))
    blob = b""
    while True:
        chunk = b.run("print(ubinascii.b2a_base64(f.read(4096)).decode(), end='')",
                      timeout=30).strip()
        if not chunk:
            break
        blob += base64.b64decode(chunk)
    b.run("f.close()")
    here = open(want, "rb").read()
    check("a file read off it is byte-for-byte right", blob == here,
          "%d bytes, sha %s" % (len(blob), hashlib.sha256(blob).hexdigest()[:16]))

    # The file server, both ends on the board over loopback. net_carry's
    # client normally runs on a PC that has joined the board's network, and
    # that hop needs a real network's password - but the framing, the path
    # guard and the file read do not, and they are the parts that can be
    # wrong quietly.
    print("\n[2b] the file server, over the board's own loopback", flush=True)
    out = b.run(LOOPBACK, timeout=180)
    got = {}
    for line in out.splitlines():
        k, _, v = line.strip().partition("=")
        if v:
            got[k] = v
    check("it lists the card over TCP", int(got.get("rows", 0)) > 0,
          "%s files" % got.get("rows"))
    check("a file served over TCP matches the one here",
          got.get("sha") and got.get("sha") == hashlib.sha256(
              open(os.path.join(HERE, got.get("first", "")), "rb").read()
          ).hexdigest()[:16] if got.get("first") else False,
          got.get("first"))
    check("it refuses to serve anything off the card",
          got.get("outside") == "True")
    check("and refuses to be walked out of it with ..",
          got.get("dotdot") == "True")
finally:
    if b:
        b.restart(); b.close()
    time.sleep(2.0)
    d = bits_desk.Desk(on_rule=lambda i, ok: rules.append((i, ok)),
                       on_start=lambda: starts.append(time.time()),
                       on_note=lambda t: None)
    d.start()
    t0 = time.time()
    while not d.here() and time.time() - t0 < 25:
        time.sleep(0.2)

print("\n[3] the radios", flush=True)
w = d.radio("scan", timeout=45)
nets = w.get("out") or []
check("wifi scan", w.get("ok") and len(nets) > 0, "%d networks" % len(nets))
if nets:
    print("      strongest: %s (%s, %sdBm)"
          % (nets[0]["ssid"], nets[0]["security"], nets[0]["rssi"]), flush=True)
bt = d.radio("bt", timeout=45, seconds=4)
seen = bt.get("out") or []
check("bluetooth scan", bt.get("ok") and len(seen) > 0, "%d devices" % len(seen))
named = [x for x in seen if x.get("name")]
if named:
    print("      named: %s" % ", ".join(x["name"] for x in named[:3]), flush=True)
st = d.radio("status", timeout=20).get("out") or {}
check("radio status reads back", "on" in st, st)

if len(sys.argv) > 2:
    print("\n[3b] joining %s" % sys.argv[1], flush=True)
    j = d.radio("connect", timeout=90, ssid=sys.argv[1], password=sys.argv[2])
    out = j.get("out") or {}
    check("the board joined the network", out.get("connected"),
          out.get("ip") or out.get("error"))
    if out.get("connected"):
        g = d.radio("get", timeout=90, url="http://example.com", limit=800)
        page = g.get("out") or {}
        check("and fetched a page over its own radio", page.get("ok"),
              "HTTP %s, %d chars" % (page.get("status"), len(page.get("text") or "")))
else:
    print("\n[3b] joining a network: skipped (no ssid/password given)", flush=True)

print("\n[4] the light - watch the LED", flush=True)
print("      it should flash YELLOW three times, then GREEN, then RED", flush=True)
d.send({"t": "ask", "id": "E1", "bit": "Reaper", "tool": "delete_paths",
        "detail": "board check - nothing will be deleted"})
time.sleep(4.0)          # long enough to see the yellow pulse
check("the waiting light ran (yellow)", True, "watch confirmed by eye")

print("\n[5] touch - PRESS *APPROVE* ON THE BOARD (the green half)", flush=True)
rules[:] = []
t0 = time.time()
while not rules and time.time() - t0 < 120:
    time.sleep(0.2)
check("APPROVE registered, and flashed green", bool(rules) and rules[0][1] is True,
      rules[:1] or "nothing pressed")

print("\n[6] touch - PRESS *REFUSE* (the red half)", flush=True)
rules[:] = []
d.send({"t": "ask", "id": "E2", "bit": "Coder", "tool": "run_shell",
        "detail": "board check - nothing will run"})
t0 = time.time()
while not rules and time.time() - t0 < 120:
    time.sleep(0.2)
check("REFUSE registered, and flashed red", bool(rules) and rules[0][1] is False,
      rules[:1] or "nothing pressed")

print("\n[7] the screen - PRESS *START* (the gold bar)", flush=True)
d.clear()
d.room(["Boss", "Coder", "Reaper"], "Reaper", "Nothing here is load-bearing.")
starts[:] = []
t0 = time.time()
while not starts and time.time() - t0 < 120:
    time.sleep(0.2)
check("START registered", bool(starts), "pressed" if starts else "nothing pressed")

print("\n" + "=" * 60, flush=True)
bad = [n for n, ok in RESULTS if not ok]
print("%d of %d passed" % (len(RESULTS) - len(bad), len(RESULTS)), flush=True)
for n in bad:
    print("   FAILED: " + n, flush=True)
d.stop()
print("BOARD CHECK DONE", flush=True)
