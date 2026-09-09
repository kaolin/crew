#!/usr/bin/env bash
# Tests crew against a fixture so we never need live sessions to catch a regression.
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "FAIL: $1"; exit 1; }

# Every state path (~/.crew aliases + manifests, Telegram cursors, status files)
# resolves under CREW_HOME, so the fixtures never read the live machine — the
# homeless-session test broke the moment a real alias mapped "kaolin" to a Space.
export CREW_HOME="$(mktemp -d)"
trap 'rm -rf "$CREW_HOME"' EXIT

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
grep -qE "claude.* --resume ff10d5a8" <<<"$r" || fail "restore missing resume command"
grep -q "'--name' '\[claude\] " <<<"$r" || fail "restore didn't pass a [claude] --name label"
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

echo "== tmux pane parsing + adapter routing =="
python3 -c "
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)
p=m._parse_panes('foo','/dev/ttys021\t0:0.0\n/dev/ttys099\twork:1.2\ngarbage-line')
assert p=={'/dev/ttys021':('foo','0:0.0'),'/dev/ttys099':('foo','work:1.2')}, p
assert m.TmuxAdapter('foo','0:0.0').bounds('/dev/ttys021') is None
assert m.TmuxAdapter('foo','0:0.0').name=='tmux'
print('  tmux adapter logic OK')
" || fail "tmux adapter logic wrong"

echo "== tmux tell: bracketed paste for multi-line, send-keys for single =="
python3 -c "
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)
m.time.sleep=lambda *a: None
class R: returncode=0
a=m.TmuxAdapter('foo','0:0.0'); calls=[]
a._tmux=lambda *args: (calls.append(args), R())[1]
a.tell('/dev/ttys021','one line')
assert any(c[0]=='send-keys' and '-l' in c for c in calls), calls
assert not any(c[0]=='paste-buffer' for c in calls), calls
calls.clear()
a.tell('/dev/ttys021','line1\nline2\nline3')
assert any(c[0]=='set-buffer' for c in calls) and any(c[0]=='paste-buffer' for c in calls), calls
assert any(c[0]=='send-keys' and c[-1]=='Enter' for c in calls), calls
print('  tmux tell branching OK')
" || fail "tmux tell branching wrong"

echo "== transcript parsing =="
python3 -c "
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
import json
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)
assert m._msg_text({'message':{'content':'hi'}})=='hi'
assert m._msg_text({'message':{'content':[{'type':'text','text':'a'},{'type':'tool_use','name':'Bash'},{'type':'text','text':'b'}]}})=='a\n[Bash]\nb'
lines=[json.dumps({'type':'user','message':{'content':'q1'}}),
       json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'r1'}]}}),
       'garbage-line',
       json.dumps({'type':'system','message':{'content':'ignore me'}})]
assert m._parse_turns(lines)==[('user','q1'),('assistant','r1')], m._parse_turns(lines)
print('  transcript parsing OK')
" || fail "transcript parsing wrong"

echo "== artifact URL extraction =="
python3 -c "
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)
t='live https://claude.ai/code/artifact/f158d9ff-4b21-44bb-acb6-6a6aa050b8f1** and (https://claude.ai/public/artifacts/b4b147bd-fbd0-412c-a29d-9f6c39ed47f5) but not https://claude.ai/code/artifact/abc123'
assert m._artifact_urls(t)==['https://claude.ai/code/artifact/f158d9ff-4b21-44bb-acb6-6a6aa050b8f1','https://claude.ai/public/artifacts/b4b147bd-fbd0-412c-a29d-9f6c39ed47f5'], m._artifact_urls(t)
assert m._artifact_urls('no links here')==[]
print('  artifact extraction OK')
" || fail "artifact extraction wrong"

echo "== blocked sessions: question vs permission, and tell refuses both =="
python3 -c "
import json, os, tempfile
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)

def jl(rows):
    fd,p=tempfile.mkstemp(suffix='.jsonl')
    with os.fdopen(fd,'w') as f:
        for r in rows: f.write(json.dumps(r)+'\n')
    return p
def tu(i,n,inp): return {'type':'assistant','message':{'role':'assistant','content':[{'type':'tool_use','id':i,'name':n,'input':inp}]}}
def tr(i):       return {'type':'user','message':{'role':'user','content':[{'type':'tool_result','tool_use_id':i,'content':'ok'}]}}

