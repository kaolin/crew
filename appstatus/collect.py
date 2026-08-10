#!/usr/bin/env python3
"""Collect the true state of every app across App Store, TestFlight and Play.

Run headless on a timer. Writes status.json and status.html, and exits 10 when
anything changed since the last run so a watcher knows there is news.

The one non-obvious rule in here: App Store Connect cannot tell you whether an
app is on sale. A delisted app keeps appStoreState READY_FOR_SALE and its full
territory list — Crashteroids, TumbleDots and Missile VR all read as fully
available while being absent from the store. The public storefront is the only
honest source, so availability comes from the iTunes lookup.
"""
import datetime, json, os, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asc import call, paged                                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "status.json")
PLAY_KEY = os.path.expanduser("~/keys/play-claude-appdev-820105877775.json")
PLAY_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"

QUEUE_STATES = {"WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_APPLE_RELEASE",
                "PENDING_DEVELOPER_RELEASE", "PROCESSING_FOR_APP_STORE"}
SETTLED = {"REPLACED_WITH_NEW_VERSION", "READY_FOR_SALE"}


def iso_ago(iso):
    if not iso:
        return None
    t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    h = (time.time() - t.timestamp()) / 3600
    return round(h, 1)


def storefront(app_id, country="us"):
    """True/False if the app is really buyable; None if the lookup failed."""
    url = "https://itunes.apple.com/lookup?" + urllib.parse.urlencode(
        {"id": app_id, "country": country})
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            return bool(json.loads(r.read().decode()).get("results"))
    except Exception:
        return None


