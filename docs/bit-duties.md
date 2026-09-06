# The Bits — Operational Duties

What each Bit actually *does* on the machine, not just what it says. One rule holds the
whole design together:

> **One Bit, one verb.** If two Bits could plausibly own a job, the job is split wrong.

Nine verbs: *measure, build, move, dig, cut, schedule, orchestrate, remember, file.*

## The four ways a Bit works

Every Bit exposes the same four surfaces. A Bit that can't fill one just doesn't have it.

| Surface | What it means |
|---|---|
| **Ambient** | It watches something and speaks unprompted. The only reason it earns desktop space. |
| **Drop** | Drag a file, folder, URL or selected text onto its card. Each Bit does one thing with what it's handed. |
| **Ask** | Type or mic into its box. Natural language, but it resolves to real actions. |
| **Scope** | What it's pointed at — set by where you put it. See *Placement* below. |

## Placement — "any device I place them on"

The Bit's scope comes from where it physically sits, so the same character behaves
differently on each screen without any reconfiguration:

- **Per-monitor.** Coder on the code monitor watches that repo. Secretary on the comms
  monitor watches that calendar. Position is saved per-Bit, per-machine.
- **Per-machine.** Work laptop vs. home desktop = separate scope profiles under one
  identity. Courier is the Bit that carries state between them.
- **Drop-on-window.** Drag a Bit onto an open Explorer window and it adopts that folder
  as its working scope until dismissed. Reaper dropped on `Downloads` audits `Downloads`.
- **Headless.** A Bit with no window still runs its ambient duties and queues what it
  wanted to say. Summon it and it delivers the backlog.

---

## The Boss — *measure*

Holds the license, so he also holds the **approval gate**. Anything destructive or costly
another Bit proposes comes to him first. That's the mechanical reason he exists, beyond
the numbers.

- **Ambient** — Monday rollup and a daily one-line pulse: the 3–5 numbers you told him to
  care about, with the delta. Silent when nothing moved more than your threshold.
- **Drop** — CSV / XLSX / a folder of invoices → totals, trend, outliers, the number
  you'd actually be asked about. Not a chart dump; a verdict with the numbers under it.
- **Ask** — "what did I bill in August", "what's my hourly on this client", "is this
  worth doing at £X". Runway, margin, unit economics against real files.
- **Gate** — Reaper's deletions, Courier's outbound sends, Wizard's installs. He shows
  the diff and asks once.

## The Coder — *build*

The only Bit allowed to execute a shell. Everything else routes through him.

- **Ambient** — watches the repo / project folder in scope: failing builds, uncommitted
  work sat for days, a dependency that just broke, a script that exited non-zero. Speaks
  when something breaks, not when it succeeds.
- **Drop** — any code or config file → what it does, what's wrong with it, the fix as a
  diff. A log or stack trace → root cause and the line.
- **Ask** — run the script, fix the env, make the venv, write the small tool, explain the
  error. Git: status, branch, commit, push.
- **Clipboard** — copy a traceback anywhere on the machine and he offers the fix
  unprompted. This one is worth more than the rest of his features combined.

## The Courier — *move*

Every crossing of a boundary — folder to folder, machine to machine, you to someone else
— is his. He's the only Bit with outbound network rights.

- **Ambient** — watches `Downloads` and the desktop. Files land, he sorts them by rule
  (invoices → the invoice folder, renamed to convention) and reports what he moved.
- **Drop** — a file → "where's it going?" → email it, Drive it, put it on the other
  machine, push it to your phone, USB, print it. One drag replaces the whole ritual.
- **Ask** — "send the quote to X", "get this on the laptop", "chase the invoice from
  last Tuesday". He drafts, shows you, sends on your word (via Boss for anything external).
- **Sync** — he carries Bit state, notes and settings between your devices. When you place
  a Bit on a new machine, Courier is what makes it the *same* Bit.

## The Investigator — *dig*

