#!/usr/bin/env python3
"""status.json -> status.html. Pure rendering; no network, no API keys."""
import datetime, html, json, os, sys


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
DATA = json.load(open(os.path.join(HERE, "status.json")))
OUT = os.path.join(HERE, "status.html")

# Hand-maintained next-steps. Optional: the page still renders without it, just
# without the "What's next" section. Everything else here comes from an API;
# this is the part only a person knows.
try:
    NOTES = json.load(open(os.path.join(HERE, "notes.json")))
except (OSError, ValueError):
    NOTES = {"apps": {}, "_STAGES": {}}

PLAY_LABEL = {"com.fractroam": "FractRoam", "org.erif.izzit": "izzit",
              "org.erif.spotthehustle": "Spot The Hustle"}
TRACK_ORDER = {"production": 0, "beta": 1, "alpha": 2, "internal": 3}


def esc(s):
    return html.escape(str(s), quote=True)


def dur(h):
    if h is None:
        return ""
    # "0h" read as a stuck clock rather than as freshly submitted.
    if h < 1:
        return "just now"
    return f"{h:.0f}h" if h < 48 else f"{h/24:.0f}d"


def cell(mark=None, sub=None, kind="m1"):
    if not mark:
        return '<td class="dash">—</td>'
    s = f'<span class="sub">{esc(sub)}</span>' if sub else ""
    return f'<td><span class="mark {kind}">{esc(mark)}{s}</span></td>'


apps = DATA["apps"]


def update_in_flight(a):
    """TestFlight carrying a newer marketing version than what's on sale.

    kaolin's framing (2026-08-13): an update in progress IS a submission in
    progress. Derived rather than hand-listed in notes.json, so it can't go
    stale — the day 2.1.0 goes live, BabyPaints stops being 'in flight' with
    no edit anywhere.
    """
    tf = a.get("testflight") or {}
    return bool(a.get("onSale") and tf.get("version") and a.get("live")
                and tf["version"] != a["live"])


# Who is holding the app, derived from the ASC state rather than hand-written.
# PENDING_DEVELOPER_RELEASE is the one that matters most here: the old page drew
# it identically to WAITING_FOR_REVIEW, so "Apple approved it, release when you
# like" looked exactly like "Apple hasn't looked at it yet" — opposite answers to
# the question this page exists to answer.
APPLE_HOLDS = {"READY_FOR_REVIEW": "submitted, queueing",
               "WAITING_FOR_REVIEW": "Apple review",
               "IN_REVIEW": "in review now",
               "PROCESSING_FOR_APP_STORE": "processing",
               "PENDING_APPLE_RELEASE": "Apple releasing"}
YOU_RELEASE = "PENDING_DEVELOPER_RELEASE"

# States that mean Apple has handed it back. These land in `draft`, not `queue`,
# and carry no hand-written action — so before this existed a REJECTED app fell
# through every bucket and rendered as "Nothing pending". Cosmic Specks was
# rejected on 17 Aug after ten days in review and the page said nothing at all.
HANDED_BACK = {
    "REJECTED": "Apple rejected it",
    "METADATA_REJECTED": "Apple rejected the metadata",
    "DEVELOPER_REJECTED": "you withdrew it",
    "INVALID_BINARY": "Apple flagged the binary",
}


def handed_back(a):
    """(state, label) if Apple has bounced it back, else None."""
    for slot in (a.get("queue"), a.get("draft")):
        if slot and slot[1] in HANDED_BACK:
            return slot[1], HANDED_BACK[slot[1]]
    return None


def queue_state(a):
    q = a.get("queue")
    return q[1] if q else None


def queue_label(a):
    """"1.2.0 (149)" — the thing that's actually in the queue."""
    q = a.get("queue")
    if not q:
        return ""
    return f'{q[0]} ({a["queueBuild"]})' if a.get("queueBuild") else q[0]


