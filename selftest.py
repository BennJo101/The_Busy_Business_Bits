"""
The Busy Business Bits - self test.

    python selftest.py

Covers the paths a demo run cannot. `--demo` swaps `ask_bit` out for canned
lines, so everything between the room log and the API - the system prompt, the
tool loop, the gate - is never touched by it. A KeyError in the room rules made
every Bit answer with an error while the demo stayed perfectly happy, which is
what this file exists to stop happening again.

No API key and no network: the transport is stubbed.
"""

import os
import sys
from string import Formatter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bits_core as core          # noqa: E402
import bits_tools as tools        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print("  %-52s %s" % (name, "ok" if cond else "FAILED"))
    if not cond:
        FAILED.append("%s %s" % (name, detail))


# ---------------------------------------------------------------------------
def test_room_rules():
    print("room rules")
    text = core.room_rules(["The Boss", "The Coder"])
    left = [f for _, f, _, _ in Formatter().parse(text) if f]
    check("every placeholder is filled", not left, left)
    check("the roster is named", "The Boss, The Coder" in text)
    check("an empty room still renders", "nobody else" in core.room_rules([]))


def test_ask_bit():
    """The whole reply path, transport stubbed."""
    print("ask_bit")
    sent = []

    def stub(url, key, payload=None, method="GET", timeout=60):
        sent.append(payload)
        if len(sent) == 1 and payload.get("tools"):
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "id": "t1", "name": "system_state", "input": {}}]}
        return {"stop_reason": "end_turn",
                "content": [{"type": "text", "text": "Okay... BAM!"}]}

    real, core._request = core._request, stub
    try:
        log = [("You", "how is the machine?")]
        used = []
        reply = core.ask_bit("k", "m", "The Wizard", log, ["The Wizard"],
                             on_tool=lambda b, t, a: used.append(t))
        check("a Bit with tools replies", reply == "Okay... BAM!", reply)
        check("it ran its tool", used == ["system_state"], used)
        check("it took a second hop for the result", len(sent) == 2, len(sent))
        check("the system prompt is fully rendered",
              "{" not in sent[0]["system"].replace("{present}", ""))
        check("tool rules are attached", "act on this machine" in sent[0]["system"])

        sent.clear()
        saved = dict(tools.TOOLS)
        tools.TOOLS.clear()
        try:
            reply = core.ask_bit("k", "m", "The Boss", log, ["The Boss"])
            check("a Bit with no tools still replies", reply == "Okay... BAM!", reply)
            check("no tools key is sent", "tools" not in sent[0])
        finally:
            tools.TOOLS.update(saved)
    finally:
        core._request = real


def test_ownership():
    print("tool ownership")
    out = tools.run_tool("The Ghost", "delete_paths", {"paths": ["x"]})
    check("a Bit cannot call another's tool", "isn't your job" in out, out[:60])
    check("every tool has a real owner",
          all(t.owner == "*" or t.owner in core.BITS for t in tools.TOOLS.values()))
    owned = {t.owner for t in tools.TOOLS.values()} - {"*"}
    check("all nine have tools", len(owned) == 9, sorted(owned))


