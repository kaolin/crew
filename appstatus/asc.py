#!/usr/bin/env python3
"""Minimal App Store Connect client for the hub."""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

import jwt

KEY_ID = "GAGZAJHNKX"
ISSUER = "69a6de76-9d85-47e3-e053-5b8c7c11a4d1"
KEY_PATH = os.path.expanduser(f"~/.appstoreconnect/private_keys/AuthKey_{KEY_ID}.p8")
BASE = "https://api.appstoreconnect.apple.com/v1"


def token():
    key = open(KEY_PATH).read()
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1"},
        key, algorithm="ES256", headers={"kid": KEY_ID, "typ": "JWT"},
    )


TOK = token()


def call(method, path, body=None, params=None):
    url = path if path.startswith("http") else f"{BASE}{path}"
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOK}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode(errors="replace")[:400]}


def paged(path, params=None):
    out, url = [], path
    p = dict(params or {}, limit=200)
    while url:
        st, d = call("GET", url, params=p if url == path else None)
        if st != 200:
            raise SystemExit(f"GET {url} -> {st} {json.dumps(d)[:300]}")
        out += d.get("data", [])
        url = (d.get("links") or {}).get("next")
        p = None
    return out


if __name__ == "__main__":
    print(json.dumps(paged("/apps", {"fields[apps]": "name,bundleId"}), indent=1)[:200])
