# The Busy Business Bits

Nine pixel-art characters who live in borderless, always-on-top windows on your
desktop. Each one is a separate window with its own text box, its own synthesised
voice, and its own set of tools that act on the actual machine.

They are not nine chatbots. Each Bit owns exactly one verb — *measure, build,
move, dig, cut, schedule, orchestrate, remember, file* — and the tools that verb
implies. The Reaper can audit your disk and kill processes; he cannot touch your
calendar. The Secretary owns the calendar; she cannot delete anything. If two
Bits could plausibly own a job, the job is split wrong.

![The roster](Preview/bits-preview.png)

## The roster

| Bit | Verb | What it does on the machine |
|---|---|---|
| **Boss** | measure | Metric pulse with deltas, CSV/XLSX analysis, and the approval gate every other Bit passes through |
| **Coder** | build | Clipboard traceback catch, repo health, syntax checks, git status, shell |
| **Courier** | move | Downloads triage and filing by rule, delivery between folders and machines, email drafts |
| **Investigator** | dig | Fetches and reads web pages, extracts PDF text, hunts logs, builds dossiers from local files |
| **Reaper** | cut | Disk audit, duplicate detection, startup items, abandoned programs, process control |
| **Secretary** | schedule | Tasks with owners and dates, morning brief, end-of-day reckoning |
| **Wizard** | orchestrate | Summons and dismisses the other Bits on request, named multi-Bit routines, system state, installs |
| **Ghost** | remember | Finds what stopped moving and makes you give it a verdict: revive, kill or haunt |
| **Librarian** | file | Indexes documents, searches by name and content, tracks which version supersedes which |

A fuller breakdown of what each character owns and why — the four surfaces, the
routines, the build order — is in [docs/bit-duties.md](docs/bit-duties.md).

There's also a landing page at [docs/index.html](docs/index.html): one
self-contained file with all nine characters animating in it, no build step and
no external assets. Point GitHub Pages at the `/docs` folder to publish it.

## Running it

| File | What it does |
|---|---|
| `Demo The Bits.bat` | Canned lines, no API key needed. Try this first. |
| `Run The Bits.bat` | The real thing. Needs an API key. |
| `busy_business_bits.py --voices` | Plays every Bit's voice once, for tuning. |
| `busy_business_bits.py --song` | Plays the party tune once, for tuning. |
| `python bits_tools.py` | Prints the tool registry: who owns what, and which tools are gated. |
| `python selftest.py` | Checks the reply path, the gate, the sprites and the party. No API key needed. |

Needs Python 3.8+ and Pillow.

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Then double-click `Run The Bits.bat`, click **settings**, paste your API key,
click **fetch models**, **save**. Click a name in the roster to summon that Bit —
or just ask the Wizard, below.

Settings are written to `~/.busy_business_bits.json` and working state to
`~/.busy_business_bits/` — both deliberately outside the project folder, so
neither an API key nor a task list can end up in a commit.

## Who answers

The console is the Wizard's desk. A line typed into it with no name on it is
said to **him** — he reads it, and either answers it or hands it to whoever it
actually belongs to, fetching them if they aren't in the room. If he can't tell
whose it is, he gives it to the Boss and lets him rule.

```
You:     something keeps eating my disk
Wizard:  A hunger in the dark. Reaper, this is yours.
Reaper:  Fourteen gigabytes in Downloads hasn't moved since March.
```

Naming a Bit is you doing the routing yourself, and it still reaches them
directly — as does typing into a Bit's own text box, which is as addressed as it
gets. Everything else goes through the desk.

It used to fall to whoever happened to be on screen first instead, which made
the answer depend on summoning order: the same question got the Coder on Monday
and the Reaper on Tuesday. Handing your line on is *delivery*, not chatter, so
it happens even with *let Bits answer each other* switched off — what the Bit he
hands it to says next is chatter again, and that switch still governs it. Your
line goes up on the receiving Bit's card as it arrives, so its transcript reads
as a conversation with you rather than opening on an answer to nothing.

## Summoning

The roster down the left of the console is one way in. The other is to say so.

```
You:     Wizard, I need the Coder in here.
Wizard:  Okay... BAM! Coder, take a look at this.
Coder:   Give me the actual error, not the vibe of the error.
```

Summoning is a real tool the Wizard owns, not a line he says — he casts, the Bit
lands on the sparkle at the end of the cast, and the handoff waits for it, so the
arriving Bit picks the job up rather than the request falling on an empty desk.
He can send one back the same way (*"Wizard, the Reaper's done"*), and he'll tell
you plainly when he can't: no such Bit, already in the room, no sprites on disk.

