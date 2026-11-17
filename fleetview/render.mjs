#!/usr/bin/env node
// fleetview/render.mjs — fleet.json -> fleet.html, a self-contained phone page.
//
//   node render.mjs                       # fleet.json -> fleet.html (full document)
//   node render.mjs --theme dark          # stamp data-theme (for screenshots)
//   node render.mjs --artifact out.html   # also write the body-only variant the
//                                         # Artifact tool wraps in its own skeleton
//
// No external fetches: system fonts, inline CSS, inline SVG. The full document
// can be rsynced anywhere as-is.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, dflt = null) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const IN = opt('--in', path.join(HERE, 'fleet.json'));
const OUT = opt('--out', path.join(HERE, 'fleet.html'));
const ARTIFACT = opt('--artifact', null);
const THEME = opt('--theme', null);
const SHOT = args.includes('--shot');            // left-align for headless screenshots
const ONLY = (opt('--sections', '') || '').split(',').filter(Boolean); // e.g. needs,live

const F = JSON.parse(fs.readFileSync(IN, 'utf8'));
const NOW = new Date(F.generatedAt);

// ---------------------------------------------------------------- formatting
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function age(h) {
  if (h == null || isNaN(h)) return '—';
  if (h < 1 / 30) return 'now';
  if (h < 1) return `${Math.round(h * 60)}m`;
  if (h < 48) return `${Math.round(h)}h`;
  return `${Math.round(h / 24)}d`;
}
const ageOf = (iso) => (iso ? age((NOW - new Date(iso)) / 3.6e6) : '—');
const sev = (h) => (h == null ? '' : h >= 7 * 24 ? 'crit' : h >= 48 ? 'warn' : '');
function clip(s, n) {
  s = String(s ?? '').replace(/\s+/g, ' ').trim();
  if (s.length <= n) return s;
  const cut = s.slice(0, n).replace(/\s+\S*$/, '');
  return cut + '…';
}
const mb = (b) => (b >= 1e6 ? `${(b / 1e6).toFixed(b >= 1e7 ? 0 : 1)} MB` : b > 0 ? `${Math.round(b / 1e3)} KB` : '0');
function localStamp(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
const tzShort = () => { try { return new Date(F.generatedAt).toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop(); } catch { return ''; } };
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
// Local getters only: Intl weekday formatting has been seen to fall back to UTC.
function shortDay(iso) { const d = new Date(iso); return isNaN(d) ? '?' : `${WD[d.getDay()]} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
function untilStr(iso) {
  const d = new Date(iso); if (isNaN(d)) return '?';
  const h = (d - NOW) / 3.6e6;
  if (h < 0) return 'passed';
  if (h < 1) return `in ${Math.max(1, Math.round(h * 60))}m`;
  if (h < 24) return `in ${Math.round(h)}h`;
  return shortDay(iso);
}
function humanState(s) {
  return ({ PREPARE_FOR_SUBMISSION: 'preparing', READY_FOR_SALE: 'ready', WAITING_FOR_REVIEW: 'in queue', IN_REVIEW: 'in review', REJECTED: 'rejected', DEVELOPER_REJECTED: 'withdrawn', PENDING_DEVELOPER_RELEASE: 'approved, unreleased' }[s]) || String(s || '').toLowerCase().replace(/_/g, ' ');
}

// ---------------------------------------------------------------- sections
function needsSection() {
  const groups = F.needs.map((n) => {
    const s = sev(n.ageH);
    const items = n.items.map((it) => `<li>${esc(clip(it, 170))}</li>`).join('');
    const blocked = n.blockers.length ? `<li class="blk"><span class="tag">blocked</span> ${esc(clip(n.blockers[0], 140))}</li>` : '';
    const stale = n.deviceStale ? `<span class="tag warn">device stale</span>` : '';
    return `<article class="group${s ? ' s-' + s : ''}">
  <header><span class="who"><b>${esc(n.app)}</b>${n.app !== n.project ? ` <span class="mono dim">${esc(n.project)}</span>` : ''}${stale}</span><span class="age mono ${s}">${age(n.ageH)}</span></header>
  <ul>${items}${blocked}</ul>
  <footer class="mono dim">${n.items.length} item${n.items.length === 1 ? '' : 's'} · 14d ${mb(n.bytes14d)} · ${n.commits14d} commit${n.commits14d === 1 ? '' : 's'}</footer>
</article>`;
  }).join('\n');
  return `<section id="needs">
<h2><span>Needs you</span><span class="mono n">${F.needs.length} projects · ${F.counts.decisions} items</span></h2>
<p class="lede">Oldest and most-touched first. Age is the session's last status write.</p>
${groups || '<p class="empty">Nothing waiting on you.</p>'}
</section>`;
}

function liveSection() {
  const rows = F.sessions.map((s) => {
    const dot = s.status === 'busy' ? 'busy' : s.status === 'waiting' ? 'wait' : 'idle';
    const flags = [];
    if (s.deviceStale) flags.push('<span class="tag warn">device stale</span>');
    if (s.waitingFor) flags.push(`<span class="tag crit">${esc(s.waitingFor)}</span>`);
    if (s.statusFile && s.statusFile.ageH > 24) flags.push(`<span class="tag">status ${age(s.statusFile.ageH)} old</span>`);
    const build = s.statusFile?.build ? ` · build ${esc(s.statusFile.build)}` : '';
    return `<div class="row live">
  <span class="dot ${dot}" title="${dot}"></span>
  <div class="main">
    <div class="l1"><b>${esc(s.app)}</b>${s.app !== s.project ? ` <span class="mono dim">${esc(s.project)}</span>` : ''}<span class="mono r">${esc(dot)} · ${ageOf(s.lastActivity)}</span></div>
    <div class="l2 mono dim">${esc(s.name)} · up ${age(s.uptimeH)}${build}${flags.length ? ' ' + flags.join(' ') : ''}</div>
  </div>
</div>`;
  }).join('\n');
  return `<section id="live">
<h2><span>Live</span><span class="mono n">${F.counts.sessions} sessions · ${F.counts.busy} busy${F.counts.waiting ? ` · ${F.counts.waiting} waiting` : ''}</span></h2>
<p class="lede">Right column: state now, and when the transcript last moved.</p>
${rows}
</section>`;
}

function storesSection() {
  const S = F.stores;
  if (!S.available) return `<section id="stores"><h2><span>Stores</span></h2><p class="empty">No appstatus snapshot found.</p></section>`;
  const sessBuild = (app) => {
    const s = F.sessions.find((x) => x.app === app.name);
    const b = Number(s?.statusFile?.build);
    const tf = Number(app.testflight?.build);
    return b && tf && b > tf ? b : null;
  };
  const row = (a) => {
    let ios;
    if (a.live) ios = `${esc(a.live)} ${a.onSale ? '<span class="ok">on sale</span>' : '<span class="warn">not on sale</span>'}`;
    else ios = '<span class="dim">no App Store version</span>';
    if (a.draft) ios += ` · <span class="mono">${esc(a.draft.version)}</span> ${esc(humanState(a.draft.state))}`;
    if (a.queue) ios += ` · in review ${a.waitHours ? Math.round(a.waitHours) + 'h' : ''}`;
    let tf = 'no TestFlight';
    if (a.testflight?.expired) tf = `TF expired (last ${esc(a.testflight.last)})`;
    else if (a.testflight) {
      tf = `TF ${esc(a.testflight.version)} (${esc(a.testflight.build)}) ${age(a.testflight.ageH)}`;
      const exp = a.testflight.expires ? (new Date(a.testflight.expires + 'T12:00') - NOW) / 864e5 : null;
      if (exp != null && exp < 21) tf += ` <span class="warn">· expires ${exp < 0 ? 'passed' : 'in ' + Math.round(exp) + 'd'}</span>`;
    }
    const nb = sessBuild(a);
    if (nb) tf += ` <span class="warn">· session says ${nb}</span>`;
    const play = a.play.filter((t) => t.status === 'completed' || t.status === 'draft').map((t) => `${t.track === 'production' ? 'prod' : t.track} ${t.name ? esc(t.name) : '—'}${t.status === 'draft' ? ' draft' : ''}`);
    const playStr = play.length ? `Play ${play.join(' · ')}` : '';
    const next = a.do ? `<div class="l3">${esc(clip(a.do, 120))}</div>` : a.waitingOn ? `<div class="l3 dim">waiting on ${esc(a.waitingOn)}</div>` : '';
    return `<div class="row store${a.hasSession ? '' : ' nosess'}">
  <div class="l1"><b>${esc(a.name)}</b>${a.alias ? ` <span class="mono dim">${esc(a.alias)}</span>` : ''}</div>
  <div class="l2">${ios}</div>
  <div class="l2 mono dim">${tf}${playStr ? ' · ' + playStr : ''}</div>${next}
</div>`;
  };
  const compact = (a) => {
    const ios = a.live ? `${esc(a.live)} ${a.onSale ? 'on sale' : '<span class="warn">not on sale</span>'}` : a.draft ? `${esc(a.draft.version)} ${esc(humanState(a.draft.state))}` : 'no version';
    const tf = a.testflight?.expired ? 'TF expired' : a.testflight ? `TF ${esc(a.testflight.version)} (${esc(a.testflight.build)})` : 'no TF';
    const play = a.play.find((t) => t.track === 'production' && t.status === 'completed');
    return `<div class="row store nosess compact"><b>${esc(a.name)}</b>${a.alias ? ` <span class="mono dim">${esc(a.alias)}</span>` : ''}<span class="mono r">${ios} · ${tf}${play ? ` · Play ${esc(play.name)}` : ''}</span></div>`;
  };
  const withSess = S.apps.filter((a) => a.hasSession);
  const without = S.apps.filter((a) => !a.hasSession);
  const ageDays = S.ageH != null ? (S.ageH / 24).toFixed(1) : '?';
  return `<section id="stores">
<h2><span>Stores</span><span class="mono n">${S.apps.length} apps</span></h2>
<p class="lede">From the appstatus snapshot of <span class="mono">${esc(localStamp(S.generatedAt))}</span> — <b class="${S.ageH > 48 ? 'warn' : ''}">${ageDays} days old</b>. A live session that reports a newer build is marked.</p>
${withSess.map(row).join('\n')}
<h3 class="mono">No session</h3>
${without.map(compact).join('\n')}
</section>`;
}

function strip(perDay, maxBytes) {
  const W = 6, G = 2, H = 26, TH = 3;
  const w = perDay.length * (W + G) - G;
  const sc = (b) => (b <= 0 ? 0 : Math.max(1, Math.round(Math.sqrt(b / maxBytes) * H)));
  const bars = perDay.map((d, i) => {
    const h = sc(d.bytes);
    const bar = h ? `<rect x="${i * (W + G)}" y="${H - h}" width="${W}" height="${h}" class="bar"/>` : `<rect x="${i * (W + G)}" y="${H - 1}" width="${W}" height="1" class="bar0"/>`;
    const tick = d.commits ? `<rect x="${i * (W + G)}" y="${H + 2}" width="${W}" height="${TH}" class="tick"/>` : '';
    return bar + tick;
  }).join('');
  return `<svg class="strip" viewBox="0 0 ${w} ${H + 2 + TH}" width="${w}" height="${H + 2 + TH}" role="img" aria-label="14-day activity"><g>${bars}</g></svg>`;
}
function usageSection() {
  const H = F.headroom;
  let head;
  if (!H?.available) head = `<div class="headroom"><b>Max headroom</b> <span class="dim">not available</span>${H?.reason ? ` <span class="mono dim">(${esc(H.reason)})</span>` : ''}</div>`;
  else {
    const stale = H.ageMin > 60;
    head = `<div class="headroom">
  <div class="meters">
    <div class="meter"><span class="mono k">5h window</span><span class="bar"><i style="width:${Math.min(100, H.fiveHourPct)}%"></i></span><span class="mono v">${H.fiveHourPct}%</span></div>
    <div class="meter"><span class="mono k">7d window</span><span class="bar"><i style="width:${Math.min(100, H.sevenDayPct)}%"></i></span><span class="mono v">${H.sevenDayPct}%</span></div>
  </div>
  <div class="l2 mono dim">5h resets ${esc(untilStr(H.fiveHourResets))} · 7d resets ${esc(untilStr(H.sevenDayResets))} · sampled ${age(H.ageMin / 60)} ago${stale ? ' <span class="warn">(sampler stale)</span>' : ''}</div>
</div>`;
  }
  const max = Math.max(1, ...F.usage.flatMap((u) => u.perDay.map((d) => d.bytes)));
  const rows = F.usage.filter((u) => u.bytes14d > 0 || u.commits14d > 0 || u.hasSession).map((u) => `<div class="row use${u.hasSession ? '' : ' nosess'}">
  <div class="name"><b>${esc(u.app)}</b>${u.app !== u.project ? `<span class="mono dim">${esc(u.project)}</span>` : ''}</div>
  ${strip(u.perDay, max)}
  <div class="nums mono">${mb(u.bytes14d)}<span class="dim">${u.commits14d}c</span></div>
</div>`).join('\n');
  const first = new Date(F.days[0] + 'T12:00'), last = new Date(F.days.at(-1) + 'T12:00');
  const md = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `<section id="usage">
<h2><span>Usage</span><span class="mono n">${md(first)} → ${md(last)}</span></h2>
${head}
<p class="lede">Bars: transcript growth per day (height ∝ √MB, one scale for every row); ticks: days with commits. Right: 14-day total and commit count.</p>
${rows}
</section>`;
}

function reposSection() {
  const rows = F.repos.map((r) => {
    const flags = r.flags.map((f) => `<span class="tag ${/no remote|not a repo/.test(f) ? 'crit' : /unpushed/.test(f) ? 'warn' : ''}">${esc(f)}</span>`).join(' ');
    const remote = r.remotes.length ? r.remotes.map((x) => esc(x.host)).join(', ') : '';
    return `<div class="row repo${r.atRisk ? '' : ' fine'}">
  <div class="l1"><b>${esc(r.project)}</b>${r.branch ? ` <span class="mono dim">${esc(r.branch)}</span>` : ''}<span class="mono r">${r.lastCommit ? 'last commit ' + ageOf(r.lastCommit) : ''}</span></div>
  <div class="l2">${flags || `<span class="tag ok">pushed · ${remote}</span>`}${flags && remote ? ` <span class="mono dim">→ ${remote}</span>` : ''}</div>${r.note ? `<div class="l3 dim">${esc(clip(r.note, 120))}</div>` : ''}
</div>`;
  }).join('\n');
  const n = F.repos.filter((r) => r.atRisk).length;
  return `<section id="repos">
<h2><span>Repos at risk</span><span class="mono n">${n} of ${F.repos.length}</span></h2>
<p class="lede">Work that exists only on this Mac: no remote, no repo, or commits nothing has pulled.</p>
${rows}
</section>`;
}

function parkedSection() {
  const rows = F.parked.map((p) => {
    const moving = p.commits14d > 0 || p.bytes14d > 1e6;
    const note = p.session ? `<span class="tag ${moving ? 'warn' : ''}">session ${esc(p.session)}${moving ? ` · ${p.commits14d}c · ${mb(p.bytes14d)} in 14d` : ' · quiet'}</span>` : '';
    return `<div class="row parked"><b>${esc(p.app)}</b>${p.repo ? ` <span class="mono dim">${esc(p.repo)}</span>` : ''} <span class="dim">— ${esc(clip(p.state, 90))}</span> ${note}</div>`;
  }).join('\n');
  return `<section id="parked">
<h2><span>Parked</span><span class="mono n">${F.parked.length}${F.parkedSince ? ` · since ${esc(F.parkedSince)}` : ''}</span></h2>
<p class="lede">No work and no session, on purpose. If one starts moving it says so here.</p>
${rows}
</section>`;
}

// ---------------------------------------------------------------- page
const CSS = `
:root{
  --bg:#F1F3F4; --ink:#1B1F23; --mute:#5C6874; --line:#D3D9DE; --line2:#E6EAED;
  --accent:#2B63C9; --warn:#A55A00; --crit:#B2382C; --ok:#2E7A4C; --tick:#1B1F23;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0F1316; --ink:#E5E9EC; --mute:#8C97A1; --line:#262E35; --line2:#1B2127;
  --accent:#7FA9EE; --warn:#E1A24B; --crit:#EE7B6C; --ok:#6EC08D; --tick:#E5E9EC;
}}
:root[data-theme="dark"]{
  --bg:#0F1316; --ink:#E5E9EC; --mute:#8C97A1; --line:#262E35; --line2:#1B2127;
  --accent:#7FA9EE; --warn:#E1A24B; --crit:#EE7B6C; --ok:#6EC08D; --tick:#E5E9EC;
}
html{color-scheme:light dark}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.4;-webkit-text-size-adjust:100%}
*{box-sizing:border-box}
.page{max-width:430px;margin:0 auto;padding:18px 16px 40px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:12px}
.dim{color:var(--mute)}
.warn{color:var(--warn)} .crit{color:var(--crit)} .ok{color:var(--ok)}
b{font-weight:600}
a{color:var(--accent)}
.mast{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px;padding-bottom:12px;border-bottom:2px solid var(--ink)}
.mast h1{margin:0;font-size:28px;letter-spacing:-.02em;font-weight:700}
.mast .asof{flex:1 1 auto;text-align:right;color:var(--mute)}
.mast .tally{width:100%;color:var(--mute)}
section{padding-top:22px}
h2{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin:0 0 6px;font-family:var(--mono);font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--line);padding-bottom:6px}
h2 .n{font-weight:400;letter-spacing:0;text-transform:none;color:var(--mute)}
h3{margin:14px 0 0;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
.lede{margin:0 0 8px;font-size:12px;color:var(--mute);text-wrap:pretty}
.empty{color:var(--mute);font-style:italic}
.tag{display:inline-block;font-family:var(--mono);font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;padding:0 5px;border:1px solid var(--line);border-radius:3px;color:var(--mute);vertical-align:1px;white-space:nowrap}
.tag.warn{border-color:var(--warn);color:var(--warn)} .tag.crit{border-color:var(--crit);color:var(--crit)} .tag.ok{border-color:var(--ok);color:var(--ok)}
/* needs you */
.group{border-left:3px solid var(--line);padding:6px 0 6px 10px;margin:8px 0 12px}
.group.s-warn{border-left-color:var(--warn)} .group.s-crit{border-left-color:var(--crit)}
.group header{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.group header .who{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px}
.group header b{font-size:15px}
.group .age{font-size:13px;font-weight:700}
.group ul{margin:4px 0 4px;padding-left:16px}
.group li{margin:3px 0;font-size:13.5px;text-wrap:pretty}
.group li.blk{color:var(--mute)}
.group footer{margin-top:2px}
/* rows */
.row{padding:7px 0;border-bottom:1px solid var(--line2)}
.row:last-child{border-bottom:0}
.l1{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
.l1 .r{margin-left:auto;color:var(--mute);white-space:nowrap}
.l2{font-size:12.5px;margin-top:1px} .l3{font-size:12px;margin-top:2px;color:var(--ink)}
.live{display:flex;gap:9px;align-items:flex-start}
.live .main{flex:1;min-width:0}
.dot{flex:none;width:9px;height:9px;border-radius:50%;margin-top:6px;border:1.5px solid var(--ink);background:transparent}
.dot.busy{background:var(--accent);border-color:var(--accent)}
.dot.wait{background:var(--crit);border-color:var(--crit)}
.dot.idle{border-color:var(--mute)}
.nosess{opacity:.72}
.store.compact .r{margin-left:auto;white-space:normal;text-align:right}
.store.compact{display:flex;flex-wrap:wrap;gap:4px 8px;align-items:baseline}
html[data-shot] .page{margin:0}
/* usage */
.headroom{padding:8px 0 10px;border-bottom:1px solid var(--line)}
.meters{display:grid;gap:5px}
.meter{display:grid;grid-template-columns:76px 1fr 44px;align-items:center;gap:8px}
.meter .bar{display:block;height:8px;background:var(--line2);border:1px solid var(--line);border-radius:2px;overflow:hidden}
.meter .bar i{display:block;height:100%;background:var(--accent)}
.meter .v{text-align:right}
.use{display:grid;grid-template-columns:1fr auto 78px;align-items:center;gap:10px}
.use .name{display:flex;flex-direction:column;min-width:0}
.use .name b{font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.use .name .mono{font-size:11px}
.use .nums{text-align:right;display:flex;flex-direction:column;line-height:1.2}
.strip .bar{fill:var(--accent)} .strip .bar0{fill:var(--line)} .strip .tick{fill:var(--tick);opacity:.55}
/* repos */
.repo.fine{opacity:.75}
.repo .l2{display:flex;flex-wrap:wrap;gap:4px;align-items:center;margin-top:3px}
/* parked */
.parked{font-size:13.5px}
footer.end{margin-top:28px;padding-top:10px;border-top:1px solid var(--line);color:var(--mute);font-size:11.5px}
footer.end .mono{font-size:11px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
`;

const stamp = `${localStamp(F.generatedAt)} ${tzShort()}`;
const SECTIONS = { needs: needsSection, live: liveSection, stores: storesSection, usage: usageSection, repos: reposSection, parked: parkedSection };
const chosen = ONLY.length ? ONLY.filter((k) => SECTIONS[k]) : Object.keys(SECTIONS);
const body = `<main class="page">
<header class="mast">
  <h1>Fleet</h1>
  <div class="asof mono">as of ${esc(stamp)}</div>
  <div class="tally mono">${F.counts.sessions} sessions · ${F.counts.busy} busy · ${F.counts.needs} need you · ${F.counts.decisions} decisions</div>
</header>
${chosen.map((k) => SECTIONS[k]()).join('\n')}
<footer class="end">
  <div>Sources: <span class="mono">claude agents --json</span>, <span class="mono">crew brief --no-ack</span>, <span class="mono">~/.claude/status</span>, <span class="mono">~/.claude/projects</span> transcripts, <span class="mono">crew/appstatus/status.json</span>, <span class="mono">crew/usage/readings.tsv</span>, per-repo git. Nothing on this page touched a network.</div>
  <div class="mono">fleetview · generated ${esc(stamp)}</div>
</footer>
</main>`;

const headBits = `<title>Fleet</title>
<style>${CSS}</style>`;
const full = `<!doctype html>
<html lang="en"${THEME ? ` data-theme="${esc(THEME)}"` : ''}${SHOT ? ' data-shot=""' : ''}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
${headBits}
<script>
// lets shot.sh read the rendered height via --dump-dom
document.addEventListener('DOMContentLoaded',()=>{
  const de=document.documentElement;
  de.setAttribute('data-h',String(de.scrollHeight));
  // per-section top/height so shot.sh can crop the one full screenshot into legible pieces
  const m=[...document.querySelectorAll('main > section')].map(s=>s.id+':'+Math.round(s.getBoundingClientRect().top+window.scrollY)+':'+Math.round(s.getBoundingClientRect().height));
  de.setAttribute('data-sections',m.join(','));
});
</script>
</head>
<body>
${body}
</body>
</html>
`;
fs.writeFileSync(OUT, full);
console.error(`[render] wrote ${OUT} (${(full.length / 1024).toFixed(0)} KB)`);
if (ARTIFACT) {
  fs.writeFileSync(ARTIFACT, `${headBits}\n${body}\n`);
  console.error(`[render] wrote ${ARTIFACT} (artifact fragment)`);
}
