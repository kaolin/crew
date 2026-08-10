#!/usr/bin/env python3
"""A polling session must not re-send the same news every few minutes.

orrery ran a monitor that re-reported "still WAITING_FOR_REVIEW, nothing
changed" on a loop. Every one of those became a full ✅ report with the clock
moved on, which buries the reports that matter — kaolin, 2026-08-10: "way too
verbose and frequent a feedback. Good to know it's still running. Nothings
changed, great." """
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


def gist(text):
    return [(False, line) for line in text.strip().splitlines()]


POLL_A = gist("""
Your read holds. Nothing new in anything the API exposes:
what — state
version 1.0 — WAITING_FOR_REVIEW
checked 02:14, next check in 5 minutes
""")
POLL_B = gist("""
Your read holds. Nothing new in anything the API exposes:
what — state
version 1.0 — WAITING_FOR_REVIEW
checked 02:19, next check in 5 minutes
""")
REAL_NEWS = gist("""
State changed. Version 1.0 moved WAITING_FOR_REVIEW -> IN_REVIEW at 03:40.
Apple is looking at it now; expedited, so hours not days.
""")

a, b, c = tick.report_sig(POLL_A), tick.report_sig(POLL_B), tick.report_sig(REAL_NEWS)

check("clock-only difference is the same news", tick.same_news(a, b), True)
check("a real state change is not", tick.same_news(a, c), False)
check("signature drops digits", any(ch.isdigit() for ch in a), False)
check("identical text matches itself", tick.same_news(a, a), True)

# Never suppress against nothing — the first report of a session must go out.
check("no previous signature -> send", tick.same_news(a, None), False)
check("no previous signature (empty) -> send", tick.same_news(a, ""), False)
check("empty new gist -> not a match", tick.same_news("", b), False)

# The quiet-hours escape hatch: silence forever would be its own failure.
check("quiet window is 6h", tick.SAME_REPORT_QUIET, 6 * 3600)
check("threshold leaves room for wording drift", tick.SAME_REPORT_RATIO < 0.95, True)

# Guard rails that must survive this change.
check("finished alerts still on", tick.NOTIFY_FINISHED, True)
check("hub still excluded", "hub" in tick.EXCLUDE_NAMES, True)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("ok — 11 assertions")
