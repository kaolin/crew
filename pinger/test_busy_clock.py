#!/usr/bin/env python3
"""The busy clock must measure the current turn, not the session's whole life.

`claude agents --json` calls a session busy while ANY background shell lives, so
status never returns to idle and `busy_since` never got cleared. fusiontrainer-fb
was announced as "busy 3.7h — may be hung" while it was nine minutes into a turn
and had finished several turns in between (2026-08-11). kaolin, correctly:
"Probably not, right?"

These call tick.busy_clock itself rather than a copy of its condition — a test
that mirrors the logic passes happily while the shipped code is wrong."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []
H = 3600.0
NOW = 1_000_000.0
OVER = NOW - tick.STUCK_HOURS * H - 60      # busy_since long enough to be "due"
UNDER = NOW - 60                            # a minute in


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


# --- an empty prompt is a turn boundary, whatever the JSON says -------------
alert, since, notified = tick.busy_clock(OVER, NOW, at_prompt=True, notified=False)
check("at prompt never alerts", alert, False)
check("at prompt restarts the clock", since, NOW)

# The exact fusiontrainer case: hours on the clock, at prompt, nothing wrong.
alert, since, _ = tick.busy_clock(NOW - 3.7 * H, NOW, at_prompt=True, notified=False)
check("3.7h at an empty prompt is not a hang", alert, False)
check("...and the clock resets so the next report is honest", since, NOW)

# One false alert must not silence the session forever. Because it never goes
# idle, `notified` is only ever cleared here.
_, _, notified = tick.busy_clock(OVER, NOW, at_prompt=True, notified=True)
check("clears notified at a turn boundary", notified, False)

# --- a genuinely stalled turn still alerts ----------------------------------
alert, since, notified = tick.busy_clock(OVER, NOW, at_prompt=False, notified=False)
check("mid-turn past the threshold alerts", alert, True)
check("alerting does not move the clock", since, OVER)
check("alerting marks it notified", notified, True)

# The duration the alert prints comes from `since`; that is the whole point.
check("reported hours are the turn, not the session",
      round((NOW - since) / H, 1), round(tick.STUCK_HOURS + 60 / H, 1))

# --- it only alerts once per episode ----------------------------------------
alert, _, _ = tick.busy_clock(OVER, NOW, at_prompt=False, notified=True)
check("already notified stays quiet", alert, False)

# --- below the threshold ----------------------------------------------------
alert, since, _ = tick.busy_clock(UNDER, NOW, at_prompt=False, notified=False)
check("a fresh turn is not a hang", alert, False)
check("...and its clock is left alone", since, UNDER)

# --- not looking is not the same as "at prompt" -----------------------------
# The screen scrape costs a subprocess, so callers skip it when it cannot
# change anything. Skipping must never be read as a turn boundary.
alert, since, notified = tick.busy_clock(OVER, NOW, at_prompt=None, notified=False)
check("no screen check, no alert", alert, False)
check("no screen check, clock untouched", since, OVER)
check("no screen check, notified untouched", notified, False)

# --- the suppression switches -----------------------------------------------
alert, _, _ = tick.busy_clock(OVER, NOW, False, False, notify=False)
check("NOTIFY_STUCK off", alert, False)
alert, _, _ = tick.busy_clock(OVER, NOW, False, False, first_run=True)
check("first run never alerts", alert, False)
alert, _, _ = tick.busy_clock(OVER, NOW, False, False, excluded=True)
check("excluded session never alerts", alert, False)

# An excluded session at a prompt should still have its clock restarted, so it
# reports honestly if it is ever un-excluded.
_, since, _ = tick.busy_clock(OVER, NOW, True, False, excluded=True)
check("excluded still gets a fresh clock", since, NOW)

if fails:
    print("\n".join("FAIL " + f for f in fails))
    raise SystemExit(1)
print("busy_clock: ok")
