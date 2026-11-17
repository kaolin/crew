#!/bin/bash
# fleetview/shot.sh — render fleet.html to PNGs at phone width with headless Chrome.
#
#   ./shot.sh               # light theme, 430 CSS px wide, 2x pixels
#   THEME=dark ./shot.sh    # dark theme
#   WIDTH=390 ./shot.sh     # a narrower phone
#
# Produces fleet.png (the whole page) and one crop per section
# (fleet-needs.png, fleet-live.png, …) cut from that same shot with sips, so
# each piece stays legible when a chat app scales a tall image to fit a phone.
#
# Chrome is run twice: --dump-dom to learn the page and section geometry that
# render.mjs stamps on <html>, then --screenshot at exactly that height. Chrome
# on macOS keeps a helper alive after headless work is done, so each run is
# watched for its output and then killed rather than waited on.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
WIDTH="${WIDTH:-430}"
THEME="${THEME:-light}"
SCALE="${SCALE:-2}"
HTML="$HERE/fleet.html"
SHOT_HTML="$HERE/.fleet-shot.html"
PNG="$HERE/fleet.png"

if [ ! -x "$CHROME" ]; then
  echo "shot.sh: Chrome not found at $CHROME — set CHROME=/path/to/binary; skipping screenshot" >&2
  exit 2
fi
if [ ! -f "$HERE/fleet.json" ]; then
  echo "shot.sh: fleet.json missing — run: node $HERE/collect.mjs" >&2
  exit 2
fi
[ -f "$HTML" ] || node "$HERE/render.mjs" >/dev/null

# A screenshot-only variant: same content, theme stamped, page left-aligned
# (Chrome's window can't go narrower than ~500px, so a centred 430px page
# would be pushed right and clipped).
node "$HERE/render.mjs" --theme "$THEME" --shot --out "$SHOT_HTML" >/dev/null

PROFILE="$(mktemp -d "${TMPDIR:-/tmp}/fleetview-chrome.XXXXXX")"
cleanup() { rm -rf "$PROFILE" "$SHOT_HTML" "$PNG.stdout"; }
trap cleanup EXIT
COMMON=(--headless=new --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check
        --user-data-dir="$PROFILE" --force-device-scale-factor="$SCALE")

# run_chrome <expect-file> <grep-pattern-or-empty> <chrome args…>: start Chrome,
# wait until the expected output exists (and, for stdout captures, is complete),
# then kill it. Times out after 45 s.
run_chrome() {
  local expect="$1" pattern="$2"; shift 2
  "$CHROME" "${COMMON[@]}" "$@" >"$expect.stdout" 2>/dev/null &
  local pid=$! i=0
  while [ $i -lt 450 ]; do
    if [ -n "$pattern" ]; then
      grep -q -- "$pattern" "$expect.stdout" 2>/dev/null && break
    else
      [ -s "$expect" ] && sleep 0.5 && break
    fi
    sleep 0.1; i=$((i + 1))
  done
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  [ $i -lt 450 ] || { echo "shot.sh: Chrome produced nothing in 45 s" >&2; return 1; }
}

DOM="$PROFILE/dom"
run_chrome "$DOM" "</html>" --window-size="$WIDTH,900" --dump-dom "file://$SHOT_HTML"
H="$(sed -n 's/.*data-h="\([0-9]*\)".*/\1/p' "$DOM.stdout" | head -1)"
SECTIONS="$(sed -n 's/.*data-sections="\([^"]*\)".*/\1/p' "$DOM.stdout" | head -1)"
if [ -z "${H:-}" ] || [ "$H" -lt 100 ]; then H=4000; echo "shot.sh: could not read page height, using $H" >&2; fi
H=$((H + 8))

rm -f "$PNG"
run_chrome "$PNG" "" --window-size="$WIDTH,$H" --screenshot="$PNG" "file://$SHOT_HTML"
echo "$PNG  (${WIDTH}x${H} css px @${SCALE}x, $THEME)"

# Crop each section out of the full shot. sips wants integer pixel offsets.
IFS=',' read -r -a parts <<<"${SECTIONS:-}"
for part in "${parts[@]}"; do
  IFS=':' read -r id top height <<<"$part"
  [ -n "$id" ] || continue
  y=$(( (top - 6) * SCALE )); [ $y -lt 0 ] && y=0
  h=$(( (height + 12) * SCALE ))
  out="$HERE/fleet-$id.png"
  sips --cropOffset "$y" 0 --cropToHeightWidth "$h" $((WIDTH * SCALE)) "$PNG" --out "$out" >/dev/null 2>&1 \
    && echo "$out  (${height} css px)" || echo "shot.sh: crop of $id failed" >&2
done
