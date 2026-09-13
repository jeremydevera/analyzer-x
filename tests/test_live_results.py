"""Results land on this PC WHILE the machines are still measuring.

The operator, Sep 09, 2026: *"why not immediately put the results in my pc"*,
then *"i want it open then, i want you to post the result immediately to my
pc"*. Before this, a machine's rows sat in a GitHub artifact until the whole
machine finished, this PC asked "anything done?" every five minutes, and then
spent an hour importing — run 34307921614 finished at 7:32am and was still
landing at 10:42pm.

These tests drive the door the way a GitHub machine drives it: a real socket, a
real gzip body, the real token check — never a stubbed handler, because the
thing being trusted here is an address on the internet.
"""
import gzip
import importlib.util
import json
import pathlib
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tradingagents import cloud_sweep as cs, live_ingest as li, market_sweep as msw

REPO = pathlib.Path(__file__).resolve().parents[1]
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"
YML = REPO / ".github" / "workflows" / "sweep.yml"
PANEL = REPO / "webapp" / "src" / "components" / "backtest" / "JobsPanel.tsx"
API_TS = REPO / "webapp" / "src" / "lib" / "api.ts"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A scratch store AND a scratch secret: never the operator's own."""
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    (tmp_path / "state").mkdir()
    (tmp_path / "rows").mkdir()
    monkeypatch.setattr(li, "HOME", tmp_path)
    monkeypatch.setattr(li, "TOKEN_FILE", tmp_path / "ingest_token")
    monkeypatch.setattr(li, "URL_FILE", tmp_path / "ingest_url.json")
    monkeypatch.setattr(li, "PROGRESS_FILE", tmp_path / "ingest_progress.json")
    return tmp_path


def _rows(coin="AAA", tf="1h", last_ms=1_000, n=3):
    out = [json.dumps({"coin": coin, "tf": tf, "signal": f"s{i}", "tp": 0.4,
                       "sl": 0.3, "profit": 1.0 * i, "trades": 10 + i,
                       "last_ms": last_ms}) + "\n" for i in range(n)]
    out.append(json.dumps({"coin": coin, "tf": tf, "pair_done": True,
                           "rows": n, "last_ms": last_ms}) + "\n")
    return out


@pytest.fixture
def door(store):
    """The real listener on a real socket, with no tunnel in front of it."""
    li.token()                                   # make the scratch secret
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), li.Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(url, body, token="", run="7", path="/rows", sig=None):
    headers = {"Content-Type": "application/octet-stream", "X-Run-Id": run}
    if token or sig:
        headers["X-Ingest-Sig"] = sig or li.sign(token, path.rstrip("/") or "/", body)
    req = urllib.request.Request(url + path, data=body, method="POST",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read().decode() or "{}")


# --------------------------------------------------------------- the door
@pytest.mark.integration
def test_a_posted_pair_is_in_the_store_before_the_run_ends(door, store):
    """The whole point: one machine finishes one coin, and the coin is in the
    store seconds later — not when all twenty machines stop."""
    code, got = _post(door, gzip.compress("".join(_rows()).encode()), li.token())
    assert code == 200 and got["pairs"] == 1 and got["rows"] == 3
    assert len(msw.pair_rows("AAA", "1h")) == 3
    assert msw.pair_watermark("AAA", "1h") == 1_000, \
        "the watermark is what stops the artifact landing the same pair twice"
    prog = li.progress()
    assert prog["run"] == "7" and prog["pairs"] == 1 and prog["rows"] == 3
    assert prog["last"] == "AAA 1h"


@pytest.mark.integration
def test_the_same_pair_posted_twice_is_written_once(door, store):
    """A machine that retries a post, or an artifact collected afterwards,
    must not double the rows: equal is not newer."""
    _post(door, gzip.compress("".join(_rows()).encode()), li.token())
    code, got = _post(door, gzip.compress("".join(_rows()).encode()), li.token())
    assert code == 200 and got["pairs"] == 0 and got["stale"] == 1
    assert len(msw.pair_rows("AAA", "1h")) == 3
    # and the artifact path, arriving later, refuses it by the same rule
    assert cs.land_rows("AAA", "1h", [json.loads(x) for x in _rows()[:3]]) == "stale"


@pytest.mark.integration
def test_a_newer_measurement_still_wins(door, store):
    _post(door, gzip.compress("".join(_rows(last_ms=1_000)).encode()), li.token())
    code, got = _post(door, gzip.compress(
        "".join(_rows(last_ms=2_000, n=5)).encode()), li.token())
    assert code == 200 and got["pairs"] == 1
    assert len(msw.pair_rows("AAA", "1h")) == 5
    assert msw.pair_watermark("AAA", "1h") == 2_000


