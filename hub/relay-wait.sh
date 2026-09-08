#!/bin/bash
# usage: relay-wait.sh <session-name> <ProjectDirBasename> <transcript-dir> <needle> <message>
# Waits for the session to be idle, tells it ONE line, verifies the needle in its transcript.
C=/Users/kaolin/dev/crew/crew; NAME="$1"; PROJ="$2"; TDIR="$3"; NEEDLE="$4"; MSG="$5"
for i in $(seq 1 240); do
  st=$($C status 2>/dev/null | grep -A1 "^  $PROJ" | grep -oi "idle\|busy" | head -1)
  if [ "$st" = "idle" ]; then
    if $C tell "$NAME" "$MSG"; then
      sleep 10
      n=$(cat "$TDIR"/*.jsonl 2>/dev/null | grep -c -- "$NEEDLE")
      echo "landed: $n"
      [ "$n" -gt 0 ] && exit 0
      echo "not landed, retrying"
    else
      echo "tell failed, retrying"
    fi
  fi
  sleep 30
done
echo "gave up"; exit 1
