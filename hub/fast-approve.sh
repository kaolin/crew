#!/bin/sh
# fast-approve.sh — fast approver for Chrome-consent-heavy console work, for a
# bounded window. FIXED copy for the 2026-09-24 review (fixes #1, #2, #10). The
# hub swaps this in deliberately.
#
# WHAT CHANGED vs the live script:
#  #2  THE CRITICAL ONE. The live else-branch pressed `crew keys --force enter`
#      for ANY waiting session whose `crew pending` line-2 wasn't "permission
#      prompt" — WITHOUT ever looking at the screen. An AskUserQuestion
#      ("QUESTION FOR YOU") fell into that branch and its option 1 was submitted
#      as kaolin's answer. This version NEVER presses Enter on the no-transcript
#      path without positively confirming a permission / Claude-in-Chrome dialog
#      on the actual screen, and treats a question (picker chrome) as human-only.
#  #1  Uses `crew pending --json` (structured kind, no prose grep / sed regex),
#      CHECKS the `crew keys` exit code, VERIFIES the session left `waiting`
#      before counting an approval, and ESCALATES (crew escalate) after MAXFAIL
#      non-clears on the same prompt instead of looping silently.
#  #10 Case-INSENSITIVE, broadened shared destructive pattern (was `grep -Eq`
#      with no -i, so it auto-approved `RESET --HARD`, `Git Push`).
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:$PATH
CREW=/Users/kaolin/dev/crew/crew
NAME="$1"; MINUTES="${2:-25}"
LOG=/Users/kaolin/.crew/hub/fast-approve-$(echo "$NAME" | tr -c 'A-Za-z0-9' '_').log
MAXFAIL=3

DESTRUCTIVE='rm +-[rf]|--force|force-with-lease|reset +--hard|--hard|git +clean|git +checkout +--|git +restore|erase|deleteall|drop +table|truncate|git +push|push +origin|push +-|devicectl device (erase|uninstall)|xcrun simctl (erase|delete)|launchctl (bootout|unload)|defaults +delete|security +delete|shutdown|reboot|diskutil|mkfs|dd +if=|dd +of=|(^|[^a-z])sudo '

fail=0; esc_sig=""; n=0
end=$(( $(date +%s) + MINUTES*60 ))

classify() {
  "$CREW" pending "$1" --json 2>/dev/null | python3 -c '
import sys, json
try:
    recs = json.load(sys.stdin)
except Exception:
    recs = []
name = sys.argv[1]
r = next((x for x in recs if x.get("name") == name), recs[0] if recs else None)
if not r:
    print("none"); print(""); sys.exit()
kind = r.get("kind") or "null"
det = (r.get("detail") or "")
if r.get("options"):
    det = det + " | " + " / ".join(o for o in r["options"] if o)
print(kind)
print(" ".join(det.split())[:400])
' "$1"
}
screen_of() { "$CREW" peek "$1" --screen --lines 30 2>/dev/null; }

escalate_once() {   # $1=sig $2=message
  [ "$esc_sig" = "$1" ] && return
  esc_sig="$1"
  "$CREW" escalate "$NAME" "$2" >/dev/null 2>&1
  echo "$(date +%H:%M:%S) ESCALATED: $2" >> "$LOG"
}

