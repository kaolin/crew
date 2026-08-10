#!/usr/bin/env python3
"""crew-pinger: watch the Claude fleet and Telegram-alert on state changes.

Runs once per invocation (driven by a launchd StartInterval). Detects, by
diffing against the previous snapshot in state.json:

  * FINISHED  — a session went busy -> idle after being busy at least
                MIN_FINISHED_SECS (filters out trivial per-turn chatter).
  * STUCK     — a session has been continuously busy >= STUCK_HOURS
                (catches hung / blocked sessions). Alerts once per episode.

There is no "blocked/waiting" flag in `claude agents --json` (only idle/busy),
so these two transitions are the honest signals available.

Sends one batched message per tick to every paired Telegram chat, straight
through the bot API — independent of the hub session.
"""
import calendar, difflib, json, os, re, subprocess, sys, time, urllib.request, urllib.parse

HOME        = os.path.expanduser("~")
CLAUDE      = "/Users/kaolin/.local/bin/claude"
ENV_PATH    = f"{HOME}/.claude/channels/telegram/.env"
ACCESS_PATH = f"{HOME}/.claude/channels/telegram/access.json"
STATE_PATH  = f"{HOME}/dev/crew/pinger/state.json"
LOG_PATH    = f"{HOME}/dev/crew/pinger/pinger.log"
INBOUND_LOG    = f"{HOME}/.claude/channels/telegram/inbound.jsonl"
INBOUND_CURSOR = f"{HOME}/.claude/channels/telegram/inbound.cursor"
BOT_PID_FILE   = f"{HOME}/.claude/channels/telegram/bot.pid"

# --- tunables ---------------------------------------------------------------
NOTIFY_FINISHED   = True
NOTIFY_STUCK      = True
NOTIFY_WAITING    = True       # session blocked on a question/permission prompt -> ping
                               # (it never un-blocks on its own; silence = lost hours)
MIN_FINISHED_SECS = 120        # only ping "finished" for busy episodes >= this
STUCK_HOURS       = 3.0        # busy this long with no change -> "may be hung"
EXCLUDE_NAMES     = {"hub"}     # sessions to never ping about (the hub itself)
QUIET_HOURS       = None       # e.g. (23, 8) to mute 23:00-08:00 local; None = off
TUNNEL_STALL_SECS = 120        # inbound queued-but-undelivered longer than this -> tunnel is down
POLLER_DOWN_SECS  = 180        # bot poller process dead this long -> whole bridge down (rides out a brief restart)

# "finished" alerts carry WHAT finished, plus any images the session just made.
# A bare "✅ done after 12m" is meaningless on a phone (kaolin, 2026-07-20).
GIST_CHARS        = 12000     # max chars of the closing message; batched across
                              # messages, not trimmed — a synthesis report cut
                              # mid-list is useless on a phone (kaolin, 2026-07-31)
MIN_GIST_CHARS    = 80         # ignore short acks ("On it.") when picking the gist
SEND_PHOTOS       = True       # attach screenshots/renders the session just wrote
MAX_ARTIFACTS     = 3          # photos per finished session
MAX_PHOTO_BYTES   = 9 * 1024 * 1024      # Telegram sendPhoto ceiling is 10MB
ARTIFACT_SLACK    = 300        # secs before busy_since a file may have been written
TAIL_LINES        = 400       # transcript lines to scan for artifact paths (episode-filtered)
IMG_RE            = re.compile(r"/[^\s\"'`<>()\[\],]+\.(?:png|jpg|jpeg|gif)", re.I)
TG_LIMIT          = 3900       # Telegram hard-caps sendMessage at 4096; leave headroom
# ----------------------------------------------------------------------------


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"{ts}  {msg}\n")
    except OSError:
        pass


def load_token():
    try:
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def load_chats():
    try:
        with open(ACCESS_PATH) as f:
            return [str(c) for c in json.load(f).get("allowFrom", [])]
    except (OSError, ValueError):
        return []


