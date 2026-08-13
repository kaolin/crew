#!/usr/bin/env python3
"""readings.tsv -> hourly spend, as deltas between consecutive samples.

The endpoint reports a cumulative percentage of each window, so spend for an
hour is the rise across it. Two things make that less trivial than subtraction:

- A window reset makes the counter fall. `resets_at` moving is the signal; the
  delta across that boundary is discarded, not recorded as negative spend.
- Samples land every ~15 min, so an hour holds several. The hour's spend is
  last-minus-first WITHIN the hour, and the gap between hours is carried by the
  next hour's first sample rather than being dropped.

Units are percent of the weekly window — the endpoint returns utilization only
(limit_dollars and used_dollars are null on this plan), so there is no honest
conversion to tokens or dollars here.
"""
import collections, csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "readings.tsv")


def load(path=SRC):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    out = []
    for r in rows:
        try:
            pct = float(r["seven_day_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"ts": r["ts"], "pct": pct, "window": r.get("seven_day_resets", "")[:10]})
    return out


def hourly(samples):
    """[(hour, delta_pct, n_samples)] — window resets break the chain."""
    by_hour = collections.OrderedDict()
    for s in samples:
        by_hour.setdefault(s["ts"][:13], []).append(s)

    result, prev_last = [], None
    for hour, group in by_hour.items():
        first, last = group[0], group[-1]
        # Prefer measuring from the previous hour's last sample so the gap
        # between hours isn't silently dropped; fall back to within-hour.
        base = prev_last if prev_last and prev_last["window"] == first["window"] else first
        delta = last["pct"] - base["pct"]
        if last["window"] != base["window"] or delta < 0:
            delta = None                      # window rolled over — unknowable
        result.append((hour, delta, len(group)))
        prev_last = last
    return result


if __name__ == "__main__":
    samples = load()
    if not samples:
        print("no readings yet — the sampler writes one every 15 min", file=sys.stderr)
        raise SystemExit(1)
    rows = hourly(samples)
    print(f"{len(samples)} samples over {len(rows)} hour(s)"
          f"  ({samples[0]['ts']} → {samples[-1]['ts']})")
    print(f"{'hour':<14}{'Δ% of week':>12}{'samples':>9}")
    for hour, delta, n in rows:
        shown = "  window reset" if delta is None else f"{delta:>11.2f}%"
        print(f"{hour:<14}{shown:>12}{n:>9}")
    known = [d for _, d, _ in rows if d is not None]
    if known:
        print(f"\ntotal measured: {sum(known):.2f}% of the weekly window"
              f"  ·  current: {samples[-1]['pct']:.1f}%")