def test_gate():
    print("the gate")
    before = len([i for i in tools._approvals()["items"] if i["state"] == "pending"])
    out = tools.run_tool("The Coder", "run_shell", {"cmd": "echo selftest"})
    check("a gated tool queues instead of running", "QUEUED FOR APPROVAL" in out,
          out[:60])
    items = [i for i in tools._approvals()["items"] if i["state"] == "pending"]
    check("the approval is recorded", len(items) == before + 1)
    if items:
        got = tools.run_tool("The Boss", "refuse",
                             {"id": items[-1]["id"], "reason": "selftest"})
        check("the Boss can refuse it", "refused" in got, got[:60])
    check("ungated tools still run directly",
          "tools" in tools.run_tool("The Wizard", "bit_status", {}).lower()
          or "scope" in tools.run_tool("The Wizard", "bit_status", {}).lower())

    # The Boss rules when he is in the room, and the desk unit's screen is what
    # happens when he is not. Without this he could clear a gate he was never
    # present for: a Bit asks, he agrees, and the work runs unseen.
    tools.STAGE_PRESENT = lambda: ["The Coder"]
    try:
        out = tools.run_tool("The Boss", "approve", {"id": "A1"})
        check("the Boss can't rule from outside the room", "isn't in the room" in out,
              out[:70])
        check("and it is sent to the desk unit instead", "desk unit" in out)
        tools.STAGE_PRESENT = lambda: ["The Boss", "The Coder"]
        out = tools.run_tool("The Boss", "approve", {"id": "A1"})
        check("in the room, he rules as before", "isn't in the room" not in out,
              out[:70])
    finally:
        tools.STAGE_PRESENT = None
    check("with no screen wired at all it still works",
          "isn't in the room" not in tools.run_tool("The Boss", "approve",
                                                    {"id": "A1"}))

    # the gate has to reach the screen: a ruling can't happen off screen, so
    # hitting it fetches the Boss and tells the queuing Bit he is coming
    raised = []
    tools.ON_APPROVAL_NEEDED = lambda it: (raised.append(it)
                                           or "The Boss is on his way.")
    try:
        out = tools.run_tool("The Reaper", "delete_paths", {"paths": ["x"]})
    finally:
        tools.ON_APPROVAL_NEEDED = None
    check("hitting the gate raises the Boss", len(raised) == 1, raised)
    check("the approval says who wanted what",
          raised and raised[0]["bit"] == "The Reaper"
          and "delete_paths" in raised[0]["summary"], raised)
    check("and the Bit is told he is coming", "on his way" in out, out[:90])
    if raised:
        tools.run_tool("The Boss", "refuse",
                       {"id": raised[0]["id"], "reason": "selftest"})


def test_summoning():
    """The Wizard summoning by voice - the part the roster buttons never touch."""
    print("summoning")
    check("names resolve loosely",
          [tools.resolve_bit(x) for x in ("coder", "The Coder", "the  reaper", "@ghost")]
          == ["The Coder", "The Coder", "The Reaper", "The Ghost"],
          [tools.resolve_bit(x) for x in ("coder", "The Coder", "the  reaper", "@ghost")])
    check("a name nobody has resolves to nothing", tools.resolve_bit("the plumber") == "")

    cast = []
    tools.ON_STAGE = lambda action, name: cast.append((action, name)) or "%s is arriving." % name
    tools.STAGE_PRESENT = lambda: ["The Boss"]
    try:
        out = tools.run_tool("The Wizard", "summon_bit", {"name": "coder"})
        check("summoning reaches the screen", cast == [("summon", "The Coder")], cast)
        check("and it isn't gated", "APPROVAL" not in out, out[:60])
        check("someone already in the room isn't summoned twice",
              "already" in tools.run_tool("The Wizard", "summon_bit", {"name": "Boss"}))
        check("a Bit who isn't here can't be dismissed",
              "isn't here" in tools.run_tool("The Wizard", "dismiss_bit", {"name": "Ghost"}))
        check("dismissing reaches the screen",
              "arriving" in tools.run_tool("The Wizard", "dismiss_bit", {"name": "Boss"})
              and ("dismiss", "The Boss") in cast, cast)
        check("bit_status says who is on screen",
              "on  The Boss" in tools.run_tool("The Wizard", "bit_status", {}))
        check("only the Wizard summons",
              "isn't your job" in tools.run_tool("The Ghost", "summon_bit", {"name": "Boss"}))
    finally:
        tools.ON_STAGE = tools.STAGE_PRESENT = None
    check("with no screen wired it says so, rather than lying",
          tools.NO_STAGE in tools.run_tool("The Wizard", "summon_bit", {"name": "Coder"}))


