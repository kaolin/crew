#!/usr/bin/env python3
"""Sample the point-in-time usage endpoint and append one row to readings.tsv.

This is the number the plan actually meters — `/api/oauth/usage` is what the
CLI's own /usage screen reads. Unlike hourly.py, which reconstructs spend from
this machine's transcripts, these figures are account-wide: claude.ai, other
computers, every session, all included.

The catch that shapes the whole design: the endpoint reports utilization RIGHT
NOW and keeps no history. Nothing can backfill it. An hour that goes unsampled
is gone, so this runs on a timer and the series only ever starts from the first
sample. Deltas between consecutive readings within one window are the hourly
spend; a reading whose `resets_at` moved means the window rolled over and the
delta across that boundary is meaningless, not negative.

The OAuth token is read from the Keychain on every run (Claude Code refreshes
it in place) and never written to disk.
"""
import json, os, subprocess, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "readings.tsv")
URL = "https://api.anthropic.com/api/oauth/usage"
COLS = ("ts", "five_hour_pct", "five_hour_resets", "seven_day_pct",
        "seven_day_resets", "opus_pct", "extra_enabled",
        "fable_pct", "fable_resets")
# fable_pct/fable_resets: the per-model weekly cap the endpoint reports under
# `limits` as kind=weekly_scoped with scope.model.display_name. Added
# 2026-09-12 after kaolin hit that cap with nothing tracking it; rows before
# then have the two fields empty.


def token():
    """Current OAuth access token from the login keychain, or None."""
    try:
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if raw.returncode != 0:
        return None
    try:
        blob = json.loads(raw.stdout)
    except ValueError:
        return None
    oauth = blob.get("claudeAiOauth") or blob
    return oauth.get("accessToken")


def fetch(tok):
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {tok}",
        "anthropic-beta": "oauth-2025-04-20",
        "accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def row(data):
    def part(name, field="utilization"):
        block = data.get(name)
        return (block or {}).get(field)

    def scoped(model_name, field="percent"):
        for lim in data.get("limits") or []:
            if lim.get("kind") != "weekly_scoped":
                continue
            model = ((lim.get("scope") or {}).get("model") or {})
            if model.get("display_name") == model_name:
                return lim.get(field)
        return None

    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "fable_pct": scoped("Fable"),
        "fable_resets": scoped("Fable", "resets_at"),
        "five_hour_pct": part("five_hour"),
        "five_hour_resets": part("five_hour", "resets_at"),
        "seven_day_pct": part("seven_day"),
        "seven_day_resets": part("seven_day", "resets_at"),
        "opus_pct": part("seven_day_opus"),
        "extra_enabled": (data.get("extra_usage") or {}).get("is_enabled"),
    }


def migrate_header():
    """Older files carry fewer columns; rewrite once so DictReader keeps the
    column names aligned. Old rows get empty trailing fields."""
    with open(OUT) as f:
        lines = f.read().splitlines()
    if not lines or lines[0].split("\t") == list(COLS):
        return
    old = lines[0].split("\t")
    if old != list(COLS[:len(old)]):
        raise SystemExit(f"readings.tsv header {old} is not a prefix of COLS; refusing to rewrite")
    pad = "\t" * (len(COLS) - len(old))
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        f.write("\t".join(COLS) + "\n")
        for ln in lines[1:]:
            f.write(ln + pad + "\n")
    os.replace(tmp, OUT)


def append(r):
    new = not os.path.exists(OUT) or os.path.getsize(OUT) == 0
    if not new:
        migrate_header()
    with open(OUT, "a") as f:
        if new:
            f.write("\t".join(COLS) + "\n")
        f.write("\t".join("" if r.get(c) is None else str(r[c]) for c in COLS) + "\n")


def main():
    tok = token()
    if not tok:
        print("no OAuth token in keychain — is Claude Code logged in?", file=sys.stderr)
        return 2
    try:
        data = fetch(tok)
    except urllib.error.HTTPError as e:
        # 401 means the stored token expired before Claude Code refreshed it.
        # Skip this sample rather than writing a row that looks like zero usage.
        print(f"usage endpoint returned {e.code}", file=sys.stderr)
        return 3
    except Exception as e:                                    # noqa: BLE001
        print(f"usage fetch failed: {e}", file=sys.stderr)
        return 4
    r = row(data)
    append(r)
    print(f"{r['ts']}  5h {r['five_hour_pct']}%  7d {r['seven_day_pct']}%"
          f"  fable {r['fable_pct']}%"
          f"  (7d resets {r['seven_day_resets']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
