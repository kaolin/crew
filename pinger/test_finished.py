#!/usr/bin/env python3
"""A session that never goes idle must still report that it finished a turn.

orrery-0e ran a persistent monitor, so `claude agents --json` called it busy for
57 straight hours. "Finished" fired on the busy->idle edge, which never came, so
the pinger sent nothing about it for two and a half days while it was producing
constantly — kaolin asked twice before any of it reached him (2026-08-06)."""
import importlib.util, json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


# --- transcript_lines -------------------------------------------------------
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    f.write('{"a":1}\n{"a":2}\n{"a":3}\n')
    tpath = f.name
check("counts transcript lines", tick.transcript_lines(tpath), 3)
check("missing transcript is 0, not a crash", tick.transcript_lines("/nope/nope.jsonl"), 0)
os.unlink(tpath)

# --- the decision itself ----------------------------------------------------
# Mirrors the busy-branch guard. Kept as a pure function here so the condition
# is testable without launchd, a live fleet, or a terminal to scrape.
def should_report(nlines, seen, since, now, at_prompt,
                  notify=True, first_run=False, excluded=False):
    if seen is None:
        return False                       # first sight: arm, never fire
    return bool(notify and not first_run and not excluded
                and nlines > seen
                and (now - since) >= tick.MIN_FINISHED_SECS
                and at_prompt)


NOW = 1_000_000.0
OLD = NOW - 600          # ten minutes ago, well past MIN_FINISHED_SECS

check("the orrery case: busy forever, new output, at prompt",
      should_report(500, 400, OLD, NOW, at_prompt=True), True)
check("no new output -> silent",
      should_report(400, 400, OLD, NOW, at_prompt=True), False)
check("still generating -> silent",
      should_report(500, 400, OLD, NOW, at_prompt=False), False)
check("first sight arms without firing",
      should_report(500, None, OLD, NOW, at_prompt=True), False)
check("too soon after the last report -> silent",
      should_report(500, 400, NOW - 5, NOW, at_prompt=True), False)
check("first run stays quiet",
      should_report(500, 400, OLD, NOW, at_prompt=True, first_run=True), False)
check("excluded sessions stay quiet (the hub itself)",
      should_report(500, 400, OLD, NOW, at_prompt=True, excluded=True), False)
check("NOTIFY_FINISHED off stays quiet",
      should_report(500, 400, OLD, NOW, at_prompt=True, notify=False), False)

# Consecutive turns: after reporting, the marker advances so the same output
# can't be sent twice — the failure mode that would make this worse than silence.
seen, since = 400, OLD
fired = should_report(500, seen, since, NOW, at_prompt=True)
if fired:
    seen, since = 500, NOW
check("first turn reports", fired, True)
check("same output does not report again",
      should_report(500, seen, since, NOW + 300, at_prompt=True), False)
check("the next turn's output does report",
      should_report(560, seen, since, NOW + 300, at_prompt=True), True)

# --- guard rails still in the module ---------------------------------------
check("hub is still excluded", "hub" in tick.EXCLUDE_NAMES, True)
check("NOTIFY_FINISHED is on", tick.NOTIFY_FINISHED, True)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("ok — 15 assertions")
