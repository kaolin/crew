# appstatus

Where every app stands, across App Store, TestFlight and Google Play.

    python3 collect.py     # hits the APIs, writes status.json, exit 10 = something changed
    python3 render.py      # status.json -> status.html, no network

`collect.py` is the only part that needs credentials (the ASC key in
`~/.appstoreconnect/private_keys/`, the Play service account in `~/keys/`).
`render.py` is pure, so the page can be rebuilt from a stored snapshot.

## Two things that are easy to get wrong

**App Store Connect cannot tell you whether an app is on sale.** A delisted app
keeps `appStoreState: READY_FOR_SALE` *and* its full 175-territory list forever.
Crashteroids, TumbleDots and Missile VR all read as fully available to the API
while being absent from the store. Availability therefore comes from the public
iTunes lookup — the storefront is the only honest source.

**Play package names are case-sensitive and don't always match the iOS bundle
id.** `org.erif.SpotTheHustle` returns 403 — a different package this service
account can't see. The real one is `org.erif.spotthehustle`.

Also: the builds endpoint rejects both `sort` and `include`, and isn't
newest-first, so builds are sorted client-side; and queue ages come from
`reviewSubmissions.submittedDate`, not the version's `createdDate`, which is
when the record was drafted and reads days too old.

## Keeping it fresh

Run `collect.py` on a timer. Exit 10 means a state actually changed — versions,
availability, queue membership, TestFlight build — as opposed to clocks ticking,
which are deliberately excluded from the change signature. Wire that exit code to
whatever should react; the only step that still needs a Claude session is
republishing the artifact, which is one turn.
