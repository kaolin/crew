#!/usr/bin/env node
// fleetview/collect.mjs — gather "all the things" into fleet.json.
//
// Read-only. No network. Node built-ins only. Shells out to `claude agents
// --json` (what `crew status` itself reads), `crew brief --plain --no-ack`
// (never advances the hub's pinger cursor) and `git`. Everything else is
// files on this Mac: ~/.claude/status/*.json, ~/.claude/projects/**/*.jsonl,
// crew/appstatus/status.json (a stored snapshot — collect.py is NOT run),
// crew/usage/readings.tsv (the launchd sampler's output), and two memory
// notes for repo→app names and the parked list.
//
//   node collect.mjs            # writes fleet.json beside this file
//   node collect.mjs --quiet    # no progress on stderr
//
// Transcript scanning is incremental: .cache.json remembers how far into each
// .jsonl it has read, so the first run is the slow one (~GBs of logs) and
// later runs only read what was appended.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOME = os.homedir();
const DEV = path.join(HOME, 'dev');
const CREW = path.resolve(HERE, '..');
const CREW_BIN = path.join(CREW, 'crew');
const STATUS_DIR = path.join(HOME, '.claude', 'status');
const PROJECTS_DIR = path.join(HOME, '.claude', 'projects');
const MEMORY_DIR = path.join(PROJECTS_DIR, '-Users-kaolin', 'memory');
const APPSTATUS = path.join(CREW, 'appstatus', 'status.json');
const APPNOTES = path.join(CREW, 'appstatus', 'notes.json');
const USAGE_TSV = path.join(CREW, 'usage', 'readings.tsv');
const OUT = path.join(HERE, 'fleet.json');
const CACHE = path.join(HERE, '.cache.json');
const WINDOW_DAYS = 14;
const QUIET = process.argv.includes('--quiet');

const NOW = new Date();
const log = (...a) => { if (!QUIET) console.error('[collect]', ...a); };

// ---------------------------------------------------------------- helpers
function sh(cmd, args, { silent = false, ...opts } = {}) {
  try {
    return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 120_000, ...opts });
  } catch (e) {
    if (!silent) log(`${cmd} ${args.join(' ')} failed: ${(e.stderr || e.message || '').toString().trim().split('\n')[0]}`);
    return null;
  }
}
function readJSON(p) { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; } }
function readText(p) { try { return fs.readFileSync(p, 'utf8'); } catch { return null; } }
function exists(p) { try { fs.accessSync(p); return true; } catch { return false; } }

// Status files write timestamps three ways: "2026-09-03T22:18-0700",
// "2026-09-08T13:05:00-0700", "2026-09-03T07:58:47-07:00". Normalise.
function parseWhen(s) {
  if (!s) return null;
  if (typeof s === 'number') return new Date(s);
  const m = String(s).match(/^(\d{4}-\d\d-\d\d)T(\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?/);
  if (!m) { const d = new Date(s); return isNaN(d) ? null : d; }
  let tz = m[5] || '';
  if (/^[+-]\d{4}$/.test(tz)) tz = tz.slice(0, 3) + ':' + tz.slice(3);
  const d = new Date(`${m[1]}T${m[2]}:${m[3]}:${m[4] || '00'}${tz}`);
  return isNaN(d) ? null : d;
}
const hoursAgo = (d) => (d ? (NOW - d) / 3.6e6 : null);
const localDate = (d) => {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};
const DAYS = [];
for (let i = WINDOW_DAYS - 1; i >= 0; i--) {
  const d = new Date(NOW); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i); DAYS.push(localDate(d));
}
const WINDOW_START = new Date(NOW); WINDOW_START.setHours(0, 0, 0, 0); WINDOW_START.setDate(WINDOW_START.getDate() - (WINDOW_DAYS - 1));

