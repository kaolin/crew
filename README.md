# crew

**htop + a remote for the Claude Code sessions you already have open.**

If you keep a lot of `claude` sessions running by hand — scattered across terminal
windows and macOS Spaces — crew gives you one place to *see* them, *drive* them, and
bring them all back after a reboot.

```
  5 sessions   ·   1 waiting   ·   2 busy   ·   2 idle

  api   ~/src/api
    ● waiting   api-4f       2d3h   ⟵ QUESTION FOR YOU
    ○ idle      api-90       2d3h

  web   ~/src/web
    ▶ busy      web-1c       6h12m
    ▶ busy      web-e7       6h12m   ⟵ at prompt (bg task)

  infra   ~/src/infra
    ○ idle      infra-b2     4d1h
```

Needs-you first: the session blocked on a question sorts above everything else, and
`crew pending` will tell you what it's actually asking without switching to it.

## What it is — and isn't

crew does **not** spawn, own, or sandbox sessions. Claude Code's own Agent view does
that, as do Claude Squad, Sculptor and vibe-kanban — most of which run sessions in
their own tmux, git worktrees or containers.

crew is the opposite bet: **your hand-arranged sessions are the source of truth.** It
attaches to what's already running, never rearranges your windows, and stays a thin
layer over `claude agents --json` + iTerm2. If you like tools that manage your sessions
for you, one of the above is a better fit. If you've already got your fleet exactly how
you want it and just want a console over it, that's this.

**Requirements:** macOS, iTerm2, and the `claude` CLI at **≥ 2.1.139** (that's the
version that added `claude agents --json`). tmux sessions are visible and drivable too;
window/Space operations are iTerm2-only. Python 3 stdlib — no pip, no venv.

## Install

```sh
brew install kaolin/tap/crew
crew                          # your fleet, grouped by project, needs-you first
brew services start crew      # optional: auto-snapshot every 5 min (reboot safety)
```

The formula installs the `crew` CLI. For the phone hub and the alert daemon — which are
separate pieces that live in this repo — clone it instead:

```sh
git clone https://github.com/kaolin/crew && crew/crew setup
```

## Commands

| command | what it does |
|---|---|
| `crew` · `crew status` | fleet overview, grouped by project, needs-you first |
| `crew peek <name>` | read a session's recent conversation (any terminal; `--screen` for raw TUI) |
| `crew pending [name]` | what a blocked session needs from you — a question vs a permission prompt |
| `crew ask <name> "…"` | send a prompt and **wait for the reply** (round-trip) |
| `crew tell <name> "…"` | fire-and-forget a prompt to an **idle** session |
| `crew keys <name> down enter` | raw keystrokes, no Enter appended — drives multi-select pickers |
| `crew at-prompt <name>` | exit 0 if it'll take input now (`busy` can just mean a background task) |
| `crew artifacts` | every live artifact URL your fleet has published |
| `crew jump <name>` | go to where its window *actually* is (+ front it) |
| `crew goto <name>` · `crew where <name>` | go to its *tagged* Space · show actual vs. tagged |
| `crew snapshot` · `crew restore` | save / rebuild the whole layout across a reboot |
| `crew setup` · `crew doctor` | install onto PATH + agent / health-check |

`<name>` resolves by exact name, name-prefix, project, or substring.

## Two things it knows that the raw status doesn't

**`waiting` doesn't tell you who's blocked on what.** The CLI reports every blocked
session as "permission prompt" — whether it's a tool asking to run `rm`, or a question
meant for *you* with four options. `crew pending` reads the transcript (falling back to
scraping the terminal, because the prompt often goes up before it's logged) and tells
them apart. `crew keys` then answers a picker without submitting a half-filled form.

**`busy` doesn't mean working.** A session stays busy for as long as *any* background
shell or monitor is alive, long after the model has finished. crew scrapes for the
difference — a live spinner and "esc to interrupt" mean a turn is running; their absence
with an input box means it'll take your message right now — and marks those
`⟵ at prompt (bg task)` instead of letting them look hung.

## How it works

- **Awareness** — `claude agents --json` reports every running session, interactive ones
  included, with cwd / sessionId / name / live status. No hooks, no wrapper process.
- **Dispatch & jump** — resolve a session, join `pid → tty → the live iTerm2 session`,
  and act in place via AppleScript.
- **Reboot map** — a launchd agent snapshots the fleet every 5 min into
  `~/.crew/latest.json` (shutdown-safe, history in `~/.crew/history/`). After a reboot,
  `crew restore --go` reopens, places and resumes every session. Conversation state
  already lives on disk in `~/.claude/projects/`, so nothing is lost.

## Reach your fleet from your phone (optional)

Run one session as a **hub**: Telegram messages from your phone land in it, it drives
crew on your behalf, and a launchd daemon pushes back "finished" and "needs you" alerts.
Useful for checking a long build, unblocking a session, or starting something while
you're out.

```sh
cp hub-protocol.example.md ~/.claude/hub-protocol.md   # edit it — this is the hub's brief
./hub
```

Both files ship in the repo, so this path needs the clone rather than the brew formula.
Full setup — creating the bot, the allowlist, the launchd pinger — plus the two gotchas
that cost real messages (Telegram allows exactly one `getUpdates` consumer per token;
and delivery ≠ handling, which is why there's a separate `actioned.cursor`) is in
**[docs/reach-your-fleet-from-your-phone.md](docs/reach-your-fleet-from-your-phone.md)**.

The alert daemon has no dependency on crew — it only reads `claude agents --json` and
the plugin's token file, so it works for anyone running the telegram plugin.

## Spaces (optional)

crew delegates all macOS-Space navigation to **[spacetags](https://spacetags.app/)**, a
menubar app that labels each Space by project. crew maps a session to a Space by
matching its project to the Space's tag; spacetags switches there. Without it crew still
does everything else — status, dispatch, peek, and conversation restore — it just won't
place windows on Spaces.

## Test

```sh
./test.sh                                        # fixtures; no live sessions needed
for t in pinger/test_*.py; do python3 "$t"; done # the alert daemon's own suite
```

## License

MIT © Kaolin Fire