Points **outward**. Anything he tells you came from outside your machine. (Inside is the
Librarian — that's the whole boundary between them.)

- **Ambient** — pre-meeting dossier fired ~20 min before any calendar event with an
  external attendee: who they are, the company, recent news, your last dealings with them.
- **Drop** — a URL, PDF or company name → teardown. Claims vs. evidence, pricing, who's
  behind it, what doesn't add up.
- **Ask** — supplier checks, competitor pricing, "is this legit", "what's the going rate
  for X", due diligence before you sign anything.
- **Root cause** — hand him a recurring problem and he goes through logs, history and
  files until he can say *why*, not *what*. He'll tell you what he'd check next.

## The Reaper — *cut*

Subtraction, machine-wide. Proposes; never acts without the Boss's gate and your word.

- **Ambient** — weekly reckoning: apps not opened in 90 days, startup entries costing you
  boot time, duplicate files, caches over a threshold, recurring meetings that produce no
  artefact, subscriptions still billing.
- **Drop** — a folder → what in here is dead, with sizes and last-touched dates, sorted
  by how little you'd miss it.
- **Ask** — "what should I stop doing", "kill the stuck process", "what's eating the
  disk", "which of these 40 tasks is never happening".
- **The question** — his one contribution to any planning conversation: *what happens if
  we simply do not?* Applied to features, projects, meetings and commitments.

## The Secretary — *schedule*

Owns time and commitments. The calendar and the task file are hers; nobody else writes
to them.

- **Ambient** — morning brief at login (today's shape, what's due, what you promised),
  10-minute heads-up before events, end-of-day recap of what you said you'd do and
  didn't. Handoff to Ghost for anything that survives a week.
- **Drop** — meeting notes, a transcript, a rambling voice memo → owners, actions, dates,
  written into the task file and the calendar.
- **Ask** — "what's my Thursday look like", "move the 2pm", "book an hour for X",
  "what did we agree with that client in June".
- **Institutional memory** — she's the one who says *you already decided this in March*.

## The Wizard — *orchestrate*

Not a worker. The control surface — he lives in the console and runs the machine that
runs the Bits.

- **Summoning** — the roster buttons are one way in; asking him is the other. "Wizard,
  get me the Coder", or just "Coder, look at this" into an empty room, and he casts for
  real, then hands the job over by name so the Bit lands already holding it. "Send the
  Reaper away" puts one back.
- **Routines** — named multi-Bit macros on one word. "Okay… BAM!" and a whole sequence
  fires. See *Routines* below.
- **Profiles** — desktop states. *Work* summons Boss, Coder, Secretary and opens the
  app set. *Deep* dismisses everyone but Coder and mutes ambient. *Shutdown* runs the
  end-of-day chain and clears the screen.
- **Install & wire** — dependencies, API keys, n8n webhook URLs, new Bits, new sprites.
  Anything that changes the system rather than using it.
- **Routing** — an unaddressed request goes to whoever actually owns the verb. He's the
  fallback when you don't know who to ask, and with nobody on screen he's the one who
  answers, because he can fetch whoever the request was really for.

## The Ghost — *remember what you dropped*

The counterweight to the Reaper. Reaper wants it dead; Ghost wants you to *admit* it's
dead. Between them nothing rots silently.

- **Ambient** — surfaces one abandoned thing at a quiet moment, never the same thing twice
  in a session: unanswered email past 5 days, a draft never sent, a branch never merged, a
  note untouched in 60 days, a download never opened, a task that's been rolling over for
  a month.
- **Drop** — a folder or project → what died in here and when it stopped moving.
- **Ask** — "what am I forgetting", "what's still open with this client", "what did I
  abandon last quarter".
- **The verdict** — every ghost gets one of three: **revive** (Secretary schedules it),
  **kill** (Reaper takes it), or **haunt** (it comes back later). No fourth option, which
  is the point.

## The Librarian — *file*

Points **inward**. The vault, the drives, the documents. Every answer comes with a path.

- **Ambient** — quietly indexes new and changed documents; flags naming-convention breaks
  and the moment two versions of the same document diverge.
- **Drop** — any document → filed to the right place, renamed to convention, indexed,
  cross-linked to what it relates to. One drag, correctly filed forever.
- **Ask** — "where's the signed version", "which contract is current", "what did we call
  this before", "find everything about X". Search across vault, Drive and disk at once.
- **Supersession** — he tracks which version replaces which, so *current* is a fact he
  knows rather than a guess you make from filenames.

---

## Routines — the Bits working as a crew

The value isn't nine assistants, it's the chains. Wizard fires these:

| Routine | Chain |
|---|---|
| **Morning** | Secretary's brief → Boss's pulse → Investigator's dossier if there's an external meeting → Ghost adds one thing you dropped. |
| **Triage** | Courier sorts what landed → Librarian files and indexes it → Reaper flags what shouldn't have been kept. |
| **Pre-meeting** | Secretary gives the agenda and last decisions → Investigator gives the dossier → Librarian pulls the relevant documents. |
| **End of day** | Secretary recaps commitments → Coder reports uncommitted work → Ghost logs what slipped. |
| **Weekly reckoning** | Reaper's cut list → Ghost's abandoned list → Boss approves or refuses each → Secretary schedules the survivors. |
| **Ship it** | Coder builds and commits → Librarian files the artefacts → Courier delivers → Secretary logs it done. |

## Permission tiers

The gate is what makes it safe to leave these running unattended.

| Tier | Bits | Rule |
|---|---|---|
| **Read** | Investigator, Ghost, Librarian, Boss | Free rein. Can look at anything, change nothing. |
| **Write** | Secretary, Librarian, Coder, Wizard | Create and edit inside their scope. Reversible by definition. Summoning sits here: it changes the desktop, and it undoes with a word. |
| **Execute** | Coder, Wizard | Shell, installs, system settings. Shows the command before running it. |
| **Send** | Courier | Anything leaving the machine. Always previewed, always Boss-gated. |
| **Destroy** | Reaper | Proposes only. Never acts without Boss gate *and* your explicit word. |

## Build order

Each of these is useful alone, so build in this order and you get value at every step:

1. **Coder clipboard-catch** — copy a traceback, get the fix. Smallest thing, biggest daily payoff.
2. **Courier's Downloads watcher** — file-by-rule. Immediately visible, zero risk.
3. **Secretary's calendar** — morning brief and pre-event heads-up (Google Calendar is already available to this project).
4. **Librarian's index** — the vault first, then the drives. Everything after this gets better because of it.
5. **Boss's pulse + gate** — once anything can act, the gate has to exist.
6. **Ghost and Reaper** — they need 3–4 weeks of accumulated history to be worth anything. Build them last, deliberately.

## How each is wired

Your app already supports both routes; the split falls out naturally:

- **Local Python tools** (in `bits_core.py`, called by the model) — anything touching the
  filesystem, the shell, the clipboard or the OS: Coder, Reaper, Librarian, Wizard, and
  Courier's local half.
- **n8n webhooks** (per-Bit, already in settings) — anything touching an external service:
  Secretary's calendar, Courier's send half, Investigator's research, Boss's data pulls.
  These get their own tools and personality inside the workflow, which is what the
  per-Bit webhook was built for.
- **Both** — Courier and Boss straddle it. Give them a local tool that calls their own
  webhook, so the Bit doesn't have to know which side it's on.