// Privacy: the page shows project names and states, never addresses or secrets.
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const SECRET = /\b(?:sk-[A-Za-z0-9_-]{8,}|AKIA[A-Z0-9]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abp]-[A-Za-z0-9-]{10,}|[A-Fa-f0-9]{40,}|[A-Za-z0-9+/]{48,}={0,2})\b/g;
const scrub = (v) => (v == null ? v : String(v).replace(EMAIL, '[email]').replace(SECRET, '[redacted]'));
const listish = (v) => (Array.isArray(v) ? v.map(scrub) : v == null || v === '' ? [] : [scrub(v)]);
const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
const projectOf = (cwd) => (cwd === HOME ? 'hub' : path.basename(cwd));

// ---------------------------------------------------------------- sessions
function collectSessions() {
  const claude = sh('which', ['claude'])?.trim() || path.join(HOME, '.local', 'bin', 'claude');
  const raw = sh(claude, ['agents', '--json']);
  let list = raw ? readJSONText(raw) : null;
  if (!Array.isArray(list)) {
    log('claude agents --json unavailable; falling back to `crew status`');
    list = parseCrewStatus(sh(CREW_BIN, ['status']) || '');
  }
  return list.map((s) => ({
    name: s.name || '?',
    cwd: s.cwd || '',
    project: projectOf(s.cwd || ''),
    kind: s.kind || null,
    status: s.status || 'unknown',
    waitingFor: s.waitingFor || null,
    startedAt: s.startedAt ? new Date(s.startedAt).toISOString() : null,
    uptimeH: s.startedAt ? (NOW - s.startedAt) / 3.6e6 : null,
  }));
}
function readJSONText(t) { try { return JSON.parse(t); } catch { return null; } }
// Fallback only: the text view groups "  Project   /path" then "    ▶ busy   name   age".
function parseCrewStatus(text) {
  const out = []; let cwd = '';
  for (const line of text.split('\n')) {
    const g = line.match(/^  (\S+)\s+(\/\S+)\s*$/);
    if (g) { cwd = g[2]; continue; }
    const s = line.match(/^\s+[▶○⏸!]\s+(\w+)\s+(.+?)\s+(\d+[dhm][\dhm]*)\s*$/);
    if (s && cwd) out.push({ cwd, status: s[1], name: s[2].trim() });
  }
  return out;
}

// ---------------------------------------------------------------- crew brief
function collectBrief() {
  const raw = scrub(sh(CREW_BIN, ['brief', '--plain', '--no-ack']) || '');
  const sections = {}; let cur = null; let entry = null;
  for (const line of raw.split('\n')) {
    const h = line.match(/^([A-Z][A-Z ]+?)(?:\s+—\s+(.*))?\s*$/);
    if (h && !line.startsWith(' ')) { cur = h[1].trim(); sections[cur] = { note: h[2] || '', entries: [] }; entry = null; continue; }
    if (!cur) continue;
    const b = line.match(/^\s{4,}·\s*(.*)$/);
    if (b && entry) { entry.items.push(b[1].trim()); continue; }
    const e = line.match(/^  (\S+)\s*(.*)$/);
    if (e) { entry = { project: e[1], rest: e[2].trim(), items: [] }; sections[cur].entries.push(entry); }
  }
  return { raw, sections };
}

// ---------------------------------------------------------------- status files
function collectStatusFiles() {
  if (!exists(STATUS_DIR)) return [];
  const out = [];
  for (const f of fs.readdirSync(STATUS_DIR).sort()) {
    if (!f.endsWith('.json') || f.startsWith('_')) continue;
    const d = readJSON(path.join(STATUS_DIR, f));
    const project = f.replace(/\.json$/, '');
    if (!d) { out.push({ project, unreadable: true }); continue; }
    const updatedAt = parseWhen(d.updated_at || d.updated);
    const dev = d.device;
    const device = dev == null ? null : typeof dev === 'string'
      ? { name: scrub(dev), stale: false, note: null }
      : { name: scrub(dev.name) || null, stale: !!dev.stale, note: scrub(dev.note) || null, shipped: scrub(dev.shipped_commit || dev.shipped_build) || null };
    out.push({
      project,
      updatedAt: updatedAt ? updatedAt.toISOString() : null,
      ageH: hoursAgo(updatedAt),
      state: typeof d.state === 'string' ? scrub(d.state.slice(0, 120)) : null,
      head: d.head == null ? null : String(d.head).slice(0, 60),
      build: d.build ?? d.testflight?.latest ?? null,
      lastAction: scrub(d.last_action || d.headline) || null,
      needsDecision: listish(d.needs_decision ?? d.your_move),
      blockers: listish(d.blockers ?? d.blocked_on),
      unpushed: listish(d.unpushed),
      device,
    });
  }
  return out;
}