ASK={'questions':[{'question':'Name for the unlock?','options':[{'label':'Deep Time'},{'label':'20,000 Years'}]}]}

# an AskUserQuestion with no result = a question FOR KAOLIN
p=jl([tu('t1','Read',{'file_path':'/a'}),tr('t1'),tu('t2','AskUserQuestion',ASK)])
got=m._pending({'sessionId':'x'},screen=False) if False else None
m._jsonl_path=lambda s,_p=p: _p
got=m._pending({'sessionId':'x'},screen=False)
assert got and got['kind']=='question', got
assert 'Name for the unlock' in got['detail'], got
assert got['options']==['Deep Time','20,000 Years'], got
assert 'QUESTION FOR YOU' in m._pending_line(got), m._pending_line(got)
os.unlink(p)

# a tool awaiting approval = a permission prompt (the disasteroids Artifact case)
p=jl([tu('a1','Artifact',{'file_path':'/tmp/gallery.html'})])
m._jsonl_path=lambda s,_p=p: _p
got=m._pending({'sessionId':'x'},screen=False)
assert got and got['kind']=='permission' and got['tool']=='Artifact', got
assert 'gallery.html' in got['detail'], got
os.unlink(p)

# everything answered = nothing pending
p=jl([tu('b1','Bash',{'command':'ls'}),tr('b1')])
m._jsonl_path=lambda s,_p=p: _p
assert m._pending({'sessionId':'x'},screen=False) is None
os.unlink(p)

# screen fallback: option-picker chrome on screen, nothing in the transcript
rows=['Which model should I build for the release?','❯ 1. Free + \$1.99 color unlock (Recommended)',
      '  2. Completely free','  5. Type something.','────────','  6. Chat about this',
      'Enter to select · ↑/↓ to navigate · Esc to cancel']
sc=m._classify_screen(rows)
assert sc and sc['kind']=='question', sc
assert sc['detail'].startswith('Which model'), sc
assert 'Free + \$1.99 color unlock (Recommended)' in sc['options'], sc
assert 'Type something.' not in sc['options'], sc   # picker chrome, not a real choice
assert m._classify_screen(['just some output','no chrome here']) is None
assert m._classify_screen([]) is None

# the guard itself: refuses ONLY when waiting, and never silently
assert m._blocked_refusal({'name':'n','status':'idle'},'send') is False
assert m._blocked_refusal({'name':'n','status':'busy'},'send') is False
m._pending=lambda s,**k: {'kind':'question','tool':'AskUserQuestion','detail':'q?','options':['a']}
assert m._blocked_refusal({'name':'n','status':'waiting'},'send') is True
print('  blocked-session detection + tell guard OK')
" || fail "blocked-session handling wrong"

echo "== snapshot records the intended home beside the actual Space, and reports the homeless =="
dm=$(mktemp)
dout=$(./crew snapshot --source fixture.json --spaces-source spaces_fixture.json --out "$dm")
python3 -c "import json; m={s['name']:s for s in json.load(open('$dm'))}; assert m['izzit-2b']['homeSpaceIndex']==4, m['izzit-2b']; assert m['kaolin-e8']['homeSpace'] is None, m['kaolin-e8']; print('  izzit-2b home=4, kaolin-e8 homeless')" || fail "snapshot didn't record homeSpace"
grep -q "no Space tag" <<<"$dout" || fail "snapshot didn't report the homeless session"
grep -q "kaolin-e8"    <<<"$dout" || fail "homeless report didn't name kaolin-e8"

echo "== restore re-resolves home from live Spaces and says where the window was =="
python3 -c "
import json
m=json.load(open('$dm')); sp={s['index']:s for s in json.load(open('spaces_fixture.json'))}
for s in m:
    if s['name']=='izzit-2b':
        s['space'], s['spaceIndex'], s['spaceTag'] = sp[2]['uuid'], 2, sp[2].get('tag')   # scattered onto fractroam
