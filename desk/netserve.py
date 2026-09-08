"""The board as a file server on its own WiFi, for when the wire is too slow.

The serial link is 115200 baud - about 11KB/s, and the wire is already 95%
saturated, so nothing but the baud rate can improve it. The same board has
WiFi. Over TCP the same files move at hundreds of KB/s, which is the difference
between handing over a 78MB runtime in three hours and doing it in three
minutes.

Deliberately plain: a length-prefixed request, a length-prefixed reply, no HTTP,
no framework. It only ever touches the card's own folders.

It reads and writes. For a long time it only read, which meant the fast path
ran one way: pulling the card's contents off took seconds over the radio,
while putting a 35MB bundle back on took seventy-five minutes down the wire -
the direction actually used most, on the slowest link available. PUT answers
with the sha256 of what landed, so the sender can check the copy without
reading all of it back again.
"""
import os
import socket
import struct
import ubinascii

import carrier

PORT = 8266
CHUNK = 4096


def _send(conn, blob):
    conn.sendall(struct.pack("<I", len(blob)))
    if blob:
        conn.sendall(blob)


def _recv_line(conn):
    got = b""
    while not got.endswith(b"\n"):
        b = conn.recv(1)
        if not b:
            return ""
        got += b
        if len(got) > 400:
            return ""
    return got.decode("utf-8", "replace").strip()


ROOTS = (carrier.ROOT, "/sd/BusyBusinessBitsVault", "/sd/BitsPortable")

# The handover bundle sits at the top of the card rather than inside a project
# folder, because the board's web page serves it from there. It is named here
# so that reading and writing stay exactly as narrow as each other.
PAYLOAD = "/sd/bits.zip"


def _safe(path):
    """Only ever inside the card's own folders."""
    path = path.replace("\\", "/")
    if ".." in path.split("/"):
        return ""
    if path == PAYLOAD:
        return path
    for root in ROOTS:
        if path == root or path.startswith(root + "/"):
            return path
    return ""


def serve(seconds=0):
    """Answer requests until told to stop. Returns the address it is on."""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORT))
    s.listen(1)
    while True:
        conn, who = s.accept()
        try:
            while True:
                line = _recv_line(conn)
                if not line:
                    break
                verb, _, rest = line.partition(" ")
                if verb == "LIST":
                    rows = carrier.walk(rest or carrier.ROOT)
                    body = "\n".join("%s\t%d" % (p, n) for p, n in rows)
                    _send(conn, body.encode())
                elif verb == "GET":
                    p = _safe(rest)
                    if not p:
                        _send(conn, b"")
                        continue
                    try:
                        size = os.stat(p)[6]
                    except Exception:
                        _send(conn, b"")
                        continue
                    conn.sendall(struct.pack("<I", size))
                    f = open(p, "rb")
                    try:
                        while True:
                            block = f.read(CHUNK)
                            if not block:
                                break
                            conn.sendall(block)
                    finally:
                        f.close()
                elif verb == "PUT":
                    # PUT <path> <bytes>, then the bytes. Answers with the
                    # sha256 of what actually landed, so the sender can check
                    # the copy without reading all of it back again.
                    where, _, count = rest.rpartition(" ")
                    p = _safe(where)
                    try:
                        want = int(count)
                    except ValueError:
                        want = -1
                    if not p or want < 0:
                        _send(conn, b"")
                        continue
                    if "/" in p:
                        carrier.mkdirs(p.rsplit("/", 1)[0])
                    try:
                        import uhashlib as _h
                    except ImportError:
                        import hashlib as _h
                    digest = _h.sha256()
                    left = want
                    f = open(p, "wb")
                    try:
                        while left > 0:
                            block = conn.recv(CHUNK if left > CHUNK else left)
                            if not block:
                                break
                            f.write(block)
                            digest.update(block)
                            left -= len(block)
                    finally:
                        f.close()
                    if left:
                        _send(conn, b"")          # short: the sender will retry
                    else:
                        _send(conn, ubinascii.hexlify(digest.digest()))
                elif verb == "SIZE":
                    p = _safe(rest)
                    try:
                        _send(conn, str(os.stat(p)[6]).encode() if p else b"")
                    except Exception:
                        _send(conn, b"0")
                elif verb == "BYE":
                    break
                else:
                    _send(conn, b"")
        except Exception as e:                  # noqa: BLE001
            # Say why. Swallowing it made every failure identical from the far
            # end - the connection simply closed - so a memory error, a full
            # card and a bad path all looked like the same nothing.
            try:
                print("netserve: %s: %s" % (type(e).__name__, e))
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
