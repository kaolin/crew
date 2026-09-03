#!/usr/bin/env python3
"""hubnotes — a ledger of kaolin's notes, so "relayed" stops being mistaken for "handled".

Why this exists: on 2026-08-24 kaolin asked why he'd commented on the same Hide
and See screen repeatedly with nothing changing. His feedback had reached the
session fine — but the session compacted, and compaction turned his live notes
into a NUMBERED LIST OF QUOTES inside a summary. A history list does not
generate work. The note survived and the screen never moved.

So the hub keeps its own ledger. Every note kaolin sends gets a row. A row
closes only when there is EVIDENCE of a change — a commit, a build, a shipped
screen — not when the relay succeeds.

    hubnotes add <app> "<his words>"       # returns the id
    hubnotes list [app]                    # open notes, oldest first
    hubnotes close <id> "<evidence>"       # evidence is required, on purpose
    hubnotes all [app]                     # open + closed
    hubnotes stale [hours]                 # open longer than N hours (default 12)
"""
import sys, os, io, json, time, argparse

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, ".claude", "status", "_hubnotes.jsonl")


def _rows():
    if not os.path.exists(LEDGER):
        return []
    out = []
    for line in io.open(LEDGER, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _write(rows):
    tmp = LEDGER + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, LEDGER)


def _stamp(ts=None):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts or time.time()))


def _next_id(rows):
    return max([r.get("id", 0) for r in rows] or [0]) + 1


def cmd_add(a):
    rows = _rows()
    nid = _next_id(rows)
    rows.append({
        "id": nid,
        "app": a.app,
        "text": a.text.strip(),
        "sent": _stamp(),
        "state": "open",
    })
    _write(rows)
    print("#%d %s" % (nid, a.app))


def _fmt(r, now):
    age = ""
    try:
        t = time.mktime(time.strptime(r["sent"], "%Y-%m-%d %H:%M"))
        h = (now - t) / 3600.0
        age = "%dh" % h if h >= 1 else "%dm" % (h * 60)
    except Exception:
        pass
    mark = {"open": "·", "stale": "~"}.get(r.get("state"), "✓")
    txt = r.get("text", "").replace("\n", " ")
    if len(txt) > 110:
        txt = txt[:107] + "..."
    line = "  %s #%-3d %-14s %-5s %s" % (mark, r.get("id", 0), r.get("app", "?"), age, txt)
    if r.get("state") != "open" and r.get("evidence"):
        line += "\n        → %s" % r["evidence"]
    return line


def cmd_list(a):
    now = time.time()
    allrows = _rows()
    if a.app:
        allrows = [r for r in allrows if r.get("app") == a.app]
    rows = [r for r in allrows if r.get("state") == "open"]
    shelved = [r for r in allrows if r.get("state") == "stale"]
    if not rows:
        print("nothing open")
    else:
        print("%d open" % len(rows))
        for r in rows:
            print(_fmt(r, now))
    # Shelved notes are hidden from the pinger, not from people. Omitting them
    # here turned the anti-nag device into an amnesia device: two fixed notes and
    # one containing a decision kaolin owed sat as neither open nor done until a
    # session went looking (thereby-8e, 2026-09-03). Always show the count and ids.
    if shelved:
        print("%d shelved (no nag; `unshelve <id>` to revive)" % len(shelved))
        for r in shelved:
            print(_fmt(r, now))


def cmd_all(a):
    now = time.time()
    rows = _rows()
    if a.app:
        rows = [r for r in rows if r.get("app") == a.app]
    for r in rows:
        print(_fmt(r, now))


def cmd_close(a):
    rows = _rows()
    hit = None
    for r in rows:
        if r.get("id") == a.id:
            hit = r
            break
    if not hit:
        print("no note #%d" % a.id)
        return
    if not a.evidence.strip():
        print("evidence is required — that is the entire point of this ledger")
        return
    hit["state"] = "done"
    hit["evidence"] = a.evidence.strip()
    hit["closed"] = _stamp()
    _write(rows)
    print("closed #%d" % a.id)


def cmd_reopen(a):
    rows = _rows()
    for r in rows:
        if r.get("id") == a.id:
            r["state"] = "open"
            r["evidence"] = "REOPENED: " + a.why.strip()
            _write(rows)
            print("reopened #%d" % a.id)
            return
    print("no note #%d" % a.id)


