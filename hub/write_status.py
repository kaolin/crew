#!/usr/bin/env python3
"""Write a session's ~/.claude/status/<app>.json, with the clock READ, not recalled.

    python3 ~/.crew/hub/write_status.py --state "..." --last "..." \
        [--decision "..."]... [--blocker "..."]... [--app NAME] [--show]

Run it from anywhere inside the project's repo; --app defaults to the git
root's directory name lowercased. Generic version of poemranker's
tools/status.py (dd35cae) -- same guarantee, no project-specific paths.

WHY A SCRIPT FOR A SIX-LINE JSON WRITE.

~/.claude/status/<app>.json is not private notes. crew-pinger reads
`updated_at` to decide whether a session has STALLED, and the hub reads the
whole file on a restart and relays what it says to kaolin. So a wrong line
in it does not stay wrong locally -- it becomes the hub's fact and then
kaolin's decision. The propagation path is: session file -> hub relay -> his
call.

That happened on 2026-09-27. poemranker's file said batch 15 was "staged,
awaiting go" when it had been live on the server for days, and that claim
went out in two of its messages and two of the hub's before anyone diffed
the server. Same evening, subtler: the file's CONTENT was corrected but its
`updated_at` was twelve minutes stale, because a worked-out time was typed
instead of a read one. A stale timestamp on correct content is worse than
obviously old content -- it reads as current. The hub had the same drift at
larger scale, up to 27 minutes, from the same habit.

Writing "always read the clock" down did not prevent it on either side: the
rule was already in the hub's notes from a previous instance. Drift
accumulates silently and nothing in a transcript contradicts a guessed time.
So the guard is mechanical -- this script stamps from the system clock and
offers NO WAY to pass a time in. `head` and `unpushed` come from git for the
same reason.

Everything it does not mention it leaves alone, so it is safe for a
one-field update.
"""
import argparse, json, pathlib, subprocess, sys


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo)] + list(args),
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ''


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--state', help='where the work stands')
    ap.add_argument('--last', dest='last_action', help='what was just finished')
    ap.add_argument('--decision', action='append', default=None,
                    help='replaces needs_decision; repeat per item')
    ap.add_argument('--blocker', action='append', default=None,
                    help='replaces blockers; repeat per item (--blocker "" for none)')
    ap.add_argument('--device', help='device this work targets, if any')
    ap.add_argument('--app', help='status file basename; default = git root dir name')
    ap.add_argument('--show', action='store_true', help='print the file afterwards')
    a = ap.parse_args()

    root = git(pathlib.Path.cwd(), 'rev-parse', '--show-toplevel')
    repo = pathlib.Path(root) if root else pathlib.Path.cwd()
    app = a.app or repo.name.lower()
    status = pathlib.Path.home() / '.claude' / 'status' / f'{app}.json'

    d = json.loads(status.read_text()) if status.exists() else {'session': app}

    # never passed in, always taken from the machine
    d['updated_at'] = subprocess.run(['date', '+%Y-%m-%dT%H:%M%z'],
                                     capture_output=True, text=True).stdout.strip()
    if root:
        d['head'] = git(repo, 'rev-parse', '--short', 'HEAD')
        dirty = git(repo, 'status', '--porcelain')
        d['unpushed'] = ('uncommitted changes in the working tree' if dirty
                         else 'committed (working tree clean)') + (
                         '; repo has no remote' if not git(repo, 'remote') else '')

    if a.state:
        d['state'] = a.state
    if a.last_action:
        d['last_action'] = a.last_action
    if a.device:
        d['device'] = a.device
    # Omitting --decision/--blocker RETAINS what was there. That default is the
    # safe one -- a session writing a routine status must not silently drop a real
    # open decision it simply didn't restate. But silent retention has its own
    # failure, and it bit on 2026-09-29: curiouser wrote a status at 12:45 without
    # --decision, so a question kaolin had answered THAT MINUTE stayed in the file.
    # The hub then read it while assembling his "what's outstanding" list and
    # nearly handed him a decision he had already made.
    #
    # So retention stays, but it is no longer silent: anything carried forward is
    # echoed back. The writer sees the stale line in its own terminal and fixes it.
    # This is the same discipline as reading the clock instead of recalling it --
    # the value you did not set is exactly the one you stop checking.
    carried = []
    if a.decision is not None:
        d['needs_decision'] = [x for x in a.decision if x]
    elif d.get('needs_decision'):
        carried += [('needs_decision', x) for x in d['needs_decision']]
    if a.blocker is not None:
        d['blockers'] = [x for x in a.blocker if x]
    elif d.get('blockers'):
        carried += [('blockers', x) for x in d['blockers']]

    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(json.dumps(d, indent=2) + '\n')

    print(f"{status}  updated_at {d['updated_at']}  head {d.get('head', '(not a repo)')}")
    if carried:
        print(f"  CARRIED FORWARD unchanged ({len(carried)}) -- still true? "
              f"pass --decision/--blocker to replace, or '' to clear:", file=sys.stderr)
        for field, item in carried:
            print(f"    {field}: {item[:120]}", file=sys.stderr)
    if a.show:
        print(json.dumps(d, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
