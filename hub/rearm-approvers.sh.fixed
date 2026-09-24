#!/bin/sh
# rearm-approvers.sh — ensure exactly one watch-approve2.sh instance per covered session.
# FIXED copy for the 2026-09-24 review (fix #11). The hub swaps this in deliberately.
#
# WHY THIS EXISTS: the old inline heartbeat check `grep -qv grep` returns exit 1
# (== "missing") even when procs ARE present on macOS/BSD grep, so every heartbeat
# stacked another ~11 procs (seen: 100+ dupes, 2026-09-14). And `pgrep -f "... [claude] X"`
# never matches because [claude] is a regex char class. This script uses the ONLY
# reliable form: fixed-string, and kills by PID (never pkill on a name with [claude]).
#
# WHAT CHANGED (#11): count_for used `grep -F "watch-approve2.sh $1"`, a PREFIX
# match — the watcher for "[claude] izzit" also matched the process line for
# "[claude] izzit-site-wild" (and "timeful" matched "timeful-99"), so the
# shorter name read as armed when it was NOT and never got its own watcher.
# Now it strips everything up to and including "watch-approve2.sh " and matches
# the remaining name argument EXACTLY (grep -Fxc), so siblings can't collide.
#
# Usage:
#   rearm-approvers.sh              # arm one per name in approver-covered.txt if absent
#   rearm-approvers.sh --reset      # kill ALL watch-approve2.sh, then arm one per name
#   rearm-approvers.sh --count      # just print the per-name process count and exit

HUB="/Users/kaolin/.crew/hub"
LIST="$HUB/approver-covered.txt"
WATCH="$HUB/watch-approve2.sh"

count_for() {  # $1 = name; prints number of live procs whose trailing arg is EXACTLY $1
  ps -axo command= \
    | sed -n 's#.*watch-approve2\.sh ##p' \
    | grep -Fxc -- "$1"
}

if [ "$1" = "--count" ]; then
  ps -axo command= | grep -F "watch-approve2.sh" | grep -v grep \
    | sed -E 's/.*watch-approve2\.sh //' | sort | uniq -c
  echo "total: $(ps -axo command= | grep -F watch-approve2.sh | grep -vc grep)"
  exit 0
fi

if [ "$1" = "--reset" ]; then
  pkill -f watch-approve2.sh
  sleep 2   # let them die before re-arming
fi

while IFS= read -r n; do
  [ -z "$n" ] && continue
  cnt=$(count_for "$n")
  if [ "$cnt" -gt 0 ]; then
    echo "present($cnt): $n"
  else
    (nohup "$WATCH" "$n" >/dev/null 2>&1 &)
    echo "armed: $n"
  fi
done < "$LIST"
