# fleetview

One phone-readable page of everything kaolin runs Claude Code sessions for,
shaped by how he actually uses them: what needs him, what is live, where each
app stands in the stores, 14 days of activity, repos that exist only on this
Mac, and the parked list. Read-only, no network, Node built-ins only.

    node collect.mjs      # every source -> fleet.json  (incremental; first run scans the transcripts)
    node render.mjs       # fleet.json -> fleet.html    (self-contained; rsync-able as-is)
    ./shot.sh             # fleet.html -> fleet.png     (headless Chrome, 430px wide, 2x; THEME=dark for dark)

Sources: `claude agents --json` (what `crew status` reads), `crew brief --plain
--no-ack` (never advances the hub's pinger cursor), `~/.claude/status/*.json`,
`~/.claude/projects/**/*.jsonl` transcript growth per local day, `git` per
session cwd (plus nested `godot/`, `ios/`, `android/` repos), the stored
`../appstatus/status.json` snapshot (its age is printed; `collect.py` is never
run from here), `../usage/readings.tsv` from the launchd usage sampler, and the
two memory notes that map repo names to store names and list the parked apps.

`render.mjs --artifact out.html` also writes a body-only variant for the
Artifact tool. Generated files are gitignored: `fleet.json` holds session
notes and local paths and this repo is public.
