#!/usr/bin/env python3
"""One malformed session row must not cost every other session its alerts.

`claude agents --json` returned rows with no `status` on 2026-08-07. The unpack
`sid, name, status = s["sessionId"], s["name"], s["status"]` raised KeyError out
of main(), so the entire tick died — four times — and the whole fleet went
unreported for those cycles. Nothing said so: the failure only ever reached
pinger.err.log."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


OK = {"sessionId": "s1", "name": "izzit-2b", "status": "busy", "cwd": "/x"}
OK2 = {"sessionId": "s2", "name": "orrery-e7", "status": "idle", "cwd": "/y"}

# --- the real crash ---------------------------------------------------------
good, skipped = tick.usable_sessions([OK, {"sessionId": "s3", "name": "n"}, OK2])
check("survivors kept", [s["name"] for s in good], ["izzit-2b", "orrery-e7"])
check("bad row counted", skipped, 1)

# The point of the fix: a bad row costs only itself.
check("one bad row does not empty the fleet", len(good), 2)

# --- every missing essential ------------------------------------------------
for missing in ("sessionId", "name", "status"):
    row = dict(OK)
    del row[missing]
    good, skipped = tick.usable_sessions([row])
    check(f"drops row missing {missing}", (len(good), skipped), (0, 1))

# Empty strings are as unusable as absent keys — `crew` addresses by name.
good, skipped = tick.usable_sessions([{"sessionId": "s", "name": "", "status": "idle"}])
check("empty name is not a session", (len(good), skipped), (0, 1))

# --- shapes that should not raise -------------------------------------------
check("None is empty, not a crash", tick.usable_sessions(None), ([], 0))
check("empty list", tick.usable_sessions([]), ([], 0))
good, skipped = tick.usable_sessions(["nonsense", 42, None, OK])
check("non-dict rows are skipped", (len(good), skipped), (1, 3))

# --- a clean fleet is untouched ---------------------------------------------
good, skipped = tick.usable_sessions([OK, OK2])
check("nothing dropped from a clean fleet", (len(good), skipped), (2, 0))
check("rows pass through by identity", good[0] is OK, True)

if fails:
    print("\n".join("FAIL " + f for f in fails))
    raise SystemExit(1)
print("usable_sessions: ok")
