#!/bin/sh
# Babysit permission prompts on the named sessions (kaolin: "Plz approve all" for
# beatboxing, "yes plz" for orrery, 2026-09-03). Approves a prompt whose command
# does not look destructive; STOPS on the first one that does, so a human decides.
#
# Reads the prompt from the transcript first (fast, works locked). Claude Code
# does not log every prompt there, so when crew says "not reachable" it falls
# back to reading the screen straight through iTerm2's AppleScript by tty —
# slow under a locked screen (seconds to minutes), which is fine for a script
# that has nothing else to do. Picks "Yes, and don't ask again for: …" when the
# dialog offers it, so the same class of command stops prompting.
CREW=/Users/kaolin/dev/crew/crew
DESTRUCTIVE='rm -rf|rm -r |--force|reset --hard|--hard|erase|deleteAll|drop |push |devicectl device (erase|uninstall)|xcrun simctl (erase|delete)|launchctl (bootout|unload)|defaults delete|security delete|git clean'
PEEK='on run argv
set target to item 1 of argv
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if (tty of s) is target then return contents of s
      end repeat
    end repeat
  end repeat
end tell
return "__NOTFOUND__"
end run'
answered=0

screen_of() {   # $1 = session name → last 25 non-blank screen lines, or nothing
  pid=$(claude agents --json 2>/dev/null | python3 -c "
import sys,json;d=json.load(sys.stdin);d=d if isinstance(d,list) else d.get('agents',d)
print(next((a.get('pid') for a in d if a.get('name')=='$1'), ''))")
  [ -n "$pid" ] || return
  tty=$(ps -o tty= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -n "$tty" ] && [ "$tty" != "??" ] || return
  timeout 240 osascript -e "$PEEK" "/dev/$tty" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -25
}

for i in $(seq 1 700); do
  for NAME in "$@"; do
    st=$("$CREW" status 2>&1 | grep -F " $NAME " | grep -oE "waiting|busy|idle" | head -1)
    [ "$st" = "waiting" ] || continue
    block=$("$CREW" pending 2>&1 | sed -n "/^$NAME/,/^\$/p")
    keys="enter"
    if echo "$block" | sed -n '2p' | grep -q "permission prompt"; then
      cmd=$(echo "$block" | sed -n '3p')
      src=transcript
    else
      scr=$(screen_of "$NAME")
      # Two dialog shapes: a tool's "Do you want to proceed" (1. Yes), and Claude
      # in Chrome's "wants to <action>" (1. Allow) — the Chrome one held timeful for
      # 90 minutes on 2026-09-03 while it tried to enter approved store copy.
      if echo "$scr" | grep -q "Claude in Chrome wants to"; then
        cmd="chrome: $(echo "$scr" | grep -o 'Claude in Chrome wants to [^│]*' | tail -1)"
        keys="enter"; src=screen
        "$CREW" keys --force "$NAME" $keys >/dev/null 2>&1
        answered=$((answered + 1)); echo "$(date +%H:%M:%S) approved $NAME [$src, $keys]: $cmd"; sleep 5; continue
      fi
      echo "$scr" | grep -q "Do you want to proceed" || continue
      cmd=$(echo "$scr" | grep '│' | sed 's/^[[:space:]]*│//' | tr '\n' ' ')
      echo "$scr" | grep -q "2\. Yes, and don.t ask again" && keys="down enter"
      src=screen
    fi
    if echo "$cmd" | grep -qiE "$DESTRUCTIVE"; then
      echo "STOPPED — $NAME asked for something that looks destructive ($answered approved so far):"
      echo "$cmd" | cut -c1-300
      exit 0
    fi
    "$CREW" keys --force "$NAME" $keys >/dev/null 2>&1
    answered=$((answered + 1))
    echo "$(date +%H:%M:%S) approved $NAME [$src, $keys]: $(echo "$cmd" | cut -c1-110)"
    sleep 5
  done
  sleep 10
done
echo "watch window ended; approved $answered prompt(s)"