def test_sprites():
    print("sprites")
    sp = core.discover_sprites(os.path.dirname(os.path.abspath(__file__)))
    have = core.available_bits(sp)
    check("every Bit has an idle frame", len(have) == 9, sorted(have))
    check("the Wizard has a cast", bool(sp.get("The Wizard", {}).get("snap")))

    # Opening, converting and scaling a state is 85% of what a sprite costs and
    # has to stay free of Tk, or it can't be done off the main thread and every
    # first state change drops frames again. Proved by doing one on a thread,
    # in a process with no Tk root anywhere in it.
    import threading
    import busy_business_bits as app
    path, out = sp["The Boss"]["idle"], []
    t = threading.Thread(target=lambda: out.append(app.Animator.prepare(path, 64)))
    t.start()
    t.join(30)
    check("a sprite decodes off the main thread", out == [True], out)
    check("and its frames wait there for Tk", (path, 64) in app.Animator._pil)
    check("a second pass doesn't decode it twice",
          app.Animator.prepare(path, 64) is False)
    app.Animator._pil.pop((path, 64), None)


def test_party():
    """The Konami code and the tune it plays."""
    print("the party")
    k = core.Konami()
    code = list(core.KONAMI)
    check("the code is not done until the last key",
          [k.feed(x) for x in code[:-1]][-1] != "go")
    check("the last key lands it", k.feed(code[-1]) == "go")
    check("and it rearms behind itself", k.i == 0)

    k = core.Konami()
    for x in code[:4] + ["z"] + code:
        got = k.feed(x)
    check("a wrong key restarts the sequence", got == "go")

    k = core.Konami()
    for x in ["Up"] + code:
        got = k.feed(x)
    check("a false start is still a start", got == "go", "Up Up Up Down... must work")

    k = core.Konami()
    check("the letters are flagged, so they can be untyped",
          [k.feed(x) for x in code].count("letter") == 2)
    k = core.Konami()
    check("a shouted code is the same code",
          [k.feed(x.upper()) for x in code][-1] == "go")

    wav, dur = core.synth_song()
    check("the tune renders", wav[:4] == b"RIFF" and len(wav) > 100000, len(wav))
    check("it is a listenable length", 8 < dur < 40, dur)
    check("rendering it twice is free", core.synth_song()[0] is wav)


def test_routing():
    """Who a line typed into the console goes to."""
    print("routing")
    everyone = list(core.BITS)
    HOST = "The Wizard"

    t, relay = core.route("what happened to my disk space?", everyone, HOST)
    check("an unaddressed line goes to the Wizard", t == [HOST], t)
    check("and it is marked as undelivered", relay is True)

    t, relay = core.route("Coder, is the repo clean?", everyone, HOST)
    check("naming a Bit reaches them directly", t == ["The Coder"], t)
    check("and that is not a relay", relay is False)

    t, _ = core.route("Wizard, get me the Coder", everyone, HOST)
    check("naming two reaches both", t == [HOST, "The Coder"], t)

    t, _ = core.route("Boss, Coder and Reaper - thoughts?", everyone, HOST)
    check("naming three reaches three", len(t) == 3, t)
    t, _ = core.route("Boss, Coder, Reaper, Ghost, Courier, all of you", everyone, HOST)
    check("but a roster read-out is capped", len(t) == 3, t)

    # the change: who is on screen no longer decides who answers
    t, _ = core.route("how is it going?", everyone, HOST)
    check("a crowded room doesn't hijack the line", t == [HOST], t)

    t, _ = core.route("what about the Plumber?", everyone, HOST)
    check("a name nobody has falls through to the Wizard", t == [HOST], t)


