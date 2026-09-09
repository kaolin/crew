You are writing the status file for one Claude Code session in kaolin's fleet. The hub session reads these files as its first act on every wake (`crew brief`), and an alert daemon quotes `needs_decision[0]` in the Telegram ping that says a session finished. Nobody reads your prose; they read the JSON.

Session: {{SESSION}}
Project directory: {{PROJECT}}
Now: {{NOW}}

## What you must output

Exactly one JSON object and nothing else — no markdown fence, no commentary before or after. It must follow this schema (nothing is required except `session` and `updated_at`; every other key earns its place only if true — an empty list beats a stale one):

```jsonc
{
  "session": "{{SESSION}}",
  "updated_at": "{{NOW}}",
  "state": "working | blocked | idle | done",

  "head": "da8c66e",                // git HEAD this describes (given below; copy it)
  "build": 113,                     // if the project ships numbered builds
  "last_action": "one line, what the session just did",
  "unpushed": ["109", "110"],       // work that exists only locally (given below)

  "needs_decision": [               // KAOLIN's move. Phrase as what HE does.
    "one line per decision, enough context to answer from a phone"
  ],
  "blockers": [                     // waiting on something that is NOT him
    "apple review", "device off-network"
  ],
  "open_partials": [                // half-done, so it is not reported as finished
    "#19: rows say what they stretch, but still don't read as tappable"
  ],

  "settled": {                      // decisions already made — stops re-litigation
    "price": "$1.99 paid up front (decided 2026-08-21)"
  },

  "device": {                       // only if the project deploys to hardware
    "name": "Grayhame",
    "reachable": true,
    "shipped_commit": "068969b",
    "stale": false                  // shipped_commit != head → he is testing code that no longer exists
  },

  "verified":   ["claims the session actually stood up, and how"],
  "unverified": ["claims it has not"],

  "artifacts": ["/abs/path.png", "https://…"],
  "verify": { "tests": "swift test", "screens": "scripts/journey.sh" }
}
```

## Rules

1. **Start from the previous status and update it.** Keep every key it had (including ones not in the schema, like `testflight`, `asc`, `goal`, `release`) unless the transcript shows it changed. `settled` in particular only grows: a decision kaolin made stays made.
2. **`needs_decision` vs `blockers`:** waiting on Apple is not waiting on kaolin. Only things HE has to do go in `needs_decision`. If the transcript shows he answered one, remove it.
3. **Do not invent.** Everything must come from the previous status, the git log, or the transcript. A claim the transcript makes without evidence (a build "installed", a test "passing") goes in `unverified`, not `verified`.
4. **`head`** is the first sha in the git log below. **`unpushed`**: if the count below is a number, express it (e.g. `["3 commits ahead of origin/main"]`, or `[]` for 0); if it says there is no upstream or no repo, say that in one line.
5. **`state`**: `blocked` if `needs_decision` or `blockers` is non-empty and nothing is running; `working` if the last turn is mid-task; `idle` if it finished and is waiting for the next ask; `done` only if the session said the whole goal is complete.
6. `last_action` is one line about the most recent turn — what happened, not what was planned.
7. Keep strings short; a phone is the display. Never exceed 200 characters in a `needs_decision` line.

## Previous status (the file as it is now; `{}` if none)

```json
{{PREVIOUS_STATUS}}
```

## git log --oneline -20

```
{{GIT_LOG}}
```

Unpushed: {{UNPUSHED}}

## Transcript tail (newest last; USER is kaolin or the hub relaying him, ASSISTANT is the session)

```
{{TRANSCRIPT_TAIL}}
```

Output the JSON object now.
