# hub/ — helper scripts the Telegram hub session runs

Launched from `~/.crew/hub/` (a symlink here) so they survive the /private/tmp reaper.

- `watch-approve2.sh <session-name>` — babysits permission prompts (incl. "Claude in Chrome wants to…") for ~700 iterations; re-arm on its completion notification. Stops on anything that looks destructive.
- `relay-wait.sh <name> <ProjectDirBasename> <transcript-dir> <needle> <msg>` — waits for the session to be idle, `crew tell`s ONE line, verifies the needle in its transcript, retries.
- `asc_review_state.py <build>` — beta review state of a FractRoam build (uses FractRoam's `scripts/asc_screenshots.ASC`, conda python).
- `watch-fractroam-13.sh` — one-off: polled build 13 and told fractroam to submit 14 when it cleared.
- `relay-applespam.sh` — one-off relay of the 2026-09-06 Apple-ID decision.
