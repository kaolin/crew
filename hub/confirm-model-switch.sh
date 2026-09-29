#!/bin/sh
# For each session: if its screen shows the "Switch model?" dialog, press Enter
# (option 1 "Yes, switch" is preselected), then confirm "Set model" appeared.
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH
CREW=/Users/kaolin/dev/crew/crew
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
screen_of() {
  pid=$(claude agents --json 2>/dev/null | python3 -c "
import sys,json;d=json.load(sys.stdin);d=d if isinstance(d,list) else d.get('agents',d)
print(next((a.get('pid') for a in d if a.get('name')=='$1'), ''))")
  [ -n "$pid" ] || return
  tty=$(ps -o tty= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -n "$tty" ] && [ "$tty" != "??" ] || return
  timeout 120 osascript -e "$PEEK" "/dev/$tty" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -30
}
for NAME in "$@"; do
  scr=$(screen_of "$NAME")
  if echo "$scr" | grep -q "Switch model?"; then
    "$CREW" keys --force "$NAME" $'\r' >/dev/null 2>&1
    sleep 4
    scr2=$(screen_of "$NAME")
    if echo "$scr2" | grep -q "Set model to Opus"; then echo "$NAME: switched (confirmed)"; else echo "$NAME: pressed Enter, not yet confirmed"; fi
  elif echo "$scr" | grep -q "Set model to Opus"; then
    echo "$NAME: already switched"
  else
    echo "$NAME: no dialog, no confirmation visible"
  fi
done