def test_the_floor():
    """Passing, and putting one question to the whole room."""
    print("the floor")
    check("a bare ellipsis is a pass", core.is_pass("..."))
    check("so is nothing at all", core.is_pass("") and core.is_pass("   "))
    check("and the word itself", core.is_pass("Pass.") and core.is_pass("nothing to add"))
    check("a real short answer is not a pass",
          not core.is_pass("No.") and not core.is_pass("Pass it to the Coder."))

    check("the rules tell them they may pass", '"..."' in core.ROOM_RULES)
    check("and that naming several brings several",
          "more than one" in core.ROOM_RULES)

    check("a spoken list of names resolves",
          tools.resolve_bits("Boss, the Coder and Reaper")
          == ["The Boss", "The Coder", "The Reaper"],
          tools.resolve_bits("Boss, the Coder and Reaper"))
    check("blank means the whole roster",
          len(tools.resolve_bits("")) == 8, tools.resolve_bits(""))
    check("the Wizard is never in his own round",
          "The Wizard" not in tools.resolve_bits("Wizard, Boss"))

    opened = []
    tools.ON_FLOOR = lambda names, q: (opened.append((names, q))
                                       or "the floor is open to them.")
    try:
        out = tools.run_tool("The Wizard", "open_floor",
                             {"question": "ship on Friday?", "who": "Boss, Coder"})
        check("opening the floor reaches the screen",
              opened == [(["The Boss", "The Coder"], "ship on Friday?")], opened)
        check("and it isn't gated", "APPROVAL" not in out, out[:60])
        check("only the Wizard opens it",
              "isn't your job" in tools.run_tool("The Boss", "open_floor",
                                                 {"question": "x"}))
    finally:
        tools.ON_FLOOR = None
    check("with no screen wired it says so",
          tools.NO_STAGE in tools.run_tool("The Wizard", "open_floor",
                                           {"question": "x"}))


def test_layout():
    """Where a summoned Bit's card is dealt. Geometry only - no screen."""
    print("layout")
    import busy_business_bits as app     # imports tkinter, creates nothing
    A = app.App
    cw, ch, gap = 260, 414, 16

    cells = list(A._cells(0, 0, 1920, 1040, cw, ch, gap))
    check("a grid fills the space it is given", len(cells) == 12, len(cells))
    check("every cell is inside it",
          all(0 <= x and x + cw <= 1920 and 0 <= y and y + ch <= 1040
              for x, y in cells))
    check("and no two cells are the same", len(set(cells)) == len(cells))
    check("cells never touch",
          all(abs(a[0] - b[0]) >= cw + gap or abs(a[1] - b[1]) >= ch + gap
              for i, a in enumerate(cells) for b in cells[i + 1:]))
    check("a strip too thin for a card yields none",
          not list(A._cells(0, 0, 200, 1040, cw, ch, gap)))

    card = (100, 100, cw, ch)
    check("a card on top of another is not clear",
          not A._clear_of(120, 120, cw, ch, [card]))
    check("one beside it is", A._clear_of(100 + cw, 100, cw, ch, [card]))
    check("touching edges don't count as overlap",
          A._overlap(100 + cw, 100, cw, ch, [card]) == 0)
    check("and the overlap is measured, not guessed",
          A._overlap(100 + cw - 10, 100, cw, ch, [card]) == 10 * ch)

    # the case that used to stack them: no room left in the tidy grid
    spot, over = A._scan((0, 0, 1920, 1040), cw, ch, [card], 40)
    check("a free spot is found before any overlap", over == 0 and spot, spot)
    packed = [(x, 0, cw, ch) for x in range(0, 1920, 60)]
    spot, over = A._scan((0, 0, 1920, 500), cw, ch, packed, 40,
                         apart=app.CARD_CORNER)
    check("with nowhere free it still keeps a corner clear",
          spot is None or all(abs(spot[0] - t[0]) >= app.CARD_CORNER
                              or abs(spot[1] - t[1]) >= app.CARD_CORNER
                              for t in packed), spot)


def test_wake():
    """The wake word, without talking at a microphone."""
    print("the wake word")
    W = core.wake_split
    check("the word and a line gives the line",
          W("Bits, is the repo clean?") == (True, "is the repo clean?"),
          W("Bits, is the repo clean?"))
    check("the word alone wakes and asks nothing", W("bits") == (True, ""))
    check("filler in front of it is ignored",
          W("hey Bits what does everyone think")
          == (True, "what does everyone think"))
    check("so is 'the'", W("the bits") == (True, ""))
    check("the long way round works too",
          W("busy business bits, hello") == (True, "hello"))
    check("a mishearing still wakes it",
          W("Bit, is the repo clean?") == (True, "is the repo clean?"),
          "the plural is what gets dropped")

    check("a phrase not addressed to them is not for them",
          W("the weather is nice") == (False, ""))
    check("the word has to open the phrase",
          W("what do the bits think") == (False, ""))
    check("it is a whole word", W("rabbits are fine") == (False, ""))
    check("and ordinary English carrying on is not a summons",
          W("bit of a mess in downloads") == (False, "")
          and W("beats me") == (False, ""))
    check("nothing heard is nothing said", W("") == (False, "") and W(None) == (False, ""))
    check("the word is not hardcoded into the rule",
          W("oi, boss - what's the number?", word="oi")
          == (True, "boss - what's the number?"),
          W("oi, boss - what's the number?", word="oi"))