@pytest.mark.integration
def test_no_token_no_write(door, store):
    """The address is PUBLIC — it is handed to GitHub as a workflow input and
    anyone can read it. The secret is the whole guard."""
    body = gzip.compress("".join(_rows()).encode())
    # a secret that is DEFINITELY not this one: flipping the last character to
    # a fixed digit matches the real token once every sixteen runs, and a test
    # that passes fifteen times in sixteen is worse than none
    for tok in ("wrong", "deadbeef" + li.token()):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(door, body, tok)
        assert exc.value.code == 401, "a signature from another secret"
    for bad in ("", "0" * 64, li.sign(li.token(), "/rows", b"other bytes"),
                li.sign(li.token(), "/up", body), li.token()):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(door, body, sig=bad or None, token="" if bad else "")
        assert exc.value.code == 401, bad[:16]
    assert li.token() not in str(body), "and the secret itself is never sent"
    assert msw.pair_rows("AAA", "1h") == []
    assert li.progress() == {}


@pytest.mark.integration
def test_only_two_things_answer_at_all(door, store):
    """Nothing here reads a key, moves money or touches the runner: the door
    is POST /rows and GET /up, and everything else is 404 — including the
    paths a scanner tries first."""
    body = gzip.compress(b"")
    for path in ("/", "/api/positions", "/api/credentials", "/rows/../x",
                 "/api/jobs/backtest"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(door, body, li.token(), path=path)
        assert exc.value.code == 404, path
    req = urllib.request.Request(
        door + "/up", headers={"X-Ingest-Sig": li.sign(li.token(), "/up")})
    with urllib.request.urlopen(req, timeout=20) as r:
        assert r.status == 200 and json.loads(r.read())["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(door + "/up", timeout=20)
    assert exc.value.code == 401, "even 'are you there' needs the secret"


@pytest.mark.integration
def test_rubbish_is_counted_and_dropped_not_stored(door, store):
    """A line that is not a row, a timeframe that is not a timeframe, a coin
    name that is a path — none of them may reach the store."""
    lines = ["not json\n",
             json.dumps({"coin": "AAA", "tf": "nope", "last_ms": 9}) + "\n",
             json.dumps({"coin": "../../etc", "tf": "1h", "last_ms": 9}) + "\n",
             json.dumps({"coin": "AAA", "tf": "1h", "signal": "s", "last_ms": 9}) + "\n"]
    code, got = _post(door, gzip.compress("".join(lines).encode()), li.token())
    assert code == 200 and got["bad"] == 3 and got["pairs"] == 1
    assert [p.name for p in (store / "rows").iterdir()] == ["AAA-1h.json"]


@pytest.mark.integration
def test_a_body_that_is_not_ours_is_refused_without_a_stack_trace(door, store):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(door, b"not gzip at all", li.token())
    assert exc.value.code == 500
    assert msw.pair_rows("AAA", "1h") == []
    # an empty body never even reaches the reader
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(door, b"", li.token())
    assert exc.value.code == 413


def test_a_name_this_router_will_not_look_up_is_not_a_shut_door(store, monkeypatch):
    """Measured on this PC, Sep 09, 2026 11:15pm: the tunnel registered fine
    and the router's resolver (globebroadband.net) still answered "Non-existent
    domain" for the new *.trycloudflare.com name, which 1.1.1.1 resolved in
    milliseconds. GitHub's machines resolve it fine, so refusing to open the
    door over that would be this PC's DNS deciding the feature is off."""
    li.token()
    tried = []

    def no_dns(req, timeout=0):
        raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")

    monkeypatch.setattr(li.urllib.request, "urlopen", no_dns)
    monkeypatch.setattr(li, "_up_over_doh",
                        lambda url, t: tried.append(url) or (200, '{"ok": true}'))
    assert li.reachable("https://abc.trycloudflare.com") == ""
    assert tried == ["https://abc.trycloudflare.com"]

    # any OTHER failure is still a failure — a shut door must never read as open
    def refused(req, timeout=0):
        raise ConnectionRefusedError("no listener")

    monkeypatch.setattr(li.urllib.request, "urlopen", refused)
    assert "ConnectionRefusedError" in li.reachable("https://abc.trycloudflare.com")
    monkeypatch.setattr(li.urllib.request, "urlopen", no_dns)
    monkeypatch.setattr(li, "_up_over_doh", lambda url, t: (404, "nope"))
    assert "404" in li.reachable("https://abc.trycloudflare.com")


def test_the_door_is_never_opened_by_a_test_run(monkeypatch):
    """`ensure()` starts a process and an address on the internet. A suite that
    reaches a dispatch by accident must not do that on someone's laptop."""
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "yes")
    monkeypatch.setattr(li.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("a test opened the door"))
    got = li.ensure()
    assert got["url"] == "" and "test" in got["why"]


# -------------------------------------------------------------- the machine
@pytest.fixture
def shard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k, v in {"SHARD": "0", "SHARDS": "1", "TFS": "1h", "DAYS": "60",
                 "MODE": "full", "STATE_RUNS": "",
                 "INGEST_URL": "https://x.trycloudflare.com/",
                 "INGEST_TOKEN": "sekret", "GITHUB_RUN_ID": "99"}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("sweep_shard_live_test", SHARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "report", lambda *a, **k: None)
    return mod


class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def test_a_machine_posts_the_pair_it_just_finished(shard, monkeypatch):
    sent = []
    monkeypatch.setattr(shard.urllib.request if hasattr(shard, "urllib") else
                        __import__("urllib.request", fromlist=["request"]),
                        "urlopen", lambda req, timeout=0: sent.append(req) or _Resp())
    lines = _rows(coin="ZZZ")
    assert shard.post_pair("ZZZ", "1h", lines) is True
    req = sent[0]
    assert req.full_url == "https://x.trycloudflare.com/rows", "no double slash"
    import hashlib
    import hmac
    assert req.get_header("X-ingest-sig") == hmac.new(
        b"sekret", b"/rows" + req.data, hashlib.sha256).hexdigest(),         "the shard and live_ingest.sign must compute one signature"
    assert "sekret" not in str(dict(req.header_items())),         "the secret itself must never go on the wire"
    assert req.get_header("X-run-id") == "99"
    assert req.get_header("Content-encoding") is None, \
        "a proxy would unzip that on the way and the receiver gets bytes it cannot read"
    assert gzip.decompress(req.data).decode() == "".join(lines)
    assert shard.report.posted == 1


def test_the_artifact_is_written_before_the_post_and_whatever_the_post_does():
    """The post is speed; the artifact is the record. If the order were the
    other way round, a machine killed mid-post would lose the pair — and a PC
    that is asleep would lose the run."""
    src = SHARD.read_text(encoding="utf-8")
    calls = list(_finds(src, "\n    post_pair(coin, tf, lines)"))
    assert len(calls) == 2, "both the full path and the continuation post their pair"
    for i in calls:
        before = src[:i]
        w = before.rindex("out.write(")
        assert w > before.rindex("\ndef "), \
            "the artifact write must come first, inside the same function"
        assert "out.flush()" in src[w:i], "and be flushed before the copy leaves"


def _finds(hay, needle):
    at = 0
    while True:
        i = hay.find(needle, at)
        if i < 0:
            return
        yield i
        at = i + 1


def test_a_door_that_answers_401_turns_posting_off_for_the_rest_of_the_run(shard, monkeypatch):
    """A wrong secret cannot cost 5,000 doomed posts: the machine says so once
    and finishes on artifacts alone."""
    tries = []

    def boom(req, timeout=0):
        tries.append(req)
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

    monkeypatch.setattr(__import__("urllib.request", fromlist=["request"]),
                        "urlopen", boom)
    assert shard.post_pair("ZZZ", "1h", _rows()) is False
    assert len(tries) == 1, "401 is not retried"
    assert shard.INGEST_URL == ""
    assert shard.post_pair("ZZZ", "1h", _rows()) is False
    assert len(tries) == 1, "and nothing is attempted after that"
    assert shard.report.post_failed == 1


def test_a_network_blip_is_retried_then_let_go(shard, monkeypatch):
    tries = []

    def flaky(req, timeout=0):
        tries.append(req)
        raise TimeoutError("the tunnel went quiet")

    monkeypatch.setattr(__import__("urllib.request", fromlist=["request"]),
                        "urlopen", flaky)
    monkeypatch.setattr(shard.time, "sleep", lambda s: None)
    assert shard.post_pair("ZZZ", "1h", _rows()) is False
    assert len(tries) == shard.INGEST_TRIES
    assert shard.INGEST_URL, "a blip must NOT switch live posting off"


def test_no_url_no_post(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for k, v in {"SHARD": "0", "SHARDS": "1", "TFS": "1h", "INGEST_URL": "",
                 "INGEST_TOKEN": ""}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("sweep_shard_nolive", SHARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(__import__("urllib.request", fromlist=["request"]),
                        "urlopen", lambda *a, **k: pytest.fail("posted with no url"))
    assert mod.post_pair("ZZZ", "1h", _rows()) is False


# ------------------------------------------------------------- the wiring
def test_the_workflow_carries_the_url_in_and_the_secret_from_the_repository():
    y = YML.read_text(encoding="utf-8")
    assert "ingest_url:" in y
    assert "INGEST_URL: ${{ github.event.inputs.ingest_url }}" in y
    assert "INGEST_TOKEN: ${{ secrets.INGEST_TOKEN }}" in y, \
        "the secret must come from the repository, never an input — inputs are " \
        "printed in the run's own log"
    assert "${{ github.event.inputs.ingest_token }}" not in y


def test_the_dispatch_opens_the_door_and_says_when_it_could_not(monkeypatch):
    import inspect

    calls = []
    seen = []
    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: calls.append(a) or "[]")
    # the run before the dispatch, then the new one it started
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=5: seen.append(1) or [
        {"databaseId": 4 if len(seen) == 1 else 5, "url": "u", "status": "queued"}])
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    monkeypatch.setattr(li, "ensure",
                        lambda **k: {"url": "https://abc.trycloudflare.com", "why": ""})
    monkeypatch.setattr(li, "sync_secret", lambda slug="": "")
    got = cs.dispatch(shards=1, timeframes="1h")
    assert got["live"] is True
    flat = [x for c in calls for x in c]
    assert "ingest_url=https://abc.trycloudflare.com" in flat

    # and when the door cannot open, the run STILL GOES — with the reason said
    calls.clear()
    seen.clear()
    monkeypatch.setattr(li, "ensure",
                        lambda **k: {"url": "", "why": "no tunnel program"})
    got = cs.dispatch(shards=1, timeframes="1h")
    assert got["live"] is False and "no tunnel" in got["live_why"]
    assert "ingest_url=" in [x for c in calls for x in c]
    assert "live" in inspect.signature(cs.dispatch).parameters


def test_a_token_this_pc_rotated_is_pushed_to_github(store, monkeypatch):
    """The machines read `secrets.INGEST_TOKEN`. A token made here and never
    pushed is 401 on every post, and the run quietly falls back to artifacts."""
    sent = []
    monkeypatch.setattr(cs, "_gh", lambda *a, **k: sent.append(a) or "")
    monkeypatch.setattr(cs, "repo_slug", lambda cwd=None: "me/repo")
    assert li.sync_secret() == ""
    assert sent and sent[0][:3] == ("secret", "set", "INGEST_TOKEN")
    assert li.token() in sent[0]
    assert li.sync_secret() == "", "unchanged: nothing to push"
    assert len(sent) == 1
    (store / "ingest_token").write_text("a-new-one")
    assert li.sync_secret() == ""
    assert len(sent) == 2, "a rotated token is pushed"


def test_the_panel_prints_what_THIS_PC_received():
    """label-must-match-data: the count beside "landing here" has to be the
    receiver's own tally, not the machines' claim of what they sent."""
    p = PANEL.read_text(encoding="utf-8")
    i = p.index("results are landing here")
    block = p[i - 1500:i + 900]
    assert "cloud.live" in block
    assert "live.pairs" in block and "live.rows" in block
    # a coin that arrived ALREADY UP TO DATE is a success, and saying only
    # "0 written" made a working door read as broken (run 34370227474)
    assert "live.stale" in block and "already up to date" in block
    assert "nothing has arrived yet" in block, \
        "before the first coin, say that — not '0 written'"
    assert "s.posted" not in p[i:i + 900], \
        "the machines' own count must not be printed as what landed"
    assert "post_failed" in block, "a post that never arrived is named, not hidden"
    t = API_TS.read_text(encoding="utf-8")
    assert "live?: {" in t and "posted?: number;" in t


def test_the_api_only_shows_a_tally_that_belongs_to_the_run_on_screen():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api._read_cloud_status)
    i = src.index('out["live"]')
    block = src[i:src.index("return out", i)]
    assert 'str(prog.get("run") or "") == rid' in block, \
        "an earlier run's count under this run's name is the label bug this " \
        "repo keeps paying for"
    assert '"open": bool(got.get("open"))' in block, \
        "whether the door is open is read from the receiver, not assumed"