// ---------------------------------------------------------------- app stores
function collectStores() {
  const snap = readJSON(APPSTATUS);
  const notes = readJSON(APPNOTES)?.apps || {};
  if (!snap) return { available: false, generatedAt: null, ageH: null, apps: [] };
  const generatedAt = parseWhen(snap.generated);
  const playByBundle = {};
  for (const [bundle, tracks] of Object.entries(snap.play || {})) playByBundle[bundle.toLowerCase()] = tracks;
  const apps = (snap.apps || []).map((a) => {
    const n = notes[a.name] || {};
    const tf = a.testflight;
    return {
      name: a.name,
      alias: n.alias || null,
      bundle: a.bundle,
      live: a.live,
      onSale: !!a.onSale,
      territories: Array.isArray(a.territories) ? a.territories[0] : null,
      queue: a.queue, queueBuild: a.queueBuild, waitHours: a.waitHours,
      draft: a.draft ? { version: a.draft[0], state: a.draft[1] } : null,
      testflight: !tf ? null : tf.expired
        ? { expired: true, last: tf.last, ageH: tf.age_h }
        : { version: tf.version, build: tf.build, ageH: tf.age_h, expires: tf.expires },
      play: (playByBundle[(a.bundle || '').toLowerCase()] || []).map((t) => ({ track: t.track, status: t.status, name: t.name, codes: t.codes })),
      everSubmitted: !!a.everSubmitted,
      stage: n.stage ?? null,
      do: scrub(n.do) || null,
      waitingOn: scrub(n.waitingOn) || null,
    };
  });
  // Play packages with no ASC record still deserve a row.
  const seen = new Set(apps.map((a) => (a.bundle || '').toLowerCase()));
  for (const [bundle, tracks] of Object.entries(snap.play || {})) {
    if (seen.has(bundle.toLowerCase())) continue;
    apps.push({ name: bundle, alias: null, bundle, live: null, onSale: false, draft: null, testflight: null, play: tracks, everSubmitted: false, stage: null, do: null });
  }
  return { available: true, generatedAt: generatedAt?.toISOString() || null, ageH: hoursAgo(generatedAt), apps };
}

// ---------------------------------------------------------------- git
function gitFacts(dir) {
  const g = (args) => sh('git', ['-C', dir, ...args], { silent: true })?.trim() ?? null;
  const top = g(['rev-parse', '--show-toplevel']);
  if (!top) return { path: dir, isRepo: false, reason: 'not a git repo' };
  if (path.resolve(top) !== path.resolve(dir)) return { path: dir, isRepo: false, reason: `inside ${top.replace(HOME, '~')}, not its own repo` };
  const remotes = (g(['remote', '-v']) || '').split('\n').filter((l) => l.includes('(fetch)'))
    .map((l) => { const [name, url] = l.split(/\s+/); return { name, host: hostOf(url) }; });
  const upstream = g(['rev-parse', '--abbrev-ref', '@{u}']);
  // With an upstream: commits ahead of it. Without one but with remotes: commits
  // on no remote branch at all (`--not --remotes`), which is the honest figure.
  const unpushed = upstream ? Number(g(['rev-list', '--count', '@{u}..HEAD']) || 0)
    : remotes.length ? Number(g(['rev-list', '--count', 'HEAD', '--not', '--remotes']) || 0) : null;
  const perDay = {};
  for (const d of (g(['log', `--since=${WINDOW_DAYS} days ago`, '--format=%cs']) || '').split('\n').filter(Boolean)) perDay[d] = (perDay[d] || 0) + 1;
  const status = g(['status', '--porcelain']) || '';
  return {
    path: dir,
    isRepo: true,
    branch: g(['rev-parse', '--abbrev-ref', 'HEAD']),
    lastCommit: g(['log', '-1', '--format=%cI']),
    remotes,
    upstream,
    unpushed,
    uncommitted: status ? status.split('\n').filter(Boolean).length : 0,
    commits14d: Object.values(perDay).reduce((a, b) => a + b, 0),
    perDayCommits: perDay,
  };
}
function hostOf(url) {
  if (!url) return null;
  const m = url.match(/^(?:[a-z+]+:\/\/)?(?:[^@\/]+@)?([^:\/]+)/i);
  return m ? m[1] : null;
}
function collectRepos(cwds) {
  const out = [];
  for (const cwd of cwds) {
    if (!cwd.startsWith(DEV + path.sep) || cwd === DEV) continue; // skip ~ and ~/dev themselves
    const facts = gitFacts(cwd);
    facts.project = projectOf(cwd);
    facts.nested = [];
    for (const sub of ['godot', 'ios', 'android', 'app']) {
      const p = path.join(cwd, sub);
      if (exists(path.join(p, '.git'))) facts.nested.push({ sub, ...gitFacts(p) });
    }
    out.push(facts);
  }
  return out;
}