def play_tracks():
    """{package: [track strings]} for the Android apps we can see."""
    try:
        import jwt
    except ImportError:
        return {}
    if not os.path.exists(PLAY_KEY):
        return {}
    sa = json.load(open(PLAY_KEY))
    now = int(time.time())
    assertion = jwt.encode({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/androidpublisher",
        "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600,
    }, sa["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion}).encode()
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=30) as r:
            tok = json.loads(r.read())["access_token"]
    except Exception:
        return {}

    # Package names are CASE-SENSITIVE and don't always match the iOS bundle id.
    # "org.erif.SpotTheHustle" returns 403 (a package this account can't see);
    # the real one is lowercase, and reporting the 403 as "may exist unseen"
    # was wrong — it exists, in alpha.
    out = {}
    for pkg in ("com.fractroam", "org.erif.izzit", "org.erif.spotthehustle"):
        try:
            req = urllib.request.Request(f"{PLAY_BASE}/{pkg}/edits", method="POST")
            req.add_header("Authorization", f"Bearer {tok}")
            with urllib.request.urlopen(req, timeout=30) as r:
                eid = json.loads(r.read())["id"]
        except Exception:
            continue
        try:
            req = urllib.request.Request(f"{PLAY_BASE}/{pkg}/edits/{eid}/tracks")
            req.add_header("Authorization", f"Bearer {tok}")
            with urllib.request.urlopen(req, timeout=30) as r:
                tracks = json.loads(r.read()).get("tracks") or []
            out[pkg] = [{"track": t["track"], "status": rel.get("status"),
                         "name": rel.get("name"),
                         "codes": rel.get("versionCodes") or []}
                        for t in tracks for rel in (t.get("releases") or [])]
        except Exception:
            pass
        try:
            req = urllib.request.Request(f"{PLAY_BASE}/{pkg}/edits/{eid}", method="DELETE")
            req.add_header("Authorization", f"Bearer {tok}")
            urllib.request.urlopen(req, timeout=20)
        except Exception:
            pass
    return out


def collect():
    apps = []
    submissions = {}
    for a in sorted(paged("/apps", {"fields[apps]": "name,bundleId"}),
                    key=lambda x: x["attributes"]["name"].lower()):
        aid, at = a["id"], a["attributes"]
        vs = paged(f"/apps/{aid}/appStoreVersions",
                   {"fields[appStoreVersions]": "versionString,appStoreState"})
        states = [(v["attributes"]["versionString"], v["attributes"]["appStoreState"]) for v in vs]
        live = next((v for v, s in states if s == "READY_FOR_SALE"), None)
        queue = next(((v, s) for v, s in states if s in QUEUE_STATES), None)
        draft = next(((v, s) for v, s in states if s not in QUEUE_STATES and s not in SETTLED), None)

        # queue age: the review submission, not the version's created date.
        # Also which BUILD is attached — "2.1 in review" doesn't say whether
        # that's the build testers have.
        wait_h = None
        queue_build = None
        if queue:
            qv = next((v for v in vs
                       if v["attributes"]["versionString"] == queue[0]
                       and v["attributes"]["appStoreState"] == queue[1]), None)
            if qv:
                st, d = call("GET", f"/appStoreVersions/{qv['id']}/build",
                             params={"fields[builds]": "version"})
                if st == 200:
                    queue_build = ((d.get("data") or {}).get("attributes") or {}).get("version")
        if queue:
            subs = [r for r in paged("/reviewSubmissions",
                                     {"filter[app]": aid,
                                      "fields[reviewSubmissions]": "state,submittedDate",
                                      "limit": 10})
                    if r["attributes"].get("submittedDate")]
            subs.sort(key=lambda r: r["attributes"]["submittedDate"], reverse=True)
            if subs:
                wait_h = iso_ago(subs[0]["attributes"]["submittedDate"])

        # newest unexpired build + its marketing version. This endpoint rejects
        # both `sort` and `include`, and is not newest-first, so sort here.
        builds = paged(f"/apps/{aid}/builds",
                       {"fields[builds]": "version,uploadedDate,expired,expirationDate"})
        builds.sort(key=lambda b: b["attributes"].get("uploadedDate") or "", reverse=True)
        fresh = [b for b in builds if not b["attributes"].get("expired")]
        tf = None
        if fresh:
            b = fresh[0]
            mv = None
            st, d = call("GET", f"/builds/{b['id']}/preReleaseVersion",
                         params={"fields[preReleaseVersions]": "version"})
            if st == 200:
                mv = ((d.get("data") or {}).get("attributes") or {}).get("version")
            tf = {"version": mv, "build": b["attributes"].get("version"),
                  "age_h": iso_ago(b["attributes"].get("uploadedDate")),
                  "expires": (b["attributes"].get("expirationDate") or "")[:10]}
        elif builds:
            tf = {"expired": True,
                  "last": builds[0]["attributes"].get("version"),
                  "age_h": iso_ago(builds[0]["attributes"].get("uploadedDate"))}

        on_sale = storefront(aid) if live else False
        terr = None
        if live:
            st, d = call("GET",
                         f"https://api.appstoreconnect.apple.com/v2/appAvailabilities/{aid}"
                         f"/territoryAvailabilities",
                         params={"fields[territoryAvailabilities]": "available", "limit": 200})
            if st == 200:
                rows = d.get("data", [])
                terr = [sum(1 for t in rows if t["attributes"].get("available")), len(rows)]

        apps.append(dict(name=at["name"], bundle=at["bundleId"], appId=aid,
                         live=live, onSale=on_sale, territories=terr,
                         queue=queue, queueBuild=queue_build, waitHours=wait_h,
                         draft=draft, testflight=tf,
                         everSubmitted=bool(live or queue)))
    return dict(generated=datetime.datetime.now().isoformat(timespec="seconds"),
                apps=apps, play=play_tracks())


def signature(data):
    """What counts as a change worth waking someone for: states and versions,
    not clocks. Queue ages tick every run and are not news.

    Compared through JSON, because a tuple written to disk reads back as a
    list — comparing the live objects reported all 20 apps as changed on every
    single run, which is the same as no detector at all."""
    return json.dumps([[a["name"], a["live"], a["onSale"], a["queue"],
                        a.get("queueBuild"), a["draft"],
                        (a["testflight"] or {}).get("build")] for a in data["apps"]],
                      sort_keys=True)


if __name__ == "__main__":
    data = collect()
    old = None
    if os.path.exists(OUT_JSON):
        try:
            old = json.load(open(OUT_JSON))
        except ValueError:
            pass
    changed = old is None or signature(old) != signature(data)
    json.dump(data, open(OUT_JSON, "w"), indent=1)

    if changed and old:
        import itertools
        for a, b in itertools.zip_longest(json.loads(signature(old)),
                                          json.loads(signature(data))):
            if a != b:
                print(f"CHANGED {(a or b)[0]}: {(a or [])[1:]} -> {(b or [])[1:]}")
    print(f"{len(data['apps'])} apps · {'CHANGED' if changed else 'no change'}")
    sys.exit(10 if changed else 0)