def test_desk():
    """The desk unit's PC side, with no board plugged in."""
    print("the desk unit")
    import bits_desk

    d = bits_desk._detail
    check("it shows what is actually at stake",
          d({"args": {"paths": ["a.zip", "b.iso"]}}) == "a.zip, b.iso",
          d({"args": {"paths": ["a.zip", "b.iso"]}}))
    check("a long list is counted, not truncated mid-word",
          d({"args": {"paths": list("abcde")}}) == "a, b, c (+2 more)",
          d({"args": {"paths": list("abcde")}}))
    check("a command speaks for itself",
          d({"args": {"cmd": "rm -rf build"}}) == "rm -rf build")
    check("and with nothing better it falls back to the summary",
          d({"args": {}, "summary": "wipe_disk()"}) == "wipe_disk()")

    # the whole point: no board, no pyserial, no difference to the app
    desk = bits_desk.Desk()
    check("with no board it is simply not there", desk.here() is False)
    check("nothing is sent when nothing is listening",
          desk.clear() is True             # already clear; nothing to say
          and desk.ask({"id": "A1"}) is False
          and desk.clear() is False)       # would have sent, but there is no board
    check("and everything said to it is harmless",
          desk.room(["Boss"], "Boss", "hello") is None
          and desk.stop() is None)
    check("a ruling with nobody listening doesn't raise",
          desk._line(b'{"t":"rule","id":"A1","ok":true}') is None)
    check("and neither does junk on the wire",
          desk._line(b"MicroPython v1.29.0 on 2026-08-24") is None)


def test_vault():
    """The Bits' own vault: where it is, and what lands in it."""
    print("the vault")
    import os
    import subprocess
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    # the portable copy on the card runs with BITS_VAULT set, so this has to
    # check the rule rather than one of its two answers
    pointed = (os.environ.get("BITS_VAULT") or "").strip()
    if pointed:
        check("BITS_VAULT is where they keep their notes",
              core.bits_tools.VAULT_ROOT == pointed, core.bits_tools.VAULT_ROOT)
    else:
        check("without one they use the vault the project sits in",
              core.bits_tools.VAULT_ROOT == os.path.dirname(here),
              core.bits_tools.VAULT_ROOT)

    # BITS_VAULT has to be read at import, so ask a fresh interpreter
    made = os.path.join(here, "_vault_check")
    subprocess.run([sys.executable, os.path.join(here, "desk", "make_vault.py"),
                    "--where", made], capture_output=True, timeout=120)
    try:
        check("make_vault builds one note per Bit",
              len(os.listdir(os.path.join(made, "Bits"))) == len(core.BITS) + 1,
              sorted(os.listdir(os.path.join(made, "Bits"))))
        check("and the config that makes it a vault, not a folder",
              os.path.isfile(os.path.join(made, ".obsidian", "app.json")))
        env = dict(os.environ, BITS_VAULT=made)
        got = subprocess.run(
            [sys.executable, "-c",
             "import bits_tools as t; print(t.VAULT_ROOT); print(t.REPORTS_DIR)"],
            cwd=here, env=env, capture_output=True, text=True, timeout=60)
        lines = got.stdout.strip().splitlines()
        check("BITS_VAULT points them at the carried one",
              lines[:1] == [made], got.stdout.strip() or got.stderr[-200:])
        check("and their reports land inside it",
              lines[1:2] == [os.path.join(made, "Reports")], lines[1:2])
    finally:
        import shutil
        shutil.rmtree(made, ignore_errors=True)


