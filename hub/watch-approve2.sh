#!/bin/sh
# watch-approve2.sh — babysit permission prompts on the named sessions.
# FIXED copy for the 2026-09-24 review (fixes #1, #2, #10, #12). The hub swaps
# this in deliberately; it needs a restart of the watchers to take effect.
#
# WHAT CHANGED vs the live script:
#  #12  Classification now comes from `crew pending <name> --json` (crew's own
#       question/permission/null verdict), NOT `sed -n "/^$NAME/,/^$/p"` — the
#       old sed treated the literal name "[claude] BabyPaints" as a regex, so
#       "[claude]" is a character class and the block header never matched for
#       any [claude]-prefixed name; those names silently lost the transcript
#       fast-path AND its destructive check, hitting only the screen scrape.
#  #1   `crew keys` now returns a real exit code; we CHECK it, and we VERIFY the
#       session actually left `waiting` before counting an approval. After
#       MAXFAIL non-clears on the SAME still-waiting prompt we ESCALATE (crew
#       escalate → pinger queue + a direct Telegram push) instead of logging a
#       false "approved" forever. This is the fix for the 8h silent stall.
#  #2   A prompt crew can't classify (kind=null) is NEVER Enter'd blind. We
#       positively confirm a permission/Chrome dialog on the actual screen
#       first; an AskUserQuestion (picker chrome) is treated as human-only.
#  #10  One shared, case-INSENSITIVE destructive pattern (was case-sensitive in
#       fast-approve), broadened to cover git checkout/restore/reset, clean, dd,
#       redirection-to-file, disk tools, sudo, shutdown/reboot.
CREW=/Users/kaolin/dev/crew/crew
MAXFAIL=3          # consecutive non-clears on the same prompt before escalating

# ONE shared destructive pattern, matched case-insensitively (grep -qiE). If a
# command could delete, overwrite, force-push or erase, STOP for a human.
DESTRUCTIVE='rm +-[rf]|--force|force-with-lease|reset +--hard|--hard|git +clean|git +checkout +--|git +restore|erase|deleteall|drop +table|truncate|git +push|push +origin|push +-|devicectl device (erase|uninstall)|xcrun simctl (erase|delete)|launchctl (bootout|unload)|defaults +delete|security +delete|shutdown|reboot|diskutil|mkfs|dd +if=|dd +of=|(^|[^a-z])sudo '

STATE=$(mktemp -d "${TMPDIR:-/tmp}/wa2.XXXXXX")
trap 'rm -rf "$STATE"' EXIT INT TERM
answered=0

safe() { printf '%s' "$1" | tr -c 'A-Za-z0-9' '_'; }

# crew's structured verdict for a session: prints KIND on line 1, DETAIL on
# line 2. KIND is question | permission | null | none (none = not waiting).
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

# The live screen (works locked too — crew picks the it2 API adapter). Used
# only to confirm an unclassified (kind=null) prompt and to spot a
# "2. Yes, and don't ask again" option so the same class stops prompting.
screen_of() { "$CREW" peek "$1" --screen --lines 30 2>/dev/null; }

escalate_once() {   # $1=name $2=sig $3=message — page kaolin at most once per sig
  f="$STATE/$(safe "$1").esc"
  [ -f "$f" ] && [ "$(cat "$f")" = "$2" ] && return
  printf '%s' "$2" > "$f"
  "$CREW" escalate "$1" "$3" >/dev/null 2>&1
  echo "$(date +%H:%M:%S) ESCALATED $1: $3"
}

approve() {   # $1=name $2=keys $3=sig $3used-for-tracking $4=label $5=cmd-for-log
  name="$1"; keys="$2"; sig="$3"; label="$4"; cmd="$5"
  ff="$STATE/$(safe "$name").fail"
  if "$CREW" keys --force "$name" $keys >/dev/null 2>&1; then
    sleep 4
    # VERIFY it cleared: is it still waiting on the SAME prompt?
    st=$("$CREW" status 2>&1 | grep -F " $name " | grep -oE "waiting|busy|idle" | head -1)
    if [ "$st" = "waiting" ]; then
      nkd=$(classify "$name"); nk=$(printf '%s\n' "$nkd" | sed -n 1p)
      nd=$(printf '%s\n' "$nkd" | sed -n 2p); nsig="$nk|$nd"
      if [ "$nsig" = "$sig" ]; then          # keystroke did not clear it
        c=$(( $(cat "$ff" 2>/dev/null || echo 0) + 1 )); echo "$c" > "$ff"
        echo "$(date +%H:%M:%S) NO-CLEAR($c/$MAXFAIL) $name [$label]: keys sent, still waiting on same prompt"
        [ "$c" -ge "$MAXFAIL" ] && escalate_once "$name" "$sig" \
          "approved $MAXFAIL times but the prompt won't clear — keystrokes not landing (moved window / wrong session?)"
        return
      fi
    fi
    rm -f "$ff"; answered=$((answered + 1))
    echo "$(date +%H:%M:%S) approved $name [$label]: $(printf '%s' "$cmd" | cut -c1-110)"
  else
    rc=$?
    c=$(( $(cat "$ff" 2>/dev/null || echo 0) + 1 )); echo "$c" > "$ff"
    echo "$(date +%H:%M:%S) SEND-FAIL($c/$MAXFAIL rc=$rc) $name [$label]: crew keys did not deliver"
    [ "$c" -ge "$MAXFAIL" ] && escalate_once "$name" "$sig" \
      "can't deliver keystrokes ($MAXFAIL tries, crew keys rc=$rc) — session unreachable / window moved"
  fi
}

