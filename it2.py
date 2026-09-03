#!/usr/bin/env python3
"""it2 — crew's iTerm2 Python-API helper. Runs under conda base (the only python
with the `iterm2` package); crew shells out to it.

Why this exists (2026-09-03): with the login screen up, every Apple Event to
iTerm2 takes 4–60 s on macOS 26 (Tahoe's AppleScript regression), and crew's
AppleScript adapter costs one event per session just to find a tty. The Python
API is a websocket over a Unix socket — no Apple Events — and reads a screen in
about a second, locked or not. Its one AppleScript dependency is the login
cookie, so we mint one while the screen is unlocked and cache it.

    it2.py mint            # cookie+key via one Apple Event → ~/.crew/it2.ck
    it2.py ping            # exit 0 if the API answers within the budget
    it2.py peek <tty>      # screen contents of the session on that tty
    it2.py send <tty> <text> [--enter]   # type into that session
    it2.py list            # tty · name for every session

Exit codes: 0 ok · 2 no such tty · 3 could not connect (caller falls back) ·
4 cookie needed and none cached.
"""
import asyncio, os, subprocess, sys, time

HOME = os.path.expanduser("~")
CK_PATH = os.path.join(os.environ.get("CREW_HOME") or HOME, ".crew", "it2.ck")
CONNECT_BUDGET = float(os.environ.get("IT2_BUDGET", "6"))   # seconds; locked handshakes exceed this on purpose


def load_cookie():
    try:
        ck, ky = open(CK_PATH).read().split()[:2]
        os.environ.setdefault("ITERM2_COOKIE", ck)
        os.environ.setdefault("ITERM2_KEY", ky)
        return True
    except Exception:
        return False


def mint():
    """One Apple Event. Fast when unlocked; may take a minute when locked."""
    out = subprocess.run(["osascript", "-e",
                          'tell application "iTerm2" to request cookie and key for app named "crew"'],
                         capture_output=True, text=True, timeout=90).stdout.strip()
    if len(out.split()) < 2:
        print("mint failed:", out or "(no output)", file=sys.stderr)
        sys.exit(3)
    os.makedirs(os.path.dirname(CK_PATH), exist_ok=True)
    with open(CK_PATH, "w") as f:
        f.write(out + "\n")
    os.chmod(CK_PATH, 0o600)
    print("minted → " + CK_PATH)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "mint":
        return mint()
    have = load_cookie()
    try:
        import iterm2
    except ImportError:
        print("iterm2 module missing (pip install iterm2 in conda base)", file=sys.stderr)
        sys.exit(3)

    async def run(connection):
        app = await iterm2.async_get_app(connection)
        if cmd == "ping":
            print("ok"); return 0
        rows = []
        for w in app.terminal_windows:
            for t in w.tabs:
                for s in t.sessions:
                    rows.append(s)
        if cmd == "list":
            for s in rows:
                tty = await s.async_get_variable("tty")
                name = await s.async_get_variable("session.name")
                print(f"{tty}\t{name}")
            return 0
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        target = target if target.startswith("/dev/") else "/dev/" + target
        for s in rows:
            if await s.async_get_variable("tty") != target:
                continue
            if cmd == "peek":
                sc = await s.async_get_screen_contents()
                for i in range(sc.number_of_lines):
                    print(sc.line(i).string.rstrip())
                return 0
            if cmd == "send":
                text = sys.argv[3] if len(sys.argv) > 3 else ""
                if "--enter" in sys.argv[4:]:
                    text += "\r"
                await s.async_send_text(text, suppress_broadcast=True)
                print("sent")
                return 0
            print("unknown command", cmd, file=sys.stderr); return 1
        print("no session on", target, file=sys.stderr)
        return 2

    rc_holder = {"rc": 3}

    async def wrapped(connection):
        rc_holder["rc"] = await run(connection)

    async def with_budget():
        # iterm2.Connection.async_create does the cookie handshake if env is unset;
        # under a locked screen that is the slow path, so it gets a hard budget.
        conn = await asyncio.wait_for(iterm2.Connection.async_create(), CONNECT_BUDGET)
        await wrapped(conn)

    try:
        asyncio.run(with_budget())
    except asyncio.TimeoutError:
        print("could not connect within %.0fs%s" % (CONNECT_BUDGET, "" if have else " (no cached cookie — run `it2.py mint` while unlocked)"),
              file=sys.stderr)
        sys.exit(3 if have else 4)
    except Exception as e:  # noqa: BLE001
        print("connect failed:", str(e)[:200], file=sys.stderr)
        sys.exit(3)
    sys.exit(rc_holder["rc"])


if __name__ == "__main__":
    main()
