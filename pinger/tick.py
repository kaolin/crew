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
import calendar, json, os, re, subprocess, sys, time, urllib.request, urllib.parse

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
MIN_FINISHED_SECS = 120        # only ping "finished" for busy episodes >= this
STUCK_HOURS       = 3.0        # busy this long with no change -> "may be hung"
EXCLUDE_NAMES     = {"hub"}     # sessions to never ping about (the hub itself)
QUIET_HOURS       = None       # e.g. (23, 8) to mute 23:00-08:00 local; None = off
TUNNEL_STALL_SECS = 120        # inbound queued-but-undelivered longer than this -> tunnel is down
POLLER_DOWN_SECS  = 180        # bot poller process dead this long -> whole bridge down (rides out a brief restart)

# "finished" alerts carry WHAT finished, plus any images the session just made.
# A bare "✅ done after 12m" is meaningless on a phone (kaolin, 2026-07-20).
GIST_CHARS        = 3500      # max chars of the closing message (chunker splits if needed)
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


def send_chunked(token, chat, blocks_md, blocks_plain, header="🔔 crew"):
    """Send MarkdownV2 blocks; if the first message is rejected (an escaping bug
    would 400), fall back to plain text for the whole batch so a formatting
    error degrades gracefully instead of dropping the report (kaolin wants
    bulleted/bold, 2026-07-23). Pass header="" for a self-headed (per-app) message."""
    md = pack(blocks_md, header)
    for i, m in enumerate(md):
        if send(token, chat, m, parse_mode="MarkdownV2"):
            continue
        if i == 0:                                     # bad markup → plain for all
            log("markdownv2 send rejected; falling back to plain")
            ok = True
            for pm in pack(blocks_plain, header):
                ok = send(token, chat, pm) and ok
            return ok
        send(token, chat, m)                           # later msg: retry unformatted
    return True


def transcript_path(cwd, session_id):
    enc = (cwd or "").replace("/", "-")
    return f"{HOME}/.claude/projects/{enc}/{session_id}.jsonl"


def _clean(text):
    """Assistant message → clean lines, list items marked with '• '. Returns a
    list of (is_bullet, text) so callers can render plain or MarkdownV2."""
    out = []
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith(("```", "|", ">")):
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
            print(f"\n✅ {s['name']} ({proj}) finished after Nm")
            print(render_plain("", lines) or "   (no gist found)")
            print("  --- markdownv2 ---")
            print(render_md("", lines))
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
                events.append(("⏳", name, proj, f"busy {(now-busy_since)/3600:.1f}h — may be hung", [], []))
                notified = True
            new[sid] = {"name": name, "cwd": s.get("cwd"), "status": status,
                        "busy_since": busy_since, "notified_stuck": notified}
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
                        "busy_since": None, "notified_stuck": False}

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
                send_chunked(token, c, [render_md(head_md, lines)],
                             [render_plain(head_plain, lines)], header="")
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
