#!/usr/bin/env python3
"""Tests for crew-pinger message batching (split_report).

Regression target: 2026-07-31, an orrery synthesis was delivered to kaolin's
phone cut off mid-list at '3. Attach the build to v1.0…[trimmed]', hiding the
pricing decision. Long reports must batch across messages, never trim.

Run: python3 pinger/test_split.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tick  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILED.append(name)


def lines_from(text):
    return tick._clean(text)


def test_short_report_stays_one_message():
    lines = lines_from("Committed as 7ad1ccd. Build 49 is live on Grayhame.")
    parts = tick.split_report("✅ babypaints-08 · finished", lines)
    check("short report = 1 msg", len(parts) == 1, f"got {len(parts)}")
    check("short report keeps head", parts[0].startswith("✅ babypaints-08"))
    check("short report has body", "7ad1ccd" in parts[0])


def test_long_report_batches_not_trims():
    body = "\n".join(f"- Point {i}: {'x' * 120}" for i in range(60))
    lines = lines_from(body)
    parts = tick.split_report("✅ orrery-4c · finished", lines)
    check("long report batches", len(parts) > 1, f"got {len(parts)}")
    joined = "\n".join(parts)
    check("no trim marker", "[trimmed]" not in joined)
    check("first point present", "Point 0:" in joined)
    check("last point present", "Point 59:" in joined)
    check("all points survive",
          all(f"Point {i}:" in joined for i in range(60)))
    check("continuation marked", parts[1].startswith("… 2/"))


def test_every_part_under_telegram_cap():
    body = "\n".join(f"- {'y' * 200}" for _ in range(80))
    for escape in (False, True):
        parts = tick.split_report("head", lines_from(body), escape=escape)
        over = [len(p) for p in parts if len(p) > 4096]
        check(f"all parts <= 4096 (escape={escape})", not over, f"oversize: {over}")


def test_monster_single_line_is_split():
    lines = lines_from("z" * 9000)
    parts = tick.split_report("head", lines)
    check("monster line splits", len(parts) > 1, f"got {len(parts)}")
    check("monster line not truncated",
          sum(p.count("z") for p in parts) == 9000,
          f"kept {sum(p.count('z') for p in parts)} of 9000")


def test_markdown_escape_and_marker_safe():
    lines = lines_from("- cost is $2.99 (one-time) — no ads!\n" * 200)
    parts = tick.split_report("head", lines, escape=True)
    check("escaped body escapes dot", "2\\.99" in parts[0])
    # the continuation marker itself must not contain MarkdownV2 specials
    marker = parts[1].split("\n", 1)[0]
    bad = [c for c in marker if c in tick._MD_SPECIAL]
    check("continuation marker md-safe", not bad, f"unescaped {bad} in {marker!r}")


def test_gist_limit_covers_real_orrery_report():
    """The report that got cut was 5282 raw chars; GIST_CHARS must not clip it."""
    check("GIST_CHARS >= 12000", tick.GIST_CHARS >= 12000, f"is {tick.GIST_CHARS}")
    items = [(False, "line " + "q" * 90) for _ in range(60)]
    clipped = tick._clip(items, tick.GIST_CHARS)
    check("real-size report not clipped",
          not any(t == "…[trimmed]" for _, t in clipped))


def test_markdown_table_rows_survive():
    """A cut/park decision table must reach the phone, not be dropped as noise."""
    report = (
        "Cut / park until launch:\n"
        "| Item | Verdict |\n"
        "|---|---|\n"
        "| Vision Pro port | **Park** — audience ~1M devices |\n"
        "| Deep-time mode | **Park** — off-thesis for v1 |\n"
    )
    lines = lines_from(report)
    text = "\n".join(t for _, t in lines)
    check("table content kept", "Vision Pro port" in text and "Deep-time mode" in text)
    check("table verdicts kept", "off-thesis for v1" in text)
    check("separator row dropped", "---" not in text, text)
    check("cells joined readably", "Vision Pro port — Park" in text, text)
    check("table rows are bullets", all(b for b, t in lines if "Vision Pro" in t))


def test_no_gist_still_sends_head():
    parts = tick.split_report("✅ name · finished", [])
    check("empty gist keeps head", parts == ["✅ name · finished"], f"got {parts}")


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        print(fn.__name__)
        fn()
    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} — {FAILED}")
        sys.exit(1)
    print("all green")