// ---------------------------------------------------------------- transcripts
const encodeCwd = (cwd) => cwd.replace(/[^A-Za-z0-9]/g, '-');
function decodeDir(name) {
  if (name === '-Users-kaolin') return 'hub';
  if (name === '-Users-kaolin-dev') return 'dev';
  return name.replace(/^-Users-kaolin-dev-/, '');
}
function loadCache() { return readJSON(CACHE) || { files: {} }; }
function saveCache(c) { fs.writeFileSync(CACHE, JSON.stringify(c)); }

// Scan one .jsonl from `from` to EOF. Every line carrying "timestamp":"…" is
// bucketed by its LOCAL date: bytes, and a count of assistant messages.
function scanFile(file, from, acc) {
  const fd = fs.openSync(file, 'r');
  const CH = 1 << 20; const buf = Buffer.allocUnsafe(CH);
  let pos = from, rem = Buffer.alloc(0), scanned = from;
  const TS = Buffer.from('"timestamp":"'); const AS = Buffer.from('"type":"assistant"');
  try {
    for (;;) {
      const n = fs.readSync(fd, buf, 0, CH, pos);
      if (n <= 0) break;
      pos += n;
      let chunk = rem.length ? Buffer.concat([rem, buf.subarray(0, n)]) : buf.subarray(0, n);
      let start = 0;
      for (;;) {
        const nl = chunk.indexOf(10, start);
        if (nl < 0) break;
        const line = chunk.subarray(start, nl);
        bucketLine(line, acc);
        start = nl + 1;
      }
      rem = Buffer.from(chunk.subarray(start)); // copy: buf is reused
      scanned = pos - rem.length;
    }
  } finally { fs.closeSync(fd); }
  return scanned;
  function bucketLine(line, acc) {
    const i = line.indexOf(TS);
    if (i < 0) return;
    const ts = line.toString('latin1', i + TS.length, i + TS.length + 24);
    const d = new Date(ts.slice(0, ts.indexOf('"') > 0 ? ts.indexOf('"') : 24));
    if (isNaN(d)) return;
    const iso = d.toISOString();
    if (!acc.lastTs || iso > acc.lastTs) acc.lastTs = iso;
    const day = localDate(d);
    const b = acc.perDay[day] || (acc.perDay[day] = { bytes: 0, assistant: 0 });
    b.bytes += line.length + 1;
    if (line.indexOf(AS) >= 0) b.assistant++;
  }
}
function collectTranscripts() {
  const cache = loadCache(); const seen = new Set(); const out = {};
  if (!exists(PROJECTS_DIR)) return out;
  const cutoff = WINDOW_START.getTime();
  for (const dir of fs.readdirSync(PROJECTS_DIR)) {
    if (!(dir === '-Users-kaolin' || dir.startsWith('-Users-kaolin-dev'))) continue;
    const p = path.join(PROJECTS_DIR, dir);
    let files; try { files = fs.readdirSync(p).filter((f) => f.endsWith('.jsonl')); } catch { continue; }
    const proj = { dir, project: decodeDir(dir), perDay: {}, lastTs: null, files: files.length, bytesTotal: 0, bytes14d: 0, assistant14d: 0 };
    for (const f of files) {
      const file = path.join(p, f); let st; try { st = fs.statSync(file); } catch { continue; }
      seen.add(file);
      proj.bytesTotal += st.size;
      let c = cache.files[file];
      const fresh = st.mtimeMs >= cutoff;
      if (!c) {
        if (!fresh) continue; // untouched for the whole window: contributes nothing to it
        c = { size: 0, scanned: 0, perDay: {}, lastTs: null };
      }
      if (c.size > st.size) c = { size: 0, scanned: 0, perDay: {}, lastTs: null }; // truncated/rewritten: rescan
      if (st.size > c.scanned) {
        log(`scan ${dir}/${f} +${((st.size - c.scanned) / 1e6).toFixed(1)} MB`);
        c.scanned = scanFile(file, c.scanned, c);
        c.size = st.size;
        for (const k of Object.keys(c.perDay)) if (k < DAYS[0] && k < localDate(new Date(NOW - 60 * 864e5))) delete c.perDay[k];
      }
      cache.files[file] = c;
      if (c.lastTs && (!proj.lastTs || c.lastTs > proj.lastTs)) proj.lastTs = c.lastTs;
      for (const [day, b] of Object.entries(c.perDay)) {
        const t = proj.perDay[day] || (proj.perDay[day] = { bytes: 0, assistant: 0 });
        t.bytes += b.bytes; t.assistant += b.assistant;
      }
    }
    for (const day of DAYS) { const b = proj.perDay[day]; if (b) { proj.bytes14d += b.bytes; proj.assistant14d += b.assistant; } }
    if (proj.bytes14d > 0 || proj.lastTs) out[proj.project] = proj;
  }
  for (const f of Object.keys(cache.files)) if (!seen.has(f)) delete cache.files[f];
  saveCache(cache);
  return out;
}

