#!/usr/bin/env python3
"""usage.json -> usage.html. Pure: no network, no transcript reads.

Kept separate from hourly.py so the page can be rebuilt from a stored snapshot
(and so the collection pass can run on a timer without touching presentation).
"""
import collections, html, json, os, time


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
SRC = os.path.join(HERE, "usage.json")
OUT = os.path.join(HERE, "usage.html")

# Validated with the dataviz checker (scripts/validate_palette.js): light on
# #fcfcfb and dark on #14181c both pass lightness band, chroma floor, CVD
# separation, normal-vision floor, and contrast. Don't edit a hex without
# re-running it — adjacent-pair separation is what breaks first.
CAT_LIGHT = ["#008C6E", "#E0561F", "#3355D8", "#B02E8E", "#7C7000"]
CAT_DARK = ["#00A884", "#E2622C", "#5C82E8", "#CC55A8", "#948400"]


def human(n):
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return str(int(n))


def build():
    d = json.load(open(SRC))
    hourly = d["hourly"]
    keys = sorted(hourly)
    if not keys:
        raise SystemExit("no hourly data — run hourly.py first")

    # Fill the gaps: an hour with no work must render as an empty column, not
    # be skipped. A chart that silently drops idle hours compresses the x-axis
    # and makes a quiet stretch look like continuous activity.
    def hkey(t):
        return time.strftime("%Y-%m-%dT%H", time.localtime(t))

    start = time.mktime(time.strptime(keys[0], "%Y-%m-%dT%H"))
    end = time.mktime(time.strptime(keys[-1], "%Y-%m-%dT%H"))
    slots, t = [], start
    while t <= end:
        k = hkey(t)
        slots.append((k, hourly.get(k, {})))
        t += 3600

    peak = max((v.get("output_tokens", 0) for _, v in slots), default=1) or 1
    tot = collections.Counter()
    for _, v in slots:
        tot.update(v)

    by_day = collections.OrderedDict()
    for k, v in slots:
        by_day.setdefault(k[:10], collections.Counter()).update(v)

    bars = []
    for k, v in slots:
        out = v.get("output_tokens", 0)
        pct = 100 * out / peak
        hour = int(k[11:13])
        label = (f"{k[:10]} {hour:02d}:00 — {out:,} output tokens, "
                 f"{v.get('turns', 0)} turns") if out else f"{k[:10]} {hour:02d}:00 — idle"
        cls = " day-start" if hour == 0 else ""
        bars.append(
            f'<div class="bar{cls}" title="{html.escape(label)}">'
            f'<i style="height:{pct:.2f}%"></i></div>')

    day_rows = []
    day_peak = max((c["output_tokens"] for c in by_day.values()), default=1) or 1
    for day, c in by_day.items():
        w = 100 * c["output_tokens"] / day_peak
        weekday = time.strftime("%a", time.strptime(day, "%Y-%m-%d"))
        day_rows.append(
            f"<tr><th scope='row'>{weekday} {day[5:]}</th>"
            f"<td class='num'>{c['output_tokens']:,}</td>"
            f"<td class='num'>{c['turns']:,}</td>"
            f"<td class='trackcell'><span class='track'>"
            f"<span class='fill' style='width:{w:.1f}%'></span></span></td></tr>")

    proj = list(d["by_project"].items())
    ptot = sum(d["by_project"].values()) or 1
    proj_rows = []
    for i, (name, out) in enumerate(proj[:12]):
        colour = f"var(--cat{i % 5})"
        turns = d["turns_by_project"].get(name, 0)
        proj_rows.append(
            f"<tr><th scope='row'><span class='dot' style='background:{colour}'></span>"
            f"{html.escape(name)}</th>"
            f"<td class='num'>{out:,}</td><td class='num'>{turns:,}</td>"
            f"<td class='num'>{100 * out / ptot:.1f}%</td>"
            f"<td class='trackcell'><span class='track'><span class='fill' "
            f"style='width:{100 * out / proj[0][1]:.1f}%;background:{colour}'></span>"
            f"</span></td></tr>")

    model_rows = []
    mtot = sum(v for v in d["by_model"].values()) or 1
    for name, out in d["by_model"].items():
        if not out:
            continue
        model_rows.append(
            f"<tr><th scope='row'>{html.escape(name)}</th>"
            f"<td class='num'>{out:,}</td>"
            f"<td class='num'>{100 * out / mtot:.1f}%</td></tr>")

    active = sum(1 for _, v in slots if v.get("output_tokens"))
    ratio = tot["cache_read_input_tokens"] / max(
        tot["cache_read_input_tokens"] + tot["cache_creation_input_tokens"] + tot["input_tokens"], 1)

    return TEMPLATE.format(
        generated=d["generated"].replace("T", " "),
        span=f"{slots[0][0][:10]} → {slots[-1][0][:10]}",
        out=f"{tot['output_tokens']:,}",
        out_h=human(tot["output_tokens"]),
        turns=f"{tot['turns']:,}",
        active=active,
        total_hours=len(slots),
        peak=f"{peak:,}",
        peak_h=human(peak),
        cache_read=human(tot["cache_read_input_tokens"]),
        cache_create=human(tot["cache_creation_input_tokens"]),
        fresh_in=f"{tot['input_tokens']:,}",
        hit=f"{100 * ratio:.1f}",
        bars="".join(bars),
        day_rows="".join(day_rows),
        proj_rows="".join(proj_rows),
        model_rows="".join(model_rows),
        cat_light=" ".join(f"--cat{i}:{c};" for i, c in enumerate(CAT_LIGHT)),
        cat_dark=" ".join(f"--cat{i}:{c};" for i, c in enumerate(CAT_DARK)),
    )


