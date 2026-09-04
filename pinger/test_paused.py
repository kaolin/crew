#!/usr/bin/env python3
"""A turn that ends parked on the session's OWN background task is a pause,
not a finish. timeful pinged "✅ finished after 22m (bg task still running)"
three times in an hour on 2026-09-03 while re-running one load test; each
gist said it was waiting on the completion notification."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


def g(*texts):
    return [(False, t) for t in texts]


check("timeful 18:20", tick.waiting_on_own_task(g(
    "Everything remaining depends on the run finishing (~15 min): compose the six Android frames, "
    "fill in the PARITY run numbers, commit, and send the paths to the hub. Waiting on the completion notification.")), True)
check("timeful 17:58", tick.waiting_on_own_task(g(
    "Run restarted at load 15 and falling. Nothing else is independent of it. "
    "I'll pick up on the completion notification.")), True)
check("resume when the run finishes", tick.waiting_on_own_task(g(
    "Docs are staged. I'll resume when the sweep finishes.")), True)
check("waiting on a background task", tick.waiting_on_own_task(g(
    "Waiting for the background task to report back before committing.")), True)
check("fusiontrainer real finish with a live loop", tick.waiting_on_own_task(g(
    "Build 101 is on Grayhame. Ready for your on-device read.",
    "Rivendell is still offline. Its loop keeps trying once a minute until 23:44 and I'll confirm when it lands.")), False)
check("plain commit", tick.waiting_on_own_task(g("Committed as 84bc8aa.")), False)
check("waiting on kaolin is not own-task", tick.waiting_on_own_task(g(
    "Waiting on your call: promo text or a 1.3.3?")), False)
check("only the last two lines count", tick.waiting_on_own_task(g(
    "Waiting on the completion notification.", "Run landed.", "All sixteen frames composed; paths below.")), False)
check("timeful 18:18 (no 'notification' in it)", tick.waiting_on_own_task(g(
    "Both watchers armed: one fires at the lock-screen capture (~7 min in), the other at run end. "
    "Nothing else is independent — the commit, the six Android frames, and the hub report all hang on this run. Waiting.")), True)
check("bare closing Waiting.", tick.waiting_on_own_task(g("Frames composed. Waiting.")), True)
check("Waiting on you is not a pause", tick.waiting_on_own_task(g("Frames composed. Waiting on you.")), False)
check("'waiting' mid-sentence about kaolin", tick.waiting_on_own_task(g(
    "Still waiting on your answer about the promo text before I touch the listing.")), False)
check("empty", tick.waiting_on_own_task([]), False)
check("None", tick.waiting_on_own_task(None), False)

now = 1_000_000
lines_parked = g("Everything hangs on this run. Waiting.")
lines_plain = g("Lock screen captured. That's the frame. I'll compose the six from this single run once it finishes rather than mix sources.")
lines_q = g("Lock screen captured. Keep the notification in the frame, or crop it?")
check("parked → fold", tick.fold_bg_report(lines_parked, [], None, now), True)
check("plain repeat 2 min after a send → fold", tick.fold_bg_report(lines_plain, [], now - 120, now), True)
check("plain 31 min after a send → send", tick.fold_bg_report(lines_plain, [], now - 31 * 60, now), False)
check("never sent → send", tick.fold_bg_report(lines_plain, [], None, now), False)
check("with a photo → send even inside cooldown", tick.fold_bg_report(lines_plain, ["/x/a.png"], now - 120, now), False)
check("a question → send even inside cooldown", tick.fold_bg_report(lines_q, [], now - 120, now), False)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    raise SystemExit(1)
print("waiting_on_own_task: ok")
