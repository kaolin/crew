# crew

A **status console + dispatcher** for the Claude Code sessions you run by hand
across your iTerm2 windows and macOS Spaces. crew does *not* spawn or own sessions
(that's what Anthropic's native `claude agents` / Agent view does, and what Claude
Squad / Sculptor / vibe-kanban do) — it **attaches to the ones you already have**
and keeps your layout untouched. Think *htop + a remote for your fleet of claudes.*

It's a thin skin over one native command:

```
claude agents --json     # Claude Code >= 2.1.139; every running session,
                         # interactive ones included, with cwd/sessionId/name/status
```

## Install

```
git clone https://github.com/kaolin/crew ~/dev/crew   # (replace with your fork)
~/dev/crew/crew setup     # symlinks crew onto PATH + installs the snapshot agent
crew doctor               # verify deps
```

Or via Homebrew (see the tap):

```
brew install --HEAD kaolin/tap/crew
brew services start crew  # the 5-minute snapshot agent
```

## Use

```
crew                      # status — project-grouped, needs-you (waiting) floated up
crew status --all         # include completed sessions
crew peek izzit           # read a session's screen (read-only, safe)
crew tell izzit "run the tests"   # type a prompt into an IDLE session and submit
crew jump izzit           # switch to the session's Space and front its window
crew goto izzit           # same, explicit
crew snapshot             # save ~/.crew/latest.json — the reboot map (incl. Space)
crew restore              # DRY-RUN: show what it would resume + where
crew restore --go         # for each session: switch to its Space -> open window -> resume
crew setup / crew doctor  # (re)install / health-check
```

`<name>` resolves by exact name, name-prefix, project, or substring. `tell` refuses
a `busy` session unless `--force` (don't stomp a claude mid-turn).

## How it works

- **Awareness** comes from `claude agents --json` — no scraping, no hooks.
- **Dispatch / jump** join a session's `pid -> tty -> the live iTerm2 session`, then
  act in place via AppleScript (`write text`, `select`, `contents`).
- **Reboot map:** a launchd agent runs `crew snapshot` every 5 min into
  `~/.crew/latest.json` (with a shutdown-safe guard + timestamped history). After a
  reboot, `crew restore --go` reopens + places + resumes every session. Session state
  lives on disk (`~/.claude/projects/…`), so nothing is lost.

## Spaces & spatial restore (optional: spacetag)

crew keeps your macOS-Space layout by delegating all Space navigation to
**[spacetags](https://spacetags.app/)** — a macOS menubar app that labels
each Space by project. With it, `crew jump` and `crew restore` switch to the right
Space; crew maps a session to a Space by matching its project to the Space's tag.

Without spacetag, crew still does everything else — status, dispatch, and
conversation restore — it just won't place windows on their Spaces.

> spacetags: **https://spacetags.app/** — the piece that makes reboot
> restore rebuild your *whole* spatial layout, not just the conversations.

## Test

```
./test.sh    # runs against fixtures — no live sessions needed
```

stdlib Python 3 only; no pip/conda env. macOS + iTerm2.

## License

MIT © Kaolin Fire
