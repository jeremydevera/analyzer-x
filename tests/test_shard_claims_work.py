"""A finished machine takes the next coin — it never sits idle on a slice.

Operator, 2026-09-06, RCA'd on run 34004227228: *"Why is it idle did not i
mentioned if the machine is 100% take a new job i want rca for this"*.

What happened, from GitHub's own job records:

1. Sep 06, 9:34am — all 20 machines start; each is handed a fixed slice of
   52-53 coins (`syms[SHARD::SHARDS]`), decided before any work begins.
2. 10:57am — machine 10 finishes its 53 coins and EXITS. Nothing gives it more.
3. 11:03am, 11:05am, 11:06am — machines 18, 3 and 8 finish and exit too.
4. 11:19am — four machines idle 12-21 minutes while machine 16 is at 30 of 52.

The slices are equal in COUNT but not in WORK — a 15m coin with three years of
history costs many times a young 4h coin — so the run always ended on the
unluckiest machine: fastest slice 1h23m, slowest ~3h30m, ~61 machine-minutes
already idle when measured.

Now each shard CLAIMS one coin at a time off a shared board
(`progress.ClaimBoard`): an atomic create per coin on the sweep-progress
branch, so no coin can be claimed twice (a double measurement would APPEND
duplicate rows in the collector — the operator's "no duplicate"), and a shard
keeps claiming until the board is empty.

These tests drive `coin_stream`/`main` with a fake board and `ClaimBoard.claim`
with a fake transport — no network, per the conftest guard.
"""
import base64
import importlib.util
import json
import pathlib
import urllib.error

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SHARD = REPO / ".github" / "scripts" / "sweep_shard.py"
PROGRESS = REPO / ".github" / "scripts" / "progress.py"


def _load(path, name, tmp_path, monkeypatch, env=None):
    monkeypatch.chdir(tmp_path)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def shard(tmp_path, monkeypatch):
    for k, v in {"SHARD": "0", "SHARDS": "2", "TFS": "15m", "DAYS": "60",
                 "MIN_DAYS": "0", "COINS": "0"}.items():
        monkeypatch.setenv(k, v)
    mod = _load(SHARD, "sweep_shard_claims_under_test", tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "report", lambda *a, **k: None)
    monkeypatch.setattr(mod, "RETRY_COOLDOWN_S", 0.0)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    return mod


class FakeBoard:
    """The shared board as one in-memory set — what git + the contents API
    give the real one."""

    def __init__(self, mine=None, dead_after=None):
        self.enabled = True
        self.claims: set = set()
        self.calls = 0
        self.dead_after = dead_after

    def taken(self):
        return set(self.claims)

    def claim(self, coin):
        self.calls += 1
        if self.dead_after is not None and self.calls > self.dead_after:
            return None
        if coin in self.claims:
            return False
        self.claims.add(coin)
        return True


# ----------------------------------------------------- the incident itself
def test_a_fast_shard_takes_the_slow_shards_leftovers(shard, monkeypatch):
    """The fix for the idle machines: one shard, given a board where nothing
    else claims, walks the WHOLE market — not its half-slice."""
    coins = [f"C{i:02d}_USDT" for i in range(10)]
    board = FakeBoard()
    monkeypatch.setattr(shard, "board", board)
    got = list(shard.coin_stream(coins, t0=shard.time.time()))
    assert sorted(got) == coins, "a free machine keeps claiming to the end"


def test_two_shards_never_measure_the_same_coin(tmp_path, monkeypatch):
    """No duplicates: the board is one atomic create per coin, so two shards
    walking the same list split it with no overlap and nothing missed."""
    coins = [f"C{i:02d}_USDT" for i in range(11)]
    board = FakeBoard()                       # SHARED between both shards
    streams = []
    for n in ("0", "1"):
        for k, v in {"SHARD": n, "SHARDS": "2", "TFS": "15m", "DAYS": "60",
                     "MIN_DAYS": "0", "COINS": "0"}.items():
            monkeypatch.setenv(k, v)
        mod = _load(SHARD, f"shard{n}_under_test", tmp_path, monkeypatch)
        monkeypatch.setattr(mod, "report", lambda *a, **k: None)
        monkeypatch.setattr(mod, "board", board)
        monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
        streams.append(mod.coin_stream(coins, t0=mod.time.time()))
    a, b = ([], [])
    # interleave the two machines, as the real fleet does
    import itertools

    for stream, bucket in itertools.cycle(zip(streams, (a, b), strict=True)):
        got = next(stream, None)
        if got is None:
            if all(next(s, None) is None for s in streams):
                break
            continue
        bucket.append(got)
    assert not set(a) & set(b), f"double-measured: {set(a) & set(b)}"
    assert sorted(a + b) == coins, "every coin measured exactly once"


def test_the_walk_starts_in_this_shards_own_region(shard, monkeypatch):
    """Twenty machines claiming coin #1 at t=0 is twenty races; the stagger
    makes them claim in twenty different places."""
    coins = [f"C{i:02d}_USDT" for i in range(10)]
    board = FakeBoard()
    monkeypatch.setenv("SHARD", "1")
    mod = _load(SHARD, "shard_stagger_under_test",
                pathlib.Path(shard.OUT).parent.parent, monkeypatch)
    monkeypatch.setattr(mod, "board", board)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    first = next(mod.coin_stream(coins, t0=mod.time.time()))
    assert first == "C05_USDT", "shard 1 of 2 starts at the list's midpoint"


