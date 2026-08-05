#!/usr/bin/env python3
"""at_prompt(): does a "busy" session actually want input, or is it mid-turn?

Screens below are verbatim captures from 2026-08-05, the day `crew status` held
four relays out of thereby-ed for three hours by reporting a finished session as
busy (a background watcher kept the flag set)."""
import os, re, sys

CREW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crew")
g = {"__name__": "notmain"}
exec(compile(open(CREW).read(), CREW, "exec"), g)
at_prompt, generating = g["at_prompt"], g["generating"]

# hub, mid-turn. The ❯ box is up — Claude Code keeps it so you can queue input —
# but the footer offers "esc to interrupt" and the spinner is live.
GENERATING = [
    "     for r in g['_screen_tail'](s, lines=12): print(re…",
    "✻ Manifesting… (3m 2s · ↓ 8.2k tokens)",
    "───────────────────────────────────────────────────────────────── hub ──",
    "❯",
    "────────────────────────────────────────────────────────────────────────",
    "  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt · ← for age…",
]

# thereby-ed. Turn finished; only a background shell keeps `agents --json` busy.
# The leftover spinner is PAST TENSE ("Sautéed for"), no ellipsis, no counter.
BG_SHELL = [
    "  99 core tests (8 new) and 7 Maestro flows green.",
    "✻ Sautéed for 13m 14s · 1 shell still running",
    "                              new task? /clear to save 671.5k tokens",
    "────────────────────────────────────────────────────────────────────────",
    "❯",
    "────────────────────────────────────────────────────────────────────────",
    "  ⏵⏵ bypass permissions on · 1 shell · ← for agents · ↓ to manage",
]

# orrery-0e. Same shape, but the background task is a monitor.
BG_MONITOR = [
    "  1 tasks (0 done, 1 open)",
    "  ◻ Resubmit 1.0 (build 11) after the 4.3(a) spam rejection",
    "                              new task? /clear to save 634k tokens",
    "────────────────────────────────────────────────────────────────────────",
    "❯",
    "────────────────────────────────────────────────────────────────────────",
    "  ⏵⏵ bypass permissions on · 1 monitor · ctrl+t to hide tasks · ← for agents ·…",
]

# An AskUserQuestion picker: blocked ON kaolin. Never ours to type into blindly.
PICKER = [
    "  Which cut do you want?",
    "    1. Re-cut only (clean)",
    "    2. Online shader",
    "  ↑/↓ to navigate · Enter to select",
]

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got}, want {want}")


check("generating screen is not at_prompt", at_prompt(None, GENERATING), False)
check("generating screen is generating", generating(GENERATING), True)

check("bg-shell screen is at_prompt", at_prompt(None, BG_SHELL), True)
check("bg-shell screen is not generating", generating(BG_SHELL), False)

check("bg-monitor screen is at_prompt", at_prompt(None, BG_MONITOR), True)
check("bg-monitor screen is not generating", generating(BG_MONITOR), False)

# No input box at all → not typeable, whatever else is true.
check("picker has no input box", at_prompt(None, PICKER), False)
check("empty screen is not at_prompt", at_prompt(None, []), False)
check("None screen is not at_prompt", at_prompt(None, None), False)

# The regression that started this: matching "✻" alone reads finished as running.
check("past-tense spinner is not generating",
      generating(["✻ Sautéed for 13m 14s · 1 shell still running"]), False)
check("live spinner is generating",
      generating(["✻ Manifesting… (3m 2s · ↓ 8.2k tokens)"]), True)

# A ❯ further up the scrollback (e.g. quoted output) must not count as the box.
check("stale ❯ outside the input region",
      at_prompt(None, ["❯"] + ["x"] * 8), False)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print(f"ok — {11} assertions")