json.dump(m, open('$dm','w'))"
rr=$(./crew restore --source "$dm" --spaces-source spaces_fixture.json)
grep -q "izzit-2b .*→ Space 4 · izzit"       <<<"$rr" || fail "restore didn't send izzit home"
grep -q "was on Space 2 · fractroam"         <<<"$rr" || fail "restore didn't say where izzit had been"
ra=$(./crew restore --source "$dm" --spaces-source spaces_fixture.json --as-found)
grep -q "izzit-2b .*→ Space 2 · fractroam"   <<<"$ra" || fail "--as-found didn't keep the recorded Space"
grep -q "was on"                              <<<"$ra" && fail "--as-found still claimed to move a window"
rm -f "$dm"

echo "== snapshot (non-tty) reports Space drift only when the picture changes =="
qm=$(mktemp); rm -f "$qm"
q1=$(./crew snapshot --source fixture.json --spaces-source spaces_fixture.json --out "$qm" | cat)
q2=$(./crew snapshot --source fixture.json --spaces-source spaces_fixture.json --out "$qm" | cat)
q3=$(./crew snapshot --source fixture.json --spaces-source spaces_fixture.json --out "$qm" --verbose | cat)
grep -q "⚠" <<<"$q1" || fail "first snapshot (no previous map) should report"
grep -q "⚠" <<<"$q2" && fail "unchanged snapshot should stay quiet when not a tty (launchd log noise)"
grep -q "⚠" <<<"$q3" || fail "--verbose should always report"
rm -f "$qm"

echo "== labels: dedup, launcher lookup, drift sets =="
python3 -c "
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
l=SourceFileLoader('crewmod','./crew'); m=module_from_spec(spec_from_loader('crewmod',l)); l.exec_module(m)
one=[{'cwd':'/Users/kaolin'}]
two=[{'cwd':'/Users/kaolin'},{'cwd':'/Users/kaolin'}]
assert m.label_name('/Users/kaolin','hub',one)=='[claude] kaolin', 'unique project keeps project name'
assert m.label_name('/Users/kaolin','hub',two)=='[claude] hub', 'shared project falls back to session name'
assert m._launcher_for('nonesuch-zz') is None, 'unknown launcher must be None'
assert m._launcher_for('[claude] nonesuch-zz') is None, 'prefix stripped before lookup'
d,h=m._drift_sets([{'name':'a','space':'X','homeSpace':'Y'},{'name':'b','space':'X','homeSpace':'X'},{'name':'c','space':'X','homeSpace':None}])
assert d==frozenset({'a'}) and h==frozenset({'c'}), (d,h)
assert m._tab_escape((1,2,3),literal=True).startswith('\\\\033]6;1;bg;red;brightness;1\\\\a'), m._tab_escape((1,2,3),literal=True)
assert m._as_str('a\\\\b\"c')=='a\\\\\\\\b\\\\\"c', m._as_str('a\\\\b\"c')
print('  label/launcher/drift helpers OK')
" || fail "label helpers wrong"

