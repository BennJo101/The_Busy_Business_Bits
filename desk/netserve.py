"""The board as a file server on its own WiFi, for when the wire is too slow.

The serial link is 115200 baud - about 11KB/s, and the wire is already 95%
saturated, so nothing but the baud rate can improve it. The same board has
WiFi. Over TCP the same files move at hundreds of KB/s, which is the difference
between handing over a 78MB runtime in three hours and doing it in three
minutes.

Deliberately plain: a length-prefixed request, a length-prefixed reply, no HTTP,
no framework. It serves only from the card, and only for reading.
"""
import os
import socket
import struct

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


def _safe(path):
    """Only ever inside the card's own folders."""
    path = path.replace("\\", "/")
    if ".." in path.split("/"):
        return ""
    for root in (carrier.ROOT, "/sd/BusyBusinessBitsVault", "/sd/BitsPortable"):
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
                elif verb == "BYE":
                    break
                else:
                    _send(conn, b"")
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