// ---------------------------------------------------------------- usage headroom
function collectHeadroom() {
  const t = readText(USAGE_TSV);
  if (!t) return { available: false, reason: 'usage/readings.tsv missing' };
  const lines = t.trim().split('\n'); const cols = lines[0].split('\t');
  let last = null;
  for (let i = lines.length - 1; i > 0; i--) {
    const r = Object.fromEntries(lines[i].split('\t').map((v, j) => [cols[j], v]));
    if (r.seven_day_pct !== '' && r.seven_day_pct != null) { last = r; break; }
  }
  if (!last) return { available: false, reason: 'no usable sample' };
  const sampled = parseWhen(last.ts);
  const errTail = (readText(path.join(CREW, 'usage', 'sampler.err.log')) || '').trim().split('\n').slice(-1)[0] || null;
  return {
    available: true,
    sampledAt: sampled?.toISOString() || last.ts,
    ageMin: sampled ? (NOW - sampled) / 6e4 : null,
    fiveHourPct: num(last.five_hour_pct), fiveHourResets: last.five_hour_resets || null,
    sevenDayPct: num(last.seven_day_pct), sevenDayResets: last.seven_day_resets || null,
    opusPct: num(last.opus_pct), extraEnabled: last.extra_enabled === 'True',
    samples: lines.length - 1,
    lastSamplerError: errTail,
  };
}
const num = (v) => (v === '' || v == null ? null : Number(v));

