#!/usr/bin/env python3
"""A finish that reported to the hub must not echo its note-to-hub at kaolin.

2026-09-03 14:34: timeful sent its review packet to the hub (which forwarded it
with the files); the pinger then fired "✅ finished after 4m" with the gist
"Sent. I built him a clean packet…" — the session's message TO THE HUB, pasted
at kaolin. "I'm getting your version and then your version back to the agent?"
sent_to_hub() spots the SendMessage-to-hub in the finishing turn."""
import importlib.util, json, os, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


def rec(kind, when, content):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(when))
    return json.dumps({"type": kind, "timestamp": ts, "message": {"content": content}})


def transcript(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines) + "\n"); f.close()
    return f.name


now = time.time()
to_hub = [{"type": "tool_use", "name": "SendMessage", "input": {"to": "hub", "message": "For kaolin — packet"}}]
to_peer = [{"type": "tool_use", "name": "SendMessage", "input": {"to": "thereby-8e", "message": "fyi"}}]
plain = [{"type": "text", "text": "Committed as 84bc8aa."}]

t = transcript([rec("assistant", now - 300, plain), rec("assistant", now - 30, to_hub)])
check("SendMessage to hub in this episode", tick.sent_to_hub(t, now - 600), True)
check("but not if the episode began after it", tick.sent_to_hub(t, now + 100), False)
os.unlink(t)

t = transcript([rec("assistant", now - 30, to_peer)])
check("SendMessage to a peer is not 'to hub'", tick.sent_to_hub(t, now - 600), False)
os.unlink(t)

t = transcript([rec("assistant", now - 30, plain)])
check("no SendMessage at all", tick.sent_to_hub(t, now - 600), False)
os.unlink(t)

t = transcript([rec("user", now - 30, to_hub)])
check("a user-side record does not count", tick.sent_to_hub(t, now - 600), False)
os.unlink(t)

check("missing transcript is False, not a crash", tick.sent_to_hub("/nope/nope.jsonl", now), False)

fold = [(False, tick.HUB_FOLD)]
normal = [(False, "Committed as 84bc8aa."), (False, "Build 47 is IN_BETA_TESTING.")]
check("hub-delivered: keep the label, drop the re-paste",
      tick.fold_headline("needs you: TESTFLIGHT REACH: accept the invite as… (+4 more)", fold),
      "needs you — see the hub's message")
check("hub-delivered 'blocked' keeps its label",
      tick.fold_headline("blocked: waiting on ASC", fold), "blocked — see the hub's message")
check("a normal report keeps its headline",
      tick.fold_headline("needs you: pick 2x or print-grade", normal), "needs you: pick 2x or print-grade")
check("empty headline stays empty", tick.fold_headline("", fold), "")
check("fold line among others is not a fold", tick.fold_headline("needs you: X", fold + normal), "needs you: X")

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    raise SystemExit(1)
print("sent_to_hub: ok")
