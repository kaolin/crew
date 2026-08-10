#!/usr/bin/env python3
"""status.json -> status.html. Pure rendering; no network, no API keys."""
import datetime, html, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, "status.json")))
OUT = os.path.join(HERE, "status.html")

PLAY_LABEL = {"com.fractroam": "FractRoam", "org.erif.izzit": "izzit",
              "org.erif.spotthehustle": "Spot The Hustle"}
TRACK_ORDER = {"production": 0, "beta": 1, "alpha": 2, "internal": 3}


def esc(s):
    return html.escape(str(s), quote=True)


def dur(h):
    if h is None:
        return ""
    return f"{h:.0f}h" if h < 48 else f"{h/24:.0f}d"


def cell(mark=None, sub=None, kind="m1"):
    if not mark:
        return '<td class="dash">—</td>'
    s = f'<span class="sub">{esc(sub)}</span>' if sub else ""
    return f'<td><span class="mark {kind}">{esc(mark)}{s}</span></td>'


apps = DATA["apps"]


def rank(a):
    """Furthest-along first: on sale, then queued, then drafted, then nothing."""
    return (0 if a["onSale"] else 1, 0 if a["queue"] else 1,
            0 if a["draft"] else 1, a["name"].lower())


rows = []
for a in sorted(apps, key=rank):
    tf = a["testflight"] or {}
    tf_cell = '<td class="dash">—</td>'
    if tf.get("build"):
        # "ahead" on its own was ambiguous — ahead of what? Say which.
        # A build that is also the one in review is the more useful fact,
        # and it outranks being ahead of the store.
        qb = a.get("queueBuild")
        if qb and str(qb) == str(tf["build"]):
            rel = "in review"
        elif a["live"] and tf.get("version") and tf["version"] != a["live"]:
            rel = "ahead of store"
        else:
            rel = ""
        note = " · ".join(x for x in (dur(tf.get("age_h")), rel) if x)
        tf_cell = cell(f"{tf.get('version') or '?'} ({tf['build']})", note, "m4")
    elif tf.get("expired"):
        tf_cell = cell("expired", f"last {tf.get('last')} · {dur(tf.get('age_h'))} ago", "m6")

    # One column answers "can someone buy this?" — a version when yes, and the
    # reason when no. Splitting availability across two columns made a delisted
    # app read as blank rather than as a problem.
    terr = a["territories"]
    if a["live"] and not a["onSale"]:
        sale = cell("delisted", f"ASC still says {a['live']} ready", "m6")
    elif terr and terr[0] == 0:
        sale = cell("pulled", "0 territories", "m6")
    elif a["onSale"] and terr and terr[0] < terr[1]:
        sale = cell(a["live"], f"{terr[0]}/{terr[1]} territories", "m1")
    elif a["onSale"]:
        sale = cell(a["live"], None, "m1")
    else:
        sale = '<td class="dash">—</td>'

    rows.append(
        "<tr>"
        f'<td class="app">{esc(a["name"])}</td>'
        + sale
        + cell(f'{a["queue"][0]} ({a["queueBuild"]})' if a.get("queue") and a.get("queueBuild")
               else (a["queue"][0] if a.get("queue") else None),
               dur(a["waitHours"]) + " waiting" if a["waitHours"] else None, "m2")
        + cell(a["draft"][0] if a["draft"] else None, None, "m3")
        + tf_cell
        + cell("never" if not a["everSubmitted"] else None, None, "m5")
        + "</tr>")

# Play's tracks map onto the iOS columns: production is "on sale", the closed
# tracks are where testers live, and a draft release is Play's "drafted".
# Same left-to-right reading — most public first.
PLAY_COLS = [("production", "m1"), ("beta", "m2"), ("alpha", "m4"), ("internal", "m3")]

play_rows = []
for pkg, rels in sorted(DATA.get("play", {}).items(),
                        key=lambda kv: PLAY_LABEL.get(kv[0], kv[0]).lower()):
    cells = ""
    for track, kind in PLAY_COLS:
        here = [r for r in rels if r["track"] == track]
        # A completed release is what's actually out on that track; a draft
        # sitting there is not, and shouldn't read the same.
        done = next((r for r in here if r.get("status") == "completed"), None)
        pick = done or (here[0] if here else None)
        if not pick:
            cells += '<td class="dash">—</td>'
            continue
        codes = ",".join(map(str, pick["codes"])) or "—"
        sub = pick.get("name") or ""
        if pick.get("status") != "completed":
            sub = f'{pick.get("status")}{" · " + sub if sub else ""}'
        cells += cell(f'v{codes}', sub, kind if done else "m5")
    play_rows.append(f'<tr><td class="app">{esc(PLAY_LABEL.get(pkg, pkg))}</td>{cells}</tr>')

gen = datetime.datetime.fromisoformat(DATA["generated"])
missing = [a["name"] for a in apps if a["name"] not in
           ("FractRoam", "izzit", "Spot The Hustle")]

