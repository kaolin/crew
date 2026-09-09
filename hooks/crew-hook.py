#!/usr/bin/env python3
"""crew-hook: one JSON line per Claude Code hook event, nothing else.

Claude Code runs this with the event JSON on stdin (Notification, Stop, and
PostToolUse for Bash — see `crew hooks`). It appends one line to
~/.claude/status/_hooks.jsonl so the pinger can read "needs you" and "finished"
off a fact instead of a transcript regex, and — when the Bash command was a
`git commit` — one line to ~/.claude/status/_commits.jsonl so every commit knows
which session made it (the two things worth stealing from sauron).

Fail-open by construction: always exit 0, never print to stdout (stdout is how a
hook talks back to Claude; ours never does), never block, never raise. A hook that
misbehaves gates every session on this Mac, which is exactly what happened once.

Stdlib only. Honours CREW_HOME like crew does, so tests never touch the live log.
"""
import json, os, re, subprocess, sys, time

HOME        = os.environ.get("CREW_HOME") or os.path.expanduser("~")
STATUS_DIR  = os.path.join(HOME, ".claude", "status")
HOOKS_LOG   = os.path.join(STATUS_DIR, "_hooks.jsonl")
COMMITS_LOG = os.path.join(STATUS_DIR, "_commits.jsonl")

MAX_STDIN   = 4 * 1024 * 1024   # a Bash tool_response can be big; anything past this is not ours to parse
MAX_TEXT    = 500               # per recorded string; keeps one record inside a single write()
GIT_TIMEOUT = 0.4               # seconds per git call; three calls stay well under a second
COMMIT_FRESH_SECS = 300         # HEAD must have been committed this recently to be "this command's"

# `git commit`, `git -C <dir> commit`, `cd <dir> && git commit`, `git -c k=v --no-pager commit`;
# not `git log … # last commit`, not `git commit-tree`.
GIT_COMMIT_RE = re.compile(
    r"(?<![\w-])git\b(?:\s+-C\s+(?P<cdir>\S+))?"
    r"(?:\s+-{1,2}[\w-]+(?:[= ](?!commit\b)\S+)?)*"
    r"\s+commit(?![\w-])")
CD_RE         = re.compile(r"^\s*cd\s+(?P<dir>[^\s;&|]+)\s*(?:&&|;)")


def _s(v, n=MAX_TEXT):
    """Clip a value to a short string; None stays None."""
    if v is None:
        return None
    v = v if isinstance(v, str) else json.dumps(v)
    return v if len(v) <= n else v[:n] + "…"


def append(path, rec):
    """One line, one write(). O_APPEND keeps concurrent sessions from interleaving
    as long as a record fits in one write, which MAX_TEXT guarantees."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def git(repo, *args):
    """stdout of a git command, '' on any failure or timeout. Never raises."""
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                             timeout=GIT_TIMEOUT,
                             env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def commit_dir(command, cwd):
    """Where the commit happened: `git -C <dir>` wins, then a leading `cd <dir> &&`,
    else the session's cwd."""
    m = GIT_COMMIT_RE.search(command or "")
    if not m:
        return None
    d = m.group("cdir")
    if not d:
        cd = CD_RE.match(command or "")
        d = cd.group("dir") if cd else None
    d = os.path.expanduser(d.strip("'\"")) if d else (cwd or "")
    return os.path.normpath(os.path.join(cwd or "", d)) if not os.path.isabs(d) else d


def last_sha(path):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
        return json.loads(tail[-1]).get("sha") if tail else None
    except Exception:
        return None


def record_commit(d, command, now):
    """Log HEAD as this session's commit if the Bash command ran `git commit` and
    HEAD was committed just now. Reading git back — rather than trusting the
    command — means a commit that failed (hook, nothing staged, wrong dir) is not
    recorded, and `--amend`/`-q` are, without parsing git's chatter."""
    repo = commit_dir(command, d.get("cwd"))
    if not repo:
        return
    top = git(repo, "rev-parse", "--show-toplevel")
    if not top:
        return
    line = git(top, "log", "-1", "--format=%H%x00%ct%x00%s")
    if not line or "\x00" not in line:
        return
    sha, ctime, subject = (line.split("\x00", 2) + ["", ""])[:3]
    try:
        if now - int(ctime) > COMMIT_FRESH_SECS:
            return                         # HEAD predates this command: the commit did not happen
    except ValueError:
        return
    if sha == last_sha(COMMITS_LOG):
        return                             # a second `git commit` in one turn that changed nothing
    branch = git(top, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    append(COMMITS_LOG, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "t": round(now, 3),
        "session_id": d.get("session_id"), "cwd": d.get("cwd"),
        "repo": top, "project": os.path.basename(top.rstrip("/")),
        "branch": branch, "sha": sha, "subject": _s(subject, 200),
    })


def main():
    raw = sys.stdin.read(MAX_STDIN)
    d = json.loads(raw)
    if not isinstance(d, dict):
        return
    now = time.time()
    ev = d.get("hook_event_name") or ""
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "t": round(now, 3),
           "hook_event_name": ev, "session_id": d.get("session_id"), "cwd": d.get("cwd")}
    if ev == "Notification":
        rec["notification_type"] = _s(d.get("notification_type"), 60)
        rec["message"] = _s(d.get("message"))
        if d.get("title"):
            rec["title"] = _s(d.get("title"), 120)
    elif ev == "Stop":
        rec["stop_hook_active"] = bool(d.get("stop_hook_active"))
        if d.get("stop_reason"):
            rec["stop_reason"] = _s(d.get("stop_reason"), 60)
        if d.get("last_assistant_message"):
            rec["last_assistant_message"] = _s(d.get("last_assistant_message"), 300)
    elif ev == "PostToolUse":
        tool = d.get("tool_name") or ""
        rec["tool_name"] = _s(tool, 60)
        if tool == "Bash":
            inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
            command = inp.get("command") or ""
            rec["command"] = _s(command)
            out = d.get("tool_output", d.get("tool_response"))   # the docs have used both names
            if isinstance(out, dict) and out.get("exit_code") is not None:
                rec["exit_code"] = out.get("exit_code")
            if GIT_COMMIT_RE.search(command):
                try:
                    record_commit(d, command, now)
                except Exception:
                    pass
    append(HOOKS_LOG, rec)


if __name__ == "__main__":
    try:
        main()
    except BaseException:      # noqa: BLE001 — a hook that raises gates the session; we never do
        pass
    finally:
        os._exit(0)            # exit 0 whatever happened, and nothing ever reached stdout