def get_sessions():
    try:
        out = subprocess.run([CLAUDE, "agents", "--json"],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            log(f"claude agents failed rc={out.returncode}: {out.stderr[:200]}")
            return None
        return json.loads(out.stdout)
    except Exception as e:                      # noqa: BLE001 - daemon must not crash
        log(f"get_sessions error: {e}")
        return None


def send(token, chat, text, parse_mode=None):
    fields = {"chat_id": chat, "text": text}
    if parse_mode:
        fields["parse_mode"] = parse_mode
    data = urllib.parse.urlencode(fields).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
            r.read()
        return True
    except Exception as e:                      # noqa: BLE001
        log(f"send to {chat} failed: {e}")
        return False


_MD_SPECIAL = r"_*[]()~`>#+-=|{}.!"

def md_escape(text):
    """Backslash-escape every MarkdownV2 reserved char."""
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in text)


def pack(blocks, header="🔔 crew"):
    """Group blocks into as few messages as fit under TG_LIMIT. Oversized single
    blocks are hard-split. Telegram silently truncates past 4096 (kaolin, 2026-07-20)."""
    msgs, cur = [], header
    for b in blocks:
        if len(b) + 2 > TG_LIMIT:
            if cur.strip() != header:
                msgs.append(cur); cur = header
            for i in range(0, len(b), TG_LIMIT - 40):
                part = b[i : i + TG_LIMIT - 40]
                msgs.append(part if i == 0 else "…" + part)
            continue
        if len(cur) + len(b) + 2 > TG_LIMIT:
            msgs.append(cur); cur = header
        cur += "\n\n" + b
    if cur.strip() != header:
        msgs.append(cur)
    return msgs


def send_chunked(token, chat, blocks_md, blocks_plain, header="🔔 crew",
                 prepacked=False):
    """Send MarkdownV2 blocks; if the first message is rejected (an escaping bug
    would 400), fall back to plain text for the whole batch so a formatting
    error degrades gracefully instead of dropping the report (kaolin wants
    bulleted/bold, 2026-07-23). Pass header="" for a self-headed (per-app) message.
    prepacked=True means the caller already split at line boundaries (split_report)
    — send as-is instead of re-grouping."""
    md = blocks_md if prepacked else pack(blocks_md, header)
    for i, m in enumerate(md):
        if send(token, chat, m, parse_mode="MarkdownV2"):
            continue
        if i == 0:                                     # bad markup → plain for all
            log("markdownv2 send rejected; falling back to plain")
            ok = True
            for pm in (blocks_plain if prepacked else pack(blocks_plain, header)):
                ok = send(token, chat, pm) and ok
            return ok
        send(token, chat, m)                           # later msg: retry unformatted
    return True


def transcript_path(cwd, session_id):
    enc = (cwd or "").replace("/", "-")
    return f"{HOME}/.claude/projects/{enc}/{session_id}.jsonl"


def _table_row(ln):
    """'| Vision Pro port | Park — … |' → 'Vision Pro port — Park — …'.
    Separator rows ('|---|---|') return ''. Markdown tables used to be dropped
    whole, which silently ate an entire cut/park decision table out of an orrery
    report (kaolin, 2026-07-31)."""
    cells = [c.strip() for c in ln.strip().strip("|").split("|")]
    if not any(c.strip("-: ") for c in cells):
        return ""
    return " — ".join(c for c in cells if c)


def _clean(text):
    """Assistant message → clean lines, list items marked with '• '. Returns a
    list of (is_bullet, text) so callers can render plain or MarkdownV2."""
    out = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith(("```", ">")):
            continue
        if ln.startswith("|"):
            ln = _table_row(ln)
            if not ln:
                continue
            out.append((True, ln.replace("**", "").replace("`", "")))
            continue
        bullet = ln.startswith(("- ", "* ", "• "))
        ln = ln.lstrip("#").strip()
        if bullet:
            ln = ln[2:].strip()
        ln = ln.replace("**", "").replace("`", "").replace("·", "-")
        if ln:
            out.append((bullet, ln))
    return out


