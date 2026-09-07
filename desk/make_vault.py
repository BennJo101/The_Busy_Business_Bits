"""Build the Bits' own Obsidian vault - the one that travels on the card.

    python desk/make_vault.py                  build it in the default place
    python desk/make_vault.py --where DIR      build it somewhere else

The Bits already work inside whatever Obsidian vault the project sits in. This
is a second, portable one: it goes on the SD card, so a board carried to
another machine brings the Bits' notes, reports and rulings with it.

The nine notes are generated from the roster and the tool registry rather than
written out by hand, so a Bit that gains a tool gains a line here too, and the
vault cannot quietly drift out of step with the app.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT)

import bits_core as core          # noqa: E402
import bits_tools as tools        # noqa: E402

DEFAULT = os.path.join(os.path.expanduser("~"), "Busy Business Bits Vault")

FOLDERS = ("Bits", "Reports", "Notes", "Tasks", "Rulings")

# Enough config that it opens as a vault rather than asking to be set up.
OBSIDIAN = {
    "app.json": {"attachmentFolderPath": "Notes", "alwaysUpdateLinks": True,
                 "newFileLocation": "folder", "newFileFolderPath": "Notes"},
    "appearance.json": {"accentColor": "#c8a24a", "theme": "obsidian"},
    "core-plugins.json": ["file-explorer", "global-search", "switcher", "graph",
                          "backlink", "outgoing-link", "tag-pane", "daily-notes",
                          "page-preview", "templates", "note-composer",
                          "command-palette", "outline", "word-count"],
}

HOME = """# The Busy Business Bits

This is the Bits' own vault. It travels on the desk unit's SD card, so the
notes, reports and rulings go where the board goes.

## The roster

{roster}

## Where things land

| Folder | What goes in it |
|---|---|
| `Bits/` | One note per character - what it owns and what it can do |
| `Reports/` | Long tool output. A Bit that finds forty things writes them here and says the verdict out loud |
| `Notes/` | Anything filed by hand, and the Librarian's filing |
| `Tasks/` | What the Secretary is holding you to |
| `Rulings/` | What the Boss approved or refused, and when |

Nothing in here is written by the app unless a Bit puts it there. Settings and
machine state stay in `~/.busy_business_bits/` - they belong to the computer,
not to the card.
"""

BIT_NOTE = """---
bit: {name}
verb: {verb}
colour: "{colour}"
---
# {short}

*{verb}* - {blurb}

{persona}

## What it can do here

{tools}

## Notes

"""

READING = """# Reading this vault

It is a folder of Markdown. Any editor will do; Obsidian is what it is laid out
for - **File > Open folder as vault**, and point it here.

## If this machine has no Obsidian

Obsidian does not travel on the card by default, and it cannot travel through
the board: it is about 290MB, and the desk unit's serial link moves 7KB a
second, which is eleven and a half hours. The vault itself is kilobytes and
comes across in seconds.

Two ways round it, if you want the app on the card too:

- Put the card in a card reader and copy an Obsidian install onto it directly.
  It is an Electron app, so a copied install folder runs from where it sits;
  `--user-data-dir` pointing at a folder on the card takes its settings along.
  *(Not tested here - this card has only ever been in the board.)*
- Or read them with anything else. They are plain Markdown and were written to
  stay readable in Notepad.

## What the Bits put here

`Reports/` fills up on its own: any tool that finds more than a screenful writes
the detail here and the Bit says only the verdict out loud. The rest is yours.
"""

VERBS = {"The Boss": "measure", "The Coder": "build", "The Courier": "move",
         "The Investigator": "dig", "The Reaper": "cut",
         "The Secretary": "schedule", "The Wizard": "orchestrate",
         "The Ghost": "remember", "The Librarian": "file"}


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build(where):
    os.makedirs(os.path.join(where, ".obsidian"), exist_ok=True)
    for name, blob in OBSIDIAN.items():
        write(os.path.join(where, ".obsidian", name),
              json.dumps(blob, indent=2) + "\n")
    for folder in FOLDERS:
        os.makedirs(os.path.join(where, folder), exist_ok=True)
        keep = os.path.join(folder, "README.md")
        if not os.path.exists(os.path.join(where, keep)):
            write(os.path.join(where, keep),
                  "Anything the Bits put in `%s/` lands here.\n" % folder)

    roster = []
    for name, cfg in core.BITS.items():
        short = name.replace("The ", "")
        verb = VERBS.get(name, "")
        roster.append("- [[%s]] - *%s* - %s" % (short, verb, cfg["blurb"]))
        mine = sorted(t.name for t in tools.TOOLS.values() if t.owner == name)
        lines = []
        for tool_name in mine:
            t = tools.TOOLS[tool_name]
            gate = "  *(needs the Boss)*" if t.tier in tools.GATED else ""
            lines.append("- `%s` - %s%s" % (tool_name, t.desc.split(".")[0], gate))
        write(os.path.join(where, "Bits", short + ".md"),
              BIT_NOTE.format(name=name, short=short, verb=verb,
                              colour=cfg["color"], blurb=cfg["blurb"],
                              persona=cfg["persona"].split(". ", 1)[-1][:400],
                              tools="\n".join(lines) or "- nothing yet"))
    write(os.path.join(where, "Home.md"),
          HOME.format(roster="\n".join(roster)))
    write(os.path.join(where, "Reading this vault.md"), READING)
    return where


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--where", default=DEFAULT)
    args = ap.parse_args()
    where = build(args.where)
    n = sum(len(f) for _, _, f in os.walk(where))
    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(where) for f in fs)
    print("vault built: %s" % where)
    print("  %d files, %.1f KB - open it in Obsidian with File > Open folder as vault"
          % (n, size / 1024.0))


if __name__ == "__main__":
    main()
