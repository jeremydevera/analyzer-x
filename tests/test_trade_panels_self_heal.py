"""A dark moment must not paint the terminal red until someone reloads.

Sep 09, 2026: the API was restarted (a fix landing) while the operator's tab
was open; they clicked Auto Trade inside the few seconds it was down, the
proxy answered 500 for every panel, and three panels — credentials, trade
history, PnL — fetch exactly once, so the whole screen wore that dead
moment's errors indefinitely. The polling panels healed in seconds.
"""

API = "webapp/src/lib/api.ts"


def _p(name: str) -> str:
    return open(f"webapp/src/components/trade/{name}.tsx", encoding="utf-8").read()


def test_a_get_tries_a_second_time_after_a_restart_blip():
    s = open(API, encoding="utf-8").read()
    i = s.index("async function get<T>")
    body = s[i:s.index("async function post<T>")]
    assert body.count("await fetchLaned(") == 2, "one retry, not a loop"
    assert "r.status === 500 || r.status === 502 || r.status === 504" in body
    retry_if = [l for l in body.splitlines() if "r.status ===" in l]
    assert len(retry_if) == 1 and "503" not in retry_if[0], \
        "503 carries a sentence the panels show — never retried away"


def test_a_post_is_never_retried():
    """A second submit is a second order."""
    s = open(API, encoding="utf-8").read()
    i = s.index("async function post<T>")
    j = s.index("async function postDetail<T>")
    assert s[i:j].count("fetchLaned(") == 1
    assert s[j:s.index("// ---", j)].count("fetchLaned(") == 1


def test_the_one_shot_panels_heal_themselves():
    for name in ("TradeHistory", "PnlPanel", "CredentialsPanel"):
        p = _p(name)
        assert "SELF-HEALING" in p, name
        assert "5_000" in p, name


def test_a_healing_reload_cannot_wipe_a_save_error():
    """CredentialsPanel's save() sets the same `err`; the healer only runs
    while NOTHING has loaded (`!st`), so a save failure stays on screen."""
    p = _p("CredentialsPanel")
    assert "if (!err || st) return;" in p