echo "== telegram cursors + brief against a scratch CREW_HOME =="
th=$(mktemp -d)
mkdir -p "$th/.claude/channels/telegram" "$th/.claude/status" "$th/.crew"
old_ts=$(python3 -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time()-3*86400)))")
new_ts=$(python3 -c "import time;print(time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()))")
cat > "$th/.claude/channels/telegram/inbound.jsonl" <<EOF
{"seq": 1, "ts": "$new_ts", "params": {"content": "handled already", "meta": {"message_id": 1}}}
{"seq": 2, "ts": "$old_ts", "params": {"content": "ancient, outside the review window", "meta": {"message_id": 2}}}
{"seq": 3, "ts": "$new_ts", "params": {"content": "fresh and unhandled", "meta": {"message_id": 3, "image_path": "/x/y.jpg"}}}
EOF
echo 1 > "$th/.claude/channels/telegram/actioned.cursor"
u=$(CREW_HOME="$th" ./crew tg-unactioned)
grep -q "fresh and unhandled"   <<<"$u" || fail "tg-unactioned missed seq 3"
grep -q "image: /x/y.jpg"       <<<"$u" || fail "tg-unactioned dropped the image path"
grep -q "handled already"       <<<"$u" && fail "tg-unactioned showed an actioned message"
grep -q "ancient"               <<<"$u" && fail "tg-unactioned showed a record outside the 48h window"
ua=$(CREW_HOME="$th" ./crew tg-unactioned --all)
grep -q "ancient"               <<<"$ua" || fail "--all should include old records"
CREW_HOME="$th" ./crew tg-actioned latest | grep -q "actioned.cursor = 3" || fail "tg-actioned latest didn't reach max seq"
[[ $(cat "$th/.claude/channels/telegram/actioned.cursor") == 3 ]] || fail "cursor file not written"
CREW_HOME="$th" ./crew tg-unactioned | grep -q "caught up" || fail "after actioning, should be caught up"
# brief: one unseen pinger event, one fresh status file, one stale (3 days) status file
cat > "$th/.claude/status/_pinger.jsonl" <<EOF
{"seq": 1, "ts": "$new_ts", "kind": "✅", "session": "izzit-55", "project": "izzit", "text": "finished after 4m"}
EOF
python3 - "$th" <<'PY'
import json, sys, time, os
th = sys.argv[1]
now = time.strftime("%Y-%m-%dT%H:%M:%S-0700")
old = time.strftime("%Y-%m-%dT%H:%M:%S-0700", time.localtime(time.time() - 3*86400))
two_h = time.strftime("%Y-%m-%dT%H:%M:%S-0700", time.localtime(time.time() - 2*3600))
json.dump({"updated_at": now, "needs_decision": ["ship it?"]}, open(os.path.join(th, ".claude/status/izzit.json"), "w"))
json.dump({"updated_at": old, "summary": "old news"}, open(os.path.join(th, ".claude/status/orrery.json"), "w"))
# thereby: status 2h old, a device shipped at aaa1111 vs head bbb2222 (stale), one commit AFTER the status
json.dump({"session": "thereby-8e", "updated_at": two_h, "head": "bbb2222", "unpushed": ["139"],
           "device": {"name": "Grayhame", "shipped_commit": "aaa1111", "stale": True}},
          open(os.path.join(th, ".claude/status/thereby.json"), "w"))
t = time.time()
with open(os.path.join(th, ".claude/status/_commits.jsonl"), "w") as f:
    # izzit's commit belongs to the fixture's izzit-2b session (by id); its status is newer than it
    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t - 4*3600)), "t": t - 4*3600,
                        "session_id": "ff10d5a8-b98c-4cf5-8323-68b28e06a778", "cwd": "/Users/kaolin/dev/izzit",
                        "repo": "/Users/kaolin/dev/izzit", "project": "izzit", "branch": "main",
                        "sha": "c0ffee1234567890", "subject": "izzit: packs"}) + "\n")
    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t - 600)), "t": t - 600,
                        "session_id": "153722a7-422d-49e4-9e9a-a40c90453f00", "cwd": "/Users/kaolin/dev/thereby",
                        "repo": "/Users/kaolin/dev/thereby", "project": "thereby", "branch": "main",
                        "sha": "ccc3333abcdef", "subject": "recording on by default for testers"}) + "\n")
    f.write("garbage line\n")
