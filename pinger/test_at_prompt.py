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
prompt_text = g["prompt_text"]

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

# Claude Code renders a SUGGESTED next message as ghost text on the input line.
# A scrape cannot tell it from typing, and on 2026-08-06 it fooled us: five
# sessions were reported as holding kaolin's unsent drafts, and a probe proved
# every box empty. So a box with text on it is still a usable prompt, and
# prompt_text is unverified — never act on it.
GHOST = [
    "  Carry on whenever you've got hands on the iPad.",
    "\u271b Brewed for 11s",
    "                              new task? /clear to save 180.6k tokens",
    "-" * 72,
    "\u276f ol_diag.txt shows engaged=1 locked=1 in landscape, works",
    "-" * 72,
    "  \u23f5\u23f5 bypass permissions on (shift+tab to cycle)",
]

check("ghost text still counts as at_prompt", at_prompt(None, GHOST), True)
check("prompt_text reports it verbatim", prompt_text(None, GHOST),
      "ol_diag.txt shows engaged=1 locked=1 in landscape, works")
check("bare box reports no text", prompt_text(None, BG_SHELL), "")
check("no box at all reports no text", prompt_text(None, PICKER), "")
check("generating with a box is not at_prompt", at_prompt(None, GENERATING), False)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print(f"ok — {26} assertions")

# Truncation guard. On 2026-08-06 two ~1.8 KB relays submitted mid-paste and
# arrived beheaded; a flat 0.6s wait was enough for short notes and silently
# wrong for long ones.
settle_for = g["settle_for"]
check("short note settles fast", settle_for("hi\nthere") < 0.7, True)
check("1.8KB relay waits over 2s", settle_for("x" * 1800) > 2.0, True)
check("huge paste is capped", settle_for("x" * 500_000), 6.0)
check("wait grows with size", settle_for("x" * 4000) > settle_for("x" * 1000), True)

chunks_of = g["chunks_of"]
short = "just a line"
check("short msg is one chunk", chunks_of(short), [short])
big = "".join(f"line {i} of the relay\n" for i in range(200))
parts = chunks_of(big)
check("big msg is split", len(parts) > 1, True)
check("nothing lost in split", "".join(parts), big)
check("every chunk within size", max(len(p) for p in parts) <= 600, True)
check("splits on line boundaries", all(p.endswith("\n") for p in parts[:-1]), True)
monster = "x" * 5000
mparts = chunks_of(monster)
check("monster line still split", len(mparts) > 1, True)
check("monster line intact", "".join(mparts), monster)