# ------------------------------------------------------------ failure paths
def test_a_lost_race_skips_the_coin_without_measuring(shard, monkeypatch):
    coins = ["A_USDT", "B_USDT"]
    board = FakeBoard()
    board.claims.add("A_USDT")                 # someone else got there first
    monkeypatch.setattr(shard, "board", board)
    got = list(shard.coin_stream(coins, t0=shard.time.time()))
    assert got == ["B_USDT"]


def test_a_dead_board_stops_the_shard_instead_of_guessing(shard, monkeypatch):
    """Measuring an unclaimed-LOOKING coin twice writes duplicate rows, so a
    board that stops answering ends the shard with what it has. One dead
    answer only skips one coin — three in a row is a network that is down."""
    coins = [f"C{i:02d}_USDT" for i in range(10)]
    board = FakeBoard(dead_after=2)
    # taken() must not hide the coins from the walk, or claim() is never asked
    board.taken = lambda: set()
    monkeypatch.setattr(shard, "board", board)
    got = list(shard.coin_stream(coins, t0=shard.time.time()))
    assert got == ["C00_USDT", "C01_USDT"], \
        "two claims answered, then three dead answers in a row must stop it"


def test_without_a_token_the_old_static_slice_still_works(shard, monkeypatch):
    """Local runs and tests have no board; they must behave exactly as before."""
    shard.board.enabled = False
    coins = [f"C{i:02d}_USDT" for i in range(10)]
    got = list(shard.coin_stream(coins, t0=shard.time.time()))
    assert got == coins[0::2], "SHARD 0 of 2: the old every-Nth slice"


# ------------------------------------------------- the claim primitive itself
def _board(monkeypatch, transport):
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setenv("SHARD", "4")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    spec = importlib.util.spec_from_file_location("progress_under_test", PROGRESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_req", transport)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    return mod, mod.ClaimBoard()


def _http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


def test_creating_the_claim_file_wins_the_coin(monkeypatch):
    seen = []

    def transport(method, url, token, body=None):
        seen.append((method, url, body))
        return {}

    _mod, b = _board(monkeypatch, transport)
    assert b.claim("BTC_USDT") is True
    method, url, body = seen[0]
    assert method == "PUT" and "claims/run-77/BTC_USDT.json" in url
    assert "sha" not in body, \
        "a create sends NO sha — the 422 on an existing file IS the lock"


def test_422_owned_by_another_shard_is_a_lost_race(monkeypatch):
    other = base64.b64encode(json.dumps({"shard": 9, "attempt": 1}).encode()).decode()

    def transport(method, url, token, body=None):
        if method == "PUT":
            raise _http_error(422)
        return {"content": other, "sha": "s1"}

    _mod, b = _board(monkeypatch, transport)
    assert b.claim("BTC_USDT") is False


def test_422_on_my_own_claim_is_still_mine(monkeypatch):
    """A create whose RESPONSE was lost on the wire retries into a 422 on its
    own file; treating that as a lost race would strand the coin: claimed by a
    ghost, measured by nobody."""
    mine = base64.b64encode(json.dumps({"shard": 4, "attempt": 1}).encode()).decode()

    def transport(method, url, token, body=None):
        if method == "PUT":
            raise _http_error(422)
        return {"content": mine, "sha": "s1"}

    _mod, b = _board(monkeypatch, transport)
    assert b.claim("BTC_USDT") is True


def test_a_rerun_retakes_its_own_stale_claims(monkeypatch):
    """'Re-run failed jobs': the failed shard's attempt-1 claims died with it
    and nobody else will take them — its attempt-2 self may, via CAS update."""
    stale = base64.b64encode(json.dumps({"shard": 4, "attempt": 1}).encode()).decode()
    puts = []

    def transport(method, url, token, body=None):
        if method == "PUT":
            puts.append(body)
            if "sha" not in body:
                raise _http_error(422)     # the attempt-1 file exists
            return {}
        return {"content": stale, "sha": "oldsha"}

    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    _mod, b = _board(monkeypatch, transport)
    b.attempt = 2
    assert b.claim("BTC_USDT") is True
    assert puts[-1].get("sha") == "oldsha", "the retake is a CAS on the old sha"


def test_contention_is_retried_not_fatal(monkeypatch):
    """Twenty first-claims race one branch ref at t=0; every collision is a
    409. Three tries used to fail a healthy shard out of claiming three
    seconds into the run."""
    calls = {"n": 0}

    def transport(method, url, token, body=None):
        calls["n"] += 1
        if calls["n"] < 5:
            raise _http_error(409)
        return {}

    _mod, b = _board(monkeypatch, transport)
    assert b.claim("BTC_USDT") is True


def test_a_board_that_never_answers_returns_none(monkeypatch):
    def transport(method, url, token, body=None):
        raise OSError("network down")

    _mod, b = _board(monkeypatch, transport)
    assert b.claim("BTC_USDT") is None
