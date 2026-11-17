#!/usr/bin/env python3
"""Tests for per-app Telegram forum topics in the pinger (kaolin #9970, 2026-11-15).

Each app's page goes into its own topic, created on first use and remembered
in tg-topics.json. Pages that need him (🔐 permission, 🙋 question) ALSO go to
the main chat. No topic -- mode off, createForumTopic failing, or a topic he
deleted -- falls back to the main chat, as it was before topics.

The Telegram API is faked at urlopen; nothing is sent.

Run: python3 pinger/test_topics.py
"""
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tick  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILED.append(name)


class FakeAPI:
    """Records every call; createForumTopic hands out ids from 100 up."""

    def __init__(self, create_ok=True, gone_threads=(), md_ok=True):
        self.calls = []
        self.create_ok = create_ok
        self.gone = set(gone_threads)
        self.md_ok = md_ok
        self.next_id = 100

    def urlopen(self, req, timeout=None):
        method = req.full_url.rsplit("/", 1)[1]
        if method == "sendPhoto":
            body = req.data.decode("latin-1")
            fields = {"thread": "message_thread_id" in body}
        else:
            fields = dict(urllib.parse.parse_qsl(req.data.decode()))
        self.calls.append((method, fields))
        if method == "createForumTopic":
            if not self.create_ok:
                raise self._err(req, "Bad Request: the chat is not a forum")
            self.next_id += 1
            return io.BytesIO(json.dumps(
                {"ok": True, "result": {"message_thread_id": self.next_id}}).encode())
        if method == "sendMessage":
            t = fields.get("message_thread_id")
            if t is not None and int(t) in self.gone:
                raise self._err(req, "Bad Request: message thread not found")
            if fields.get("parse_mode") and not self.md_ok:
                raise self._err(req, "Bad Request: can't parse entities")
        return io.BytesIO(b'{"ok":true,"result":{}}')

    @staticmethod
    def _err(req, desc):
        return urllib.error.HTTPError(
            req.full_url, 400, desc, {},
            io.BytesIO(json.dumps({"ok": False, "description": desc}).encode()))

    def sends(self):
        """[(thread_id or None, text)] for sendMessage calls."""
        return [(f.get("message_thread_id"), f.get("text")) for m, f in self.calls
                if m == "sendMessage"]

    def creates(self):
        return [f["name"] for m, f in self.calls if m == "createForumTopic"]


def run(api, kind="✅", app="BabyPaints", topics=None, photos=()):
    tick.urllib.request.urlopen = api.urlopen
    topics = {} if topics is None else topics
    n = tick.deliver_app_page("tok", "111222333", kind, app,
                              ["*md* page"], ["plain page"], list(photos),
                              "cap", topics)
    return topics, n


def fresh_topics_file():
    d = tempfile.mkdtemp(prefix="crew-topics-")
    tick.TOPICS_PATH = os.path.join(d, "tg-topics.json")
    tick.LOG_PATH = os.path.join(d, "pinger.log")
    return tick.TOPICS_PATH


def test_first_page_creates_topic_and_posts_there():
    path = fresh_topics_file()
    api = FakeAPI()
    topics, _ = run(api)
    check("topic created once, named after the app", api.creates() == ["BabyPaints"], api.creates())
    check("page went to the new topic only", api.sends() == [("101", "*md* page")], api.sends())
    saved = json.load(open(path))
    check("mapping saved for the hub to read", saved == {"111222333": {"BabyPaints": 101}}, saved)


def test_title_override_names_the_topic():
    fresh_topics_file()
    api = FakeAPI()
    topics, _ = run(api, app="tgthreads")
    check("override title used", api.creates() == ["Threads"], api.creates())
    check("still keyed by session name", "tgthreads" in topics["111222333"], topics)


def test_known_topic_is_reused():
    fresh_topics_file()
    api = FakeAPI()
    run(api, topics={"111222333": {"BabyPaints": 55}})
    check("no new topic for a known app", api.creates() == [], api.creates())
    check("page went to the known topic", api.sends() == [("55", "*md* page")], api.sends())


def test_permission_page_goes_to_topic_and_main():
    fresh_topics_file()
    for kind in ("🔐", "🙋"):
        api = FakeAPI()
        run(api, kind=kind, topics={"111222333": {"BabyPaints": 55}})
        check(f"{kind} page in topic AND main chat",
              api.sends() == [("55", "*md* page"), (None, "*md* page")], api.sends())


def test_create_failure_falls_back_to_main():
    path = fresh_topics_file()
    api = FakeAPI(create_ok=False)
    topics, _ = run(api)
    check("topic mode off -> main chat", api.sends() == [(None, "*md* page")], api.sends())
    check("nothing remembered on failure", not os.path.exists(path) and topics.get("111222333") == {}, topics)


def test_deleted_topic_is_forgotten_and_page_still_arrives():
    path = fresh_topics_file()
    api = FakeAPI(gone_threads={55})
    topics, _ = run(api, topics={"111222333": {"BabyPaints": 55, "Other": 7}})
    check("page re-sent to main after topic vanished",
          api.sends() == [("55", "*md* page"), (None, "*md* page")], api.sends())
    check("dead topic forgotten, others kept", topics == {"111222333": {"Other": 7}}, topics)
    check("forgetting persisted", json.load(open(path)) == {"111222333": {"Other": 7}})


def test_markdown_fallback_stays_in_topic():
    fresh_topics_file()
    api = FakeAPI(md_ok=False)
    run(api, topics={"111222333": {"BabyPaints": 55}})
    check("plain fallback keeps the thread",
          api.sends() == [("55", "*md* page"), ("55", "plain page")], api.sends())


def test_switch_off_means_main_only():
    fresh_topics_file()
    tick.TG_APP_TOPICS = False
    try:
        api = FakeAPI()
        run(api, topics={"111222333": {"BabyPaints": 55}})
        check("TG_APP_TOPICS=False -> main chat, no create",
              api.sends() == [(None, "*md* page")] and api.creates() == [], api.calls)
    finally:
        tick.TG_APP_TOPICS = True


def test_photos_follow_the_page_into_topic():
    fresh_topics_file()
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    f.write(b"\x89PNG fake"); f.close()
    api = FakeAPI()
    _, n = run(api, topics={"111222333": {"BabyPaints": 55}}, photos=[f.name])
    photo_calls = [fl for m, fl in api.calls if m == "sendPhoto"]
    check("photo sent into the topic", n == 1 and photo_calls == [{"thread": True}], photo_calls)
    api = FakeAPI(create_ok=False)
    run(api, photos=[f.name])
    photo_calls = [fl for m, fl in api.calls if m == "sendPhoto"]
    check("photo without a topic has no thread field", photo_calls == [{"thread": False}], photo_calls)


if __name__ == "__main__":
    real = tick.urllib.request.urlopen
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_") and callable(fn):
                print(name)
                fn()
    finally:
        tick.urllib.request.urlopen = real
    if FAILED:
        print(f"{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("all green")
