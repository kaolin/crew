# hub/ — helper scripts the Telegram hub session runs

Launched from `~/.crew/hub/` (a symlink here) so they survive the /private/tmp reaper.

### Approving prompts on a worker's behalf

- `fast-approve-hubroute.sh <session-name> [minutes]` — **the current one.** Watches a session,
  recognises each prompt shape, and answers the safe ones. Anything destructive-looking is
  escalated to the hub (`crew escalate --no-push`) and then *held*: it never presses a key on
  that prompt, and it keeps watching, so the rest of the session's ordinary prompts still clear.
  Default window 25 min; pass `480` for a working day. Logs to
  `~/.crew/hub/fast-approve-<name>.log`.
  Four things it knows that cost real time to learn, all in the comments: a prompt's question
  line uses NUL bytes where spaces appear; WebFetch and file-edit prompts are their own shapes;
  escalating used to `exit`, which left the whole session unattended; and docker's
  `--force-recreate` is not a destructive `--force`.
- `fast-approve.sh <session-name> [minutes]` — the pre-hub-routing original. Same recognition,
  no escalation path.
- `rearm-approvers.sh` — re-arm approvers whose window has expired.
- `confirm-model-switch.sh` — clears the "Switch model?" dialog fleet-wide.

**Counting them:** an approver is a process whose *parent is not itself an approver*. Do not
filter on `PPID == 1` — a freshly `nohup`-ed approver keeps the spawning shell as its parent
until that shell exits, so a PPID-1 filter reports zero while several are running, and the
obvious next move is to start duplicates that then both press Enter. The script's own command
substitutions *do* have an approver as their parent, which is what excludes them. (`setsid`
does not exist on macOS.)

### Everything else

- `fanout.sh <needle> <msgfile> [<needle2> <msgfile2>]` — tell every non-hub session one line,
  sequential per session, parallel across sessions. The `fanout-*.sh` variants are one-offs and
  are deliberately untracked.
- `write_status.py` — writes `~/.claude/status/<app>.json` with the clock **read, not recalled**.
  Omitting `--decision`/`--blocker` keeps the previous value and now *echoes what it kept*, because
  a silently retained decision becomes the hub's fact and then a wrong call by the user.
- `watch-approve2.sh <session-name>` — older approver: babysits permission prompts (incl. "Claude in Chrome wants to…") for ~700 iterations; re-arm on its completion notification. Stops on anything that looks destructive.
- `relay-wait.sh <name> <ProjectDirBasename> <transcript-dir> <needle> <msg>` — waits for the session to be idle, `crew tell`s ONE line, verifies the needle in its transcript, retries.
- `asc_review_state.py <build>` — beta review state of a FractRoam build (uses FractRoam's `scripts/asc_screenshots.ASC`, conda python).
- `watch-fractroam-13.sh` — one-off: polled build 13 and told fractroam to submit 14 when it cleared.

### What is not in git, and why

`.gitignore` here excludes by **class**, not by filename, so new residue of the same kind is
covered without anyone noticing it: `*.log` (verbatim screen scrapes of private repos),
`msg-*.txt` (one-off relay drafts), `fanout-*.sh`, `approver-covered.txt` (live roster),
and hand-rolled `*.bak-*` / `*.prev-*`. Commit the machine; ignore what went through it.

## crew commands the hub owns (run after review, never from a worker session)

- `crew hooks install --yes` — merges the three Claude Code hook entries into `~/.claude/settings.json`
  (run without `--yes` first: it prints the exact JSON and refuses). A global settings write once gated
  every session on this Mac, so this is the hub's call, after kaolin has seen the JSON. `crew hooks status`
  shows what is installed and how many events the log holds; sessions started before the install keep
  the pinger's transcript heuristics until they restart.
- `crew commits [name]` — which session made which commit (`~/.claude/status/_commits.jsonl`, written by
  the same hook on every Bash `git commit`). `crew brief` folds it in: the real HEAD behind a DEVICE STALE
  line, "+N commit(s) since this status" under UNPUSHED WORK, and a status file with commits after it
  is listed as stale. Verify a ship against these shas, not the session's claim.
- `crew status-refresh <name>` / `--stale` — when `crew brief` lists STALE STATUS FILES and the session is
  idle, this rewrites the file from its transcript with one headless haiku call (`summarizer.md` is the
  prompt) instead of `crew tell`-ing the session to do it. Same schema, mirrored to `<project>/.crew/status.json`.
  One call per refresh; `--dry-run` first if unsure. Nothing schedules it — see the README before you do.
