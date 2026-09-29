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
# printf, not echo: echo's trailing newline is outside [A-Za-z0-9], so `tr` turned
# it into a '_' and every log was really fast-approve-<name>_.log. That is not
# cosmetic -- the hub looked for the un-suffixed name, found nothing, and reported
# an approver's log as empty when it was several hundred lines long (2026-09-29).
LOG=/Users/kaolin/.crew/hub/fast-approve-$(printf '%s' "$NAME" | tr -c 'A-Za-z0-9' '_').log
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
# THE SPACES IN A PROMPT'S QUESTION LINE ARE NUL BYTES, NOT SPACES.
# Claude Code's TUI renders them as spaces, and `tail` shows them as spaces, but
# the captured stream holds e.g.  D o \0 y o u \0 w a n t ...  So every pattern
# written with ordinary spaces -- "Do you want to proceed", "Do you want to make
# this edit to" -- silently failed to match, while single words like "want" hit.
# That is the real cause of the UNRECOGNIZED storms on 2026-09-28/29 (217 in a row
# on one session), which I first misdiagnosed as AppleScript contention. Note the
# SURROUNDING lines have real spaces, which is why "Claude in Chrome wants to" kept
# working and made the failure look intermittent and session-specific.
# TRANSLATING NUL->space (not deleting: deleting joins the words into one
# run-on string) repairs every screen-path branch at once.
screen_of() { "$CREW" peek "$1" --screen --lines 30 2>/dev/null | tr '\000' ' '; }

escalate_once() {   # $1=sig $2=message
  [ "$esc_sig" = "$1" ] && return
  esc_sig="$1"
  "$CREW" escalate --no-push "$NAME" "$2" >/dev/null 2>&1
  echo "$(date +%H:%M:%S) ESCALATED: $2" >> "$LOG"
}

# A destructive-looking prompt is a human's call, not ours -- but the four
# branches below used to `exit 3` after escalating, which killed the WHOLE watch.
# So the one prompt reached a human and every ORDINARY prompt after it went
# unattended (alethe, 2026-09-29: died this way twice in one morning; overnight
# 2026-09-28 four sessions sat blocked with no approver at all). Note the
# `question` branch never did this -- it escalates and keeps looping -- and that
# asymmetry was the bug.
#
# Holding is strictly safer than exiting and loosens nothing: escalate_once has
# already fired for this signature and won't repeat, and no key is ever pressed
# on this prompt because every destructive branch returns before `approve`. When
# a human resolves it the session leaves `waiting`, the top of the loop clears
# esc_sig, and full service resumes by itself.
#
# 30s rather than the loop's 4-6: while we're parked on a prompt nobody but a
# human can clear, each probe is an AppleScript round-trip costing 10-20s with
# the screen locked, and there is nothing to be gained by asking sooner.
hold_for_human() { sleep 30; }

# docker compose's `--force-recreate` is not a destructive `--force`. It rebuilds
# containers, which is ordinary dev work, and on 2026-09-29 it stalled alethe
# twice while the flag was merely STRING CONTENT inside a bin/revive rewrite --
# text being edited, not a command being run. With the watch now holding instead
# of exiting, each false positive costs a session ~25 minutes waiting for the
# hub's next tick, so a recurring one is a real drag on the work.
#
# Scrub that ONE token before testing, leaving `--force` to catch everything
# else. Every exemption here has to be earned by an observed false positive --
# do not add flags speculatively, and never scrub a bare `--force`.
is_destructive() {
  printf '%s' "$1" | sed 's/--force-recreate/FORCE_RECREATE_OK/g' | grep -qiE "$DESTRUCTIVE"
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
      if is_destructive "$detail"; then
        echo "$(date +%H:%M:%S) STOP destructive-looking: $detail" >> "$LOG"
        escalate_once "$sig" "destructive-looking prompt needs your call: $(printf '%s' "$detail" | cut -c1-160)"
        hold_for_human; continue
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
      elif printf '%s' "$scr" | grep -q "Do you want to allow Claude to fetch this content"; then
        # A WebFetch prompt. Unknown to the reviewed script, so it fell through to
        # UNRECOGNIZED -- 217 times on the nandgame session on 2026-09-29 while it
        # did web research, which is most of what that session exists to do.
        # A fetch is READ-ONLY: it retrieves a URL and summarises it. That is
        # strictly less powerful than the arbitrary Bash this script already
        # auto-approves. The URL is on screen, so the destructive check below
        # still sees it.
        cmd=$(printf '%s' "$scr" | grep -oE 'https?://[^ ]+' | head -1)
        if is_destructive "$scr"; then
          echo "$(date +%H:%M:%S) STOP destructive-looking fetch: $cmd" >> "$LOG"
          escalate_once "$sig" "a fetch prompt looks destructive, needs your call: $cmd"
          hold_for_human; continue
        fi
        approve "enter" "$sig" "web-fetch" "$cmd"
      elif printf '%s' "$scr" | grep -q "Do you want to make this edit to"; then
        # A FILE-EDIT prompt. The reviewed script knows nothing about this shape,
        # so it fell through to UNRECOGNIZED and escalated -- six times on
        # erif-html-f3 on 2026-09-28 while it did ordinary CSS work in its own
        # worktree. Approving an edit is strictly LESS powerful than the arbitrary
        # Bash this script already auto-approves, so recognising it is not a
        # loosening. The destructive pattern is still applied, to the diff text:
        # a diff is not a command, so this can only false-POSITIVE (refuse), which
        # is the safe direction.
        cmd=$(printf '%s' "$scr" | grep -o 'Do you want to make this edit to.*' | head -1)
        if is_destructive "$scr"; then
          echo "$(date +%H:%M:%S) STOP destructive-looking text in an edit: $cmd" >> "$LOG"
          escalate_once "$sig" "an edit whose diff looks destructive needs your call: $cmd"
          hold_for_human; continue
        fi
        approve "enter" "$sig" "file-edit" "$cmd"
      elif printf '%s' "$scr" | grep -q "Do you want to proceed"; then
        cmd=$(printf '%s' "$scr" | grep '│' | sed 's/^[[:space:]]*│//' | tr '\n' ' ')
        if is_destructive "$cmd"; then
          echo "$(date +%H:%M:%S) STOP destructive-looking (screen): $cmd" >> "$LOG"
          escalate_once "$sig" "destructive-looking prompt (screen) needs your call: $(printf '%s' "$cmd" | cut -c1-160)"
          hold_for_human; continue
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