def triage():
    """Split every app into: needs you, waiting on someone else, or neither.

    An external hold WINS over a written action. kaolin, 2026-08-15, on finding
    Orrery filed under his move because it had a "decide whether to keep waiting"
    note: *"it's waiting on someone else. it's my decision what to do with it."*
    The option to intervene exists for everything in a queue, so treating it as a
    task promotes every waiting app into the column that's supposed to mean
    "nothing moves until you act". Who holds it decides the bucket; what he could
    choose to do about it does not.
    """
    notes = NOTES.get("apps", {})
    by_name = {a["name"]: a for a in apps}
    # Apps that exist only as a note (no ASC record yet) were silently dropped
    # before — which hid exactly the ones with the most work left.
    for name in notes:
        by_name.setdefault(name, {"name": name, "queue": None, "draft": None,
                                  "live": None, "onSale": False,
                                  "testflight": None, "waitHours": None})

    move, waiting, idle = [], [], []
    for name, a in by_name.items():
        n = notes.get(name, {})
        st = queue_state(a)
        hb = handed_back(a)
        if hb:
            # Sorts above everything: a rejection is the most time-sensitive
            # thing on the page and the one most easily missed.
            move.append((a, n, -1, hb[1]))
        elif st == YOU_RELEASE:
            # The one queue state that genuinely is his: Apple is done and the
            # build ships the moment he says so.
            move.append((a, n, 0, "Apple approved it — release when you want"))
        elif st in APPLE_HOLDS:
            waiting.append((a, n, APPLE_HOLDS[st]))
        elif n.get("waitingOn"):
            waiting.append((a, n, n["waitingOn"]))
        elif n.get("do"):
            move.append((a, n, int(n.get("stage", 6)), None))
        elif name in notes or a.get("onSale"):
            idle.append((a, n))
    move.sort(key=lambda t: (t[2], t[0]["name"].lower()))
    # Longest wait first: the stalled one is the one worth looking at.
    waiting.sort(key=lambda t: (-(t[0].get("waitHours") or 0), t[0]["name"].lower()))
    idle.sort(key=lambda t: t[0]["name"].lower())
    return move, waiting, idle


def why_line(n):
    return f'<p class="why">{esc(n["why"])}</p>' if n.get("why") else ""


def title_of(a, n):
    """Store name, plus the name he actually calls it when they differ.

    "Cosmic Specks" on its own read as an app he didn't recognise, and he took
    the page to be missing Orrery entirely.
    """
    alias = n.get("alias")
    extra = f' <span class="alias">{esc(alias)}</span>' if alias else ""
    return f'<span class="who">{esc(a["name"])}{extra}</span>'


def elapsed_tag(el):
    """The wait, as a numeral — except "just now", which is a phrase and would
    look like a stuck reading set in the big tabular face."""
    if not el:
        return ""
    small = " small" if not el[0].isdigit() else ""
    return f'<span class="elapsed{small}">{esc(el)}</span>'


def build_triage():
    notes = NOTES.get("apps", {})
    if not notes:
        return ""
    move, waiting, idle = triage()

    move_cards = []
    for a, n, _, urgent in move:
        tags = []
        if urgent:
            kind = "m6" if handed_back(a) else "m2"
            tags.append(f'<span class="mark {kind}">{esc(urgent)}</span>')
        if update_in_flight(a):
            tags.append('<span class="mark m4">update in flight</span>')
        move_cards.append(
            f'<div class="card"><div class="cardtop">'
            f'{title_of(a, n)}{"".join(tags)}</div>'
            f'<p class="do">{esc(n.get("do") or "Needs your decision — Apple handed it back.")}</p>'
            f'{why_line(n)}</div>')

    wait_cards = []
    for a, n, who in waiting:
        el = dur(a.get("waitHours"))
        ver = queue_label(a)
        wait_cards.append(
            f'<div class="card"><div class="cardtop">'
            f'{title_of(a, n)}'
            f'{elapsed_tag(el)}</div>'
            f'<p class="do">{esc(who)}{f" — {esc(ver)}" if ver else ""}</p>'
            f'{why_line(n)}</div>')

    idle_names = ", ".join(esc(a["name"]) for a, _ in idle)
    idle_block = (f'<p class="idle"><b>Nothing pending</b> · {idle_names}</p>'
                  if idle else "")


    return f"""
  <div class="triage">
    <section class="panel act">
      <h2>Your move <span class="cnt">{len(move_cards)}</span></h2>
      <p class="phint">Something is blocked on a decision or a step only you take.</p>
      {"".join(move_cards) or '<p class="idle">Nothing.</p>'}
    </section>
    <section class="panel hold">
      <h2>Waiting on someone else <span class="cnt">{len(wait_cards)}</span></h2>
      <p class="phint">Out of your hands. Longest wait first.</p>
      {"".join(wait_cards) or '<p class="idle">Nothing.</p>'}
    </section>
  </div>
  {idle_block}"""


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

triage_block = build_triage()