def test_radios():
    """The board's WiFi and Bluetooth, and the toggle that uses them."""
    print("the board's radios")
    import bits_desk

    owners = {n: tools.TOOLS[n].owner for n in
              ("wifi_scan", "bluetooth_scan", "board_network", "board_join",
               "board_leave")}
    check("seeing what is out there is the Investigator's",
          owners["wifi_scan"] == owners["bluetooth_scan"] == "The Investigator",
          owners)
    check("wiring the board onto a network is the Wizard's",
          owners["board_network"] == owners["board_join"] == "The Wizard", owners)
    check("joining a network needs the Boss",
          tools.TOOLS["board_join"].tier in tools.GATED,
          tools.TOOLS["board_join"].tier)
    check("but looking does not",
          tools.TOOLS["wifi_scan"].tier not in tools.GATED)

    check("with no board they say so rather than failing",
          tools.NO_RADIO in tools.run_tool("The Investigator", "wifi_scan", {}))

    asked = []
    tools.ON_RADIO = lambda do, timeout=0, **a: (asked.append((do, a))
                                                 or {"ok": True, "out": []})
    try:
        out = tools.run_tool("The Investigator", "wifi_scan", {})
        check("a scan reaches the board", asked and asked[0][0] == "scan", asked)
        check("and an empty sky is said plainly", "nothing at all" in out, out[:60])
        asked[:] = []
        tools.run_tool("The Investigator", "bluetooth_scan", {"seconds": 99})
        check("a bluetooth scan is capped at ten seconds",
              asked and asked[0][1].get("seconds") == 10, asked)

        # the toggle: over the board, and never quietly back to this machine
        tools.USE_BOARD_NET = True
        tools.ON_RADIO = lambda do, timeout=0, **a: {"ok": False,
                                                     "error": "not on a network"}
        out = tools.run_tool("The Investigator", "fetch_url",
                             {"url": "example.com"})
        check("with the toggle on and no board network, it refuses",
              "not on a network" in out and "example.com" not in out.lower()[:40],
              out[:80])
        check("and says how to undo it", "turn that setting off" in out)
    finally:
        tools.ON_RADIO = None
        tools.USE_BOARD_NET = False

    d = bits_desk.Desk()
    check("asking a board that isn't there is answered, not hung",
          d.radio("scan", timeout=1).get("ok") is False)


def test_undo_filing():
    """Filing writes down what it moved, so it can be put back."""
    print("undoing a filing run")
    import os
    import shutil
    import tempfile

    check("undo belongs to the Bit that did the moving",
          tools.TOOLS["undo_filing"].owner == "The Courier")
    check("and putting things back needs nobody's approval",
          tools.TOOLS["undo_filing"].tier not in tools.GATED)

    sand = tempfile.mkdtemp()
    keep = tools._load(tools.FILINGS_PATH, {"runs": []})
    try:
        for name in ("photo.jpg", "notes.pdf", "sheet.xlsx"):
            with open(os.path.join(sand, name), "w") as f:
                f.write("x")
        tools.run_tool("The Courier", "file_by_rule",
                       {"path": sand, "_approved": True})
        left = sorted(f for f in os.listdir(sand)
                      if os.path.isfile(os.path.join(sand, f)))
        check("filing moves them out", left == [], left)
        out = tools.run_tool("The Courier", "undo_filing", {})
        back = sorted(f for f in os.listdir(sand)
                      if os.path.isfile(os.path.join(sand, f)))
        check("and undo brings every one back",
              back == ["notes.pdf", "photo.jpg", "sheet.xlsx"], back)
        check("it says how many", "put 3 file(s) back" in out, out[:60])
        again = tools.run_tool("The Courier", "undo_filing", {})
        check("undoing twice moves nothing further",
              "put 0 file(s) back" in again, again[:60])
    finally:
        shutil.rmtree(sand, ignore_errors=True)
        tools._save(tools.FILINGS_PATH, keep)   # leave the real log alone


