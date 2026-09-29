#!/bin/bash
# fanout.sh <needle> <msgfile> [<needle2> <msgfile2>]  -- tells every non-hub session, sequential per session, parallel across sessions
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH
C=/Users/kaolin/dev/crew/crew
RW=/Users/kaolin/.crew/hub/relay-wait.sh
N1="$1"; M1=$(cat "$2"); N2="$3"; M2=""; [ -n "$4" ] && M2=$(cat "$4")
proj=""; path=""
while IFS= read -r line; do
  if [[ "$line" =~ ^\ \ ([A-Za-z0-9_.-]+)\ +(/Users/[^ ]+) ]]; then
    proj="${BASH_REMATCH[1]}"; path="${BASH_REMATCH[2]}"; continue
  fi
  if [[ "$line" =~ (idle|busy) ]] && [ -n "$proj" ]; then
    name=$(echo "$line" | sed -E 's/.*(idle|busy) +//; s/ +[0-9dhm]+ *$//; s/ +$//')
    [ "$name" = "hub" ] && { proj=""; continue; }
    tdir="/Users/kaolin/.claude/projects/$(echo "$path" | tr '/._' '---')"
    [ -d "$tdir" ] || echo "WARN no transcript dir for $name: $tdir"
    echo "queue: $name ($proj) $tdir"
    ( "$RW" "$name" "$proj" "$tdir" "$N1" "$M1" 2>&1 | sed "s/^/[$proj 1] /"
      if [ -n "$M2" ]; then sleep 20; "$RW" "$name" "$proj" "$tdir" "$N2" "$M2" 2>&1 | sed "s/^/[$proj 2] /"; fi ) &
    sleep 3
    proj=""
  fi
done < <($C status 2>/dev/null)
wait
echo "fan-out complete"