You don't have to name him. Naming *anyone* is enough — a Bit who isn't on
screen is off screen, not unavailable, and that distinction is what the Wizard
is for. Ask for the Coder and the Coder is fetched, whether the desk is empty or
crowded. The question waits for the cast and goes up on the new card as it
lands, so what arrives is a Bit already holding the thing it was called for
rather than one blinking at an empty room.

The Bits do it to each other too, which is what makes the chains work. The
Courier saying *"Librarian, this one's yours"* fetches the Librarian; she reads
the request off the room and files it. Before this, a handoff to anyone not
already on screen simply fell on the floor — which quietly broke every routine
started from an empty desk. Only the first name in a line summons, and only as
deep as `MAX_CHAIN`, so a Bit reeling off the roster doesn't fill the desktop
with it. Turn Bit-to-Bit chatter off with *let Bits answer each other* in
settings; the Wizard passing you on is delivery and keeps working either way.

This works in `Demo The Bits.bat` too, with no API key — it's the one thing in
demo mode that actually happens rather than being canned.

## The four surfaces

Every Bit exposes the same four, and the ones it can't fill it simply doesn't have.

- **Ambient** — it watches something and speaks unprompted.
- **Drop** — drag a file, folder or URL onto its card.
- **Ask** — type or speak into its box.
- **Scope** — what it's pointed at, set by where you put it.

Scope is the interesting one. A Bit's working folder comes from where it physically
sits, so the same character behaves differently on each screen with no configuration:
the Coder on your code monitor watches that repo, and dragging a Bit onto an open
folder window makes it adopt that folder until dismissed.

## Speaking first

Tools let a Bit answer when spoken to; the watchers in `bits_ambient.py` let one
speak without being asked. Each watcher belongs to a single Bit and returns
something only when the world has actually changed — which is almost never, and
that's the point. A character who comments on everything gets muted within a day.

| Watcher | Bit | Fires when |
|---|---|---|
| clipboard | Coder | You copy something that looks like an error — a traceback, a stack frame, a compiler code. Ordinary copies are ignored. |
| downloads | Courier | New files land in Downloads |
| brief | Secretary | First time you're at the desk each day, and only if something is actually due |
| due | Secretary | A task falls due or goes past due |
| approvals | Boss | A Bit queues something needing his nod |
| repo | Coder | The build breaks, or work sits uncommitted for days |
| haunt | Ghost | Occasionally, one abandoned thing — never the same one twice |

Four rules keep it bearable: only summoned Bits speak, nothing fires twice (keys
are persisted, so it survives a restart), a global cooldown means two watchers
going off together still produce one line, and a watcher's first poll records the
world rather than announcing all of it. Turn the lot off with *let Bits speak up
on their own* in settings.

## Permissions and the gate

The Boss holds the license in the fiction, so he holds the permission gate in the
architecture. Tools are tiered, and the gated tiers **do not run when called** —
they queue an approval that has to be cleared before anything happens.

Hitting the gate fetches him, and that one doesn't need anybody to say his
name. A ruling can't be given from off screen, so the Wizard casts for the Boss
the moment a Bit queues something, and the queuing Bit is told he's on his way —
it puts the case to him and he lands already holding it. Every other Bit is
fetched by being named; the Boss is fetched by the gate itself.

| Tier | Bits | Rule |
|---|---|---|
| Read | Investigator, Ghost, Librarian, Boss | Free rein. Looks at anything, changes nothing. |
| Write | Secretary, Librarian, Coder, Wizard | Creates and edits inside its scope. Reversible. Summoning is here: it changes the desktop, and it undoes with a word. |
| Execute | Coder, Wizard | Shell, installs, system settings. Gated. |
| Send | Courier | Anything leaving the machine. Gated. |
| Destroy | Reaper, Librarian, Courier | Proposes only. Gated, and deletions move to a dated graveyard rather than vanishing. |

This is what makes it safe to leave the characters running unattended all day.
A Bit can also only call tools it owns — asking the Ghost to delete something
gets you *"that isn't your job — delete_paths belongs to The Reaper."*

## Routines

The value isn't nine assistants, it's the chains. The Wizard fires these:

| Routine | Chain |
|---|---|
| **morning** | Secretary's brief → Boss's pulse → Ghost adds one thing you dropped |
| **triage** | Courier sorts what landed → Librarian files and indexes → Reaper flags what shouldn't have been kept |
| **pre-meeting** | Secretary's agenda → Investigator's dossier → Librarian's documents |
| **end of day** | Secretary recaps → Coder reports uncommitted work → Ghost logs what slipped |
| **reckoning** | Reaper's cut list → Ghost's open loops → Boss approves or refuses → Secretary schedules the survivors |
| **ship it** | Coder builds and commits → Librarian files → Courier delivers → Secretary logs it done |

