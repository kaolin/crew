#!/usr/bin/env python3
"""crew-relaygate: prefix the relay rule's QUESTION to every hub input.

kaolin, 2026-10-10, Telegram #9073: "What if literally every message was
prefixed with the rule?" — #9075 "Sgtm".

Why a hook and not another paragraph in hub-protocol.md. On 2026-09-29 he gave
the hub three rules. One got a per-message hook (crew-clock.py, from his own
"add a 'it is now' to every input") and has held since. The other two got
protocol sections, and on 2026-10-10 he asked why they keep disappearing. They
had not disappeared: the relay rule occupied THREE of the protocol's 19
sections, 28 lines mentioned it, and the launcher demonstrably loads the file
into every hub session. It was present and overridden anyway. Writing it down
a fourth time is the intervention that has already failed four times.

What the clock hook got right, and what this copies: it supplies the ANSWER
(the actual time), not a reminder to go find one. So this does not restate the
principle — it asks for an output. Naming the category is a step you either
take or visibly skip; "don't interpret" is a mood.

The clause about a worker's output is here because that is the specific thing
that failed: asked for screenshots, the hub read a stale plan, decided the work
had six faults, and relayed them — two false and one half-false, all
disprovable from the repo in a minute. A judgement about a worker's work is
never context that worker lacks. It is the one case worth naming explicitly.

SCOPE — the hub only, two independent conditions, because this is registered in
the user-level settings.json and therefore runs for every session on the Mac:

  1. cwd is exactly the hub's. Verified 2026-10-10: the hub is the only session
     at ~, all seven workers are in ~/dev/<repo>, and kaolin's own Remote
     Control sessions live under ~/Library/.../scratch-workspaces. Unlike a
     session id this survives a hub restart.
  2. the marker file exists. That is kaolin's kill switch: `rm` it and the line
     stops, with no settings edit and no restart.

FAIL-OPEN BY CONSTRUCTION. Any error, any missing condition, means exit 0 with
nothing on stdout — the prompt goes through exactly as it does today. A broken
gate degrades to the current behaviour, never to a stray line in someone
else's session. A global prompt change once gated the whole fleet (auto mode,
2026-09-02); that is the failure this shape rules out.
"""
import json, os, sys

HUB_CWD = "/Users/kaolin"
MARKER  = os.path.expanduser("~/.crew/hub/relaygate-on")
# 2026-10-11: cwd alone was the wrong discriminator. The harness reports the
# SESSION's working directory, which for the hub is ~/dev/crew (its launch dir),
# and a `cd` from inside a Bash call does not persist. So the gate stayed silent
# for 19 hours while every condition "verified" fine by hand. The hub's PROJECT
# dir is stable and unique to it: ~/.claude/projects/-Users-kaolin/. Workers get
# -Users-kaolin-dev-<repo>. Match that when the payload offers it, and keep the
# cwd match as a fallback.
#
# The real UserPromptSubmit payload, captured 2026-10-11 12:19 rather than
# guessed: session_id, transcript_path, cwd, scratchpad_dir, prompt_id,
# permission_mode, hook_event_name, prompt, session_title. Note cwd was
# "/Users/kaolin/dev/crew" at that moment, which is why the old check failed.
# session_title was "hub" and would also serve, but transcript_path is proven.
HUB_PROJECT = "/projects/-Users-kaolin/"


def is_hub(d):
    """True only for the hub session. Checked against the payload, not the shell."""
    for k in ("transcript_path", "transcriptPath", "transcript"):
        v = d.get(k)
        if isinstance(v, str) and HUB_PROJECT in v:
            return True
    cwd = d.get("cwd")
    if isinstance(cwd, str) and os.path.realpath(cwd) == os.path.realpath(HUB_CWD):
        return True
    return False

LINE = (
    "RELAY GATE — you are the switchboard (plus context). Before anything "
    "leaves this session, name which it is: (a) his words, (b) context the "
    "receiving session cannot have, or (c) conversation management. None of "
    "the three → it does not go out. Do NOT judge a worker's output — not to "
    "kaolin, not to the worker (kaolin, 2026-10-17). Pass it through."
)


def main():
    raw = sys.stdin.read(1 << 20)
    d = json.loads(raw) if raw.strip() else {}
    if not isinstance(d, dict):
        return
    if not os.path.exists(MARKER):
        return
    if not is_hub(d):
        return
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": LINE}}))
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException:   # noqa: BLE001 — fail open: no output, prompt untouched
        pass
    finally:
        os._exit(0)