PY
b=$(CREW_HOME="$th" ./crew brief --plain --no-ack)
grep -q "1 event(s) you have not seen" <<<"$b" || fail "brief didn't show the unseen pinger event"
grep -q "NEEDS KAOLIN"                 <<<"$b" || fail "brief didn't surface needs_decision"
grep -q "STALE STATUS FILES"           <<<"$b" || fail "brief didn't flag the 3-day-old status file"
grep -q "orrery"                       <<<"$b" || fail "stale block should name orrery"
# commit attribution feeding brief: exact head behind the stale device, commits since the status
grep -q "shipped aaa1111 vs head bbb2222 (latest commit ccc3333" <<<"$b" || fail "DEVICE STALE didn't use the commit record's sha"
grep -q "+1 commit(s) since this status, latest ccc3333"       <<<"$b" || fail "UNPUSHED WORK didn't count the commit after the status"
grep -qE "thereby +1 commit\(s\) after it, latest ccc3333"     <<<"$b" || fail "STALE block didn't flag the status with a commit after it"
grep -q "izzit .*commit(s) after it"                            <<<"$b" && fail "a commit OLDER than the status must not count"
# crew commits: resolves a name the way every other command does; lists newest first
cc=$(CREW_HOME="$th" ./crew commits --source fixture.json)
[[ $(head -1 <<<"$cc") == *ccc3333* ]] || fail "crew commits should list newest first"
grep -q "c0ffee1 .*izzit-2b .*izzit: packs" <<<"$cc" || fail "crew commits didn't name the session that made the commit"
CREW_HOME="$th" ./crew commits izzit --source fixture.json | grep -q "c0ffee1" || fail "crew commits <name> didn't resolve izzit"
CREW_HOME="$th" ./crew commits izzit --source fixture.json | grep -q "ccc3333" && fail "crew commits izzit showed thereby's commit"
CREW_HOME="$th" ./crew commits thereby --source fixture.json | grep -q "ccc3333" || fail "a project with no live session should still match by record"
CREW_HOME="$th" ./crew commits nonesuch --source fixture.json | grep -q "no recorded commits match" || fail "unknown name should say so"
CREW_HOME="$th" ./crew commits --source fixture.json --limit 1 | wc -l | grep -q "^ *1$" || fail "--limit not honoured"
mkdir -p "$th/empty/.claude/status"
CREW_HOME="$th/empty" ./crew commits | grep -q "no commits recorded" || fail "no log should say so, not crash"
[[ -e "$th/.claude/status/_brief.cursor" ]] && fail "--no-ack must not write the brief cursor"
CREW_HOME="$th" ./crew brief --plain >/dev/null
[[ $(cat "$th/.claude/status/_brief.cursor") == 1 ]] || fail "brief without --no-ack should ack to seq 1"
CREW_HOME="$th" ./crew brief --plain | grep -q "you have not seen" && fail "acked events must not repeat"
# tg-patch with no plugin installed must not crash
CREW_HOME="$th" ./crew tg-patch >/dev/null 2>&1 || fail "tg-patch errored with no plugin dir"
rm -rf "$th"

echo "== hooks: install prints the JSON and refuses without --yes; --yes is idempotent; uninstall is surgical =="
hh=$(mktemp -d)
mkdir -p "$hh/.claude"
echo '{"model":"x","hooks":{"Stop":[{"hooks":[{"type":"command","command":"/other/thing.sh"}]}]}}' > "$hh/.claude/settings.json"
hi=$(CREW_HOME="$hh" ./crew hooks install; echo "rc=$?")
grep -q '"matcher": "Bash"'          <<<"$hi" || fail "hooks install didn't print the PostToolUse Bash entry"
grep -q '"Notification"'             <<<"$hi" || fail "hooks install didn't print the Notification entry"
grep -q '"Stop"'                     <<<"$hi" || fail "hooks install didn't print the Stop entry"
grep -q '"command": "/'              <<<"$hi" || fail "hook command is not an absolute path"
grep -q 'hooks/crew-hook.py'         <<<"$hi" || fail "hook command doesn't point at hooks/crew-hook.py"
grep -q 'rc=2'                       <<<"$hi" || fail "hooks install without --yes must refuse (exit 2)"
grep -q 'crew-hook' "$hh/.claude/settings.json" && fail "hooks install without --yes wrote settings.json"
CREW_HOME="$hh" ./crew hooks status | grep -q "not installed" || fail "hooks status should say not installed"
CREW_HOME="$hh" ./crew hooks install --yes >/dev/null || fail "hooks install --yes failed"
python3 - "$hh/.claude/settings.json" <<'PY' || fail "merged settings wrong"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["model"] == "x", "other keys must survive"
assert d["hooks"]["Stop"][0]["hooks"][0]["command"] == "/other/thing.sh", "existing Stop hook must survive"
assert len(d["hooks"]["Stop"]) == 2, d["hooks"]["Stop"]
assert d["hooks"]["PostToolUse"][0]["matcher"] == "Bash"
assert "matcher" not in d["hooks"]["Notification"][0], "Notification takes no matcher (match all)"
cmds = {h["command"] for ev in ("Notification", "Stop", "PostToolUse") for g in d["hooks"][ev] for h in g["hooks"]}
assert any(c.endswith("/hooks/crew-hook.py") and c.startswith("/") for c in cmds), cmds
assert all(h.get("timeout") for ev in ("Notification", "PostToolUse") for g in d["hooks"][ev] for h in g["hooks"])
print("  merge OK")
PY
before=$(cat "$hh/.claude/settings.json")
CREW_HOME="$hh" ./crew hooks install --yes | grep -q "nothing to do" || fail "second install should be a no-op"
[[ "$(cat "$hh/.claude/settings.json")" == "$before" ]] || fail "second install changed settings.json"
CREW_HOME="$hh" ./crew hooks status | grep -q "PostToolUse   installed" || fail "hooks status should say installed"
CREW_HOME="$hh" ./crew hooks uninstall >/dev/null && fail "uninstall without --yes must refuse"
CREW_HOME="$hh" ./crew hooks uninstall --yes >/dev/null || fail "uninstall --yes failed"
python3 - "$hh/.claude/settings.json" <<'PY' || fail "uninstall left the wrong thing behind"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "/other/thing.sh"}]}]}, d["hooks"]
print("  uninstall OK")
PY
ls "$hh/.claude/" | grep -q "settings.json.bak-" || fail "no backup written beside settings.json"
rm -f "$hh"/.claude/settings.json*; rmdir "$hh/.claude" "$hh" 2>/dev/null || true