def cmd_shelve(a):
    """Open → stale for notes older than N hours. A stale note is kept, shown by
    `all` with a ~, and no longer counts toward the pinger's STALLED rule — so a
    backlog nobody is going to evidence stops nagging kaolin every idle stretch.
    Not closed: closing needs evidence, and there is none."""
    now = time.time()
    rows = _rows()
    done, refused = [], []
    for r in rows:
        if r.get("state") != "open":
            continue
        if a.app and r.get("app") != a.app:
            continue
        try:
            t = time.mktime(time.strptime(r["sent"], "%Y-%m-%d %H:%M"))
        except Exception:
            continue
        if now - t < a.older * 3600:
            continue
        # Refuse when the app has moved since the note was filed: its status file
        # is newer than the note, so the note may already be fixed and needs
        # closing with evidence, not hiding. (#58/#59 were fixed three days before
        # a blanket shelve buried them, 2026-09-03.) --force overrides.
        touched = _app_touched_since(r.get("app"), t)
        if touched and not a.force:
            refused.append((r, touched))
            continue
        r["state"] = "stale"
        r["shelved"] = _stamp()
        done.append(r)
    if done:
        _write(rows)
    print("shelved %d note(s) open longer than %dh%s" % (len(done), a.older, (" in " + a.app) if a.app else ""))
    for r in done:
        print(_fmt(r, now))
    if refused:
        print("refused %d — the app has a status file newer than the note; close with evidence or --force:" % len(refused))
        for r, when in refused:
            print(_fmt(r, now) + "\n        → app status updated %s" % when)


def _app_touched_since(app, since_epoch):
    """The app's ~/.claude/status/<app>.json updated_at, if it is newer than the
    note; else None. Best effort — no file, no opinion."""
    if not app:
        return None
    path = os.path.join(os.path.dirname(LEDGER), app + ".json")
    try:
        d = json.load(io.open(path, encoding="utf-8"))
        s = str(d.get("updated_at") or "").strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                if fmt.endswith("%z"):
                    import datetime as _dt
                    ts = _dt.datetime.strptime(s, fmt).timestamp()
                else:
                    ts = time.mktime(time.strptime(s[:19], fmt))
                return s if ts > since_epoch else None
            except ValueError:
                continue
    except Exception:
        return None
    return None


def cmd_unshelve(a):
    rows = _rows()
    for r in rows:
        if r.get("id") == a.id and r.get("state") == "stale":
            r["state"] = "open"
            r.pop("shelved", None)
            _write(rows)
            print("reopened #%d" % a.id)
            return
    print("no stale note #%d" % a.id)


def cmd_stale(a):
    now = time.time()
    cutoff = a.hours * 3600
    out = []
    for r in _rows():
        if r.get("state") != "open":
            continue
        try:
            t = time.mktime(time.strptime(r["sent"], "%Y-%m-%d %H:%M"))
        except Exception:
            continue
        if now - t >= cutoff:
            out.append(r)
    if not out:
        print("nothing open longer than %dh" % a.hours)
        return
    print("%d open longer than %dh" % (len(out), a.hours))
    for r in out:
        print(_fmt(r, now))


def main():
    ap = argparse.ArgumentParser(prog="hubnotes")
    sub = ap.add_subparsers()

    p = sub.add_parser("add", help="record a note kaolin sent")
    p.add_argument("app")
    p.add_argument("text")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("list", help="open notes")
    p.add_argument("app", nargs="?")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("all", help="every note")
    p.add_argument("app", nargs="?")
    p.set_defaults(fn=cmd_all)

    p = sub.add_parser("close", help="close a note WITH evidence of the change")
    p.add_argument("id", type=int)
    p.add_argument("evidence")
    p.set_defaults(fn=cmd_close)

    p = sub.add_parser("reopen", help="a fix shipped but kaolin has not seen it work")
    p.add_argument("id", type=int)
    p.add_argument("why")
    p.set_defaults(fn=cmd_reopen)

    p = sub.add_parser("stale", help="open longer than N hours")
    p.add_argument("hours", nargs="?", type=int, default=12)
    p.set_defaults(fn=cmd_stale)

    p = sub.add_parser("shelve", help="mark open notes older than N hours stale (kept, but no longer nag)")
    p.add_argument("--older", type=int, default=168, help="hours (default 168 = a week)")
    p.add_argument("--force", action="store_true", help="shelve even if the app has moved since the note")
    p.add_argument("app", nargs="?")
    p.set_defaults(fn=cmd_shelve)

    p = sub.add_parser("unshelve", help="stale -> open")
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_unshelve)

    a = ap.parse_args()
    if not hasattr(a, "fn"):
        ap.print_help()
        return
    a.fn(a)


if __name__ == "__main__":
    main()
