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
SLUG=$(printf '%s' "$NAME" | tr -c 'A-Za-z0-9' '_')
LOG=/Users/kaolin/.crew/hub/fast-approve-$SLUG.log
MAXFAIL=3

# ONE approver per session, enforced here rather than by whoever counts `ps`.
# On 2026-09-29 eight ran against nandgame, and two `down enter` sequences
# landing together picked "3. No", a rejection kaolin never made. The hub
# miscounted three different ways (PPID==1, parent command text, and matching
# its own prompt text). A lock makes the count irrelevant. mkdir is atomic.
# A lock left by a dead pid is taken over. Exit 4 means "already covered".
LOCK=/Users/kaolin/.crew/hub/fast-approve-$SLUG.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  other=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
    echo "approver for '$NAME' already running (pid $other); not starting a second" >&2
    exit 4
  fi
  rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null
  mkdir "$LOCK" 2>/dev/null || { echo "could not take $LOCK" >&2; exit 4; }
fi
echo $$ > "$LOCK/pid"
trap 'rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null' EXIT
trap 'exit 130' INT TERM HUP

DESTRUCTIVE='rm +-[rf]|--force|force-with-lease|reset +--hard|--hard|git +clean|git +checkout +--|git +restore|erase|deleteall|drop +table|truncate|git +push|push +origin|push +-|devicectl device (erase|uninstall)|xcrun simctl (erase|delete)|launchctl (bootout|unload)|defaults +delete|security +delete|shutdown|reboot|diskutil|mkfs|dd +if=|dd +of=|(^|[^a-z])sudo '

# One counter per failure kind. A single shared `fail` once escalated
# "approved 3 times but prompt won't clear" at NO-CLEAR(25/3): one real
# no-clear on top of 24 UNRECOGNIZED (nandgame, 2026-09-29 07:16). The alert
# named the wrong failure.
f_unrec=0; f_noclear=0; f_send=0; esc_sig=""; n=0
reset_fails() { f_unrec=0; f_noclear=0; f_send=0; }
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
# The same shape bit again at 16:56 the same day: headless Chrome's
# `--force-device-scale-factor=2`, in the render loop that is most of what the
# nandgame session exists to run. It sat escalated for 20 minutes.
#
# Scrub those tokens before testing, leaving `--force` to catch everything else.
# Every exemption here has to be earned by an OBSERVED false positive -- do not
# add flags speculatively, and never scrub a bare `--force`. Two entries is a
# list; if this reaches four or five, stop adding and reconsider the rule itself
# (matching `--force` only as a whole word would cover all of these at once, but
# it would also stop catching a destructive `--force-<something>` nobody has met
# yet, so it is a trade to make deliberately rather than by accretion).
is_destructive() {
  printf '%s' "$1" \
    | sed -e 's/--force-recreate/FORCE_RECREATE_OK/g' \
          -e 's/--force-device-scale-factor/FORCE_DSF_OK/g' \
    | grep -qiE "$DESTRUCTIVE"
}

# crew keys' own output is KEPT. It used to go to /dev/null, and on 2026-09-29/30
# that discarded "not reachable — window/pid moved" on 4,144 consecutive
# attempts against fusiontrainer. That line named the real fault (a --name
# parse bug in crew), and nobody saw it for 13 hours.
approve() {   # $1=keys $2=sig $3=label $4=cmd-for-log
  kout=$("$CREW" keys --force "$NAME" $1 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then
    sleep 4
    st=$("$CREW" status 2>&1 | grep -F " $NAME " | grep -oE "waiting|busy|idle" | head -1)
    if [ "$st" = "waiting" ]; then
      nkd=$(classify "$NAME"); nsig="$(printf '%s\n' "$nkd" | sed -n 1p)|$(printf '%s\n' "$nkd" | sed -n 2p)"
      if [ "$nsig" = "$2" ]; then
        f_noclear=$((f_noclear+1)); echo "$(date +%H:%M:%S) NO-CLEAR($f_noclear/$MAXFAIL) [$3]: still waiting on same prompt" >> "$LOG"
        [ "$f_noclear" -ge "$MAXFAIL" ] && escalate_once "$2" "approved $MAXFAIL times but prompt won't clear — keystrokes not landing?"
        return
      fi
    fi
    reset_fails; n=$((n+1)); echo "$(date +%H:%M:%S) approved [$3]: $(printf '%s' "$4" | cut -c1-140)" >> "$LOG"
  else
    why=$(printf '%s' "$kout" | tr '\n' ' ' | cut -c1-160)
    f_send=$((f_send+1)); echo "$(date +%H:%M:%S) SEND-FAIL($f_send/$MAXFAIL rc=$rc) [$3]: $why" >> "$LOG"
    [ "$f_send" -ge "$MAXFAIL" ] && escalate_once "$2" "can't deliver keystrokes ($MAXFAIL tries, rc=$rc): $why"
  fi
}

while [ "$(date +%s)" -lt "$end" ]; do
  st=$("$CREW" status 2>&1 | grep -F " $NAME " | grep -oE "waiting|busy|idle" | head -1)
  if [ "$st" != "waiting" ]; then
    reset_fails; esc_sig=""; sleep 6; continue
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
        f_unrec=$((f_unrec+1)); echo "$(date +%H:%M:%S) UNRECOGNIZED($f_unrec/$MAXFAIL); not pressing Enter" >> "$LOG"
        [ "$f_unrec" -ge "$MAXFAIL" ] && escalate_once "$sig" "waiting on an unrecognized prompt shape — needs you"
      fi
      ;;
  esac
  sleep 4
done
echo "$(date +%H:%M:%S) window ended; approved $n" >> "$LOG"
