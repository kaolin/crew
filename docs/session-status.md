# Session status files

Every session writes **one file at the end of every turn**:

```
~/.claude/status/<session>.json
```

The hub reads the whole directory as its **first act on any wake** (`crew brief`).

## Why this exists

Nothing can wake the hub except kaolin. `crew tell` types into a TUI and returns —
no callback on start, finish or failure. `crew-pinger` detects finished/stuck/waiting
every minute but pushes straight to Telegram, where a bot's own messages never come
back as inbound. So the loop was:

> session finishes → pinger tells kaolin → kaolin asks the hub → hub looks

Kaolin was the interrupt handler. On 2026-08-21 that left finished work sitting
twice for ~25 minutes. It also produced worse failures than latency: a four-day-stale
"say go on publishing PGS" telling him to redo work already done, and seven hours of
bug reports filed against a build that was no longer on the device.

Status files fix it without a new wake path. The hub still can't be woken — but the
moment kaolin says *anything*, it already knows what finished, what's blocked, and on
whom.

## Schema

Nothing is required except `session` and `updated_at`. Everything else earns its place
only if true; an empty list is better than a stale one.

```jsonc
{
  "session": "thereby",
  "updated_at": "2026-08-21T19:32:00-07:00",   // ISO 8601 with offset
  "state": "working | blocked | idle | done",

  "head": "da8c66e",                // git HEAD this describes
  "build": 113,
  "last_action": "one line, what you just did",
  "unpushed": ["109", "110"],       // work that exists only locally

  "needs_decision": [               // ← KAOLIN's move. Phrase as what HE does.
    "one line per decision, enough context to answer from a phone"
  ],
  "blockers": [                     // ← waiting on something that is not him
    "apple review", "device off-network", "..."
  ],
  "open_partials": [                // half-done, so it isn't reported as finished
    "#19: rows say what they stretch, but still don't read as tappable"
  ],

  "settled": {                      // decisions already made — stops re-litigation
    "price": "$1.99 paid up front (decided 2026-08-21)"
  },

  "device": {                       // if you deploy to hardware
    "name": "Grayhame",
    "reachable": true,
    "shipped_commit": "068969b",
    "stale": false                  // shipped_commit != head → he is testing code that no longer exists
  },

  "verified":   ["claims you actually stood up, and how"],
  "unverified": ["claims you have not"],

  "artifacts": ["/abs/path.png", "https://…"],
  "verify": { "tests": "swift test", "screens": "scripts/journey.sh" }
}
```

### The fields that matter most

- **`needs_decision`** — authored by the session that actually knows, so the pipeline
  page stops carrying hand-maintained lines that rot. The pinger quotes the first entry
  in kaolin's Telegram ping, turning *"session finished"* into *"finished; needs one
  Play Console click"*.
- **`blockers`** vs `needs_decision` — waiting on Apple is not waiting on kaolin. The
  store page conflated these for days.
- **`device.stale`** — the single field that would have saved 2026-08-20, when 26 bug
  reports were filed against a build that had not reached the phone.
- **`verified` / `unverified`** — a background build once exited 0, printed a plausible
  log line, and had actually installed nothing; the old build answered. Anything that
  scrapes your last message will eventually propagate that. Say which claims you stood up.
- **`settled`** — cheap insurance against a relay re-opening a closed decision.

## Reading it

```bash
crew brief              # unseen pinger events + every session's status, triaged
crew brief --plain      # no colour
crew brief --no-ack     # don't advance the seen-cursor
```

`crew brief` groups sessions into **needs kaolin / blocked on something else / quiet**,
then flags stale devices and unpushed work. Unseen pinger events replay from
`~/.claude/status/_pinger.jsonl` until acknowledged — the cursor advances only when the
hub has actually read them.