open(OUT, "w").write(f"""<title>Store pipeline — {gen:%-d %b %Y}</title>
<style>
  :root {{
    --ground:#f2f1ee; --card:#fff; --edge:#dcdad4; --ink:#1c1d21; --ink-2:#5c5f68; --ink-3:#8b8e97;
    --sale:#2e6b45; --sale-bg:#e7f2eb; --queue:#b4690e; --queue-bg:#fdf2e1;
    --draft:#5b6270; --draft-bg:#eceef1; --flight:#2f5c93; --flight-bg:#e8eff8;
    --never:#7a7a7a; --never-bg:#eeedeb; --gone:#9a3b3b; --gone-bg:#f8eaea; --rule:#e5e3de;
  }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
    --ground:#15161a; --card:#1d1f24; --edge:#2b2e35; --ink:#eaeaec; --ink-2:#a3a6ae; --ink-3:#737782;
    --sale:#6cc08b; --sale-bg:#16261b; --queue:#e8a33d; --queue-bg:#2a2317;
    --draft:#9aa1ae; --draft-bg:#23262c; --flight:#79aae4; --flight-bg:#182432;
    --never:#8b8e95; --never-bg:#212327; --gone:#e08585; --gone-bg:#2b1b1b; --rule:#292c32;
  }} }}
  :root[data-theme="dark"] {{
    --ground:#15161a; --card:#1d1f24; --edge:#2b2e35; --ink:#eaeaec; --ink-2:#a3a6ae; --ink-3:#737782;
    --sale:#6cc08b; --sale-bg:#16261b; --queue:#e8a33d; --queue-bg:#2a2317;
    --draft:#9aa1ae; --draft-bg:#23262c; --flight:#79aae4; --flight-bg:#182432;
    --never:#8b8e95; --never-bg:#212327; --gone:#e08585; --gone-bg:#2b1b1b; --rule:#292c32;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:26px 14px 60px;background:var(--ground);color:var(--ink);
    font:15px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif;-webkit-text-size-adjust:100%}}
  .wrap{{max-width:1000px;margin:0 auto;display:flex;flex-direction:column;gap:20px}}
  h1{{margin:0;font-size:24px;letter-spacing:-.02em}}
  h2{{margin:0 0 2px;font-size:15px}}
  .stamp{{margin:4px 0 0;font-size:13px;color:var(--ink-3)}}
  .hint{{margin:0;font-size:13px;color:var(--ink-3)}}
  .scroll{{overflow-x:auto;border:1px solid var(--edge);border-radius:9px;background:var(--card)}}
  table{{border-collapse:collapse;width:100%;min-width:780px}}
  thead th{{position:sticky;top:0;background:var(--card);text-align:left;padding:12px 10px 9px;
    font-size:10.5px;font-weight:700;letter-spacing:.075em;text-transform:uppercase;
    border-bottom:1px solid var(--edge);white-space:nowrap}}
  th.c1{{color:var(--sale)}} th.c2{{color:var(--queue)}} th.c3{{color:var(--draft)}}
  th.c4{{color:var(--flight)}} th.c5{{color:var(--never)}} th.c6{{color:var(--gone)}}
  th.app,td.app{{position:sticky;left:0;z-index:2;background:var(--card);
    border-right:1px solid var(--edge);padding:9px 12px;text-align:left;
    font-weight:600;font-size:14px;white-space:nowrap}}
  thead th.app{{z-index:3}}
  td{{padding:7px 8px;border-bottom:1px solid var(--rule);vertical-align:middle}}
  tbody tr:last-child td{{border-bottom:0}}
  .mark{{display:inline-block;padding:3px 8px;border-radius:5px;
    font:600 12px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;
    font-variant-numeric:tabular-nums;white-space:nowrap}}
  .m1{{background:var(--sale-bg);color:var(--sale)}}
  .m2{{background:var(--queue-bg);color:var(--queue)}}
  .m3{{background:var(--draft-bg);color:var(--draft)}}
  .m4{{background:var(--flight-bg);color:var(--flight)}}
  .m5{{background:var(--never-bg);color:var(--never)}}
  .m6{{background:var(--gone-bg);color:var(--gone)}}
  .sub{{display:block;font-size:10.5px;font-weight:500;opacity:.85;letter-spacing:0}}
  .dash{{color:var(--ink-3);opacity:.4;font-size:13px}}
  .note2{{font-size:12px;color:var(--ink-3)}}
  footer{{border-top:1px solid var(--rule);padding-top:13px;font-size:12.5px;color:var(--ink-3);
    display:flex;flex-direction:column;gap:5px}}
  footer b{{color:var(--ink-2)}}
</style>
<div class="wrap">
  <div>
    <h1>Store pipeline</h1>
    <p class="stamp">Generated by <code>crew/appstatus</code> · {gen:%-d %b %Y, %H:%M}</p>
  </div>
  <p class="hint">A row lights up in every column that applies — most apps are in several at once.
    <b>On sale</b> answers can-someone-buy-this: a version when yes, the reason when no.</p>
  <div class="scroll"><table>
    <thead><tr><th class="app">App</th><th class="c1">On sale</th><th class="c2">In queue</th>
      <th class="c3">Drafted</th><th class="c4">In TestFlight</th>
      <th class="c5">Never submitted</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>

  <div>
    <h2>Google Play</h2>
    <p class="hint">Same reading as above — most public on the left. Production is Play’s
      “on sale”; the closed tracks are where testers are. A greyed cell is a draft, not a release.</p>
  </div>
  <div class="scroll"><table>
    <thead><tr><th class="app">App</th><th class="c1">Production</th>
      <th class="c2">Beta</th><th class="c4">Alpha</th>
      <th class="c3">Internal</th></tr></thead>
    <tbody>{''.join(play_rows)}</tbody>
  </table></div>

  <footer>
    <div><b>“On sale” is the public storefront, not App Store Connect.</b> A delisted app keeps
      READY_FOR_SALE and its full territory list forever — three apps here read as fully available
      to ASC while being absent from the store.</div>
    <div><b>Queue ages</b> use the review-submission date, not the version’s created date.</div>
    <div><b>TestFlight</b> shows the newest unexpired build with its marketing version.</div>
    <div>{len(missing)} apps have no Play listing at all.</div>
  </footer>
</div>
""")
print(f"wrote {OUT}  ({len(rows)} apps, {len(play_rows)} play)")