approve() {   # $1=keys $2=sig $3=label $4=cmd-for-log
  if "$CREW" keys --force "$NAME" $1 >/dev/null 2>&1; then
    sleep 4
    st=$("$CREW" status 2>&1 | grep -F " $NAME " | grep -oE "waiting|busy|idle" | head -1)
    if [ "$st" = "waiting" ]; then
      nkd=$(classify "$NAME"); nsig="$(printf '%s\n' "$nkd" | sed -n 1p)|$(printf '%s\n' "$nkd" | sed -n 2p)"
      if [ "$nsig" = "$2" ]; then
        fail=$((fail+1)); echo "$(date +%H:%M:%S) NO-CLEAR($fail/$MAXFAIL) [$3]: still waiting on same prompt" >> "$LOG"
        [ "$fail" -ge "$MAXFAIL" ] && escalate_once "$2" "approved $MAXFAIL times but prompt won't clear — keystrokes not landing?"
        return
      fi
    fi
    fail=0; n=$((n+1)); echo "$(date +%H:%M:%S) approved [$3]: $(printf '%s' "$4" | cut -c1-140)" >> "$LOG"
  else
    rc=$?; fail=$((fail+1)); echo "$(date +%H:%M:%S) SEND-FAIL($fail/$MAXFAIL rc=$rc) [$3]: crew keys did not deliver" >> "$LOG"
    [ "$fail" -ge "$MAXFAIL" ] && escalate_once "$2" "can't deliver keystrokes ($MAXFAIL tries, rc=$rc) — session unreachable"
  fi
}

while [ "$(date +%s)" -lt "$end" ]; do
  st=$("$CREW" status 2>&1 | grep -F " $NAME " | grep -oE "waiting|busy|idle" | head -1)
  if [ "$st" != "waiting" ]; then
    fail=0; esc_sig=""; sleep 6; continue
  fi
  kd=$(classify "$NAME"); kind=$(printf '%s\n' "$kd" | sed -n 1p)
  detail=$(printf '%s\n' "$kd" | sed -n 2p); sig="$kind|$detail"

  case "$kind" in
    question)
      escalate_once "$sig" "question needs your answer: $detail"
      echo "$(date +%H:%M:%S) HUMAN-ONLY (question): $detail" >> "$LOG"
      ;;
    permission)
      if printf '%s' "$detail" | grep -qiE "$DESTRUCTIVE"; then
        echo "$(date +%H:%M:%S) STOP destructive-looking: $detail" >> "$LOG"
        escalate_once "$sig" "destructive-looking prompt needs your call: $(printf '%s' "$detail" | cut -c1-160)"
        exit 3
      fi
      keys=enter
      scr=$(screen_of "$NAME"); printf '%s' "$scr" | grep -qi "2\. *Yes, and don.t ask again" && keys="down enter"
      approve "$keys" "$sig" "transcript" "$detail"
      ;;
    *)
      # kind = null: NEVER Enter blind (#2). Confirm the dialog on screen.
      scr=$(screen_of "$NAME")
      if printf '%s' "$scr" | grep -q "Claude in Chrome wants to"; then
        approve "enter" "$sig" "chrome-consent" "$(printf '%s' "$scr" | grep -o 'Claude in Chrome wants to [^│]*' | tail -1)"
      elif printf '%s' "$scr" | grep -q "Do you want to proceed"; then
        cmd=$(printf '%s' "$scr" | grep '│' | sed 's/^[[:space:]]*│//' | tr '\n' ' ')
        if printf '%s' "$cmd" | grep -qiE "$DESTRUCTIVE"; then
          echo "$(date +%H:%M:%S) STOP destructive-looking (screen): $cmd" >> "$LOG"
          escalate_once "$sig" "destructive-looking prompt (screen) needs your call: $(printf '%s' "$cmd" | cut -c1-160)"
          exit 3
        fi
        keys=enter; printf '%s' "$scr" | grep -qi "2\. *Yes, and don.t ask again" && keys="down enter"
        approve "$keys" "$sig" "screen" "$cmd"
      elif printf '%s' "$scr" | grep -qE "↑/↓ to navigate|Enter to select"; then
        escalate_once "$sig" "question/selection on screen needs you"
        echo "$(date +%H:%M:%S) HUMAN-ONLY (screen picker); not pressing Enter" >> "$LOG"
      else
        fail=$((fail+1)); echo "$(date +%H:%M:%S) UNRECOGNIZED($fail/$MAXFAIL); not pressing Enter" >> "$LOG"
        [ "$fail" -ge "$MAXFAIL" ] && escalate_once "$sig" "waiting on an unrecognized prompt shape — needs you"
      fi
      ;;
  esac
  sleep 4
done
echo "$(date +%H:%M:%S) window ended; approved $n" >> "$LOG"