for i in $(seq 1 700); do
  for NAME in "$@"; do
    st=$("$CREW" status 2>&1 | grep -F " $NAME " | grep -oE "waiting|busy|idle" | head -1)
    if [ "$st" != "waiting" ]; then
      rm -f "$STATE/$(safe "$NAME").fail" "$STATE/$(safe "$NAME").esc"   # moved on; reset memory
      continue
    fi
    kd=$(classify "$NAME"); kind=$(printf '%s\n' "$kd" | sed -n 1p)
    detail=$(printf '%s\n' "$kd" | sed -n 2p); sig="$kind|$detail"

    case "$kind" in
      question)
        # An AskUserQuestion is FOR kaolin — anything typed becomes his answer.
        # Never touch it; page him once and leave it for a human.
        escalate_once "$NAME" "$sig" "question needs your answer: $detail"
        echo "$(date +%H:%M:%S) HUMAN-ONLY $NAME (question): $detail"
        ;;
      permission)
        if printf '%s' "$detail" | grep -qiE "$DESTRUCTIVE"; then
          echo "$(date +%H:%M:%S) STOPPED $NAME — destructive-looking ($answered approved so far): $detail"
          escalate_once "$NAME" "$sig" "destructive-looking prompt needs your call: $(printf '%s' "$detail" | cut -c1-160)"
          continue   # do not approve; leave it up for a human
        fi
        keys=enter
        # Prefer "Yes, and don't ask again" when the dialog offers it.
        scr=$(screen_of "$NAME")
        printf '%s' "$scr" | grep -qi "2\. *Yes, and don.t ask again" && keys="down enter"
        approve "$NAME" "$keys" "$sig" "permission" "$detail"
        ;;
      *)
        # kind = null: crew is sure it's waiting but can't classify from the
        # transcript. DO NOT press Enter blind (review #2). Confirm on-screen.
        scr=$(screen_of "$NAME")
        if printf '%s' "$scr" | grep -q "Claude in Chrome wants to"; then
          approve "$NAME" "enter" "$sig" "chrome-consent" \
            "$(printf '%s' "$scr" | grep -o 'Claude in Chrome wants to [^│]*' | tail -1)"
        elif printf '%s' "$scr" | grep -q "Do you want to proceed"; then
          cmd=$(printf '%s' "$scr" | grep '│' | sed 's/^[[:space:]]*│//' | tr '\n' ' ')
          if printf '%s' "$cmd" | grep -qiE "$DESTRUCTIVE"; then
            echo "$(date +%H:%M:%S) STOPPED $NAME — destructive-looking (screen): $cmd"
            escalate_once "$NAME" "$sig" "destructive-looking prompt (screen) needs your call: $(printf '%s' "$cmd" | cut -c1-160)"
            continue
          fi
          keys=enter
          printf '%s' "$scr" | grep -qi "2\. *Yes, and don.t ask again" && keys="down enter"
          approve "$NAME" "$keys" "$sig" "screen" "$cmd"
        elif printf '%s' "$scr" | grep -qE "↑/↓ to navigate|Enter to select"; then
          # picker chrome with no permission wording = an AskUserQuestion → human
          escalate_once "$NAME" "$sig" "question/selection on screen needs you: $(printf '%s' "$scr" | tail -6 | tr '\n' ' ' | cut -c1-160)"
          echo "$(date +%H:%M:%S) HUMAN-ONLY $NAME (screen picker)"
        else
          # Unrecognized prompt shape — count it, escalate after MAXFAIL. NEVER Enter.
          ff="$STATE/$(safe "$NAME").fail"
          c=$(( $(cat "$ff" 2>/dev/null || echo 0) + 1 )); echo "$c" > "$ff"
          echo "$(date +%H:%M:%S) UNRECOGNIZED($c/$MAXFAIL) $NAME — not pressing Enter"
          [ "$c" -ge "$MAXFAIL" ] && escalate_once "$NAME" "$sig" \
            "waiting on a prompt shape the approver doesn't recognize — needs you"
        fi
        ;;
    esac
    sleep 5
  done
  sleep 10
done
echo "watch window ended; approved $answered prompt(s)"
