#!/bin/bash
# Poll build 13's beta review state every 10 min; when it leaves WAITING_FOR_REVIEW, tell fractroam to submit 14.
S=/private/tmp/claude-501/-Users-kaolin/45db065a-706e-4428-84b3-81a253d29c9c/scratchpad
for i in $(seq 1 144); do
  out=$(bash -l -c 'eval "$(conda shell.bash hook)" && conda activate base && python '"$S"'/asc_review_state.py 13' 2>&1 | tail -1)
  echo "$(date +%H:%M) $out"
  case "$out" in
    *WAITING_FOR_REVIEW*|*ERR*|"") sleep 600; continue ;;
  esac
  st=$(echo "$out" | grep -o 'betaReviewState=[A-Z_]*' | cut -d= -f2)
  $S/relay-wait.sh "[claude] fractroam" "FractRoam" "/Users/kaolin/.claude/projects/-Users-kaolin-dev-FractRoam" "build 13 review state changed" "[hub $(date +%H:%M)] hub watcher: FractRoam build 13 review state changed → $st (read from /v1/builds/{id}/betaAppReviewSubmission). Per your 22:41 report, submit build 14 to Beta App Review now (his one-person group only; nothing else), then report to the hub (SendMessage) with the API state read back for both builds."
  echo "PINGED fractroam: $st"; exit 0
done
echo "gave up after 24h"; exit 1
