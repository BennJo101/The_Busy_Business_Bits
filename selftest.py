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


def main():
    for t in (test_room_rules, test_ask_bit, test_ownership, test_gate,
              test_summoning, test_sprites):
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