// ---------------------------------------------------------------- identity
function collectIdentity() {
  const repoToApp = {
    // repos that are not store apps, or whose name kaolin uses differs
    erif_html: 'erif.org', spacetag: 'spacetag (Mac)', fenriswatch: 'Fenris watch logger',
    teethwatch: 'Teethwatch', beatboxing: 'BeatBoxing', hub: 'hub', dev: '~/dev',
  };
  const names = readText(path.join(MEMORY_DIR, 'reference_repo_to_app_names.md')) || '';
  for (const line of names.split('\n')) {
    const m = line.match(/^\|\s*`([^`]+)`[^|]*\|\s*\*\*([^*]+)\*\*/);
    if (m) repoToApp[m[1].trim()] = m[2].trim();
  }
  const parkedMd = readText(path.join(MEMORY_DIR, 'project_parked_apps.md')) || '';
  const parked = [];
  for (const line of parkedMd.split('\n')) {
    const m = line.match(/^\|\s*\*\*([^*]+)\*\*([^|]*)\|\s*([^|]+)\|/);
    if (m) {
      const repo = (m[2].match(/`([^`]+)`/) || [])[1] || null;
      parked.push({ app: m[1].trim(), repo, state: m[3].trim() });
    }
  }
  const parkedSince = (parkedMd.match(/Parked as of (\d{4}-\d\d-\d\d)/) || [])[1] || null;
  return { repoToApp, parked, parkedSince };
}
function appFor(project, identity, stores) {
  if (identity.repoToApp[project]) return identity.repoToApp[project];
  const n = norm(project);
  for (const a of stores.apps) {
    if (norm(a.name) === n || (a.alias && norm(a.alias) === n)) return a.name;
  }
  for (const a of stores.apps) if (norm(a.name).startsWith(n) && n.length >= 5) return a.name;
  return project;
}
function storeFor(project, app, stores) {
  const n = norm(project), na = norm(app);
  return stores.apps.find((a) => norm(a.name) === na || norm(a.name) === n || (a.alias && norm(a.alias) === n)) || null;
}

