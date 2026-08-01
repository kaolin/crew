#!/usr/bin/env python3
"""Tests for blocked-session detection (pending_prompt + the waiting branch).

Regression targets, both 2026-07-31:
  - orrery-4c sat on an AskUserQuestion for 1h40m; `crew status` called it a
    "permission prompt" and the pinger said nothing, so nobody noticed.
  - a hub probe typed at that session and was consumed as kaolin's answer.

Run: python3 pinger/test_pending.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tick  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILED.append(name)


def write_jsonl(rows):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return path


def tool_use(tid, name, inp):
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def tool_result(tid):
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


ASK = {"questions": [{"question": "New name for the $2.99 unlock?",
                      "options": [{"label": "Deep Time"},
                                  {"label": "Ten Thousand Years"},
                                  {"label": "The Long Sweep"}]}]}


def test_unanswered_question_is_detected():
    p = write_jsonl([tool_use("t1", "Read", {"file_path": "/a"}), tool_result("t1"),
                     tool_use("t2", "AskUserQuestion", ASK)])
    got = tick.pending_prompt(p)
    check("question detected", got is not None and got[0] == "question", str(got))
    check("question text kept", got and "unlock" in got[1])
    check("options enumerated",
          got and all(o in got[1] for o in ("Deep Time", "Ten Thousand Years", "The Long Sweep")))
    os.unlink(p)


def test_answered_question_is_not_pending():
    p = write_jsonl([tool_use("t2", "AskUserQuestion", ASK), tool_result("t2")])
    check("answered question not pending", tick.pending_prompt(p) is None)
    os.unlink(p)


def test_permission_prompt_is_distinguished():
    p = write_jsonl([tool_use("t9", "Bash", {"command": "rm -rf /tmp/x && echo done"})])
    got = tick.pending_prompt(p)
    check("permission detected", got is not None and got[0] == "permission", str(got))
    check("permission names tool", got and got[1].startswith("Bash"))
    check("permission shows command", got and "rm -rf /tmp/x" in got[1])
    os.unlink(p)


def test_artifact_publish_reads_as_permission():
    """The disasteroids case: an Artifact publish, NOT a question."""
    p = write_jsonl([tool_use("a1", "Artifact", {"file_path": "/tmp/gallery.html",
                                                 "title": "Disasteroids Screenshots"})])
    got = tick.pending_prompt(p)
    check("artifact = permission", got and got[0] == "permission", str(got))
    check("artifact shows path", got and "gallery.html" in got[1])
    os.unlink(p)


def test_idle_transcript_has_nothing_pending():
    p = write_jsonl([tool_use("t1", "Bash", {"command": "ls"}), tool_result("t1")])
    check("nothing pending when all answered", tick.pending_prompt(p) is None)
    os.unlink(p)


def test_missing_file_is_safe():
    check("missing transcript returns None",
          tick.pending_prompt("/nonexistent/nope.jsonl") is None)


def test_crew_enrichment_fails_safe():
    """pending_via_crew is enrichment — a bad name or missing binary must not raise."""
    check("unknown session -> []", tick.pending_via_crew("no-such-session-xyz") == [])
    real, tick.CREW_BIN = tick.CREW_BIN, "/nonexistent/crew"
    try:
        check("missing binary -> []", tick.pending_via_crew("whatever") == [])
    finally:
        tick.CREW_BIN = real


def test_waiting_notify_enabled():
    check("NOTIFY_WAITING on", tick.NOTIFY_WAITING is True)


def test_question_body_renders_as_lines():
    """The pinger sends the question through _clean/split_report — must survive."""
    p = write_jsonl([tool_use("t2", "AskUserQuestion", ASK)])
    got = tick.pending_prompt(p)
    lines = tick._clean(got[1])
    text = "\n".join(t for _, t in lines)
    check("rendered body keeps question", "unlock" in text)
    check("rendered body keeps all options",
          all(o in text for o in ("Deep Time", "Ten Thousand Years", "The Long Sweep")), text)
    parts = tick.split_report("🙋 orrery-4c · needs your answer", lines)
    check("question fits one message", len(parts) == 1, f"{len(parts)}")
    os.unlink(p)


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        print(fn.__name__)
        fn()
    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} — {FAILED}")
        sys.exit(1)
    print("all green")
