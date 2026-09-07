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


def main():
    for t in (test_room_rules, test_ask_bit, test_ownership, test_gate,
              test_summoning, test_sprites, test_routing, test_the_floor,
              test_layout, test_wake, test_desk, test_vault, test_radios,
              test_party):
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