TEMPLATE = """<title>Token spend — hourly</title>
<style>
:root {{
  --bg:#fcfcfb; --panel:#ffffff; --line:#e4e3df; --ink:#1b1d1c; --dim:#5d615e;
  --faint:#8d918d; --accent:#008C6E; --bar:#008C6E; --idle:#eceae5;
  {cat_light}
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#14181c; --panel:#191e23; --line:#2b3238; --ink:#e8ecea; --dim:#9aa4a0;
    --faint:#6d7773; --accent:#00A884; --bar:#00A884; --idle:#232a30;
    {cat_dark}
  }}
}}
:root[data-theme="dark"] {{
  --bg:#14181c; --panel:#191e23; --line:#2b3238; --ink:#e8ecea; --dim:#9aa4a0;
  --faint:#6d7773; --accent:#00A884; --bar:#00A884; --idle:#232a30;
  {cat_dark}
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.55 ui-sans-serif,-apple-system,"SF Pro Text",Inter,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1080px; margin:0 auto; padding:40px 24px 72px; }}
header {{ display:flex; flex-wrap:wrap; gap:16px; align-items:baseline;
         justify-content:space-between; margin-bottom:28px; }}
h1 {{ font-size:23px; letter-spacing:-.015em; margin:0; font-weight:640; }}
.sub {{ color:var(--dim); font-size:13px; margin-top:3px; }}
.stamp {{ color:var(--faint); font-size:12px; font-variant-numeric:tabular-nums; }}
.tiles {{ display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
          margin-bottom:26px; }}
.tile {{ background:var(--panel); border:1px solid var(--line); border-radius:11px;
         padding:15px 16px; }}
.tile .k {{ font-size:11px; letter-spacing:.075em; text-transform:uppercase;
            color:var(--faint); font-weight:600; }}
.tile .v {{ font-size:26px; font-weight:660; letter-spacing:-.02em; margin-top:5px;
            font-variant-numeric:tabular-nums; }}
.tile .n {{ font-size:12px; color:var(--dim); margin-top:2px;
            font-variant-numeric:tabular-nums; }}
section {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
           padding:20px 20px 18px; margin-bottom:20px; }}
h2 {{ font-size:12px; letter-spacing:.075em; text-transform:uppercase; color:var(--faint);
      margin:0 0 3px; font-weight:650; }}
.note {{ color:var(--dim); font-size:13px; margin:0 0 16px; max-width:66ch; }}
.chart {{ overflow-x:auto; padding-bottom:4px; }}
.bars {{ display:flex; align-items:flex-end; gap:1px; height:190px; min-width:640px;
         border-bottom:1px solid var(--line); }}
.bar {{ flex:1 1 0; min-width:3px; height:100%; display:flex; align-items:flex-end;
        background:linear-gradient(var(--idle),var(--idle)) bottom/100% 1px no-repeat; }}
.bar i {{ display:block; width:100%; background:var(--bar); border-radius:2px 2px 0 0;
          min-height:0; }}
.bar.day-start {{ box-shadow:inset 1px 0 0 var(--line); }}
.axis {{ display:flex; justify-content:space-between; color:var(--faint); font-size:11px;
         margin-top:7px; font-variant-numeric:tabular-nums; }}
table {{ width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; }}
th, td {{ text-align:left; padding:7px 10px 7px 0; border-bottom:1px solid var(--line);
          font-weight:400; }}
thead th {{ font-size:11px; letter-spacing:.06em; text-transform:uppercase;
            color:var(--faint); font-weight:600; }}
tbody th {{ font-weight:520; }}
.num {{ text-align:right; white-space:nowrap; }}
.trackcell {{ width:34%; padding-right:0; }}
.track {{ display:block; height:7px; background:var(--idle); border-radius:4px;
          overflow:hidden; }}
.fill {{ display:block; height:100%; background:var(--accent); border-radius:4px; }}
.dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:8px;
        vertical-align:baseline; }}
.caveat {{ border-left:3px solid var(--cat1); padding-left:14px; margin-top:24px;
           color:var(--dim); font-size:13px; max-width:72ch; }}
.caveat strong {{ color:var(--ink); font-weight:620; }}
@media (max-width:640px) {{ .trackcell {{ display:none; }} .wrap {{ padding:28px 16px 56px; }} }}
</style>
<div class="wrap">
<header>
  <div>
    <h1>Token spend, hour by hour</h1>
    <div class="sub">{span} · from Claude CLI transcripts on this Mac</div>
  </div>
  <div class="stamp">collected {generated}</div>
</header>

<div class="tiles">
  <div class="tile"><div class="k">Output tokens</div><div class="v">{out_h}</div>
    <div class="n">{out}</div></div>
  <div class="tile"><div class="k">Assistant turns</div><div class="v">{turns}</div>
    <div class="n">{active} of {total_hours} hours active</div></div>
  <div class="tile"><div class="k">Busiest hour</div><div class="v">{peak_h}</div>
    <div class="n">{peak} output tokens</div></div>
  <div class="tile"><div class="k">Cache reads</div><div class="v">{cache_read}</div>
    <div class="n">{hit}% of input served warm</div></div>
</div>

<section>
  <h2>Hourly output tokens</h2>
  <p class="note">One column per hour; height is output tokens, the quantity the
     plan's weekly limit actually meters. Empty columns are idle hours, kept in
     place so the gaps read as gaps. Hover any column for its exact figures.</p>
  <div class="chart"><div class="bars">{bars}</div></div>
  <div class="axis"><span>{span}</span><span>peak {peak} tok/h</span></div>
</section>

<section>
  <h2>By day</h2>
  <table>
    <thead><tr><th>Day</th><th class="num">Output</th><th class="num">Turns</th>
      <th></th></tr></thead>
    <tbody>{day_rows}</tbody>
  </table>
</section>

<section>
  <h2>By project</h2>
  <p class="note">Output tokens attributed to the session's working directory.
     Top 12 shown.</p>
  <table>
    <thead><tr><th>Project</th><th class="num">Output</th><th class="num">Turns</th>
      <th class="num">Share</th><th></th></tr></thead>
    <tbody>{proj_rows}</tbody>
  </table>
</section>

<section>
  <h2>By model</h2>
  <table>
    <thead><tr><th>Model</th><th class="num">Output</th><th class="num">Share</th></tr>
    </thead>
    <tbody>{model_rows}</tbody>
  </table>
</section>

<p class="caveat"><strong>What this is not.</strong> Anthropic's usage-report API
covers an API organization's spend. Claude Code here runs on a Max subscription,
so none of this consumption appears there, and no admin key exists on this
machine — that path is unavailable, not merely unused. These figures come from
the transcripts on this Mac, so they miss claude.ai and any other computer.
Input is split into fresh ({fresh_in}), cache writes ({cache_create}) and cache
reads ({cache_read}) rather than summed, because those bill an order of
magnitude apart.</p>
</div>
"""


if __name__ == "__main__":
    open(OUT, "w").write(ascii_safe(build()))
    print(f"wrote {OUT}")