echo "== status-refresh: fake claude -p, same schema, mirror + exclude, unchanged skip, --stale + cooldown =="
sr=$(cd "$(mktemp -d)" && pwd -P)     # realpath: git reports the repo through /private/var, not /var
mkdir -p "$sr/.claude/status" "$sr/.crew" "$sr/fake"
# a project repo with two commits and an upstream so the unpushed count is a number
mkdir -p "$sr/proj" "$sr/origin.git"
git -C "$sr/origin.git" init -q --bare
git -C "$sr/proj" init -q
git -C "$sr/proj" -c user.name=t -c user.email=t@t commit -q --allow-empty -m "proj: first"
git -C "$sr/proj" remote add origin "$sr/origin.git"
git -C "$sr/proj" push -q -u origin HEAD 2>/dev/null
git -C "$sr/proj" -c user.name=t -c user.email=t@t commit -q --allow-empty -m "proj: second, unpushed"
head_sha=$(git -C "$sr/proj" rev-parse --short HEAD)
# a session in that project, with a transcript
sid="11111111-2222-3333-4444-555555555555"
enc=$(python3 -c "import sys;print(sys.argv[1].replace('/','-'))" "$sr/proj")
mkdir -p "$sr/.claude/projects/$enc"
python3 - "$sr/.claude/projects/$enc/$sid.jsonl" <<'PY'
import json, sys
rows = [{"type": "user", "message": {"content": "ship build 12 to the moto"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Built 12, installed on the moto, 40 tests green. NEEDS YOU: pick the icon."}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}]
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
PY
cat > "$sr/sessions.json" <<EOF
[{"pid":1,"cwd":"$sr/proj","kind":"interactive","startedAt":1,"sessionId":"$sid","name":"proj-ab","status":"idle"},
 {"pid":2,"cwd":"$sr/plain","kind":"interactive","startedAt":1,"sessionId":"66666666-2222-3333-4444-555555555555","name":"plain-cd","status":"idle"},
 {"pid":3,"cwd":"$HOME","kind":"interactive","startedAt":1,"sessionId":"77777777-2222-3333-4444-555555555555","name":"hub","status":"busy"}]
EOF
mkdir -p "$sr/plain"
python3 -c "import json,sys,time; json.dump({'session':'proj-ab','updated_at':time.strftime('%Y-%m-%dT%H:%M:%S-0700'),'state':'working','settled':{'price':'\$1.99'},'needs_decision':[]}, open(sys.argv[1],'w'))" "$sr/.claude/status/proj.json"
# the fake claude: records argv + the prompt it was fed, answers with a canned envelope
cat > "$sr/fake/claude" <<'EOF'
#!/bin/bash
cat > "$FAKE_DIR/prompt.txt"
printf '%s\n' "$@" > "$FAKE_DIR/argv.txt"
echo called >> "$FAKE_DIR/calls.txt"
cat "$FAKE_DIR/reply.json"
EOF
chmod +x "$sr/fake/claude"
python3 - "$sr/fake/reply.json" <<'PY'
import json, sys
status = {"session": "proj-ab", "updated_at": "ignored", "state": "blocked", "head": "wrong",
          "last_action": "Built 12, installed on the moto", "needs_decision": ["pick the icon"],
          "settled": {"price": "$1.99"}, "verified": [], "unverified": ["installed on the moto"]}
env = {"type": "result", "subtype": "success", "is_error": False, "result": "```json\n" + json.dumps(status) + "\n```",
       "session_id": "fake-sess", "total_cost_usd": 0.0042, "duration_ms": 1200, "num_turns": 1,
       "usage": {"input_tokens": 1500, "output_tokens": 200}}
json.dump(env, open(sys.argv[1], "w"))
PY
export FAKE_DIR="$sr/fake"
calls() { wc -l < "$sr/fake/calls.txt" | tr -d " "; }   # wc pads with spaces on macOS
# dry-run: says what it would do, calls nothing
d=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh proj --source "$sr/sessions.json" --dry-run)
grep -q "proj.json" <<<"$d" || fail "dry-run didn't name the status file"
grep -q "not sent" <<<"$d" || fail "dry-run should say it did not send"
[[ -e "$sr/fake/calls.txt" ]] && fail "dry-run called claude"
# the real thing (faked): prompt carries the four inputs; output lands in both places
r=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh proj --source "$sr/sessions.json")
echo "$r"
grep -q "proj-ab → $sr/.claude/status/proj.json" <<<"$r" || fail "status-refresh didn't report the write"
grep -q '\$0.0042' <<<"$r" || fail "status-refresh didn't report the cost"
grep -q "mirror: $sr/proj/.crew/status.json" <<<"$r" || fail "status-refresh didn't mirror into the repo"
grep -q -- "--model" "$sr/fake/argv.txt" && grep -q "^haiku$" "$sr/fake/argv.txt" || fail "claude -p not called with --model haiku"
grep -q "^--output-format$" "$sr/fake/argv.txt" && grep -q "^json$" "$sr/fake/argv.txt" || fail "claude -p not called with --output-format json"
grep -q "proj: second, unpushed" "$sr/fake/prompt.txt" || fail "prompt lacks the git log"
grep -q "Unpushed: 1" "$sr/fake/prompt.txt" || fail "prompt lacks the unpushed count"
grep -q '"price": "\$1.99"' "$sr/fake/prompt.txt" || fail "prompt lacks the previous status"
grep -q "ASSISTANT: Built 12" "$sr/fake/prompt.txt" || fail "prompt lacks the transcript tail"
grep -q "USER: ship build 12" "$sr/fake/prompt.txt" || fail "prompt lacks kaolin's turn"
python3 - "$sr/.claude/status/proj.json" "$sr/proj/.crew/status.json" "$head_sha" <<'PY' || fail "written status wrong"
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
assert a == b, "mirror must equal the status file"
assert a["session"] == "proj-ab" and a["state"] == "blocked" and a["needs_decision"] == ["pick the icon"], a
assert a["head"] == sys.argv[3], ("head must come from git, not the model", a["head"])
assert a["updated_at"] != "ignored" and a["updated_at"][:2] == "20", a["updated_at"]
assert a["refreshed"]["by"] == "crew status-refresh" and a["refreshed"]["cost_usd"] == 0.0042
print("  schema + head + mirror OK")
PY
grep -qx ".crew/" "$sr/proj/.git/info/exclude" || fail ".crew/ not added to .git/info/exclude"
[[ -e "$sr/proj/.gitignore" ]] && fail "status-refresh must never touch .gitignore"
git -C "$sr/proj" status --porcelain | grep -q "crew" && fail ".crew/ shows in git status (exclude not effective)"
[[ $(git -C "$sr/proj" rev-list --count HEAD) == 2 ]] || fail "status-refresh must never commit"
# second run, same reply: unchanged → not rewritten, exclude not duplicated, cooldown recorded
m1=$(stat -f %m "$sr/.claude/status/proj.json")
sleep 1
r2=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh proj --source "$sr/sessions.json")
grep -q "unchanged" <<<"$r2" || fail "identical summary should be reported unchanged"
[[ $(stat -f %m "$sr/.claude/status/proj.json") == "$m1" ]] || fail "unchanged summary rewrote the file"
[[ $(grep -c "^.crew/$" "$sr/proj/.git/info/exclude") == 1 ]] || fail ".crew/ duplicated in exclude"
# --stale: proj is fresh (file + a refresh minutes ago); plain has no status file → exactly one call, for plain
n=$(calls)
s2=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh --stale --source "$sr/sessions.json")
grep -q "stale: plain-cd .*no status file" <<<"$s2" || fail "--stale should pick a session with no status file"
grep -q "stale: proj-ab" <<<"$s2" && fail "--stale picked a fresh status"
grep -q "hub" <<<"$s2" && fail "--stale must never summarize the hub"
[[ $(calls) == $((n + 1)) ]] || fail "--stale should have called exactly once (plain)"
# the non-git project: status written, mirror skipped, nothing created in its tree
[[ -e "$sr/.claude/status/plain.json" ]] || fail "non-git project status not written"
[[ -e "$sr/plain/.crew" ]] && fail "non-git project must not get a .crew/ mirror"
grep -q "no git repo: mirror skipped" <<<"$s2" || fail "non-git mirror skip not reported"
CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh --stale --source "$sr/sessions.json" | grep -q "nothing stale" || fail "--stale should now find nothing"
[[ $(calls) == $((n + 1)) ]] || fail "--stale called claude with nothing stale"
# a commit after the status makes proj stale; but the 15-min cooldown holds until the state is cleared
python3 - "$sr/.claude/status/_commits.jsonl" "$sr/proj" <<'PY'
import json, sys, time
t = time.time() + 2
open(sys.argv[1], "w").write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t)), "t": t,
    "session_id": "11111111-2222-3333-4444-555555555555", "cwd": sys.argv[2], "repo": sys.argv[2],
    "project": "proj", "branch": "main", "sha": "abc1234def", "subject": "proj: third"}) + "\n")
