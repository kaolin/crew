#!/usr/bin/env python3
"""Hourly token accounting from this machine's Claude CLI transcripts.

Writes usage.json for render.py. NOT the Anthropic usage API: that reports an
API organization's spend, and kaolin's Claude Code runs on a Max subscription,
so none of this consumption appears there. There is also no admin key on this
machine. Local transcripts are therefore the only available source — and they
only see sessions run HERE (not claude.ai, not other computers).

Dedupe is load-bearing. The same assistant message is written to every
transcript that replays it (sidechains, resumed sessions), so a naive sum
double-counts. Keyed on the message id, which is stable across copies.
"""
import collections, glob, json, os, sys, time

HOURS = int(os.environ.get("USAGE_HOURS", "168"))          # default: 7 days
ROOT = os.path.expanduser("~/.claude/projects")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage.json")

# Output tokens are what the plan's weekly limit actually meters, so they lead;
# the cache columns are reported separately rather than folded into an "input"
# total, because they are priced an order of magnitude apart.
FIELDS = ("input_tokens", "output_tokens",
          "cache_creation_input_tokens", "cache_read_input_tokens")


def parse_ts(s):
    """'2026-07-17T03:15:52.230Z' -> epoch seconds, or None."""
    if not s:
        return None
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except ValueError:
        return None


def collect(hours=HOURS):
    cutoff = time.time() - hours * 3600
    seen = set()
    hourly = collections.defaultdict(lambda: collections.Counter())
    by_project = collections.Counter()
    by_model = collections.Counter()
    turns = collections.Counter()
    skipped = 0

    for path in glob.glob(ROOT + "/*/*.jsonl"):
        if os.path.getmtime(path) < cutoff:
            continue                      # whole file predates the window
        project = os.path.basename(os.path.dirname(path))
        project = (project.replace("-Users-kaolin-dev-", "")
                          .replace("-Users-kaolin", "~") or "~")
        try:
            fh = open(path, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line:          # cheap prefilter
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                msg = rec.get("message") or {}
                if msg.get("role") != "assistant":
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                # Window check BEFORE dedupe: a message whose out-of-window copy
                # was read first would otherwise be dropped when its in-window
                # copy came along, silently under-counting the busiest hours.
                ts = parse_ts(rec.get("timestamp"))
                if ts is None or ts < cutoff:
                    continue
                mid = msg.get("id")
                if mid:
                    if mid in seen:
                        continue                   # replayed copy
                    seen.add(mid)

                bucket = time.strftime("%Y-%m-%dT%H", time.localtime(ts))
                row = hourly[bucket]
                for f in FIELDS:
                    row[f] += usage.get(f) or 0
                row["turns"] += 1
                out = usage.get("output_tokens") or 0
                by_project[project] += out
                by_model[msg.get("model") or "?"] += out
                turns[project] += 1

    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hours": hours,
        "source": "local Claude CLI transcripts on this machine",
        "hourly": {k: dict(v) for k, v in sorted(hourly.items())},
        "by_project": dict(by_project.most_common()),
        "by_model": dict(by_model.most_common()),
        "turns_by_project": dict(turns.most_common()),
        "unique_messages": len(seen),
        "unparsed_lines": skipped,
    }


if __name__ == "__main__":
    data = collect()
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
    tot = collections.Counter()
    for row in data["hourly"].values():
        tot.update(row)
    print(f"wrote {OUT}")
    print(f"  {len(data['hourly'])} active hours of the last {data['hours']}")
    print(f"  {tot['turns']} turns ({data['unique_messages']} unique messages)")
    print(f"  out {tot['output_tokens']:,}  in {tot['input_tokens']:,}  "
          f"cache-create {tot['cache_creation_input_tokens']:,}  "
          f"cache-read {tot['cache_read_input_tokens']:,}")
    if data["unparsed_lines"]:
        print(f"  {data['unparsed_lines']} unparsable line(s) skipped")
