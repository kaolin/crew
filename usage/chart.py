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
import collections, csv, datetime, html, json, os, time


def ascii_safe(html_text):
    """Replace non-ASCII punctuation with HTML entities.

    The page ships without a <meta charset> (the artifact wrapper owns <head>),
    so a host that guesses Latin-1 renders UTF-8 punctuation as mojibake —
    kaolin saw "838Ã—" for "838×" and "â†'" for "→". Entities sidestep the
    guess entirely. Anything still non-ASCII gets a numeric entity.
    """
    ent = {'—': '&mdash;', '–': '&ndash;', '→': '&rarr;', '←': '&larr;', '↔': '&harr;', '·': '&middot;', '×': '&times;', '÷': '&divide;', '’': '&rsquo;', '‘': '&lsquo;', '“': '&ldquo;', '”': '&rdquo;', '…': '&hellip;', '∝': '&prop;', '°': '&deg;', '≥': '&ge;', '≤': '&le;'}
    out = []
    for ch in html_text:
        if ord(ch) < 128:
            out.append(ch)
        else:
            out.append(ent.get(ch) or f"&#{ord(ch)};")
    return "".join(out)


HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "chart.html")

# Validated with the dataviz checker on both surfaces; see render.py.
CAT_LIGHT = ["#008C6E", "#E0561F", "#3355D8"]
CAT_DARK = ["#00A884", "#E2622C", "#5C82E8"]

# Eight categorical slots for the stacked per-project chart. Both surfaces pass
# all six checks of scripts/validate_palette.js; the dark set had to be respaced
# twice (cyan/salmon/violet started too light and salmon↔violet sat at ΔE 14.9,
# under the normal-vision floor).
PROJ_LIGHT = ["#008C6E", "#E0561F", "#3355D8", "#B02E8E",
              "#7C7000", "#0090B8", "#9A3B3B", "#5B3FA8"]
PROJ_DARK  = ["#00A884", "#E2622C", "#5C82E8", "#CC55A8",
              "#9E9020", "#2E9BBF", "#C96A6A", "#8E7BD0"]

# Slope grading for the weekly window: a MAGNITUDE encoding, so one hue stepped
# by lightness rather than a green-to-red rainbow. The palest step sits under
# 3:1 on the light surface, which the checker allows only against visible
# labels — hence the legend under that chart, which is not optional.
SLOPE_LIGHT = ["#D9A461", "#C4761F", "#A8500F", "#7E3A10"]
SLOPE_DARK  = ["#E8BE86", "#DE9445", "#C4671F", "#A34E1B"]
SLOPE_NAME  = ["flat", "gentle", "steep", "very steep"]


