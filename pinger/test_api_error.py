#!/usr/bin/env python3
"""A turn the API dropped is not a finished turn.

thereby-8e went busy->idle at 07:18 on 2026-09-03 because its request died on
"API Error: 529 Overloaded". The pinger read the edge as FINISHED and sent kaolin
a ✅ whose gist was the error text, with his 02:25 work list still half done.
The closing lines of the transcript tell the two apart."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


report = [(False, "Committed as 84bc8aa."), (False, "Grayhame now reads 0.1.0 (122).")]
overloaded = [(False, "On it. Order: engine work first."),
              (False, "API Error: 529 Overloaded. This is a server-side issue, usually temporary.")]
ratelimit = [(True, "point one"), (False, "Rate limit reached, retry after 30s")]
mentions = [(False, "Fixed the 529 handling in the client so overloads retry."), (False, "Tests green.")]

check("a real report is not an API error", tick.api_error_ending(report), False)
check("529 Overloaded ending is an API error", tick.api_error_ending(overloaded), True)
check("rate-limit ending is an API error", tick.api_error_ending(ratelimit), True)
check("empty gist is not an API error", tick.api_error_ending([]), False)
# Only the LAST few lines count: a session that talked about 529s and then reported normally finished.
check("error mentioned earlier, report at the end = finished",
      tick.api_error_ending([(False, "API Error: 529 Overloaded")] + [(False, "later line")] * 3 + report), False)
# But a mention in the closing lines themselves still reads as an error (a cost we accept:
# a report whose last line quotes '529' gets a ⚠️ instead of a ✅, which kaolin can see through).
check("mention in the last lines reads as error", tick.api_error_ending(mentions), True)

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    raise SystemExit(1)
print("api_error: ok")
