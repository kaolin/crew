#!/usr/bin/env python3
"""crew-clock: put the real time on every input a session receives.

Runs on UserPromptSubmit, which fires for kaolin's prompts and for
cross-session messages alike. Its stdout becomes context the model sees next
to the message, so a session never has to guess the time when it stamps a
reply. kaolin, 2026-09-29: "Edit the harness? Add a 'it is now' to every input
from me?" A written rule didn't fix this. In the week of 09-23 there were four
guessed stamps across three sessions (fleet review, 2026-09-30).

Fail-open: any error means no output, and the prompt goes through untouched.
"""
import json, os, sys, time

try:
    sys.stdin.read(1 << 20)
    now = time.strftime("%Y-%m-%d %H:%M %Z (%a)")
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": f"Clock read by hook at submit: {now}. Use this, not an estimate, for any timestamp."}}))
    sys.stdout.flush()
except BaseException:   # noqa: BLE001
    pass
finally:
    os._exit(0)
