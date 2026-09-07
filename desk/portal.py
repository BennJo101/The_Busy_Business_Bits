"""The board as its own access point, so a bare computer can be given the Bits.

A vanilla machine plugged into this board gets a COM port and nothing else -
the ESP32 has no USB peripheral, so it can never be a drive or a keyboard. What
it does have is a radio. So it becomes an access point and a small web server:
join its network, open a browser, and take what you need. No driver, no Python
on the far side, no internet.

    /            what this is, and what is on the card
    /bits.zip    the payload, streamed off the SD card
    /join        hand it the name and password of a real network

Everything is streamed in 4KB pieces. The board has about 140KB of heap and the
payload is tens of megabytes, so nothing here may ever hold a whole file.
"""
import os
import socket

import network

import carrier

AP_NAME = "BusyBusinessBits"
AP_PASS = "okaybam!"          # WPA2 needs eight characters; this is the point
PORT = 80
CHUNK = 4096
PAYLOAD = "/sd/bits.zip"

_ap = None


def start_ap(name=AP_NAME, password=AP_PASS):
    """Broadcast. Returns the address to type into a browser."""
    global _ap
    _ap = network.WLAN(network.AP_IF)
    _ap.active(True)
    try:
        _ap.config(essid=name, password=password, authmode=3)   # WPA2-PSK
    except Exception:
        _ap.config(essid=name)                                   # open, if it must
    return _ap.ifconfig()[0]


def stop_ap():
    global _ap
    if _ap:
        try:
            _ap.active(False)
        except Exception:
            pass
    _ap = None


def _size(path):
    try:
        return os.stat(path)[6]
    except Exception:
        return 0


PAGE = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>The Busy Business Bits</title>
<style>
body{background:#1a1116;color:#d8cfc0;font:15px/1.6 system-ui,sans-serif;
margin:0;padding:28px;max-width:34em}
h1{color:#e8d9b8;font-size:1.3rem;margin:0 0 .2em}
p{color:#b9a98f}a.btn,button{display:inline-block;background:#8a6f30;color:#1a1116;
font-weight:700;padding:.7em 1.2em;border:0;border-radius:3px;text-decoration:none;
cursor:pointer;font-size:1rem}
input{background:#241a20;color:#d8cfc0;border:1px solid #3d2f34;padding:.6em;
border-radius:3px;width:100%%;box-sizing:border-box;margin:.3em 0 .8em}
small{color:#7a6f63}code{color:#c8a24a}
</style>
<h1>The Busy Business Bits</h1>
<p>You are talking to the desk unit over its own radio.</p>
%s
<hr style="border:0;border-top:1px solid #3d2f34;margin:2em 0">
<h1 style="font-size:1.05rem">Put it on a network</h1>
<p><small>So it can be reached without joining this one.</small></p>
<form method=POST action=/join>
<label>network</label><input name=ssid list=seen value="">
<datalist id=seen>%s</datalist>
<label>password</label><input name=password type=password>
<button type=submit>join</button></form>
"""


def _payload_block():
    n = _size(PAYLOAD)
    if not n:
        return ("<p><b>There is nothing to hand over.</b> The card has no "
                "<code>bits.zip</code> on it.</p>")
    return ('<p><a class=btn href="/bits.zip">Download the Bits'
            ' &nbsp;(%.0f MB)</a></p>'
            '<p><small>Unzip it anywhere and run <code>Start the Bits.bat</code>.'
            ' It carries its own Python; nothing needs installing.</small></p>'
            % (n / 1048576.0))


def _seen_options():
    try:
        import radio
        return "".join('<option value="%s">' % n["ssid"] for n in radio.scan(12))
    except Exception:
        return ""


def _send_head(conn, code="200 OK", kind="text/html; charset=utf-8", length=None,
               extra=""):
    head = "HTTP/1.1 %s\r\nContent-Type: %s\r\nConnection: close\r\n" % (code, kind)
    if length is not None:
        head += "Content-Length: %d\r\n" % length
    conn.sendall((head + extra + "\r\n").encode())


def _serve_file(conn, path):
    n = _size(path)
    if not n:
        _send_head(conn, "404 Not Found", "text/plain", 9)
        conn.sendall(b"not here\n")
        return
    _send_head(conn, "200 OK", "application/zip", n,
               'Content-Disposition: attachment; filename="bits.zip"\r\n')
    f = open(path, "rb")
    try:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            conn.sendall(block)
    finally:
        f.close()


def _form(body):
    out = {}
    for pair in body.split("&"):
        k, _, v = pair.partition("=")
        v = v.replace("+", " ")
        while "%" in v:
            i = v.find("%")
            if i + 2 >= len(v):
                break
            try:
                v = v[:i] + chr(int(v[i + 1:i + 3], 16)) + v[i + 3:]
            except Exception:
                break
        out[k] = v
    return out


def serve(on_note=None):
    """Answer browsers until stopped. Runs on a thread; never returns."""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", PORT))
    s.listen(2)
    while True:
        try:
            conn, who = s.accept()
        except Exception:
            continue
        try:
            req = conn.recv(1024).decode("utf-8", "replace")
            line = req.split("\r\n", 1)[0]
            parts = line.split(" ")
            verb, path = (parts + ["", ""])[:2]
            if path.startswith("/bits.zip"):
                _serve_file(conn, PAYLOAD)
            elif verb == "POST" and path.startswith("/join"):
                body = req.partition("\r\n\r\n")[2]
                got = _form(body)
                import radio
                st = radio.connect(got.get("ssid", ""), got.get("password", ""))
                if st.get("connected"):
                    msg = ("<p>It is on <b>%s</b> as <code>%s</code>. You can "
                           "reach it there now.</p>" % (got.get("ssid"), st["ip"]))
                else:
                    msg = "<p><b>No.</b> %s</p>" % st.get("error", "it wouldn't join")
                page = (PAGE % (msg + _payload_block(), _seen_options())).encode()
                _send_head(conn, "200 OK", length=len(page))
                conn.sendall(page)
                if on_note:
                    on_note(st)
            else:
                page = (PAGE % (_payload_block(), _seen_options())).encode()
                _send_head(conn, "200 OK", length=len(page))
                conn.sendall(page)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