## Animation

Sprites are discovered off disk by filename, so dropping a new GIF into a Bit's
`GIFs and PNG` folder is enough — no code change. Recognised keywords:

`idle` → resting · `talk` → speaking · `snap_talk` → emphatic speaking ·
`snap` / `spell` / `cast` → summon flourish (the Wizard's only) ·
`typing` / `investigate` / `deliver` / `swing` / `haunt` / `float` / `shelve` /
`read` → the "thinking" state while waiting on a reply

A state with no matching file falls back to `idle` — the Librarian ships no
thinking sprite, so she simply sits at her counter while she works. Only the Wizard snaps; the
Bit he summons simply arrives — and it arrives on the BAM, once his cast has
played out in full. The wait is read off the GIF rather than guessed, so
replacing the art changes the timing with it.

## Voices

Each Bit speaks in garbled synthesised syllables — pitch, waveform, cadence,
vibrato and grit tuned per character in `bits_core.py` under `BITS[...]["voice"]`.
The text types out in time with the audio, and every line is capped at 3.4 seconds
so nobody drones. Pure stdlib synthesis; no audio library.

- **Boss** — 132 Hz square, slow, gravelly
- **Coder** — 268 Hz square, fast and clipped
- **Courier** — 312 Hz saw, bright and breathless
- **Investigator** — 196 Hz triangle, measured
- **Reaper** — 86 Hz sine + noise, very slow and dark
- **Secretary** — 346 Hz sine, high and lilting
- **Wizard** — 214 Hz saw, heavy vibrato, warbly

## The party

Type **Up Up Down Down Left Right Left Right B A Enter** anywhere in the app and
everyone stops working: a chiptune plays and every Bit on screen dances, hopping
and swaying a beat behind the one before it while the Wizard casts in the
console. It runs about thirteen seconds and then everybody lands back exactly
where they were standing.

The tune is synthesised the same way the voices are — square lead, triangle
bass, noise for the kit, written out as notes in `bits_core.py` under
`PARTY_LEAD` — so there's still no audio file anywhere in the project. It's
rendered once on a background thread at startup and cached, and it respects the
**voices** setting: turn those off and the room dances in silence.

## Giving a Bit its own workflow

Any character can be driven by its own n8n webhook instead of the shared API key,
which is how you give one its own tools, data and personality. In **settings**,
under *Per-Bit webhooks*, paste a URL next to a Bit. Blank means it keeps using
the shared key; mixed is fine.

Your workflow receives a POST:

```json
{
  "bit": "The Boss",
  "short": "Boss",
  "speaker": "You",
  "text": "what is the margin?",
  "present": ["The Boss", "The Coder", "The Wizard"],
  "room_log": [{"speaker": "You", "text": "..."}]
}
```

`text` is the line being answered and `room_log` is the last 24 turns, so the
workflow has context without keeping its own. The reply can come back as plain
text or as JSON with any of `reply` / `text` / `output` / `message` / `response` /
`content` / `answer` / `result`, including n8n's `[{"json": {...}}]` wrapper.
The first string found wins; an empty body or an error is reported in that Bit's
window rather than silently swallowed.

Since personality lives in your workflow, the built-in persona and room rules are
*not* sent — that Bit is entirely yours. The voice and sprites still work.

## Files

| File | What's in it |
|---|---|
| `busy_business_bits.py` | Windows, animation, routing, UI |
| `bits_core.py` | Roster and personalities, sprite discovery, voice synthesis, API client |
| `bits_tools.py` | The operational layer: every tool, the ownership map, the gate |
| `bits_ambient.py` | The watchers that let a Bit speak first |
| `make_sprites.py` | Builds the Ghost and Librarian art |

## Generated sprites

The Ghost and Librarian had no hand-drawn art, so theirs is generated by
`make_sprites.py` on the same 64×64 cell grid as the rest of the roster at 16px
per cell — frame, palette, title font, sizes and frame timings all match.

```
python make_sprites.py             # rebuild every Ghost + Librarian file
python make_sprites.py --preview   # just the two still cards
```

Edit the character grids near the bottom of that file and re-run; they're plain
strings with one letter per colour. Dropping real GIFs into either
`GIFs and PNG` folder overrides them with no code change.

## Licence

MIT. See [LICENSE](LICENSE).
