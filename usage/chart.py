#!/usr/bin/env python3
"""usage.json + readings.tsv -> chart.html. Pure: reads the two snapshots only.

Two sources, deliberately kept apart on the page because they answer different
questions and have different scope:

  usage.json    local transcripts. Fine-grained (exact tokens per hour) but only
                sees sessions run on this Mac.
  readings.tsv  the /api/oauth/usage sampler. Account-wide (claude.ai, other
                machines) and authoritative on the limit — but the endpoint
                reports whole-number percentages, so an hour that used 0.9% of
                the week reads as 0. That quantisation is why the hourly deltas
                look like a staircase and the token chart does not.

Linear scale throughout, on purpose. The peak hour is ~800x the quiet floor, and
a log axis would flatten exactly the spikiness the chart exists to show.
"""
import collections, csv, html, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "chart.html")

# Validated with the dataviz checker on both surfaces; see render.py.
CAT_LIGHT = ["#008C6E", "#E0561F", "#3355D8"]
CAT_DARK = ["#00A884", "#E2622C", "#5C82E8"]


def human(n):
    for unit, size in (("M", 1e6), ("K", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.0f}{unit}" if n / size >= 10 else f"{n / size:.1f}{unit}"
    return str(int(n))


def load():
    hourly = json.load(open(os.path.join(HERE, "usage.json")))["hourly"]
    with open(os.path.join(HERE, "readings.tsv"), newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return hourly, rows


def bars(pairs, peak, colour, fmt):
    out = []
    for label, value, title in pairs:
        pct = 100 * value / peak if peak else 0
        out.append(
            f'<div class="bar" title="{html.escape(title)}">'
            f'<i style="height:{pct:.2f}%;background:{colour}"></i></div>')
    return "".join(out)


def build():
    hourly, rows = load()
    keys = sorted(hourly)

    tok = [(k, hourly[k].get("output_tokens", 0), hourly[k].get("turns", 0)) for k in keys]
    peak_tok = max((v for _, v, _ in tok), default=1) or 1
    peak_hour = max(tok, key=lambda t: t[1])
    floor = min((v for _, v, _ in tok if v > 0), default=1)
    total_tok = sum(v for _, v, _ in tok)
    total_turns = sum(t for _, _, t in tok)

    tok_bars = "".join(
        f'<div class="bar" title="{k[:10]} {k[11:13]}:00 — {v:,} output tokens, {t} turns">'
        f'<i style="height:{100 * v / peak_tok:.2f}%"></i></div>'
        for k, v, t in tok)

    # Sampled windows. Plot every sample, not an hourly roll-up: the 5-hour
    # window resets mid-hour and a roll-up would hide the sawtooth.
    seven = [(r["ts"], float(r["seven_day_pct"] or 0)) for r in rows]
    five = [(r["ts"], float(r["five_hour_pct"] or 0)) for r in rows]
    peak5 = max((v for _, v in five), default=1) or 1

    seven_bars = "".join(
        f'<div class="bar" title="{ts.replace(chr(84), chr(32))} — {v:.0f}% of the weekly window">'
        f'<i style="height:{100 * v / 100:.2f}%;background:var(--cat1)"></i></div>'
        for ts, v in seven)
    five_bars = "".join(
        f'<div class="bar" title="{ts.replace(chr(84), chr(32))} — {v:.0f}% of the 5-hour window">'
        f'<i style="height:{100 * v / peak5:.2f}%;background:var(--cat2)"></i></div>'
        for ts, v in five)

    # The quiet floor is machine, not human: those hours are the crew-pinger
    # heartbeat. Worth naming so the chart isn't read as "he works all night".
    floor_hours = sum(1 for _, v, _ in tok if v <= floor * 1.2)

    return TEMPLATE.format(
        span=f"{keys[0][:10]} {keys[0][11:13]}:00 → {keys[-1][:10]} {keys[-1][11:13]}:00",
        generated=time.strftime("%Y-%m-%d %H:%M"),
        peak=f"{peak_hour[1]:,}", peak_h=human(peak_hour[1]),
        peak_when=f"{peak_hour[0][:10]} {peak_hour[0][11:13]}:00",
        peak_turns=peak_hour[2],
        floor=f"{floor:,}", ratio=f"{peak_hour[1] / floor:.0f}",
        floor_hours=floor_hours, hours=len(tok),
        total_tok=f"{total_tok:,}", total_h=human(total_tok), total_turns=f"{total_turns:,}",
        tok_bars=tok_bars, seven_bars=seven_bars, five_bars=five_bars,
        week_now=f"{seven[-1][1]:.0f}", samples=len(rows),
        cat_light=" ".join(f"--cat{i}:{c};" for i, c in enumerate(CAT_LIGHT)),
        cat_dark=" ".join(f"--cat{i}:{c};" for i, c in enumerate(CAT_DARK)),
    )


TEMPLATE = """<title>How spiky is it — usage</title>
<style>
:root {{
  --bg:#fcfcfb; --panel:#fff; --line:#e4e3df; --ink:#1b1d1c; --dim:#5d615e;
  --faint:#8d918d; --idle:#eceae5; {cat_light}
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --bg:#14181c; --panel:#191e23; --line:#2b3238; --ink:#e8ecea; --dim:#9aa4a0;
  --faint:#6d7773; --idle:#232a30; {cat_dark}
}} }}
:root[data-theme="dark"] {{
  --bg:#14181c; --panel:#191e23; --line:#2b3238; --ink:#e8ecea; --dim:#9aa4a0;
  --faint:#6d7773; --idle:#232a30; {cat_dark}
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"SF Pro Text",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:1000px;margin:0 auto;padding:40px 22px 72px}}
h1{{font-size:24px;letter-spacing:-.02em;margin:0 0 4px;font-weight:650}}
.sub{{color:var(--dim);font-size:13.5px;margin:0 0 26px}}
.tiles{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  margin-bottom:24px}}
.tile{{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px 16px}}
.tile .k{{font-size:11px;letter-spacing:.075em;text-transform:uppercase;color:var(--faint);
  font-weight:600}}
.tile .v{{font-size:25px;font-weight:660;letter-spacing:-.02em;margin-top:5px;
  font-variant-numeric:tabular-nums}}
.tile .n{{font-size:12px;color:var(--dim);margin-top:2px;font-variant-numeric:tabular-nums}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:20px 20px 18px;margin-bottom:18px}}
h2{{font-size:12px;letter-spacing:.075em;text-transform:uppercase;color:var(--faint);
  margin:0 0 3px;font-weight:650}}
.note{{color:var(--dim);font-size:13px;margin:0 0 15px;max-width:70ch}}
.chart{{overflow-x:auto;padding-bottom:4px}}
.bars{{display:flex;align-items:flex-end;gap:1px;height:180px;min-width:600px;
  border-bottom:1px solid var(--line)}}
.bar{{flex:1 1 0;min-width:2px;height:100%;display:flex;align-items:flex-end;
  background:linear-gradient(var(--idle),var(--idle)) bottom/100% 1px no-repeat}}
.bar i{{display:block;width:100%;background:var(--cat0);border-radius:2px 2px 0 0}}
.axis{{display:flex;justify-content:space-between;color:var(--faint);font-size:11px;
  margin-top:7px;font-variant-numeric:tabular-nums}}
.caveat{{border-left:3px solid var(--cat1);padding-left:14px;margin-top:22px;
  color:var(--dim);font-size:13px;max-width:76ch}}
.caveat b{{color:var(--ink)}}
@media (max-width:640px){{ .wrap{{padding:28px 15px 56px}} }}
</style>
<div class="wrap">
<h1>How spiky is it</h1>
<p class="sub">{span} · generated {generated}</p>

<div class="tiles">
  <div class="tile"><div class="k">Peak hour</div><div class="v">{peak_h}</div>
    <div class="n">{peak} tokens · {peak_turns} turns</div></div>
  <div class="tile"><div class="k">Quiet floor</div><div class="v">{floor}</div>
    <div class="n">{floor_hours} of {hours} hours sit here</div></div>
  <div class="tile"><div class="k">Peak ÷ floor</div><div class="v">{ratio}×</div>
    <div class="n">the answer, basically</div></div>
  <div class="tile"><div class="k">Weekly window</div><div class="v">{week_now}%</div>
    <div class="n">{samples} samples so far</div></div>
</div>

<section>
  <h2>Output tokens per hour</h2>
  <p class="note">The spikiness answer. Linear scale on purpose — a log axis would
     flatten the very thing you're asking about. Peak is <b>{peak}</b> tokens at
     {peak_when}; most hours are a rounding error beside it.</p>
  <div class="chart"><div class="bars">{tok_bars}</div></div>
  <div class="axis"><span>{span}</span><span>peak {peak} tok/h</span></div>
</section>

<section>
  <h2>Weekly window consumed</h2>
  <p class="note">Account-wide, from the usage endpoint — this is the number the
     plan actually meters. It only climbs; the reset is 07:00 Thursday. Scale is
     0–100% of the window, so the height here is your real headroom.</p>
  <div class="chart"><div class="bars">{seven_bars}</div></div>
  <div class="axis"><span>0–100% of the weekly limit</span><span>now {week_now}%</span></div>
</section>

<section>
  <h2>Five-hour window</h2>
  <p class="note">The sawtooth is the rolling 5-hour limit filling and resetting.
     Every sample is plotted rather than rolled up per hour, because the window
     resets mid-hour and averaging would erase the shape.</p>
  <div class="chart"><div class="bars">{five_bars}</div></div>
  <div class="axis"><span>each bar = one 15-minute sample</span><span>peak of window</span></div>
</section>

<p class="caveat"><b>Two things that shape what you're looking at.</b>
The token chart comes from transcripts on this Mac, so it misses claude.ai and
your other machines; the two percentage charts are account-wide and authoritative
on the limit. And the endpoint reports <b>whole-number percentages only</b> — an
hour that burned 0.9% of the week reads as 0 — which is why those two look like
staircases while the token chart has texture. The quiet floor of {floor} tokens
an hour is not you: it's the crew-pinger heartbeat, a machine baseline that never
stops. Sampling began 2026-08-13 08:16; nothing before that can be recovered,
because the endpoint keeps no history.</p>
</div>
"""


if __name__ == "__main__":
    open(OUT, "w").write(build())
    print(f"wrote {OUT}")
