import tick

def _setup(monkeypatch, exp):
    sent = []
    monkeypatch.setattr(tick, "send", lambda t, c, m, parse_mode=None: sent.append(m) or True)
    monkeypatch.setattr(tick, "load_token", lambda: "x")
    monkeypatch.setattr(tick, "load_chats", lambda: ["1"])
    monkeypatch.setattr(tick, "login_expires_at", lambda: exp)
    return sent

def test_thresholds_fire_once_each(monkeypatch):
    sent, st, exp = _setup(monkeypatch, 1_000_000.0), {}, 1_000_000.0
    for now in (exp - 100*3600, exp - 70*3600, exp - 69*3600, exp - 20*3600, exp + 10):
        st["login_alert"] = tick.check_login_expiry(now, st)
    assert len(sent) == 3 and "EXPIRED" in sent[-1]

def test_rearms_after_new_login(monkeypatch):
    sent, st = _setup(monkeypatch, 1_000_000.0), {}
    st["login_alert"] = tick.check_login_expiry(1_000_010.0, st)
    monkeypatch.setattr(tick, "login_expires_at", lambda: 2_000_000.0)
    st["login_alert"] = tick.check_login_expiry(2_000_000.0 - 70*3600, st)
    assert len(sent) == 2