def test_board_labels():
    """The board's own text, checked here because it cannot be checked there.

    desk.py imports machine and tft, so it will not load on a PC - but the
    part that decides how wide a label is has nothing to do with hardware,
    and getting it wrong draws one label straight through another. It did:
    "hand over to a new cocarrying101 files".
    """
    print("what the board draws")
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "desk", "desk.py"), encoding="utf-8").read()
    ns = {}
    start = src.index("COLS = ")
    exec(src[start:src.index("class Desk:")], ns)              # noqa: S102
    fits, wrap, COLS = ns["fits"], ns["wrap"], ns["COLS"]
    W = 320

    def clash(left, right):
        l, r = fits(left, right)
        return 8 + 8 * len(l) > (W - 8 * len(r) - 8 if r else W)

    check("the strip's two labels never meet",
          not clash("hand over to a new computer", "101 files"))
    check("nor with a bigger card",
          not clash("hand over to a new computer", "999999 files"))
    check("nor with nothing on it",
          not clash("hand over to a new computer", ""))
    check("a long left label is cut, not overlapped",
          not clash("x" * 80, "101 files"))
    check("the network name fits the strip",
          len("set up a computer: BusyBusinessBits") <= COLS)
    check("wrapped body text fits the screen",
          all(len(l) <= COLS for l in wrap("a " * 200, COLS)))
    check("a word longer than the screen is broken, not dropped",
          "".join(wrap("z" * 100, COLS)) == "z" * 100)


def test_install_over_itself():
    print("installing over a running copy")
    import shutil
    import tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "desk"))
    import install_here as ih

    sand = tempfile.mkdtemp()
    try:
        src = os.path.join(sand, "from")
        dst = os.path.join(sand, "to")
        os.makedirs(src)
        os.makedirs(dst)
        for name in ("a.txt", "b.dll"):
            open(os.path.join(src, name), "w").write(name)
        # a leftover from a previous update, of the kind Windows forces when
        # a file is loaded and cannot be overwritten
        open(os.path.join(dst, "b.dll.old"), "w").write("stale")

        n = ih.copy(src, dst, "test")
        check("it copies what it should", n == 2, n)
        check("and does not copy a leftover across",
              not os.path.exists(os.path.join(dst, "b.dll.old.old")))

        gone = ih.sweep_old(dst)
        check("leftovers are swept", gone == 1, gone)
        check("and the real files stay",
              sorted(os.listdir(dst)) == ["a.txt", "b.dll"], os.listdir(dst))

        # place() must survive a target that already exists
        open(os.path.join(dst, "a.txt"), "w").write("old")
        ih.place(os.path.join(src, "a.txt"), os.path.join(dst, "a.txt"))
        check("an existing file is replaced",
              open(os.path.join(dst, "a.txt")).read() == "a.txt")
    finally:
        shutil.rmtree(sand, ignore_errors=True)


def test_approvals_bounded():
    print("the approval log stays a sensible size")
    keep = tools._approvals()
    try:
        n = tools.KEEP_DECIDED
        made = [{"id": "X%d" % i, "bit": "The Coder", "tool": "run_shell",
                 "args": {}, "summary": "s", "asked": "t",
                 "state": "approved"} for i in range(n + 60)]
        made += [{"id": "P1", "bit": "The Coder", "tool": "run_shell",
                  "args": {}, "summary": "s", "asked": "t", "state": "pending"}]
        tools._put_approvals({"seq": len(made), "items": list(made)})
        got = tools._approvals()["items"]
        check("a long history is trimmed", len(got) <= n + 1, len(got))
        check("the newest decisions are the ones kept",
              got[-2]["id"] == "X%d" % (n + 59), got[-2]["id"])
        check("nothing still pending is ever dropped",
              any(i["id"] == "P1" for i in got))
        # and a short log is left alone
        tools._put_approvals({"seq": 2, "items": made[:2]})
        check("a short history is untouched",
              len(tools._approvals()["items"]) == 2)
    finally:
        tools._put_approvals(keep)          # leave the real log as it was


