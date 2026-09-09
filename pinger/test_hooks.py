#!/usr/bin/env python3
"""Hook events beat transcript heuristics — when a session has them.

`claude agents --json` has no "turn ended" or "prompt is up" signal, so the
pinger has inferred both from transcript line counts, a tool_use with no
tool_result, and a scrape of the terminal that cannot see a locked Mac. Claude
Code's own hooks state both as facts. hooks/crew-hook.py records them;
tick.py prefers them for any session that has any, and keeps the heuristics for
the sessions that were started before the hooks were installed.

The handler is tested as the subprocess Claude Code runs: it must exit 0, say
nothing on stdout, and never take long — a hook that blocks gates the session."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(os.path.dirname(HERE), "hooks", "crew-hook.py")
spec = importlib.util.spec_from_file_location("tick", os.path.join(HERE, "tick.py"))
tick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tick)

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


scratch = tempfile.mkdtemp(prefix="crew-hooks-")
env = {**os.environ, "CREW_HOME": scratch}
HOOKS_LOG = os.path.join(scratch, ".claude", "status", "_hooks.jsonl")
COMMITS_LOG = os.path.join(scratch, ".claude", "status", "_commits.jsonl")


def run_hook(payload):
    """(returncode, stdout, seconds) of the handler fed `payload` on stdin."""
    raw = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    t0 = time.time()
    out = subprocess.run([HOOK], input=raw if isinstance(raw, bytes) else raw.encode(),
                         capture_output=True, env=env, timeout=10)
    return out.returncode, out.stdout, time.time() - t0


def records(path):
    try:
        return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    except OSError:
        return []


# --- the handler as Claude Code runs it ------------------------------------
base = {"session_id": "sid-A", "cwd": "/tmp", "transcript_path": "/tmp/x.jsonl"}

rc, out, secs = run_hook({**base, "hook_event_name": "Notification",
                          "notification_type": "permission_prompt",
                          "message": "Claude needs your permission to use Bash"})
check("Notification: exit 0", rc, 0)
check("Notification: nothing on stdout", out, b"")
check("Notification: well under a second", secs < 1.0, True)
rec = records(HOOKS_LOG)[-1]
check("Notification: fields recorded",
      (rec["hook_event_name"], rec["session_id"], rec["cwd"], rec["notification_type"], rec["message"]),
      ("Notification", "sid-A", "/tmp", "permission_prompt", "Claude needs your permission to use Bash"))
check("record carries an epoch t and an ISO ts", isinstance(rec.get("t"), float) and rec["ts"][:4].isdigit(), True)

rc, out, _ = run_hook({**base, "hook_event_name": "Stop", "stop_hook_active": False,
                       "stop_reason": "end_turn", "last_assistant_message": "Done."})
check("Stop: exit 0, silent", (rc, out), (0, b""))
rec = records(HOOKS_LOG)[-1]
check("Stop: fields recorded", (rec["hook_event_name"], rec["stop_hook_active"], rec.get("stop_reason")),
      ("Stop", False, "end_turn"))

rc, out, _ = run_hook({**base, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "ls -la"}, "tool_output": {"exit_code": 0, "stdout": ""}})
rec = records(HOOKS_LOG)[-1]
check("PostToolUse Bash: command recorded", (rc, rec["tool_name"], rec["command"]), (0, "Bash", "ls -la"))
check("PostToolUse Bash: no commit record for a plain command", records(COMMITS_LOG), [])

rc, out, _ = run_hook({**base, "hook_event_name": "PostToolUse", "tool_name": "Read",
                       "tool_input": {"file_path": "/x"}})
rec = records(HOOKS_LOG)[-1]
check("PostToolUse non-Bash: no command field", (rc, rec["tool_name"], "command" in rec), (0, "Read", False))

long = "x" * 5000
run_hook({**base, "hook_event_name": "Notification", "message": long})
rec = records(HOOKS_LOG)[-1]
check("long strings are clipped so one record is one write()", len(rec["message"]) < 600, True)

n_before = len(records(HOOKS_LOG))
for bad in ("garbage{", "", "[1,2,3]", "null"):
    rc, out, secs = run_hook(bad)
    check(f"fail-open on {bad!r}: exit 0 and silent", (rc, out), (0, b""))
check("garbage stdin writes nothing", len(records(HOOKS_LOG)), n_before)

# --- commit attribution (steal 2's writer lives in the same handler) ---------
repo = os.path.join(scratch, "repo")
os.makedirs(repo)
g = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                              capture_output=True, text=True, check=True).stdout.strip()
g("init", "-q")
g("commit", "-q", "--allow-empty", "-m", "first: seed")
sha1 = g("rev-parse", "HEAD")
post = lambda cmd, cwd=repo: run_hook({**base, "cwd": cwd, "hook_event_name": "PostToolUse",
                                       "tool_name": "Bash", "tool_input": {"command": cmd},
                                       "tool_output": {"exit_code": 0, "stdout": ""}})
rc, out, secs = post("git commit -q -m 'first: seed'")
check("git commit: exit 0, silent, fast", (rc, out, secs < 1.0), (0, b"", True))
recs = records(COMMITS_LOG)
check("git commit: one record", len(recs), 1)
r = recs[0]
check("git commit: who/where/what", (r["session_id"], r["cwd"], r["repo"], r["branch"], r["sha"], r["subject"]),
      ("sid-A", repo, os.path.realpath(repo) if r["repo"] != repo else repo, g("rev-parse", "--abbrev-ref", "HEAD"), sha1, "first: seed"))

post("git commit -q -m 'first: seed'")
check("same HEAD twice is one record (a no-op re-run)", len(records(COMMITS_LOG)), 1)

g("commit", "-q", "--allow-empty", "-m", "second: via -C from elsewhere")
sha2 = g("rev-parse", "HEAD")
post(f"git -C {repo} commit -q --allow-empty -m 'second'", cwd="/tmp")
recs = records(COMMITS_LOG)
check("git -C <dir> commit resolves the repo, not the session cwd", (len(recs), recs[-1]["sha"], recs[-1]["cwd"]),
      (2, sha2, "/tmp"))

g("commit", "-q", "--allow-empty", "-m", "third: after cd")
sha3 = g("rev-parse", "HEAD")
post(f"cd {repo} && git commit -q --allow-empty -m 'third'", cwd="/tmp")
check("cd <dir> && git commit resolves the repo", records(COMMITS_LOG)[-1]["sha"], sha3)

post("git commit -m 'nothing staged'", cwd=scratch)
check("a commit outside any repo records nothing", len(records(COMMITS_LOG)), 3)

# A command that SAYS commit but HEAD did not move (pre-commit hook refused,
# nothing staged): HEAD is older than the freshness window, so it is not claimed.
old_repo = os.path.join(scratch, "old")
os.makedirs(old_repo)
subprocess.run(["git", "-C", old_repo, "init", "-q"], check=True)
subprocess.run(["git", "-C", old_repo, "-c", "user.name=t", "-c", "user.email=t@t",
                "commit", "-q", "--allow-empty", "-m", "ancient"],
               env={**os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00", "GIT_AUTHOR_DATE": "2020-01-01T00:00:00"},
               check=True)
post("git commit -m 'refused by a hook'", cwd=old_repo)
check("a commit that did not happen is not recorded", len(records(COMMITS_LOG)), 3)

post("git log -1 --format=%s   # the last commit", cwd=repo)
post("git commit-tree HEAD^{tree} -m x", cwd=repo)
check("`git log` and `git commit-tree` are not commits", len(records(COMMITS_LOG)), 3)
g("commit", "-q", "--allow-empty", "-m", "fourth: with -c and --no-pager")
sha4 = g("rev-parse", "HEAD")
post("git -c user.name=t --no-pager commit -q --allow-empty -m 'fourth'", cwd=repo)
check("options between git and commit are fine", records(COMMITS_LOG)[-1]["sha"], sha4)

# --- tick.py: reading the log ------------------------------------------------
ev = tick.hook_events(HOOKS_LOG)
check("hook_events groups by session id", set(ev), {"sid-A"})
check("hook_events keeps order", [e["hook_event_name"] for e in ev["sid-A"]][:3],
      ["Notification", "Stop", "PostToolUse"])
check("missing log -> {} (hooks not installed; heuristics carry everything)", tick.hook_events("/nope/_hooks.jsonl"), {})

with open(HOOKS_LOG, "a") as f:
    f.write("not json\n\n")
check("a corrupt line is skipped, not fatal", set(tick.hook_events(HOOKS_LOG)), {"sid-A"})

# tail read: the cut line is dropped, later ones survive
big = os.path.join(scratch, "big.jsonl")
with open(big, "w") as f:
    for i in range(200):
        f.write(json.dumps({"session_id": "S", "hook_event_name": "Stop", "t": float(i)}) + "\n")
tail = tick.hook_events(big, max_bytes=2000)
check("tail read returns whole records only", all(e["t"] == int(e["t"]) for e in tail["S"]), True)
check("tail read keeps the newest", tail["S"][-1]["t"], 199.0)

# --- tick.py: the verdict ----------------------------------------------------
N = lambda t, typ="permission_prompt", msg="Claude needs your permission to use Bash": \
    {"hook_event_name": "Notification", "t": t, "notification_type": typ, "message": msg}
S = lambda t: {"hook_event_name": "Stop", "t": t}
B = lambda t: {"hook_event_name": "PostToolUse", "t": t, "tool_name": "Bash"}

stop, notify, cur = tick.hook_verdict([B(1), S(2), B(3)], seen=0)
check("a Stop after `seen` is the turn ending", (stop["t"], notify, cur), (2, None, 3))
stop, notify, cur = tick.hook_verdict([B(1), S(2), B(3)], seen=2)
check("a Stop at or before `seen` is old news", (stop, cur), (None, 3))
stop, notify, cur = tick.hook_verdict([S(2), S(5), S(9)], seen=4)
check("the newest Stop wins", stop["t"], 9)
stop, notify, cur = tick.hook_verdict([S(2), N(5)], seen=2)
check("a Notification with no Stop after it: the prompt is still up", notify["t"], 5)
stop, notify, cur = tick.hook_verdict([S(2), N(5)], seen=100)
check("...regardless of `seen` — a prompt stays up until answered", notify["t"], 5)
stop, notify, cur = tick.hook_verdict([N(5), S(7)], seen=0)
check("a Stop after the Notification means the prompt was answered", notify, None)
stop, notify, cur = tick.hook_verdict([S(2), N(5, "idle_prompt", "Claude is waiting for your input")], seen=2)
check("idle_prompt is not needs-input", notify, None)
stop, notify, cur = tick.hook_verdict([S(2), N(5, "auth_success")], seen=2)
check("auth_success is not needs-input", notify, None)
stop, notify, cur = tick.hook_verdict([S(2), {"hook_event_name": "Notification", "t": 5, "message": "?"}], seen=2)
check("a Notification with no type is taken as needs-input", notify["t"], 5)
check("no events at all", tick.hook_verdict([], seen=0), (None, None, 0.0))
check("junk t is skipped", tick.hook_verdict([{"hook_event_name": "Stop", "t": "soon"}], 0), (None, None, 0.0))

# --- tick.py: merging the hook's word with the transcript's -------------------
q = ("question", "Name for the unlock?\n1. Deep Time\n2. 20,000 Years")
perm = ("permission", "Bash — rm -rf build/")
check("no hook notification: the transcript's verdict stands", tick.hook_pending(None, perm), perm)
check("transcript question wins on content", tick.hook_pending(N(5), q), q)
check("transcript permission detail (the command) beats the hook's generic message",
      tick.hook_pending(N(5), perm), perm)
check("hook alone: permission with the hook's message",
      tick.hook_pending(N(5), None), ("permission", "Claude needs your permission to use Bash"))
check("hook alone naming AskUserQuestion is a question",
      tick.hook_pending(N(5, msg="Claude needs your permission to use AskUserQuestion"), None),
      ("question", "Claude needs your permission to use AskUserQuestion"))
check("hook with an empty message still says something",
      tick.hook_pending({"hook_event_name": "Notification", "t": 1}, None), ("permission", "permission prompt"))

# --- the branch guards, as pure decisions -------------------------------------
# Mirrors the busy-branch condition: with hooks a Stop is the boundary and the
# screen is never consulted; without, the old line-count + at-prompt pair.
def busy_turn_over(hv, stop_ev, nlines, seen, at_prompt_calls):
    if hv is not None:
        return stop_ev is not None
    at_prompt_calls.append(1)
    return nlines > seen and True

calls = []
check("hooks: Stop -> turn over, screen never scraped", (busy_turn_over([S(1)], S(1), 400, 400, calls), calls), (True, []))
check("hooks: no Stop -> still running, even with new lines", busy_turn_over([S(1)], None, 500, 400, calls), False)
check("no hooks: heuristics as before", (busy_turn_over(None, None, 500, 400, calls), len(calls)), (True, 1))


def idle_finished(prev_status, busy_since, now, hv, stop_ev):
    finished = prev_status == "busy" and bool(busy_since) and (now - (busy_since or now)) >= tick.MIN_FINISHED_SECS
    if finished and hv is not None and stop_ev is None:
        finished = False
    return finished

NOW = 1_000_000.0
check("no hooks: busy->idle after 10m is finished", idle_finished("busy", NOW - 600, NOW, None, None), True)
check("hooks: busy->idle with a Stop is finished", idle_finished("busy", NOW - 600, NOW, [S(1)], S(1)), True)
check("hooks: busy->idle WITHOUT a Stop is not (interrupted, or already reported)",
      idle_finished("busy", NOW - 600, NOW, [S(1)], None), False)
check("either way a short turn is chatter", idle_finished("busy", NOW - 30, NOW, [S(1)], S(1)), False)

# --- guard rails --------------------------------------------------------------
check("log lives beside the other status files", tick.HOOKS_LOG.endswith("/.claude/status/_hooks.jsonl"), True)
check("handler is executable", os.access(HOOK, os.X_OK), True)
with open(HOOK) as f:
    src = f.read()
check("handler never imports beyond stdlib", all(m in ("json", "os", "re", "subprocess", "sys", "time")
                                                 for m in src.split("\nimport ", 1)[1].split("\n", 1)[0].split(", ")), True)

# The scratch tree is left to the OS temp reaper on purpose: this repo has a
# standing rule against recursive deletes, tests included.

if fails:
    print("FAIL")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("hooks: ok")
