#!/usr/bin/env bash
# Regenerate the hub's two status-artifact charts from live local data.
#
# This ONLY regenerates the local HTML. The HUB (this Telegram fleet-hub Claude
# session) republishes the outputs via the Artifact tool — a shell script can't
# publish artifacts. After running this, the hub publishes whatever changed:
#     ~/dev/crew/usage/chart.html          -> artifact b90824f1  ("How spiky is it — usage")
#     ~/dev/fenriswatch/charts/fenriswatch.html -> artifact e1aadde9 ("Watch Battery Traces")
#
# Usage:
#   refresh-artifacts.sh            # regenerate BOTH
#   refresh-artifacts.sh usage      # just the token/usage chart
#   refresh-artifacts.sh battery    # just the watch/devices battery chart
#
# The usage token history depth is controlled by USAGE_HOURS (default here 1100h
# ~= 45 days, matching the readings.tsv sampler span). The readings.tsv sampler
# itself is auto (launchd com.kaolin.claude-usage-sampler, ~15 min) — this script
# does not touch it. The fenriswatch battery DATA collection needs kaolin's
# signed-in FENRISWATCH Chrome window; this script only re-renders whatever the
# battery DB already holds.
set -uo pipefail

what="${1:-both}"
USAGE_HOURS="${USAGE_HOURS:-1100}"
rc=0

ts() { date '+%Y-%m-%d %H:%M'; }

do_usage() {
  echo "[$(ts)] usage: regenerating (USAGE_HOURS=$USAGE_HOURS)"
  bash -lc 'eval "$(conda shell.bash hook)" && conda activate base && cd ~/dev/crew/usage && USAGE_HOURS='"$USAGE_HOURS"' python hourly.py && python chart.py' \
    && echo "[$(ts)] usage: OK -> ~/dev/crew/usage/chart.html (publish to artifact b90824f1)" \
    || { echo "[$(ts)] usage: FAILED"; rc=1; }
}

do_battery() {
  echo "[$(ts)] battery: regenerating"
  ( cd ~/dev/fenriswatch && node report/interactive.mjs ) \
    && echo "[$(ts)] battery: OK -> ~/dev/fenriswatch/charts/fenriswatch.html (publish to artifact e1aadde9)" \
    || { echo "[$(ts)] battery: FAILED"; rc=1; }
}

case "$what" in
  usage)   do_usage ;;
  battery|watch|devices) do_battery ;;
  both|all|"") do_usage; do_battery ;;
  *) echo "usage: refresh-artifacts.sh [usage|battery|both]"; exit 2 ;;
esac

echo "[$(ts)] done (rc=$rc). Hub: republish the changed chart(s) to their artifact URLs."
exit $rc