def human(n):
    for unit, size in (("M", 1e6), ("K", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.0f}{unit}" if n / size >= 10 else f"{n / size:.1f}{unit}"
    return str(int(n))


def load():
    _u = json.load(open(os.path.join(HERE, "usage.json")))
    hourly, hproj = _u["hourly"], _u.get("hourly_by_project", {})
    meta = _u
    with open(os.path.join(HERE, "readings.tsv"), newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return hourly, hproj, rows, meta


def esc(t):
    return html.escape(str(t), quote=True)


def parse_iso(t):
    return datetime.datetime.fromisoformat(t.replace("Z", "")).timestamp()


def nice_ceiling(v):
    """Round up to a 1/2/5 x 10^n so axis labels land on readable numbers."""
    if v <= 0:
        return 1
    import math
    mag = 10 ** math.floor(math.log10(v))
    for mult in (1, 1.5, 2, 2.5, 3, 4, 5, 10):
        if v <= mult * mag:
            return int(mult * mag)
    return int(10 * mag)


def pct_ceiling(v):
    """Next multiple of 20 above v, so 4 steps land on round tens."""
    return max(20, int(-(-v // 20) * 20))


def yaxis(top, steps, fmt):
    """Label gutter, top value first — matches the gridlines drawn on .bars."""
    vals = [top * i / steps for i in range(steps, -1, -1)]
    return "".join(f"<span>{fmt(v)}</span>" for v in vals)


def rail(stamps):
    """A tick rail aligned 1:1 with the bars above it.

    stamps is [(YYYY-MM-DD, hour)]. One cell per bar, sharing the bars' exact
    flex/gap/min-width so tick i sits at the left edge of bar i — the alignment
    is structural rather than computed, which is why it survives the charts
    having different bar counts and irregular sample spacing.

    A tall labelled tick at each date change, a short one every 4 hours. Derived
    from the data, not from an assumed cadence: the sampled charts are ~15-minute
    readings that drop out whenever the laptop sleeps, so anything counting
    fixed strides would drift.
    """
    cells, prev_day, prev_bucket = [], None, None
    # Label only every k-th day boundary once the span is long: at a month of
    # 15-minute samples every day-label overlaps its neighbour and nothing reads.
    ndays = len({d for d, _ in stamps})
    step = max(1, -(-ndays // 8))
    day_index = -1
    for d, h in stamps:
        bucket = h // 4
        if d != prev_day:
            day_index += 1
            # Weekday first: the shape of this data is a work-week pattern, and
            # "Sat" answers "why is that stretch quiet?" faster than a date does.
            label = datetime.date.fromisoformat(d).strftime("%a %-d %b") if day_index % step == 0 else ""
            cells.append(f'<div class="t day" data-label="{label}"></div>')
        elif bucket != prev_bucket:
            cells.append('<div class="t micro"></div>')
        else:
            cells.append('<div class="t"></div>')
        prev_day, prev_bucket = d, bucket
    return "".join(cells)


def bars(pairs, peak, colour, fmt):
    out = []
    for label, value, title in pairs:
        pct = 100 * value / peak if peak else 0
        out.append(
            f'<div class="bar" title="{html.escape(title)}">'
            f'<i style="height:{pct:.2f}%;background:{colour}"></i></div>')
    return "".join(out)


def build():
    hourly, hproj, rows, meta = load()
    keys = sorted(hourly)

    tok = [(k, hourly[k].get("output_tokens", 0), hourly[k].get("turns", 0)) for k in keys]
    peak_tok = max((v for _, v, _ in tok), default=1) or 1
    peak_hour = max(tok, key=lambda t: t[1])
    floor = min((v for _, v, _ in tok if v > 0), default=1)
    total_tok = sum(v for _, v, _ in tok)
    total_turns = sum(t for _, _, t in tok)

    # Stack order is by TOTAL output across the whole window, not per bar, so a
    # project keeps the same slot and colour in every hour — colour follows the
    # entity, never its rank in that particular bar.
    totals = collections.Counter()
    for row in hproj.values():
        totals.update(row)
    ranked = [p for p, _ in totals.most_common()]
    named, rest = ranked[:7], set(ranked[7:])
    order = named + (["other"] if rest else [])
    slot = {p: i for i, p in enumerate(order)}

    tok_top = nice_ceiling(peak_tok)
    seg_rows = []
    for k, v, t in tok:
        row = collections.Counter()
        for proj, out in (hproj.get(k) or {}).items():
            row[("other" if proj in rest else proj)] += out
        segs = []
        for proj in order:                      # bottom-up, fixed order
            val = row.get(proj, 0)
            if not val:
                continue
            segs.append(
                f'<i class="seg" style="height:{100 * val / tok_top:.3f}%;'
                f'background:var(--p{slot[proj]})" title="{esc(proj)}: {val:,}"></i>')
        seg_rows.append(
            f'<div class="bar" title="{k[:10]} {k[11:13]}:00 — {v:,} output tokens, {t} turns">'
            f'{"".join(segs)}</div>')
    tok_bars = "".join(seg_rows)
    tok_axis = yaxis(tok_top, 4, human)
    tok_legend = "".join(
        f'<span class="key" data-l="{esc(p)}"><i style="background:var(--p{i})"></i>{esc(p)}'
        f' <b>{human(totals[p]) if p != "other" else human(sum(totals[q] for q in rest))}</b></span>'
        for i, p in enumerate(order))

    # Sampled windows. Plot every sample, not an hourly roll-up: the 5-hour
    # window resets mid-hour and a roll-up would hide the sawtooth.
    seven = [(r["ts"], float(r["seven_day_pct"] or 0)) for r in rows]
    five = [(r["ts"], float(r["five_hour_pct"] or 0)) for r in rows]
    peak5 = max((v for _, v in five), default=1) or 1

    # Grade each sample by how fast the line is climbing, hiking-trail style.
    # Thresholds are %-of-window per hour; the endpoint only reports whole
    # numbers, so a single step is 1% and the bands are deliberately coarse.
    def grade(prev, cur):
        if prev is None:
            return 0
        (pt, pv), (ct, cv) = prev, cur
        dt = (parse_iso(ct) - parse_iso(pt)) / 3600 or 1e-9
        rate = (cv - pv) / dt
        for i, edge in enumerate((0.15, 0.6, 1.2)):
            if rate < edge:
                return i
        return 3

    # 864px of usable width at the page's 1000px max, 4px per column.
    MAXBARS = 216
    if len(seven) > MAXBARS:
        step = -(-len(seven) // MAXBARS)          # ceil
        grouped = [seven[i:i + step] for i in range(0, len(seven), step)]
        seven = [(g[-1][0], g[-1][1]) for g in grouped]
        seven_group = step
    else:
        seven_group = 1

    seven_top = pct_ceiling(max((v for _, v in seven), default=0))
    seven_bars, prev = [], None
    for pair in seven:
        ts, v = pair
        g = grade(prev, pair)
        seven_bars.append(
            f'<div class="bar" title="{ts.replace(chr(84), chr(32))} — {v:.0f}% of the weekly '
            f'window, {SLOPE_NAME[g]}">'
            f'<i style="height:{100 * v / seven_top:.2f}%;background:var(--s{g})"></i></div>')
        prev = pair
    seven_bars = "".join(seven_bars)
    seven_axis = yaxis(seven_top, 4, lambda x: f"{x:.0f}%")
    slope_legend = "".join(
        f'<span class="key"><i style="background:var(--s{i})"></i>{n}</span>'
        for i, n in enumerate(SLOPE_NAME))
    # Same column budget, but take the MAX in each bucket rather than the last:
    # this window resets mid-hour, and peaks are the thing worth preserving. At
    # ~2-3 samples per column the trough still lands in the following column, so
    # the sawtooth survives — it would not at heavier grouping.
    if len(five) > MAXBARS:
        step5 = -(-len(five) // MAXBARS)
        five = [max(five[i:i + step5], key=lambda t: t[1])
                for i in range(0, len(five), step5)]
        five_group = step5
    else:
        five_group = 1
    peak5 = max((v for _, v in five), default=1) or 1

    five_axis = yaxis(nice_ceiling(peak5), 4, lambda x: f"{x:.0f}%")
    five_bars = "".join(
        f'<div class="bar" title="{ts.replace(chr(84), chr(32))} — {v:.0f}% of the 5-hour window">'
        f'<i style="height:{100 * v / peak5:.2f}%;background:var(--cat2)"></i></div>'
        for ts, v in five)

    tok_rail = rail([(k[:10], int(k[11:13])) for k, _, _ in tok])
    seven_rail = rail([(ts[:10], int(ts[11:13])) for ts, _ in seven])
    # built after bucketing so it stays 1:1 with the columns
    _five_rail_src = five

    # The quiet floor is machine, not human: those hours are the crew-pinger
    # heartbeat. Worth naming so the chart isn't read as "he works all night".
    floor_hours = sum(1 for _, v, _ in tok if v <= floor * 1.2)

    # Absorbed from the separate hourly page so this is one sheet. Its stacked
    # chart already carries per-project totals in the legend, so only the
    # genuinely distinct numbers come across: cache warmth, the model split,
    # and per-day totals with turn counts.
    cache_read = sum(h.get("cache_read_input_tokens", 0) for h in hourly.values())
    cache_new = sum(h.get("cache_creation_input_tokens", 0) for h in hourly.values())
    raw_in = sum(h.get("input_tokens", 0) for h in hourly.values())
    warm = 100 * cache_read / (cache_read + cache_new + raw_in) if cache_read else 0

    days = collections.defaultdict(lambda: collections.Counter())
    for k, v in hourly.items():
        days[k[:10]]["out"] += v.get("output_tokens", 0)
        days[k[:10]]["turns"] += v.get("turns", 0)
    day_rows = "".join(
        f"<tr><th>{datetime.date.fromisoformat(d).strftime('%a %-d %b')}</th>"
        f'<td class="num">{c["out"]:,}</td><td class="num">{c["turns"]:,}</td>'
        f'<td class="trackcell"><span class="track"><i class="fill" '
        f'style="width:{100 * c["out"] / max(x["out"] for x in days.values()):.1f}%"></i></span></td></tr>'
        for d, c in sorted(days.items()))

    models = meta.get("by_model", {})
    mtot = sum(models.values()) or 1
    model_rows = "".join(
        f"<tr><th>{esc(m)}</th><td class=\"num\">{v:,}</td>"
        f'<td class="num">{100 * v / mtot:.1f}%</td>'
        f'<td class="trackcell"><span class="track"><i class="fill" '
        f'style="width:{100 * v / max(models.values()):.1f}%"></i></span></td></tr>'
        for m, v in models.items())

    return TEMPLATE.format(
        total_out=f"{total_tok:,}", total_out_h=human(total_tok),
        turns_h=f"{total_turns:,}", warm=f"{warm:.1f}",
        cache_h=human(cache_read), day_rows=day_rows, model_rows=model_rows,
        span=f"{keys[0][:10]} {keys[0][11:13]}:00 → {keys[-1][:10]} {keys[-1][11:13]}:00",
        generated=time.strftime("%Y-%m-%d %H:%M"),
        peak=f"{peak_hour[1]:,}", peak_h=human(peak_hour[1]),
        peak_when=f"{peak_hour[0][:10]} {peak_hour[0][11:13]}:00",
        peak_turns=peak_hour[2],
        floor=f"{floor:,}", ratio=f"{peak_hour[1] / floor:.0f}",
        floor_hours=floor_hours, hours=len(tok),
        total_tok=f"{total_tok:,}", total_h=human(total_tok), total_turns=f"{total_turns:,}",
        tok_bars=tok_bars, seven_bars=seven_bars, five_bars=five_bars,
        tok_rail=tok_rail,
        sample_rail=rail([(ts[:10], int(ts[11:13])) for ts, _ in five]),
        seven_rail=seven_rail, five_group=five_group,
        seven_group=seven_group,
        tok_axis=tok_axis, tok_legend=tok_legend, seven_axis=seven_axis,
        slope_legend=slope_legend, five_axis=five_axis,
        proj_light=" ".join(f"--p{i}:{c};" for i, c in enumerate(PROJ_LIGHT)),
        proj_dark=" ".join(f"--p{i}:{c};" for i, c in enumerate(PROJ_DARK)),
        slope_light=" ".join(f"--s{i}:{c};" for i, c in enumerate(SLOPE_LIGHT)),
        slope_dark=" ".join(f"--s{i}:{c};" for i, c in enumerate(SLOPE_DARK)),
        week_now=f"{seven[-1][1]:.0f}", samples=len(rows), seven_top=seven_top,
        cat_light=" ".join(f"--cat{i}:{c};" for i, c in enumerate(CAT_LIGHT)),
        cat_dark=" ".join(f"--cat{i}:{c};" for i, c in enumerate(CAT_DARK)),
    )


TEMPLATE = """<title>How spiky is it — usage</title>
<style>
:root {{
  --bg:#fcfcfb; --panel:#fff; --line:#e4e3df; --ink:#1b1d1c; --dim:#5d615e;
  --faint:#8d918d; --idle:#eceae5; {cat_light} {proj_light} {slope_light}
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --bg:#14181c; --panel:#191e23; --line:#2b3238; --ink:#e8ecea; --dim:#9aa4a0;
  --faint:#6d7773; --idle:#232a30; {cat_dark} {proj_dark} {slope_dark}
}} }}
:root[data-theme="dark"] {{
  --bg:#14181c; --panel:#191e23; --line:#2b3238; --ink:#e8ecea; --dim:#9aa4a0;
  --faint:#6d7773; --idle:#232a30; {cat_dark} {proj_dark} {slope_dark}
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
.bars{{display:flex;align-items:flex-end;gap:0;height:180px;width:max-content;
  border-bottom:1px solid var(--line)}}
.bar{{flex:0 0 var(--bw);height:100%;display:flex;flex-direction:column;
  justify-content:flex-end;border-right:1px solid transparent;background-clip:padding-box;
  background:linear-gradient(var(--idle),var(--idle)) bottom/100% 1px no-repeat}}
.bar i{{display:block;width:100%;background:var(--cat0);border-radius:2px 2px 0 0}}
.plot{{display:flex;gap:8px;align-items:stretch;width:max-content}}
.yax{{display:flex;flex-direction:column;justify-content:space-between;
  width:44px;flex:0 0 44px;font-size:10px;color:var(--faint);text-align:right;
  font-variant-numeric:tabular-nums;padding-bottom:0}}
.yax span{{line-height:1;transform:translateY(-.35em)}}
.plotbody{{flex:1 1 auto;min-width:0}}
.bars.grid{{background:
  repeating-linear-gradient(to top,var(--line) 0 1px,transparent 1px 25%)}}
.seg{{display:block;width:100%}}
.seg:not(:last-child){{border-bottom:1px solid var(--panel)}}
.bar i:first-child{{border-radius:2px 2px 0 0}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;
  font-size:13px}}
th,td{{text-align:left;padding:6px 10px 6px 0;border-bottom:1px solid var(--line);
  font-weight:400}}
thead th{{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--faint);font-weight:600}}
tbody th{{font-weight:520}}
td.num,th.num{{text-align:right;white-space:nowrap}}
.trackcell{{width:32%;padding-right:0}}
.track{{display:block;height:6px;background:var(--idle);border-radius:4px;overflow:hidden}}
.fill{{display:block;height:100%;background:var(--cat0);border-radius:4px}}
@media (max-width:640px){{.trackcell{{display:none}}}}
.legend{{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:10px;
  font-size:11.5px;color:var(--dim)}}
.key{{display:inline-flex;align-items:center;gap:5px}}
.key i{{width:9px;height:9px;border-radius:2px;display:inline-block}}
.key b{{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}}
.key{{cursor:pointer;padding:2px 6px;margin:-2px -6px;border-radius:5px;
  transition:background .12s,opacity .12s}}
.key:hover,.key.on{{background:var(--idle)}}
.legend.iso .key:not(.on){{opacity:.38}}
.bars.iso .seg{{display:none}}
.bars.iso .seg.on{{display:block;border-radius:2px 2px 0 0;border-bottom:none}}
.key.hi{{background:var(--idle);box-shadow:inset 0 0 0 1.5px var(--faint)}}
.key.hi b{{color:var(--ink)}}
.legend.dim .key:not(.hi){{opacity:.35}}
.bars.dim .seg:not(.hi){{opacity:.22}}
.isonote{{min-height:1.2em;margin:6px 0 0;font-size:11.5px;color:var(--dim)}}
.rail{{display:flex;gap:0;width:max-content;height:21px}}
.rail{{margin-left:52px}}
  .rail .t{{flex:0 0 var(--bw);position:relative;border-right:1px solid transparent}}
.rail .t.micro::before{{content:"";position:absolute;left:0;top:0;width:1px;height:4px;
  background:var(--line)}}
.rail .t.day::before{{content:"";position:absolute;left:0;top:0;width:1px;height:10px;
  background:var(--faint)}}
.rail .t.day::after{{content:attr(data-label);position:absolute;left:3px;top:8px;
  font-size:10px;color:var(--faint);white-space:nowrap}}
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
  <div class="tile"><div class="k">Output tokens</div><div class="v">{total_out_h}</div>
    <div class="n">{total_out} &middot; {turns_h} turns</div></div>
  <div class="tile"><div class="k">Cache warmth</div><div class="v">{warm}%</div>
    <div class="n">{cache_h} read warm</div></div>
</div>

<section style="--bw:5px">
  <h2>Output tokens per hour</h2>
  <p class="note">The spikiness answer. Linear scale on purpose — a log axis would
     flatten the very thing you're asking about. Peak is <b>{peak}</b> tokens at
     {peak_when}; most hours are a rounding error beside it.</p>
  <div class="chart"><div class="plot">
    <div class="yax">{tok_axis}</div>
    <div class="plotbody"><div class="bars grid">{tok_bars}</div></div>
  </div>
  <div class="rail">{tok_rail}</div>
  <div class="legend" id="lg">{tok_legend}</div>
  <p class="isonote" id="iso">&nbsp;</p></div>
  <div class="axis"><span>{span}</span><span>peak {peak} tok/h</span></div>
</section>

<section style="--bw:4px">
  <h2>Weekly window consumed</h2>
  <p class="note">Account-wide, from the usage endpoint — this is the number the
     plan actually meters. It only climbs; the reset is 07:00 Thursday. The axis
     is scaled to the data (0–{seven_top}%), not to the 100% limit — so read
     headroom off the number, not off the gap above the bars. Samples are grouped
     {seven_group} to a column so the week fits without scrolling; safe here
     because this line only climbs, unlike the 5-hour window below.</p>
  <div class="chart"><div class="plot">
    <div class="yax">{seven_axis}</div>
    <div class="plotbody"><div class="bars grid">{seven_bars}</div></div>
  </div>
  <div class="rail">{sample_rail}</div>
  <div class="legend">{slope_legend}</div></div>
  <div class="axis"><span>0–{seven_top}% of the weekly limit</span><span>now {week_now}%</span></div>
</section>

<section style="--bw:4px">
  <h2>Five-hour window</h2>
  <p class="note">The sawtooth is the rolling 5-hour limit filling and resetting.
     Every sample is plotted rather than rolled up per hour, because the window
     resets mid-hour and averaging would erase the shape.</p>
  <div class="chart"><div class="plot">
    <div class="yax">{five_axis}</div>
    <div class="plotbody"><div class="bars grid">{five_bars}</div></div>
  </div>
  <div class="rail">{sample_rail}</div></div>
  <div class="axis"><span>each bar = one 15-minute sample</span><span>peak of window</span></div>
</section>

<section>
  <h2>By day</h2>
  <p class="note">Totals per calendar day, with turn counts &mdash; the hourly chart
     above shows shape, this shows size.</p>
  <table><thead><tr><th>Day</th><th class="num">Output</th><th class="num">Turns</th>
    <th class="trackcell"></th></tr></thead><tbody>{day_rows}</tbody></table>
</section>

<section>
  <h2>By model</h2>
  <p class="note">Output tokens by model. Nothing else on this page distinguishes
     them, and they are not priced alike.</p>
  <table><thead><tr><th>Model</th><th class="num">Output</th><th class="num">Share</th>
    <th class="trackcell"></th></tr></thead><tbody>{model_rows}</tbody></table>
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
<script>
(function(){{
  var lg=document.getElementById('lg'), bars=document.querySelector('.bars'),
      note=document.getElementById('iso');
  if(!lg||!bars) return;
  var keys=[].slice.call(lg.querySelectorAll('.key'));
  var segs=[].slice.call(bars.querySelectorAll('.seg'));
  var pinned=null;
  function totalFor(l){{
    var n=0;
    segs.forEach(function(s){{
      if(s.getAttribute('data-l')!==l) return;
      var m=(s.getAttribute('title')||'').match(/([\d,]+)$/);
      if(m) n+=parseInt(m[1].replace(/,/g,''),10);
    }});
    return n;
  }}
  function show(l){{
    if(!l){{
      bars.classList.remove('iso'); lg.classList.remove('iso');
      keys.forEach(function(k){{k.classList.remove('on')}});
      segs.forEach(function(s){{s.classList.remove('on')}});
      note.innerHTML='&nbsp;'; return;
    }}
    bars.classList.add('iso'); lg.classList.add('iso');
    keys.forEach(function(k){{k.classList.toggle('on',k.getAttribute('data-l')===l)}});
    var hrs=0;
    segs.forEach(function(s){{
      var hit=s.getAttribute('data-l')===l;
      s.classList.toggle('on',hit); if(hit) hrs++;
    }});
    note.innerHTML=l+' only &mdash; <b>'+totalFor(l).toLocaleString()+
      '</b> output tokens across <b>'+hrs+'</b> hours. Same y-axis.';
  }}
  // hovering a segment tells you which project it is
  var hiOn=false;
  function hi(l,detail){{
    hiOn = !!l;
    keys.forEach(function(k){{k.classList.toggle('hi',k.getAttribute('data-l')===l)}});
    lg.classList.toggle('dim',!!l);
    bars.classList.toggle('dim',!!l);
    segs.forEach(function(s){{s.classList.toggle('hi',s.getAttribute('data-l')===l)}});
    note.innerHTML = l ? detail : '&nbsp;';
  }}
  segs.forEach(function(s){{
    s.addEventListener('mouseenter',function(){{
      if(pinned||bars.classList.contains('iso')) return;
      var l=s.getAttribute('data-l');
      var bar=s.parentNode, when=(bar.getAttribute('title')||'').split(' — ')[0];
      var v=(s.getAttribute('title')||'').split(': ')[1]||'';
      hi(l,'<b>'+l+'</b> &middot; '+v+' output tokens &middot; '+when);
    }});
  }});
  bars.addEventListener('mouseleave',function(){{ if(hiOn&&!pinned) hi(null); }});

  keys.forEach(function(k){{
    var l=k.getAttribute('data-l');
    k.addEventListener('mouseenter',function(){{ if(!pinned) show(l); }});
    k.addEventListener('mouseleave',function(){{ if(!pinned) show(null); }});
    k.addEventListener('click',function(){{
      pinned = (pinned===l) ? null : l; show(pinned||l);
      if(!pinned) show(null);
    }});
  }});
  lg.addEventListener('mouseleave',function(){{ if(!pinned) show(null); }});
  var sel=document.getElementById('wsel');
  if(sel){{
    sel.addEventListener('change',function(){{
      [].forEach.call(document.querySelectorAll('.wpanel'),function(p){{
        p.hidden = (p.id !== sel.value);
      }});
    }});
  }}
}})();
</script>
"""


if __name__ == "__main__":
    open(OUT, "w").write(ascii_safe(build()))
    print(f"wrote {OUT}")