PY
s3=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh --stale --source "$sr/sessions.json")
grep -q "stale: proj-ab .*1 commit(s) after the status" <<<"$s3" || fail "--stale didn't see the commit after the status"
grep -q "cooling down" <<<"$s3" || fail "--stale ignored the 15-min cooldown"
[[ $(calls) == $((n + 1)) ]] || fail "cooldown did not stop the call"
rm -f "$sr/.crew/status-refresh.json"
s4=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh --stale --source "$sr/sessions.json")
grep -q "stale: proj-ab" <<<"$s4" || fail "--stale (no cooldown) didn't pick proj"
grep -q "plain-cd" <<<"$s4" && fail "plain's fresh status must not be re-summarized"
[[ $(calls) == $((n + 2)) ]] || fail "--stale should have called once, for proj"
# a broken reply leaves the file alone and exits non-zero
cp "$sr/.claude/status/proj.json" "$sr/proj.before"
echo 'not json at all' > "$sr/fake/reply.json"
CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh proj --source "$sr/sessions.json" >/dev/null && fail "garbage reply should exit non-zero"
cmp -s "$sr/proj.before" "$sr/.claude/status/proj.json" || fail "garbage reply changed the status file"
# unknown name
un=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh nonesuch --source "$sr/sessions.json" || true)
grep -q "no running session" <<<"$un" || fail "unknown target should say so"
un=$(CREW_HOME="$sr" CREW_CLAUDE="$sr/fake/claude" ./crew status-refresh --source "$sr/sessions.json" || true)
grep -q "usage:" <<<"$un" || fail "no target should print usage"
unset FAKE_DIR

echo "== pinger suites =="
# These lived beside tick.py and had to be remembered individually, so a broken
# one could sit green-by-omission. Globbed instead of listed: a new test_*.py
# next to the pinger is picked up without editing this file.
for t in pinger/test_*.py; do
  python3 "$t" || fail "$t"
done

echo "== doctor runs; setup --dry-run changes nothing =="
env -u CREW_HOME ./crew doctor >/dev/null || fail "doctor errored"
sdry=$(./crew setup --dry-run)
grep -q "would symlink" <<<"$sdry" || fail "setup --dry-run didn't dry-run"

rm -f "$snap"
echo
echo "ALL TESTS PASSED"