open(OUT, "w").write(ascii_safe(f"""<title>Store pipeline — {gen:%-d %b %Y}</title>
<style>
  :root {{
    --ground:#f2f1ee; --card:#fff; --edge:#dcdad4; --ink:#1c1d21; --ink-2:#5c5f68; --ink-3:#8b8e97;
    --sale:#2e6b45; --sale-bg:#e7f2eb; --queue:#b4690e; --queue-bg:#fdf2e1;
    --draft:#5b6270; --draft-bg:#eceef1; --flight:#2f5c93; --flight-bg:#e8eff8;
    --never:#7a7a7a; --never-bg:#eeedeb; --gone:#9a3b3b; --gone-bg:#f8eaea; --rule:#e5e3de;
    --act:#5b3fa8; --act-bg:#efeaf9;
  }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
    --ground:#15161a; --card:#1d1f24; --edge:#2b2e35; --ink:#eaeaec; --ink-2:#a3a6ae; --ink-3:#737782;
    --sale:#6cc08b; --sale-bg:#16261b; --queue:#e8a33d; --queue-bg:#2a2317;
    --draft:#9aa1ae; --draft-bg:#23262c; --flight:#79aae4; --flight-bg:#182432;
    --never:#8b8e95; --never-bg:#212327; --gone:#e08585; --gone-bg:#2b1b1b; --rule:#292c32;
    --act:#b39ce8; --act-bg:#241d33;
  }} }}
  :root[data-theme="dark"] {{
    --ground:#15161a; --card:#1d1f24; --edge:#2b2e35; --ink:#eaeaec; --ink-2:#a3a6ae; --ink-3:#737782;
    --sale:#6cc08b; --sale-bg:#16261b; --queue:#e8a33d; --queue-bg:#2a2317;
    --draft:#9aa1ae; --draft-bg:#23262c; --flight:#79aae4; --flight-bg:#182432;
    --never:#8b8e95; --never-bg:#212327; --gone:#e08585; --gone-bg:#2b1b1b; --rule:#292c32;
    --act:#b39ce8; --act-bg:#241d33;
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
  .triage{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
  .panel{{display:flex;flex-direction:column;gap:8px;min-width:0}}
  .panel h2{{margin:0;font-size:13px;letter-spacing:.06em;text-transform:uppercase;
    font-weight:700;display:flex;align-items:center;gap:8px}}
  .panel.act h2{{color:var(--act)}} .panel.hold h2{{color:var(--queue)}}
  .panel h2 .cnt{{border-radius:20px;padding:1px 8px;font-size:11px;letter-spacing:0;
    font-variant-numeric:tabular-nums}}
  .panel.act h2 .cnt{{background:var(--act-bg);color:var(--act)}}
  .panel.hold h2 .cnt{{background:var(--queue-bg);color:var(--queue)}}
  .phint{{margin:-4px 0 2px;font-size:12.5px;color:var(--ink-3)}}
  .card{{background:var(--card);border:1px solid var(--edge);border-left:3px solid var(--edge);
    border-radius:9px;padding:11px 13px}}
  .panel.act .card{{border-left-color:var(--act)}}
  .panel.hold .card{{border-left-color:var(--queue)}}
  .cardtop{{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin-bottom:4px}}
  .who{{font-weight:640;font-size:15px;margin-right:auto}}
  .elapsed{{font:700 15px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
    font-variant-numeric:tabular-nums;color:var(--queue)}}
  .elapsed.small{{font-size:11.5px;font-weight:600;opacity:.9}}
  .do{{margin:0;font-size:14px;font-weight:520}}
  .do.none{{font-weight:400;color:var(--ink-3)}}
  .why{{margin:5px 0 0;font-size:13px;color:var(--ink-2);line-height:1.5}}
  .idle{{margin:0;font-size:13px;color:var(--ink-3);line-height:1.6}}
  .alias{{font-weight:500;font-size:12.5px;color:var(--ink-3);letter-spacing:0}}
  .idle b{{color:var(--ink-2)}}
  details.ref summary{{cursor:pointer;font-size:13px;letter-spacing:.06em;
    text-transform:uppercase;font-weight:700;color:var(--ink-3);padding:2px 0}}
  details.ref[open] summary{{margin-bottom:12px}}
  details.ref > div, details.ref > p{{margin-top:12px}}
  @media (max-width:820px){{ .triage{{grid-template-columns:1fr}} }}
  footer{{border-top:1px solid var(--rule);padding-top:13px;font-size:12.5px;color:var(--ink-3);
    display:flex;flex-direction:column;gap:5px}}
  footer b{{color:var(--ink-2)}}
</style>
<div class="wrap">
  <div>
    <h1>Store pipeline</h1>
    <p class="stamp">Generated by <code>crew/appstatus</code> · {gen:%-d %b %Y, %H:%M}</p>
  </div>
  {triage_block}

  <details class="ref">
    <summary>Full state · {len(rows)} apps</summary>
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
  </details>

  <footer>
    <div><b>“On sale” is the public storefront, not App Store Connect.</b> A delisted app keeps
      READY_FOR_SALE and its full territory list forever — three apps here read as fully available
      to ASC while being absent from the store.</div>
    <div><b>Queue ages</b> use the review-submission date, not the version’s created date.</div>
    <div><b>TestFlight</b> shows the newest unexpired build with its marketing version.</div>
    <div>{len(missing)} apps have no Play listing at all.</div>
  </footer>
</div>
"""))
print(f"wrote {OUT}  ({len(rows)} apps, {len(play_rows)} play)")
