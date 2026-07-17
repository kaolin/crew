#!/usr/bin/env bash
# Tests crew against a fixture so we never need live sessions to catch a regression.
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "FAIL: $1"; exit 1; }

echo "== status renders groups, statuses, waitingFor =="
out=$(./crew status --source fixture.json)
echo "$out"
grep -q "izzit"            <<<"$out" || fail "missing project name"
grep -q "waiting"          <<<"$out" || fail "missing waiting status"
grep -q "permission prompt"<<<"$out" || fail "missing waitingFor detail"
grep -q "5 sessions"       <<<"$out" || fail "wrong session count"
# most-urgent group (the 'waiting' one, cwd=/Users/kaolin) must sort above idle groups
[[ $(grep -nE "^  (kaolin|izzit)" <<<"$out" | head -1) == *kaolin* ]] || fail "urgent group not sorted first"

echo "== snapshot round-trips to a manifest =="
snap=$(mktemp)
./crew snapshot --source fixture.json --out "$snap"
grep -q "sessionId" "$snap" || fail "snapshot missing sessionId"
[[ $(python3 -c "import json;print(len(json.load(open('$snap'))))") == 5 ]] || fail "snapshot wrong count"

echo "== restore is dry-run by default and emits resume commands =="
r=$(./crew restore --source "$snap")
grep -q "claude --resume ff10d5a8" <<<"$r" || fail "restore missing resume command"
grep -q "dry-run"                  <<<"$r" || fail "restore not dry-run by default"
grep -q "would put"                <<<"$r" || fail "restore executed instead of dry-run"

echo "== goto maps a session to its project-tagged Space (dry-run, no switching) =="
g=$(./crew goto izzit --dry-run --source fixture.json --spaces-source spaces_fixture.json)
echo "$g"
grep -q "Space 4" <<<"$g" || fail "izzit didn't map to Space 4"
# spaced/multi-word tag: SpotTheHustle project → 'spot the hustle' tag
g2=$(./crew goto spotthehustle --dry-run --source fixture.json --spaces-source spaces_fixture.json)
grep -q "Space 3" <<<"$g2" || fail "SpotTheHustle didn't map to Space 3"

echo "== snapshot carries each session's target Space into the manifest =="
mani=$(mktemp)
./crew snapshot --source fixture.json --spaces-source spaces_fixture.json --out "$mani" >/dev/null
python3 -c "import json; m={s['name']:s for s in json.load(open('$mani'))}; assert m['izzit-2b']['spaceIndex']==4, m['izzit-2b']; print('  izzit-2b -> Space', m['izzit-2b']['spaceIndex'])" || fail "snapshot didn't carry izzit's Space"

echo "== restore places each session on its Space (dry-run) =="
r=$(./crew restore --source "$mani")
echo "$r" | grep -q "Space 4" || fail "restore didn't show izzit on Space 4"
rm -f "$mani"

echo "== snapshot refuses to clobber a good map with an empty read =="
keep=$(mktemp)
./crew snapshot --source fixture.json --out "$keep" >/dev/null
empty=$(mktemp); echo '[]' > "$empty"
./crew snapshot --source "$empty" --out "$keep" | grep -q "skip" || fail "empty snapshot clobbered the good map"
[[ $(python3 -c "import json;print(len(json.load(open('$keep'))))") == 5 ]] || fail "good map lost after empty snapshot"
rm -f "$keep" "$empty"

echo "== launch-flag capture keeps yolo, drops resume =="
python3 -c "
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)
assert m._parse_flags('claude --dangerously-skip-permissions --resume abc')==['--dangerously-skip-permissions'], 'bare-value'
assert m._parse_flags('claude --dangerously-skip-permissions --resume')==['--dangerously-skip-permissions'], 'trailing-resume'
assert m._parse_flags('claude --model claude-opus-4-8 --dangerously-skip-permissions --resume x')==['--model','claude-opus-4-8','--dangerously-skip-permissions'], 'value-flag'
print('  parsing OK')
" || fail "launch-flag parsing wrong"

echo "== doctor runs; setup --dry-run changes nothing =="
./crew doctor >/dev/null || fail "doctor errored"
sdry=$(./crew setup --dry-run)
grep -q "would symlink" <<<"$sdry" || fail "setup --dry-run didn't dry-run"

rm -f "$snap"
echo
echo "ALL TESTS PASSED"