// ---------------------------------------------------------------- assemble
function main() {
  log('sessions'); const sessions = collectSessions();
  log('brief'); const brief = collectBrief();
  log('status files'); const statusFiles = collectStatusFiles();
  log('stores'); const stores = collectStores();
  log('identity'); const identity = collectIdentity();
  const cwds = [...new Set(sessions.map((s) => s.cwd).filter(Boolean))];
  log('repos'); const repos = collectRepos(cwds);
  log('transcripts'); const transcripts = collectTranscripts();
  log('headroom'); const headroom = collectHeadroom();

  // status files are named by session handle, not repo dir: babypaints.json ↔ BabyPaints, erif.json ↔ erif_html
  const statusFor = (project) => {
    const n = norm(project);
    return statusFiles.find((s) => norm(s.project) === n)
      || statusFiles.find((s) => n.startsWith(norm(s.project)) || norm(s.project).startsWith(n)) || null;
  };
  const transcriptFor = (project) => transcripts[project] || transcripts[project.replace(/_/g, '-')] || null;
  const repoFor = (project) => repos.find((r) => r.project === project) || null;

  const perDayFor = (project) => {
    const t = transcriptFor(project); const r = repoFor(project);
    const commits = {};
    if (r?.isRepo) for (const [d, c] of Object.entries(r.perDayCommits)) commits[d] = (commits[d] || 0) + c;
    for (const nr of r?.nested || []) if (nr.isRepo) for (const [d, c] of Object.entries(nr.perDayCommits)) commits[d] = (commits[d] || 0) + c;
    return DAYS.map((d) => ({ date: d, bytes: t?.perDay[d]?.bytes || 0, assistant: t?.perDay[d]?.assistant || 0, commits: commits[d] || 0 }));
  };

  const sessionRows = sessions.map((s) => {
    const app = appFor(s.project, identity, stores);
    const sf = statusFor(s.project); const t = transcriptFor(s.project); const r = repoFor(s.project);
    const lastActivity = t?.lastTs || sf?.updatedAt || null;
    return {
      ...s, app,
      lastActivity, lastActivityAgeH: hoursAgo(lastActivity ? new Date(lastActivity) : null),
      bytes14d: t?.bytes14d || 0, assistant14d: t?.assistant14d || 0,
      commits14d: (r?.commits14d || 0) + (r?.nested || []).reduce((a, n) => a + (n.commits14d || 0), 0),
      statusFile: sf ? { project: sf.project, updatedAt: sf.updatedAt, ageH: sf.ageH, state: sf.state, build: sf.build, head: sf.head, lastAction: sf.lastAction } : null,
      device: sf?.device || null,
      deviceStale: !!sf?.device?.stale,
    };
  });

  // Needs you: every status file with decisions, ranked oldest-first and most-touched-first (sum of ranks).
  const needsRaw = statusFiles.filter((s) => s.needsDecision?.length).map((s) => {
    const sess = sessionRows.find((x) => x.statusFile?.project === s.project);
    const project = sess?.project || s.project;
    const t = transcriptFor(project);
    return {
      project, app: sess?.app || appFor(project, identity, stores), session: sess?.name || null,
      updatedAt: s.updatedAt, ageH: s.ageH, items: s.needsDecision, blockers: s.blockers,
      bytes14d: t?.bytes14d || 0, commits14d: sess?.commits14d || 0, deviceStale: !!s.device?.stale, device: s.device,
    };
  });
  const byAge = [...needsRaw].sort((a, b) => (b.ageH ?? 0) - (a.ageH ?? 0));
  const byTouch = [...needsRaw].sort((a, b) => b.bytes14d - a.bytes14d);
  for (const n of needsRaw) n.rank = byAge.indexOf(n) + byTouch.indexOf(n);
  const needs = needsRaw.sort((a, b) => a.rank - b.rank || (b.ageH ?? 0) - (a.ageH ?? 0));

  // Usage: every project with a session, plus any transcript dir that moved in the window.
  const usageProjects = new Map();
  for (const s of sessionRows) if (!usageProjects.has(s.project)) usageProjects.set(s.project, { project: s.project, app: s.app, hasSession: true });
  for (const [proj, t] of Object.entries(transcripts)) {
    const key = [...usageProjects.keys()].find((k) => k === proj || k.replace(/_/g, '-') === proj);
    if (!key && t.bytes14d > 0) usageProjects.set(proj, { project: proj, app: appFor(proj, identity, stores), hasSession: false });
  }
  const usage = [...usageProjects.values()].map((u) => {
    const perDay = perDayFor(u.project); const t = transcriptFor(u.project);
    return { ...u, perDay, bytes14d: perDay.reduce((a, d) => a + d.bytes, 0), assistant14d: perDay.reduce((a, d) => a + d.assistant, 0), commits14d: perDay.reduce((a, d) => a + d.commits, 0), lastActivity: t?.lastTs || null };
  }).sort((a, b) => b.bytes14d - a.bytes14d);

  // Repos at risk: no remote, unpushed, not a repo at all, or a big uncommitted tree.
  const risk = [];
  for (const r of repos) {
    const sf = statusFor(r.project);
    const note = sf?.unpushed?.[0] || (brief.sections['UNPUSHED WORK']?.entries.find((e) => norm(e.project) === norm(r.project) || norm(r.project).startsWith(norm(e.project)))?.rest) || null;
    const row = { project: r.project, app: appFor(r.project, identity, stores), path: r.path.replace(HOME, '~'), isRepo: r.isRepo, reason: r.reason || null, branch: r.branch || null, remotes: r.remotes || [], upstream: r.upstream || null, unpushed: r.unpushed ?? null, uncommitted: r.uncommitted ?? null, lastCommit: r.lastCommit || null, commits14d: r.commits14d || 0, note, nested: (r.nested || []).map((n) => ({ sub: n.sub, isRepo: n.isRepo, remotes: n.remotes || [], upstream: n.upstream || null, unpushed: n.unpushed ?? null, uncommitted: n.uncommitted ?? null, lastCommit: n.lastCommit || null, commits14d: n.commits14d || 0 })) };
    const noRemote = row.isRepo && row.remotes.length === 0;
    const nestedRisk = row.nested.some((n) => n.isRepo && (n.remotes.length === 0 || (n.unpushed ?? 0) > 0));
    row.atRisk = !row.isRepo || noRemote || (row.unpushed ?? 0) > 0 || (row.isRepo && row.remotes.length > 0 && !row.upstream) || nestedRisk;
    row.flags = [];
    if (!row.isRepo) row.flags.push('not a repo');
    if (noRemote) row.flags.push('no remote');
    if ((row.unpushed ?? 0) > 0) row.flags.push(`${row.unpushed} unpushed${row.upstream ? '' : ' (branch on no remote)'}`);
    else if (row.isRepo && row.remotes.length && !row.upstream) row.flags.push('branch has no upstream');
    if ((row.uncommitted ?? 0) > 0) row.flags.push(`${row.uncommitted} uncommitted`);
    for (const n of row.nested) {
      if (n.isRepo && n.remotes.length === 0) row.flags.push(`${n.sub}/ no remote`);
      if ((n.unpushed ?? 0) > 0) row.flags.push(`${n.sub}/ ${n.unpushed} unpushed`);
      if ((n.uncommitted ?? 0) > 0) row.flags.push(`${n.sub}/ ${n.uncommitted} uncommitted`);
    }
    risk.push(row);
  }
  risk.sort((a, b) => Number(b.atRisk) - Number(a.atRisk) || b.commits14d - a.commits14d);

  const parked = identity.parked.map((p) => {
    const store = storeFor(p.repo || p.app, p.app, stores);
    const sess = sessionRows.find((s) => norm(s.app) === norm(p.app) || norm(s.project) === norm(p.repo || p.app));
    const u = usage.find((x) => norm(x.app) === norm(p.app) || norm(x.project) === norm(p.repo || p.app));
    return { ...p, store: store?.name || null, session: sess?.name || null, sessionStatus: sess?.status || null, bytes14d: u?.bytes14d || 0, commits14d: u?.commits14d || 0, lastActivity: u?.lastActivity || null };
  });

  const fleet = {
    generatedAt: NOW.toISOString(),
    generatedLocal: NOW.toLocaleString('en-CA', { hour12: false, timeZoneName: 'short' }),
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    windowDays: WINDOW_DAYS, days: DAYS,
    sources: {
      sessions: 'claude agents --json', brief: 'crew brief --plain --no-ack', statusFiles: STATUS_DIR.replace(HOME, '~'),
      stores: APPSTATUS.replace(HOME, '~'), transcripts: PROJECTS_DIR.replace(HOME, '~'), headroom: USAGE_TSV.replace(HOME, '~'),
    },
    counts: { sessions: sessionRows.length, busy: sessionRows.filter((s) => s.status === 'busy').length, idle: sessionRows.filter((s) => s.status === 'idle').length, waiting: sessionRows.filter((s) => s.status === 'waiting').length, needs: needs.length, decisions: needs.reduce((a, n) => a + n.items.length, 0) },
    needs,
    sessions: sessionRows.sort((a, b) => rankStatus(a.status) - rankStatus(b.status) || (a.lastActivityAgeH ?? 1e9) - (b.lastActivityAgeH ?? 1e9)),
    brief: { sections: brief.sections, raw: brief.raw },
    stores: { ...stores, apps: stores.apps.map((a) => ({ ...a, project: sessionRows.find((s) => s.app === a.name)?.project || null, hasSession: sessionRows.some((s) => s.app === a.name) })) },
    usage, headroom,
    repos: risk,
    parked, parkedSince: identity.parkedSince,
  };
  fs.writeFileSync(OUT, JSON.stringify(fleet, null, 1));
  log(`wrote ${OUT.replace(HOME, '~')}: ${fleet.counts.sessions} sessions, ${needs.length} projects need you (${fleet.counts.decisions} items), ${stores.apps.length} store apps, ${usage.length} usage rows, ${risk.filter((r) => r.atRisk).length}/${risk.length} repos at risk, headroom ${headroom.available ? 'ok' : 'n/a'}`);
}
const rankStatus = (s) => ({ waiting: 0, busy: 1, idle: 2 }[s] ?? 3);
main();