def last_gist(path, limit=GIST_CHARS):
    """The last substantive thing the session said, as one line. '' if unknown."""
    best = ""
    try:
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                content = (e.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        t = b.get("text", "").strip()
                        if len(t) >= MIN_GIST_CHARS:
                            best = t
    except OSError:
        return ""
    return _clip(_clean(best), limit)


def _clip(items, limit):
    """Trim a list of (is_bullet, text) lines to `limit` total chars."""
    kept, used = [], 0
    for bullet, ln in items:
        if used + len(ln) > limit and kept:
            kept.append((False, "…[trimmed]"))
            break
        kept.append((bullet, ln))
        used += len(ln) + 2
    return kept


def render_plain(head, lines):
    body = "\n".join(("• " + t) if b else t for b, t in lines)
    return f"{head}\n{body}" if body else head


def render_md(head_md, lines):
    body = "\n".join(("• " + md_escape(t)) if b else md_escape(t) for b, t in lines)
    return f"{head_md}\n{body}" if body else head_md


def split_report(head, lines, escape=False, limit=TG_LIMIT - 60):
    """Head + body → as few messages as fit, split on LINE boundaries.

    Long reports get batched across messages rather than trimmed mid-list
    (kaolin, 2026-07-31 — an orrery synthesis was cut right before the pricing
    decision). Continuation messages are marked '… n/N'; that marker and the
    ellipsis are MarkdownV2-safe, so it survives both render paths."""
    esc = md_escape if escape else (lambda t: t)
    rendered = [("• " + esc(t)) if b else esc(t) for b, t in lines]

    msgs, cur = [], head
    for ln in rendered:
        while len(ln) > limit:                       # single monster line
            cut = ln.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            part, ln = ln[:cut], "…" + ln[cut:].lstrip()
            if cur and len(cur) + 1 + len(part) > limit:
                msgs.append(cur); cur = ""
            cur += ("\n" if cur else "") + part
        if cur and len(cur) + 1 + len(ln) > limit:
            msgs.append(cur); cur = ""
        cur += ("\n" if cur else "") + ln
    if cur.strip():
        msgs.append(cur)
    if not msgs:
        return [head]
    if len(msgs) > 1:
        n = len(msgs)
        msgs = [m if i == 0 else f"… {i + 1}/{n}\n{m}" for i, m in enumerate(msgs)]
    return msgs


def pending_prompt(path, tail=400):
    """What a `waiting` session is blocked on: ('question'|'permission', text).

    `claude agents --json` says only "permission prompt" for both, but a question
    meant for kaolin is the one he must see on his phone — orrery sat on an unseen
    IAP-name question for 1h40m (2026-07-31). A tool_use with no tool_result is it.
    """
    try:
        with open(path, errors="replace") as f:
            lines = f.readlines()[-tail:]
    except OSError:
        return None

    answered, pend = set(), None
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        body = (r.get("message") or {}).get("content")
        if not isinstance(body, list):
            continue
        for b in body:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                answered.add(b["tool_use_id"])
            elif b.get("type") == "tool_use":
                pend = b
    if not pend or pend.get("id") in answered:
        return None

    name, inp = pend.get("name", "tool"), pend.get("input") or {}
    if name == "AskUserQuestion":
        q = (inp.get("questions") or [{}])[0]
        out = [q.get("question", "(question)")]
        out += [f"{i}. {o.get('label','')}" for i, o in enumerate(q.get("options") or [], 1)]
        return ("question", "\n".join(out))
    detail = inp.get("command") or inp.get("file_path") or inp.get("url") or ""
    return ("permission", f"{name} — {' '.join(str(detail).split())[:200]}")


CREW_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crew")


SAME_REPORT_RATIO = 0.86   # difflib similarity above which two reports are "the same news"
SAME_REPORT_QUIET = 6 * 3600   # ...but say something anyway if it has been this long


def report_sig(lines):
    """Comparable signature for a gist: prose only, no numbers, no timestamps.

    A polling session says the same thing every few minutes with the clock
    moved on — "still WAITING_FOR_REVIEW, checked 02:14" then "…02:19". Those
    are one piece of news, and sending each one buries the reports that matter
    (kaolin, 2026-08-10: "way too verbose and frequent")."""
    text = " ".join(t for _, t in (lines or []))
    text = re.sub(r"\d+", "", text.lower())
    return " ".join(text.split())


def same_news(a, b):
    """True when two gists are the same report wearing a different clock."""
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= SAME_REPORT_RATIO


def transcript_lines(tpath):
    """Line count of a session's transcript — our marker for "has it said
    anything new". Cheap, and monotonic within a session."""
    try:
        with open(tpath, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def at_prompt_via_crew(name, timeout=10):
    """True if `crew at-prompt <name>` says the session is typeable right now.

    A session stays "busy" in `claude agents --json` for as long as any
    background shell or monitor lives, so a finished turn can look hung for
    hours (thereby-ed, 2026-08-05: 3h "may be hung" with its report on screen).
    Only crew can see this — it scrapes the terminal, which launchd can't.
    On any failure return False, so we fall back to alerting rather than going
    quiet about a session that might really be stuck."""
    try:
        out = subprocess.run([CREW_BIN, "at-prompt", name],
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def pending_via_crew(name, timeout=10):
    """Ask `crew pending <name>` — it can scrape the live terminal, which we can't
    from launchd, so it sees prompts the transcript hasn't logged. [] on any
    failure; this is enrichment, never the thing the alert depends on."""
    try:
        out = subprocess.run([CREW_BIN, "pending", name],
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0 or not out.stdout.strip():
        return []
    skip = ("nothing pending in the transcript", "scraping the screen",
            "answer with:", "you have to approve/deny", "(not reachable",
            # crew reports these on stdout and still exits 0
            "no running session matches", "is ambiguous", "couldn't find the tty",
            "nothing waiting")
    rows = []
    for ln in out.stdout.splitlines():
        t = ln.strip()
        if not t or t.startswith("─") or any(k in t for k in skip):
            continue
        if t.startswith(name):                      # the header line
            continue
        rows.append(t)
    return rows[:20]


def find_artifacts(path, since, cap=MAX_ARTIFACTS):
    """Image files the session named in its closing message, written this episode."""
    found, seen = [], set()
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since - ARTIFACT_SLACK))
    try:
        with open(path, errors="replace") as f:
            tail = f.readlines()[-TAIL_LINES:]
    except OSError:
        return []
    for line in tail:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant":
            continue
        # ISO-8601 Z timestamps sort lexically, so a string compare is enough.
        ts = e.get("timestamp") or ""
        if ts and ts < cutoff:
            continue
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == "text"):
                continue
            for m in IMG_RE.finditer(b.get("text", "")):
                p = m.group(0)
                if p in seen:
                    continue
                seen.add(p)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_mtime >= since - ARTIFACT_SLACK and st.st_size <= MAX_PHOTO_BYTES:
                    found.append(p)
    return found[-cap:]


def send_photo(token, chat, path, caption=""):
    boundary = "----crewpinger" + str(int(time.time() * 1000))
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError:
        return False
    parts = []
    for key, val in (("chat_id", str(chat)), ("caption", caption[:1024])):
        if val:
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode()
            )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; "
        f"filename=\"{os.path.basename(path)}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(blob)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            r.read()
        return True
    except Exception as e:                      # noqa: BLE001
        log(f"sendPhoto {os.path.basename(path)} to {chat} failed: {e}")
        return False


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def in_quiet_hours(now):
    if not QUIET_HOURS:
        return False
    h = time.localtime(now).tm_hour
    a, b = QUIET_HOURS
    return (a <= h or h < b) if a > b else (a <= h < b)


