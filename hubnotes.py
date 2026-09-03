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
    mark = "·" if r.get("state") == "open" else "✓"
    txt = r.get("text", "").replace("\n", " ")
    if len(txt) > 110:
        txt = txt[:107] + "..."
    line = "  %s #%-3d %-14s %-5s %s" % (mark, r.get("id", 0), r.get("app", "?"), age, txt)
    if r.get("state") != "open" and r.get("evidence"):
        line += "\n        → %s" % r["evidence"]
    return line


def cmd_list(a):
    now = time.time()
    rows = [r for r in _rows() if r.get("state") == "open"]
    if a.app:
        rows = [r for r in rows if r.get("app") == a.app]
    if not rows:
        print("nothing open")
        return
    print("%d open" % len(rows))
    for r in rows:
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

    a = ap.parse_args()
    if not hasattr(a, "fn"):
        ap.print_help()
        return
    a.fn(a)


if __name__ == "__main__":
    main()