def test_one_watcher():
    print("only one watcher")
    import bits_desk
    if sys.platform != "win32":
        check("not Windows - the guard stands aside", bits_desk.only_one())
        return
    # The installer starts a watcher and also registers one at login, so the
    # next reboot has two, and they fight over the one serial port. Whichever
    # wins decides whether START works, which looks like a board fault.
    name = "BitsSelftest%d" % os.getpid()
    check("the first one gets the port", bits_desk.only_one(name))
    check("a second one stands down", not bits_desk.only_one(name))
    check("an unrelated name is unaffected", bits_desk.only_one(name + "b"))


def test_settings():
    print("settings")
    import json
    import re
    import tempfile
    keys = set(core.DEFAULT_SETTINGS)
    check("there is one table of defaults", len(keys) >= 8, sorted(keys))

    real = core.SETTINGS_PATH
    try:
        p = os.path.join(tempfile.mkdtemp(), "s.json")
        core.SETTINGS_PATH = p
        check("a missing file gives every default",
              set(core.load_settings()) == keys)
        open(p, "w").write("{}")
        check("an empty file does too", set(core.load_settings()) == keys)
        open(p, "w").write(json.dumps({"api_key": "k", "wake": False}))
        s = core.load_settings()
        check("what is written wins", s["api_key"] == "k" and s["wake"] is False)
        check("and the rest still answer", s["ambient"] is True
              and s["board_net"] is False and s["voices"] is True)
        open(p, "w").write("not json at all {{{")
        check("a corrupt file falls back rather than throwing",
              set(core.load_settings()) == keys)
    finally:
        core.SETTINGS_PATH = real

    # The defaults used to be written out at each call site as well as here,
    # and the two could disagree without anything saying so. They still live
    # at the call sites - `.get(key, default)` reads better than a lookup - so
    # this is what keeps them honest.
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "busy_business_bits.py"),
               encoding="utf-8").read()
    lit = {"True": True, "False": False, '""': "", "{}": {}}
    drift, unknown = [], []
    for key, dflt in re.findall(
            r'settings\.get\(\s*"([a-z_]+)"\s*(?:,\s*(True|False|""|\{\}))?\s*\)',
            src):
        if key not in keys:
            unknown.append(key)
        elif dflt and lit[dflt] != core.DEFAULT_SETTINGS[key]:
            drift.append("%s: %s here, %r in the table"
                         % (key, dflt, core.DEFAULT_SETTINGS[key]))
    check("every setting read is one the table knows", not unknown, unknown)
    check("and no call site disagrees with it", not drift, drift)


def test_clipboard():
    print("the clipboard")
    if not tools.WINDOWS:
        check("not Windows - nothing to check here", True)
        return
    import subprocess
    import time
    seq = tools._clip_seq()
    check("the sequence number is readable", isinstance(seq, int), seq)
    mark = "bits selftest %d" % time.time()
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Set-Clipboard -Value '%s'" % mark], capture_output=True)
    tools._clip_last[0] = None
    check("what was copied comes back", tools._clip_text() == mark)
    check("and the tool agrees",
          tools.run_tool("The Coder", "read_clipboard", {}) == mark)
    # the whole point of the rewrite: no process per look. A PowerShell is a
    # quarter of a second, so anything in that range means we are shelling out.
    t0 = time.time()
    for _ in range(200):
        tools.run_tool("The Coder", "read_clipboard", {})
    each = (time.time() - t0) / 200
    check("an unchanged clipboard costs almost nothing", each < 0.005,
          "%.1f ms per look" % (each * 1000))
    tools._clip_last[0] = None
    t0 = time.time()
    tools._clip_text()
    check("and a real read is still not a process", time.time() - t0 < 0.05)


def main():
    for t in (test_room_rules, test_ask_bit, test_ownership, test_gate,
              test_summoning, test_sprites, test_routing, test_the_floor,
              test_layout, test_wake, test_desk, test_vault, test_radios,
              test_undo_filing, test_settings, test_approvals_bounded,
              test_board_labels, test_install_over_itself,
              test_one_watcher,
              test_clipboard, test_party):
        t()
    print()
    if FAILED:
        print("%d FAILED:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        return 1
    print("all good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