def tunnel_backlog(now):
    """(count, oldest_age_secs) of inbound records logged but NOT yet delivered
    (seq > the delivered cursor). On a healthy channel every message is delivered
    and the cursor keeps pace, so an aging backlog means the hub session's MCP
    channel is down. Absent/empty log -> (0, 0)."""
    try:
        cur = int(open(INBOUND_CURSOR).read().strip() or "0")
    except (OSError, ValueError):
        cur = 0
    n, oldest = 0, None
    try:
        with open(INBOUND_LOG, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("seq", 0) > cur:
                    n += 1
                    try:
                        ep = calendar.timegm(time.strptime((r.get("ts") or "")[:19],
                                                           "%Y-%m-%dT%H:%M:%S"))
                    except ValueError:
                        ep = now
                    if oldest is None or ep < oldest:
                        oldest = ep
    except OSError:
        return (0, 0)
    return (n, (now - oldest) if oldest else 0)


def check_tunnel(now, state):
    """Detect a dropped Telegram tunnel from the durable inbound log and alert
    once per drop, out-of-band via the bot API (works even though the hub
    session's channel is what's down). Returns the updated 'alerted' flag."""
    already = bool(state.get("tunnel_alerted"))
    n, age = tunnel_backlog(now)
    down = n > 0 and age >= TUNNEL_STALL_SECS
    if down and not already:
        token, chats = load_token(), load_chats()
        mins = age / 60
        msg = (f"⚠️ Telegram tunnel looks DOWN — {n} message(s) queued ~{mins:.0f}m "
               f"with no delivery.\n\nNothing is lost (they're in the durable log). "
               f"Run /reload-plugins in the hub session to reconnect and replay them.")
        ok = all(send(token, c, msg) for c in chats) if chats else False
        log(f"TUNNEL-DOWN alert: {n} undelivered, oldest ~{mins:.0f}m, sent={ok}")
        return True
    if already and not down:
        log("tunnel recovered — re-arming drop alert")
        return False
    return already


def poller_alive():
    """True/False whether the telegram bot poller (bot.pid) process is running;
    None if we can't tell (no pid file)."""
    try:
        pid = int(open(BOT_PID_FILE).read().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)          # signal 0 = existence check, doesn't touch the process
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True              # exists but not ours (shouldn't happen) — treat as up
    except OSError:
        return False


def check_poller(now, state):
    """Alert if the bot poller PROCESS is dead — the whole bridge is down (nothing
    received or logged, so the backlog detector can't even fire). Requires it down
    persistently (>= POLLER_DOWN_SECS) so a normal restart doesn't false-alarm.
    Alerts once per outage via the bot API (independent HTTP; works with the poller
    down). Returns (alerted_flag, dead_since)."""
    alive = poller_alive()
    if alive is None:
        return bool(state.get("poller_alerted")), state.get("poller_dead_since")
    if alive:
        if state.get("poller_alerted"):
            log("bot poller back up — re-arming poller-down alert")
        return False, None
    dead_since = state.get("poller_dead_since") or now
    already = bool(state.get("poller_alerted"))
    if not already and (now - dead_since) >= POLLER_DOWN_SECS:
        token, chats = load_token(), load_chats()
        msg = ("🛑 Telegram bot poller is DOWN — the bridge process isn't running, so "
               "no messages are being received or logged right now. Restart it: "
               "/reload-plugins in the hub (or relaunch ~/dev/crew/hub).")
        ok = all(send(token, c, msg) for c in chats) if chats else False
        log(f"POLLER-DOWN alert sent (dead ~{(now-dead_since)/60:.0f}m), ok={ok}")
        return True, dead_since
    return already, dead_since


def main():
    now = time.time()

    if "--preview" in sys.argv:
        # Dry run: show the message each currently-idle session WOULD produce.
        # Sends nothing, writes no state.
        for s in get_sessions() or []:
            if s["status"] != "idle" or s["name"] in EXCLUDE_NAMES:
                continue
            tpath = transcript_path(s.get("cwd"), s["sessionId"])
            proj  = os.path.basename(s.get("cwd", "")) or "?"
            lines = last_gist(tpath)
            head = f"✅ {s['name']} ({proj}) finished after Nm"
            parts = split_report(head, lines)
            print(f"\n{'=' * 60}")
            for i, m in enumerate(parts):
                print(f"--- msg {i + 1}/{len(parts)}  ({len(m)} chars) ---")
                print(m if m.strip() else "   (no gist found)")
            for p in find_artifacts(tpath, now - 6 * 3600):
                print(f"   📎 {p}")
        return

    if "--test" in sys.argv:
        token, chats = load_token(), load_chats()
        ok = all(send(token, c, "🔔 crew-pinger test — alerts are wired.") for c in chats)
        log(f"test message sent to {chats}: ok={ok}")
        print("test sent, ok=", ok, "chats=", chats)
        return

    state = load_state()
    tunnel_alerted = check_tunnel(now, state)                     # inbound queued-but-undelivered
    poller_alerted, poller_dead_since = check_poller(now, state)  # bridge process dead

    sessions = get_sessions()
    if sessions is None:
        # persist the alert flags; leave the fleet snapshot untouched
        state["tunnel_alerted"] = tunnel_alerted
        state["poller_alerted"] = poller_alerted
        state["poller_dead_since"] = poller_dead_since
        state["updated"] = now
        save_state(state)
        return  # transient; launchd will retry next interval

    prev  = state.get("sessions", {})
    first_run = not state.get("initialized")

    events, new = [], {}
    for s in sessions:
        sid, name, status = s["sessionId"], s["name"], s["status"]
        proj = os.path.basename(s.get("cwd", "")) or "?"
        p = prev.get(sid, {})

        if status == "busy":
            busy_since = p.get("busy_since") if p.get("status") == "busy" and p.get("busy_since") else now
            notified   = bool(p.get("notified_stuck"))
            if (NOTIFY_STUCK and not notified and not first_run
                    and name not in EXCLUDE_NAMES
                    and (now - busy_since) >= STUCK_HOURS * 3600):
                if not at_prompt_via_crew(name):
                    # Not hung if it's sitting at an empty prompt — that's a
                    # background shell holding the flag, not a stalled turn.
                    events.append(("⏳", name, proj, f"busy {(now-busy_since)/3600:.1f}h — may be hung", [], []))
                    notified = True

            # A session with a live background task NEVER returns to idle, so
            # the busy->idle edge below never fires for it. orrery ran a
            # persistent monitor and went 57 hours without a single "finished"
            # ping while producing constantly (2026-08-06) — kaolin had to ask
            # twice before any of it reached him. So detect the turn ending on
            # the screen instead: an empty prompt plus new transcript output.
            tpath  = transcript_path(s.get("cwd"), sid)
            nlines = transcript_lines(tpath)
            seen   = p.get("reported_lines")
            since  = p.get("last_report") or busy_since
            if seen is None:
                # First sight: arm, don't fire. Stamp `since` to now rather than
                # busy_since, or the first report would claim the whole busy
                # episode as its duration ("finished after 3400m").
                seen, since = nlines, now
            elif (NOTIFY_FINISHED and not first_run
                    and name not in EXCLUDE_NAMES
                    and nlines > seen
                    and (now - since) >= MIN_FINISHED_SECS
                    # Screen check last: it shells out, so only pay for it once
                    # we already know there is something new to report.
                    and at_prompt_via_crew(name)):
                gist  = last_gist(tpath)
                sig   = report_sig(gist)
                prev_sig = p.get("last_sig")
                quiet = (now - (p.get("last_sent") or 0)) >= SAME_REPORT_QUIET
                if same_news(sig, prev_sig) and not quiet:
                    # Same news as last time — a monitor re-reporting no change.
                    # Advance the markers so it stays quiet until something
                    # actually differs, but don't spend a message on it.
                    seen, since = nlines, now
                    last_sig, last_sent = prev_sig, p.get("last_sent")
                else:
                    shots = find_artifacts(tpath, since) if SEND_PHOTOS else []
                    events.append(("✅", name, proj,
                                   f"finished after {(now - since) / 60:.0f}m (bg task still running)",
                                   gist, shots))
                    seen, since = nlines, now
                    last_sig, last_sent = sig, now
            new[sid] = {"name": name, "cwd": s.get("cwd"), "status": status,
                        "busy_since": busy_since, "notified_stuck": notified,
                        "reported_lines": seen, "last_report": since,
                        "last_sig": locals().get("last_sig", p.get("last_sig")),
                        "last_sent": locals().get("last_sent", p.get("last_sent"))}
        elif status == "waiting":
            # NOT finished — it's blocked ON KAOLIN and will sit there forever.
            # This used to fall through to the idle branch and get reported as
            # "✅ finished", which is how orrery lost 1h40m (kaolin, 2026-07-31).
            tpath = transcript_path(s.get("cwd"), sid)
            pend = pending_prompt(tpath) if NOTIFY_WAITING else None
            notified = bool(p.get("notified_waiting"))
            if (NOTIFY_WAITING and not notified and not first_run
                    and name not in EXCLUDE_NAMES):
                detail = pend[1] if pend else ""
                extra = pending_via_crew(name)      # sees screen-only prompts
                if not detail and extra:
                    detail = "\n".join(extra)
                    if any(k in detail for k in ("Enter to select", "1.")):
                        pend = ("question", detail)
                if pend and pend[0] == "question":
                    glyph, what = "🙋", "needs your answer"
                else:
                    glyph, what = "🔐", "blocked on a permission prompt"
                body = _clean(detail) if detail else [(False, "run: crew pending")]
                events.append((glyph, name, proj, what, body, []))
                notified = True
            new[sid] = {"name": name, "cwd": s.get("cwd"), "status": status,
                        "busy_since": p.get("busy_since"), "notified_stuck": False,
                        "notified_waiting": notified}
        else:  # idle
            if (NOTIFY_FINISHED and not first_run
                    and name not in EXCLUDE_NAMES
                    and p.get("status") == "busy" and p.get("busy_since")
                    and (now - p["busy_since"]) >= MIN_FINISHED_SECS):
                mins = (now - p["busy_since"]) / 60
                tpath = transcript_path(s.get("cwd"), sid)
                lines = last_gist(tpath)
                shots = find_artifacts(tpath, p["busy_since"]) if SEND_PHOTOS else []
                events.append(("✅", name, proj, f"finished after {mins:.0f}m", lines, shots))
            new[sid] = {"name": name, "cwd": s.get("cwd"), "status": status,
                        "busy_since": None, "notified_stuck": False,
                        "notified_waiting": False,
                        # keep the screen-based path in step, so a session that
                        # picks up a background task next turn doesn't re-report
                        # everything it already sent from the idle edge
                        "reported_lines": transcript_lines(
                            transcript_path(s.get("cwd"), sid)),
                        "last_report": now}

    save_state({"initialized": True, "updated": now, "sessions": new,
                "tunnel_alerted": tunnel_alerted,
                "poller_alerted": poller_alerted,
                "poller_dead_since": poller_dead_since})

    if events and not in_quiet_hours(now):
        token, chats = load_token(), load_chats()
        stamp = time.strftime("%H:%M", time.localtime(now))
        nshots = 0
        for c in chats:
            # One message PER APP (not one batched "crew" blob), each self-headed
            # with source + a visible timestamp: "✅ babypaints-08 (BabyPaints) · 08:15 · finished…"
            for kind, name, proj, extra, lines, ps in events:
                head_plain = f"{kind} {name} ({proj}) · {stamp} · {extra}"
                head_md = f"{kind} *{md_escape(name)}* \\({md_escape(proj)}\\) · {md_escape(stamp)} · {md_escape(extra)}"
                send_chunked(token, c,
                             split_report(head_md, lines, escape=True),
                             split_report(head_plain, lines),
                             header="", prepacked=True)
                for p in ps:
                    send_photo(token, c, p, head_plain)
                    nshots += 1
        log(f"sent {len(events)} per-app msg(s), {nshots} photo(s) to {len(chats)} chat(s): "
            f"{[n for _, n, _, _, _, _ in events]}")
    else:
        log(f"tick ok: {len(sessions)} sessions, {len(events)} event(s), "
            f"{'quiet' if in_quiet_hours(now) else 'no send'}"
            f"{' (seeded)' if first_run else ''}")


if __name__ == "__main__":
    main()
