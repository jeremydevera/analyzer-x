"""Every trading room on this PC asks MEXC once, not once each (Oct 02, 2026).

The operator, `Oct 02, 2026`: *"1+2 together"* — after the rooms started
getting "too many requests". Six rooms are six runner processes on one
internet line, and in the 24 hours to `Oct 02, 2026 8:00am` MEXC refused them
**64** times (Main 4, #55D32617 6, #4FC03172 10, #B2404C0B 17, #6B08FF64 12,
#CC94D9FB 15), nearly all on PRACTICE exit checks: every room fetched the
1-minute candles of every open practice trade, every cycle, and then the last
price of each coin on its own.

What these tests hold, each against REAL behaviour:

* REAL PROCESSES (`subprocess`) against a REAL HTTP server on 127.0.0.1 that
  answers the MEXC endpoints and counts every request — the real
  `mexc_futures` code on both sides, only `BASE` pointed at it. Two
  processes asking in the same second must cost ONE request.
* Each child process gets its OWN home folder (USERPROFILE), so nothing a
  child writes can reach the operator's real `~/.tradingagents`.
* The practice exit's minutes come from the live feed when it has all of
  them, and the outcome is the same as the REST read's on the same prices —
  candles and position on ONE timeline, the clock a running runner sees
  (CLAUDE.md, "a fill may only see price the order was exposed to").
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd
import pytest

from tradingagents import auto_trader as at, live_price as lp, shared_market as sm
from tradingagents.dataflows import mexc_futures as fx

REPO = Path(__file__).resolve().parents[1]
PER = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800, "Min60": 3600,
       "Hour4": 14400, "Day1": 86400}

HELD, KEY = "PDDSTOCK_USDT", "eqraid_1h_sl25tp25"      # a practice trade
ARMED, ARMED_KEY = "GPNSTOCK_USDT", "keltner_30m_sl2tp2"
ENTRY = 79.18


# ----------------------------------------------------------- a fake MEXC
class Venue:
    """The MEXC keyless endpoints the runner reads, on 127.0.0.1, counting
    every request it is asked. Flat prices: nothing crosses a barrier."""

    def __init__(self):
        self.calls: list[tuple[str, float]] = []
        self.lock = threading.Lock()
        self.throttle: dict[str, int] = {}     # route -> 510 answers left
        self.hang: dict[str, float] = {}       # route -> seconds, once
        venue = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):          # quiet
                pass

            def do_GET(self):                   # noqa: N802
                venue._serve(self)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.thread = threading.Thread(target=self.srv.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def count(self, route: str) -> int:
        with self.lock:
            return sum(1 for r, _t in self.calls if r == route)

    def times(self, route: str) -> list[float]:
        with self.lock:
            return [t for r, t in self.calls if r == route]

    def routes(self) -> dict:
        out: dict = {}
        with self.lock:
            for r, _t in self.calls:
                out[r] = out.get(r, 0) + 1
        return out

    def _serve(self, h):
        u = urllib.parse.urlparse(h.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        parts = u.path.strip("/").split("/")
        if u.path.endswith("/contract/ticker"):
            route = f"ticker:{q['symbol']}" if "symbol" in q else "ticker"
        elif "/contract/kline/" in u.path:
            route = f"kline:{parts[-1]}:{q.get('interval')}"
        else:
            route = parts[-1] if parts else "?"
        with self.lock:
            self.calls.append((route, time.time()))
            hang = self.hang.pop(route, 0.0)
            throttled = self.throttle.get(route, 0) > 0
            if throttled:
                self.throttle[route] -= 1
        if hang:
            time.sleep(hang)
        if throttled:
            body = {"success": False, "code": 510,
                    "message": "Requests are too frequent"}
        elif route == "ticker":
            body = {"success": True, "code": 0, "data": [
                {"symbol": s, "lastPrice": ENTRY}
                for s in (HELD, ARMED, "BTC_USDT")]}
        elif route.startswith("ticker:"):
            body = {"success": True, "code": 0,
                    "data": {"symbol": q["symbol"], "lastPrice": ENTRY}}
        elif route.startswith("kline:"):
            per = PER[q["interval"]]
            start, end = int(q["start"]), int(q["end"])
            ts = list(range(-(-start // per) * per, end // per * per + 1, per))
            body = {"success": True, "code": 0, "data": {
                "time": ts, "open": [ENTRY] * len(ts),
                "high": [ENTRY + 0.3] * len(ts),
                "low": [ENTRY - 0.3] * len(ts),
                "close": [ENTRY] * len(ts), "vol": [1.0] * len(ts)}}
        elif route == "ping":
            body = {"success": True, "code": 0, "data": int(time.time() * 1000)}
        else:
            body = {"success": False, "code": 404, "message": "not served"}
        raw = json.dumps(body).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(raw)))
        h.end_headers()
        h.wfile.write(raw)


@pytest.fixture
def venue():
    v = Venue()
    yield v
    v.close()


# ------------------------------------------------------- a room process
CHILD = r'''
import json, os, sys, time
cfg = json.load(open(sys.argv[1]))
sys.path.insert(0, cfg["repo"])
from tradingagents.dataflows import mexc_futures as fx
from tradingagents import shared_market as sm
fx.BASE = cfg["base"]
if cfg.get("no_backoff"):
    fx._retry_sleep = lambda s: None
if cfg.get("lock_stale"):
    sm.LOCK_STALE_S = float(cfg["lock_stale"])
if cfg.get("share"):
    sm.enable()
mode = cfg["mode"]
if mode == "cycle":
    from tradingagents import auto_trader as at
    at._write_json(at._pp(at.SETTINGS_PATH), cfg["settings"])
    at._write_json(at._pp(at.STATE_PATH), cfg["state"])
print("ready", flush=True)
while not os.path.exists(cfg["go"]):
    time.sleep(0.005)
t0 = time.time()
out = {"t0": t0}
try:
    if mode == "price":
        out["price"] = sm.last_price(fx, cfg["symbol"])
    elif mode == "klines":
        df = sm.klines(fx, cfg["symbol"], cfg["interval"], 300)
        out["t"] = [int(d.timestamp()) for d in df["Date"]]
        out["h"] = [float(x) for x in df["High"]]
    elif mode == "public":
        fx._get_public(fx.BASE + cfg["path"])
    elif mode == "cycle":
        with at.reads_once_per_cycle():
            at.run_cycle(fx=fx)
        out["state"] = at.load_state()
except Exception as exc:
    out["error"] = f"{type(exc).__name__}: {exc}"
out["t1"] = time.time()
print(json.dumps(out), flush=True)
'''


class Room:
    """One runner-like process with its own home folder and room id."""

    def __init__(self, tmp: Path, name: str, cfg: dict, home: Path):
        self.cfg_path = tmp / f"{name}.json"
        script = tmp / "room_child.py"
        if not script.exists():
            script.write_text(CHILD, encoding="utf-8")
        self.cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
               "TA_PROFILE": cfg.get("profile", "")}
        env.pop("TRADINGAGENTS_SWEEP_HOME", None)
        self.proc = subprocess.Popen(
            [sys.executable, str(script), str(self.cfg_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=env, cwd=str(REPO))

    def ready(self, timeout=60):
        line = self.proc.stdout.readline()
        assert line.strip() == "ready", (line, self.proc.stderr.read())

    def result(self, timeout=90) -> dict:
        out, err = self.proc.communicate(timeout=timeout)
        lines = [x for x in out.splitlines() if x.startswith("{")]
        assert lines, f"no result from the room process:\n{out}\n{err}"
        return json.loads(lines[-1])


def _quiet_second():
    """Start away from a minute boundary: a fetch made in the first second
    after a close is trusted only for that second (`SETTLE_S`), which is the
    rule — but it would make 'one request' depend on the wall clock."""
    while not 5 <= time.time() % 60 <= 45:
        time.sleep(0.2)


def _rooms(tmp_path, venue, n, mode, share=True, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    go = tmp_path / f"go-{mode}-{time.time_ns()}"
    rooms = []
    for i in range(n):
        cfg = {"repo": str(REPO), "base": venue.base, "mode": mode,
               "share": share, "go": str(go), **extra}
        if "profiles" in extra:
            cfg["profile"] = extra["profiles"][i]
        rooms.append(Room(tmp_path, f"room{i}-{time.time_ns()}", cfg, home))
    for r in rooms:
        r.ready()
    return rooms, go, home


def _go(go: Path):
    _quiet_second()
    go.write_text("go", encoding="utf-8")


# ======================================================== A: the price board
def test_two_rooms_asking_for_a_price_in_the_same_second_cost_one_request(
        tmp_path, venue):
    rooms, go, _home = _rooms(tmp_path, venue, 2, "price", symbol=HELD)
    _go(go)
    got = [r.result() for r in rooms]
    assert [g.get("price") for g in got] == [ENTRY, ENTRY], got
    assert venue.count("ticker") == 1, venue.routes()
    assert venue.count(f"ticker:{HELD}") == 0, (
        "a room asked MEXC for the coin's own price while the board had it")


def test_without_sharing_each_room_asks_for_itself(tmp_path, venue):
    """The control: the same two processes with sharing off are two
    requests — what every room did before Oct 02, 2026."""
    rooms, go, _home = _rooms(tmp_path, venue, 2, "price", share=False,
                              symbol=HELD)
    _go(go)
    [r.result() for r in rooms]
    assert venue.count(f"ticker:{HELD}") == 2
    assert venue.count("ticker") == 0


class BoardFx:
    """Counts the board and per-coin reads; prices can be moved."""

    def __init__(self, px=ENTRY):
        self.px, self.board_calls, self.coin_calls = px, 0, 0
        self.fail_board = False

    def last_prices(self, max_age=3.0):
        self.board_calls += 1
        return {} if self.fail_board else {HELD: self.px}

    def last_price(self, symbol):
        self.coin_calls += 1
        return self.px


def test_a_stale_board_is_fetched_again_never_read(monkeypatch):
    monkeypatch.setattr(sm, "BOARD_MAX_AGE_S", 0.3)
    sm.enable()
    f = BoardFx()
    assert sm.last_price(f, HELD) == ENTRY
    assert sm.last_price(f, HELD) == ENTRY
    assert f.board_calls == 1, "a fresh board is read, not fetched"
    f.px = 80.0
    time.sleep(0.4)
    assert sm.last_price(f, HELD) == 80.0, (
        "a board older than BOARD_MAX_AGE_S decided a practice exit")
    assert f.board_calls == 2


def test_a_board_from_the_future_or_the_past_is_not_trusted(monkeypatch):
    sm.enable()
    path = sm.SHARED_DIR / "prices.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for at_ in (time.time() - 60, time.time() + 60):
        sm._MEMO.clear()
        path.write_text(json.dumps({"at": at_, "px": {HELD: 1.0}}))
        f = BoardFx()
        assert sm.last_price(f, HELD) == ENTRY
        assert f.board_calls == 1


def test_a_failing_board_falls_back_to_the_coin_and_does_not_retry_per_coin(
        monkeypatch):
    sm.enable()
    f = BoardFx()
    f.fail_board = True
    for _ in range(5):
        assert sm.last_price(f, HELD) == ENTRY
    assert f.coin_calls == 5
    assert f.board_calls == 1, (
        "a failing board was asked again for every coin — more calls than "
        "no board at all")


def test_a_corrupt_board_file_is_a_fresh_fetch_not_a_crash():
    sm.enable()
    path = sm.SHARED_DIR / "prices.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ half a file")
    f = BoardFx()
    assert sm.last_price(f, HELD) == ENTRY
    assert f.board_calls == 1
    assert json.loads(path.read_text())["px"] == {HELD: ENTRY}, \
        "the good board was not written back over the corrupt one"


def test_an_unusable_shared_folder_is_a_direct_read(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file-not-a-folder"
    blocker.write_text("x")
    monkeypatch.setattr(sm, "SHARED_DIR", blocker / "shared")
    sm.enable()
    f = BoardFx()
    t0 = time.monotonic()
    assert sm.last_price(f, HELD) == ENTRY
    assert time.monotonic() - t0 < 2.0, "it waited for a lock it can never take"


def test_switched_off_it_is_the_plain_call_byte_for_byte():
    """Only the runner switches sharing on: the backtests, the downloads and
    the API keep their own reads exactly as before."""
    assert not sm.enabled()
    f = BoardFx()
    assert sm.last_price(f, HELD) == ENTRY
    assert (f.board_calls, f.coin_calls) == (0, 1)
    assert not (sm.SHARED_DIR / "prices.json").exists()


def test_a_killed_lock_holder_does_not_stop_the_other_rooms(tmp_path, venue):
    """Room A takes the lock and is KILLED mid-fetch (the venue hangs its
    answer). Room B must break the dead lock after LOCK_STALE_S and fetch."""
    venue.hang["ticker"] = 30.0
    home = tmp_path / "home"
    home.mkdir()
    go_a = tmp_path / "go-a"
    a = Room(tmp_path, "holder", {"repo": str(REPO), "base": venue.base,
                                  "mode": "price", "share": True,
                                  "go": str(go_a), "symbol": HELD,
                                  "lock_stale": 1.5}, home)
    a.ready()
    go_a.write_text("go")
    lock = home / ".tradingagents" / "shared" / "prices.lock"
    deadline = time.time() + 20
    while not lock.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert lock.exists(), "room A never took the board's lock"
    while venue.count("ticker") < 1 and time.time() < deadline:
        time.sleep(0.02)
    a.proc.kill()
    a.proc.communicate(timeout=30)
    assert lock.exists(), "the killed room's lock should still be on disk"

    go_b = tmp_path / "go-b"
    b = Room(tmp_path, "waiter", {"repo": str(REPO), "base": venue.base,
                                  "mode": "price", "share": True,
                                  "go": str(go_b), "symbol": HELD,
                                  "lock_stale": 1.5}, home)
    b.ready()
    go_b.write_text("go")
    got = b.result(timeout=60)
    assert got.get("price") == ENTRY, got
    assert got["t1"] - got["t0"] < 10, "the waiting room hung on a dead lock"
    assert venue.count("ticker") == 2


# ============================================================ B: candles
def _rest_page(per, n=300, now=None):
    now = int(now or time.time())
    start = now - per * n
    ts = list(range(-(-start // per) * per, now // per * per + 1, per))
    return {"success": True, "code": 0, "data": {
        "time": ts, "open": [ENTRY + i * 0.001 for i in range(len(ts))],
        "high": [ENTRY + 0.3 + i * 0.001 for i in range(len(ts))],
        "low": [ENTRY - 0.3 for _ in ts], "close": [ENTRY] * len(ts),
        "vol": [float(i) for i in range(len(ts))]}}


def test_candles_from_the_shared_file_are_the_fetched_candles(monkeypatch):
    """Byte for byte: the frame a second room reads from the file is the
    frame `fx.klines` builds from the venue's own answer — and so are the
    closed bars the runner keeps from it."""
    calls = []

    def wire(url):
        calls.append(url)
        return _rest_page(60)

    monkeypatch.setattr(fx, "_get_public", wire)
    direct = fx.klines(HELD, "Min1", 300)
    fx._KLINE_CACHE.clear()
    sm.enable()
    first = sm.klines(fx, HELD, "Min1", 300)          # room 1: fetches
    sm._MEMO.clear()                                  # room 2: a new process
    fx._KLINE_CACHE.clear()
    second = sm.klines(fx, HELD, "Min1", 300)
    assert len(calls) == 2, "room 2 asked the venue again"
    pd.testing.assert_frame_equal(first, direct)
    pd.testing.assert_frame_equal(second, direct)
    pd.testing.assert_frame_equal(at._closed_bars(second, 60),
                                  at._closed_bars(direct, 60))


def test_two_rooms_asking_for_candles_in_the_same_second_cost_one_request(
        tmp_path, venue):
    rooms, go, _home = _rooms(tmp_path, venue, 2, "klines", symbol=HELD,
                              interval="Min1")
    _go(go)
    got = [r.result() for r in rooms]
    assert got[0]["t"] == got[1]["t"] and got[0]["h"] == got[1]["h"], got
    assert venue.count(f"kline:{HELD}:Min1") == 1, venue.routes()


def test_a_new_bar_close_ends_the_file(monkeypatch):
    """A fetch made after bar N closed serves until bar N+1 closes — never
    past it, so no room can read a closed bar as it was while forming."""
    page = {"v": _rest_page(900)}
    calls = []

    def wire(url):
        calls.append(url)
        return page["v"]

    monkeypatch.setattr(fx, "_get_public", wire)
    sm.enable()
    sm.klines(fx, HELD, "Min15", 300)
    doc = json.loads((sm.SHARED_DIR / f"kl_{HELD}_Min15_300.json").read_text())
    bar_open = int(doc["at"] // 900 * 900)
    assert doc["until"] <= bar_open + 900
    # pretend the fetch was made during the PREVIOUS bar
    doc["at"] -= 900
    doc["until"] -= 900
    (sm.SHARED_DIR / f"kl_{HELD}_Min15_300.json").write_text(json.dumps(doc))
    sm._MEMO.clear()
    fx._KLINE_CACHE.clear()
    sm.klines(fx, HELD, "Min15", 300)
    assert len(calls) == 2, "a file from before the bar closed was served"


def test_a_fetch_in_the_first_second_after_a_close_is_only_trusted_that_second():
    close = 1_790_000_000 // 900 * 900
    frame = pd.DataFrame({"Date": pd.to_datetime([close], unit="s")})
    assert sm.valid_until(frame, close + 0.3, 900) == close + sm.SETTLE_S
    assert sm.valid_until(frame, close + 5, 900) == close + 900
    # a frame whose newest bar is the one just closed (no forming bar yet)
    prev = pd.DataFrame({"Date": pd.to_datetime([close - 900], unit="s")})
    assert sm.valid_until(prev, close + 0.3, 900) == close + sm.SETTLE_S
    assert sm.valid_until(prev, close + 30, 900) == close + 900


def test_a_truncated_answer_is_kept_to_the_room_that_got_it(monkeypatch):
    """MEXC answers a hammered client with truncated history; one room's
    short read must not become every room's bar."""
    pages = [_rest_page(900), _rest_page(900, n=40)]
    monkeypatch.setattr(fx, "_get_public", lambda url: pages.pop(0))
    sm.enable()
    full = sm.klines(fx, HELD, "Min15", 300)
    p = sm.SHARED_DIR / f"kl_{HELD}_Min15_300.json"
    doc = json.loads(p.read_text())
    doc["until"] = doc["at"] - 1            # expired: the next read fetches
    p.write_text(json.dumps(doc))
    sm._MEMO.clear()
    fx._KLINE_CACHE.clear()
    short = sm.klines(fx, HELD, "Min15", 300)
    assert len(short) < 50 < len(full)
    assert len(json.loads(p.read_text())["t"]) == len(full),         "the truncated answer replaced the full one for every room"


def test_a_paged_history_is_never_shared(monkeypatch):
    """The backtest's long reads page and disk-cache inside `fx.klines`;
    they are not the runner's and are not shared."""
    sm.enable()
    seen = []

    class F:
        def klines(self, s, i, n):
            seen.append(n)
            return pd.DataFrame({"Date": pd.to_datetime([0], unit="s")})

    sm.klines(F(), HELD, "Min60", 5000)
    sm.klines(F(), HELD, "Min60", 5000)
    assert seen == [5000, 5000]
    assert not list(sm.SHARED_DIR.glob("kl_*")) if sm.SHARED_DIR.exists() \
        else True


def test_a_corrupt_candle_file_is_a_fresh_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(fx, "_get_public",
                        lambda url: calls.append(url) or _rest_page(60))
    sm.enable()
    p = sm.SHARED_DIR / f"kl_{HELD}_Min1_300.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"at": 1, "per": 60, "until": 99999999999, "t": [1, 2]}')
    df = sm.klines(fx, HELD, "Min1", 300)
    assert len(calls) == 1 and len(df) > 250


# ========================================================== D: the pause
def test_a_rate_limit_in_one_room_holds_the_next_call_in_another(
        tmp_path, venue):
    """Room A hears 510 and writes the pause; room B's next keyless call
    waits until it ends."""
    venue.throttle["ping"] = 1
    home = tmp_path / "home"
    home.mkdir()
    go_a = tmp_path / "go-a"
    a = Room(tmp_path, "throttled", {"repo": str(REPO), "base": venue.base,
                                     "mode": "public", "path":
                                     "/api/v1/contract/ping",
                                     "go": str(go_a), "no_backoff": True},
             home)
    a.ready()
    go_b = tmp_path / "go-b"
    b = Room(tmp_path, "other", {"repo": str(REPO), "base": venue.base,
                                 "mode": "public",
                                 "path": "/api/v1/contract/detail",
                                 "go": str(go_b)}, home)
    b.ready()
    go_a.write_text("go")
    a.result()
    pause = home / ".tradingagents" / "shared" / "public_pause.json"
    assert pause.exists(), "the 510 was not shared"
    until = json.loads(pause.read_text())["until"]
    go_b.write_text("go")
    b.result()
    asked = venue.times("detail")
    assert asked, venue.routes()
    assert asked[0] >= until - 0.05, (
        f"room B asked {until - asked[0]:.2f}s before the pause ended")


def test_a_rooms_own_pause_does_not_hold_it_and_a_foreign_one_does(
        monkeypatch):
    waited = []
    monkeypatch.setattr(fx, "_pause_sleep", waited.append)
    fx.PUBLIC_PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fx.PUBLIC_PAUSE_PATH.write_text(json.dumps(
        {"until": time.time() + 1.5, "pid": os.getpid()}))
    assert fx._honour_shared_pause() == 0.0
    fx.PUBLIC_PAUSE_PATH.write_text(json.dumps(
        {"until": time.time() + 1.5, "pid": os.getpid() + 1}))
    assert 1.0 < fx._honour_shared_pause() <= 1.5 + fx.PUBLIC_PAUSE_JITTER_S
    fx.PUBLIC_PAUSE_PATH.write_text(json.dumps(
        {"until": time.time() + 3600, "pid": os.getpid() + 1}))
    assert fx._honour_shared_pause() == fx.PUBLIC_PAUSE_MAX_WAIT_S, \
        "a stuck pause file held a call longer than the cap"
    fx.PUBLIC_PAUSE_PATH.write_text("garbage")
    assert fx._honour_shared_pause() == 0.0


def test_a_signed_call_never_waits_for_the_pause(monkeypatch):
    """`_request` places orders and stops. A second order submit is a second
    order, and a real exit must never queue behind a practice price check."""
    waited = []
    monkeypatch.setattr(fx, "_pause_sleep", waited.append)
    fx.PUBLIC_PAUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fx.PUBLIC_PAUSE_PATH.write_text(json.dumps(
        {"until": time.time() + 2.0, "pid": os.getpid() + 1}))
    monkeypatch.setenv("MEXC_API_KEY", "k")
    monkeypatch.setenv("MEXC_API_SECRET", "s")

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"success": true, "code": 0, "data": {"ok": 1}}'

    monkeypatch.setattr(fx.urllib.request, "urlopen", lambda *a, **k: Resp())
    assert fx._request("GET", "/api/v1/private/account/assets") == {"ok": 1}
    assert waited == []
    import inspect
    src = inspect.getsource(fx._request)
    assert "_honour_shared_pause" not in src and "_note_rate_limit" not in src


def test_the_510_that_writes_the_pause_is_the_body_code(monkeypatch):
    """MEXC answers a rate limit as HTTP 200 with code 510 in the body."""
    monkeypatch.setattr(fx, "_retry_sleep", lambda s: None)

    class Resp:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.raw

    answers = [b'{"success": false, "code": 510, "message": "too frequent"}',
               b'{"success": true, "code": 0, "data": 1}']
    monkeypatch.setattr(fx.urllib.request, "urlopen",
                        lambda *a, **k: Resp(answers.pop(0)))
    assert fx._get_public("http://x/ping")["data"] == 1
    d = json.loads(fx.PUBLIC_PAUSE_PATH.read_text())
    assert d["pid"] == os.getpid() and d["until"] > time.time()


# =========================================== C: the feed's own minutes
NOW = int(time.time())
OPENED_AT = (NOW // 60) * 60 - 40 * 60 + 11     # 40 minutes ago, 11 s in


@pytest.fixture
def timeline():
    """ONE TIMELINE, read at TEST time, never at import: the runner judges
    the feed's minutes against the wall clock, so candles stamped when the
    module was collected (minutes earlier in a full run) would read as a
    feed that stopped. Started away from a minute boundary so the test ends
    in the minute it began."""
    global NOW, OPENED_AT
    while not 2 <= time.time() % 60 <= 50:
        time.sleep(0.2)
    NOW = int(time.time())
    OPENED_AT = (NOW // 60) * 60 - 40 * 60 + 11
    return NOW


def _minute_rows(touch_at=None, pre_order_spike=True):
    """One timeline for candles AND position: minutes from an hour before
    the order up to the minute still forming at NOW. A spike through the
    target BEFORE the order (must never fill), and optionally a real touch
    after it."""
    rows = []
    first = OPENED_AT // 60 * 60 - 60 * 60
    for t in range(first, NOW // 60 * 60 + 1, 60):
        hi, lo = ENTRY + 0.2, ENTRY - 0.2
        if pre_order_spike and t == OPENED_AT // 60 * 60 - 10 * 60:
            hi = ENTRY * 1.04
        if touch_at is not None and t == touch_at:
            hi = ENTRY * 1.03
        rows.append((t, hi, lo))
    return rows


def _frame(rows):
    return pd.DataFrame({
        "Date": pd.to_datetime([r[0] for r in rows], unit="s"),
        "Open": [ENTRY] * len(rows), "High": [r[1] for r in rows],
        "Low": [r[2] for r in rows], "Close": [ENTRY] * len(rows),
        "Volume": [1.0] * len(rows)})


def _hours():
    top = NOW // 3600 * 3600
    opens = [top - (59 - i) * 3600 for i in range(60)]
    return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"),
                         "Open": [ENTRY] * 60, "High": [ENTRY + 0.2] * 60,
                         "Low": [ENTRY - 0.2] * 60, "Close": [ENTRY] * 60,
                         "Volume": [1.0] * 60})


class ExitFx:
    """Answers Min1 with the minutes and Min60 with flat hours; counts."""

    SIDE_OPEN_LONG, SIDE_CLOSE_SHORT, SIDE_OPEN_SHORT, SIDE_CLOSE_LONG = 1, 2, 3, 4

    def __init__(self, minutes, hours):
        self.minutes, self.hours = minutes, hours
        self.calls: list[str] = []

    def klines(self, symbol, interval, limit):
        self.calls.append(interval)
        return (self.minutes if interval == "Min1" else self.hours).copy()

    def last_price(self, symbol):
        self.calls.append("last")
        return ENTRY

    def book_cost(self, symbol, notional_usd=200.0):
        return {"spread": 0.0002, "slippage": 0.0002, "book_exhausted": False}

    def contract_spec(self, symbol):
        return {"priceScale": 4, "maxVol": 0}

    def open_positions(self, symbol=None):
        return []

    def position_history(self, symbol=None, page_size=20):
        return []


def _feed(rows, *, drop=None):
    """A connected feed that has seen MEXC push every minute in `rows` —
    and the forming one — exactly as `_on_message` receives them."""
    f = lp.PriceFeed()
    f._connected = True
    f._last_msg_at = time.time()
    f.track_minutes([HELD])
    for t, hi, lo in rows:
        if drop is not None and t == drop:
            continue
        f._on_message({"channel": "push.kline", "symbol": HELD,
                       "data": {"symbol": HELD, "interval": "Min1", "t": t,
                                "o": ENTRY, "c": ENTRY, "h": hi, "l": lo}})
    return f


def _position():
    return {"side": 1, "vol": 5, "entry": ENTRY, "tp": ENTRY * 1.025,
            "sl": ENTRY * 0.975, "margin": 5.0, "strategy": KEY,
            "entry_ts": OPENED_AT // 3600 * 3600, "opened_at": OPENED_AT,
            "trade_id": "SHARED01", "dry": True, "bracket": True, "step": 0,
            "rt_cost": 0.0}


def _exit_cycle(fx_, monkeypatch, feed):
    monkeypatch.setattr(lp, "FEED", feed)
    at._BAR_CACHE.clear()
    slot = at.state_key(HELD, True, KEY)
    state = {slot: {"step": 0, "last_ts": {}, "position": _position()}}
    at.process_symbol(HELD, {"strategies": [KEY], "coins": [HELD],
                             "margin": 5.0},
                      state, fx=fx_, dry=True, tripped=frozenset({KEY}))
    return state[slot]


def _ledger_exits():
    if not at.LEDGER_PATH.exists():
        return []
    return [json.loads(x) for x in at.LEDGER_PATH.read_text().splitlines()
            if '"exit"' in x]


@pytest.mark.parametrize("touch", [None, "after"])
def test_the_feeds_minutes_decide_exactly_what_the_rest_read_decided(
        monkeypatch, touch, timeline):
    touch_at = (OPENED_AT // 60 * 60 + 15 * 60) if touch else None
    rows = _minute_rows(touch_at=touch_at)
    # TODAY: no feed, the REST read
    rest_fx = ExitFx(_frame(rows), _hours())
    today = _exit_cycle(rest_fx, monkeypatch, lp.PriceFeed())
    today_exits = _ledger_exits()
    at.LEDGER_PATH.unlink(missing_ok=True)
    # NOW: the feed has every minute
    feed_fx = ExitFx(_frame(rows), _hours())
    feed = _feed(rows)
    now = _exit_cycle(feed_fx, monkeypatch, feed)
    now_exits = _ledger_exits()
    assert "Min1" in rest_fx.calls
    assert "Min1" not in feed_fx.calls, \
        "the feed had every minute and the room still asked MEXC"
    assert feed.status()["minutes"]["served"] == 1
    assert (today["position"] is None) == (now["position"] is None)
    assert [(e["why"], e["exit"], e["pnl_est"]) for e in today_exits] == \
        [(e["why"], e["exit"], e["pnl_est"]) for e in now_exits]
    if touch:
        assert now["position"] is None and now_exits[-1]["why"] == "TP"
    else:
        assert now["position"] is not None, \
            "the spike from BEFORE the order filled the trade"


def test_one_missing_minute_and_the_rest_read_decides(monkeypatch, timeline):
    rows = _minute_rows()
    hole = OPENED_AT // 60 * 60 + 20 * 60
    feed_fx = ExitFx(_frame(rows), _hours())
    feed = _feed(rows, drop=hole)
    _exit_cycle(feed_fx, monkeypatch, feed)
    assert "Min1" in feed_fx.calls, "a feed with a hole answered for MEXC"
    assert feed.status()["minutes"]["fell_back"] == 1


def test_a_hole_falls_back_to_the_shared_candles_not_a_private_fetch(
        monkeypatch, timeline):
    """Coverage gap -> the shared 1-minute file: two rooms, one fetch."""
    sm.enable()
    rows = _minute_rows()
    hole = OPENED_AT // 60 * 60 + 20 * 60
    one = ExitFx(_frame(rows), _hours())
    _exit_cycle(one, monkeypatch, _feed(rows, drop=hole))
    sm._MEMO.clear()                       # the second room is a new process
    two = ExitFx(_frame(rows), _hours())
    _exit_cycle(two, monkeypatch, _feed(rows, drop=hole))
    assert one.calls.count("Min1") == 1
    assert two.calls.count("Min1") == 0, "the second room fetched again"


def test_the_newest_minute_is_final_only_when_mexc_pushed_the_next(timeline):
    rows = _minute_rows()
    f = _feed([r for r in rows if r[0] < NOW // 60 * 60])  # no forming push
    assert f.minute_bars(HELD, OPENED_AT, now=NOW) is None
    f2 = _feed(rows)
    got = f2.minute_bars(HELD, OPENED_AT, now=NOW)
    assert got and got[0][0] == OPENED_AT // 60 * 60
    assert got[-1][0] == (NOW - 60) // 60 * 60


def test_a_deal_inside_a_minute_widens_it(timeline):
    rows = _minute_rows(pre_order_spike=False)
    f = _feed(rows)
    t = OPENED_AT // 60 * 60 + 5 * 60
    f._on_message({"channel": "push.deal", "symbol": HELD,
                   "data": [{"p": ENTRY * 1.03, "t": (t + 30) * 1000}]})
    bars = {b[0]: b[1] for b in f.minute_bars(HELD, OPENED_AT, now=NOW)}
    assert bars[t] == ENTRY * 1.03


def test_a_reconnect_forgets_every_minute_and_resubscribes(monkeypatch,
                                                             tmp_path):
    """A new socket holds no subscription at all (RCA-2026-10-02-D): every
    candle stream, the minutes and the login are sent again, and no minute
    from the old socket can count as covered."""
    import asyncio

    import websockets

    sent: list[list] = []

    class WS:
        def __init__(self, n):
            self.n, self.msgs = n, []
            sent.append(self.msgs)

        async def send(self, m):
            self.msgs.append(json.loads(m))

        async def recv(self):
            await asyncio.sleep(0.05)
            if self.n == 1:
                raise ConnectionError("dropped")
            f._stop.set()
            return json.dumps({"channel": "pong", "data": 1})

    class Conn:
        count = 0

        def __init__(self, *a, **k):
            Conn.count += 1
            self.ws = WS(Conn.count)

        async def __aenter__(self):
            return self.ws

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(websockets, "connect", Conn)
    monkeypatch.setattr(lp, "BACKOFF_S", (0.01,))
    monkeypatch.setattr(lp, "STATUS_PATH", tmp_path / "live_price.json")
    f = lp.PriceFeed()
    monkeypatch.setattr(f, "publish", lambda: None)
    f.track([HELD])
    f.track_klines([(HELD, "Min60")])
    f.track_minutes([HELD])
    f.use_credentials("k", "s")
    f._minutes = {HELD: {60: [1.0, 1.0]}}
    asyncio.run(f._serve())
    assert len(sent) == 2
    for msgs in sent:
        subs = {(m["method"], m["param"].get("interval"))
                for m in msgs if m["method"] == "sub.kline"}
        assert subs == {("sub.kline", "Min60"), ("sub.kline", "Min1")}, msgs
        assert any(m["method"] == "login" for m in msgs), msgs
    assert f._minutes == {}


# ============================== the runner's own entry point, two rooms
def test_two_rooms_running_their_cycle_together_ask_mexc_once(
        tmp_path, venue):
    """`run_cycle`, the function the runner calls, in two room processes at
    the same moment: a practice trade held on a switched-off coin (its
    exit is checked: hour bars, minutes, last price) and an armed strategy
    on another coin (its own half-hour bars)."""
    now = int(time.time())
    slot = at.state_key(HELD, True, KEY)
    pos = {**_position(), "opened_at": now - 1800,
           "entry_ts": (now - 1800) // 3600 * 3600}
    settings = {"strategies": [ARMED_KEY],
                "strategy_coins": {ARMED_KEY: [ARMED]},
                "strategy_books": {ARMED_KEY: ["paper"]}, "margin": 5.0,
                "enabled": False, "dry_run": True}
    state = {slot: {"step": 0, "last_ts": {}, "position": pos}}
    common = {"settings": settings, "state": state,
              "profiles": ["55D32617", "4FC03172"]}

    rooms, go, home = _rooms(tmp_path, venue, 2, "cycle", **common)
    _go(go)
    got = [r.result(timeout=120) for r in rooms]
    for g in got:
        assert "error" not in g, g
        assert g["state"][slot]["position"] is not None, \
            "flat prices closed a practice trade"
    shared = venue.routes()
    assert venue.count(f"kline:{HELD}:Min60") == 1, shared
    assert venue.count(f"kline:{HELD}:Min1") == 1, shared
    assert venue.count(f"kline:{ARMED}:Min30") == 1, shared
    assert venue.count("ticker") == 1, shared
    assert venue.count(f"ticker:{HELD}") == 0, shared
    # each room wrote its OWN state, in its own folder
    for pid in ("55D32617", "4FC03172"):
        assert (home / ".tradingagents" / "profiles" / pid /
                "auto_trade_state.json").exists()

    # the control: the same two rooms with sharing off ask for everything
    # twice — what the 64 refusals were made of
    venue.calls.clear()
    rooms, go, _ = _rooms(tmp_path, venue, 2, "cycle", share=False, **common)
    _go(go)
    [r.result(timeout=120) for r in rooms]
    assert venue.count(f"kline:{HELD}:Min1") == 2, venue.routes()
    assert venue.count(f"ticker:{HELD}") == 2, venue.routes()


def test_the_runner_and_only_the_runner_switches_sharing_on():
    import inspect

    assert "shared_market.enable()" in inspect.getsource(at.run_forever)
    for mod in ("tradingagents.market_sweep", "tradingagents.db_jobs"):
        try:
            src = Path(__import__(mod, fromlist=["x"]).__file__).read_text(
                encoding="utf-8")
        except Exception:                                   # noqa: BLE001
            continue
        assert "shared_market" not in src, f"{mod} reads the runner's files"


def test_the_shared_files_sit_on_the_stores_drive_never_temp():
    """CLAUDE.md: big or shared files go where the store is. The real
    default (read off the source, the fixture moved the attribute)."""
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(
        "tradingagents.shared_market"))
    assert 'SHARED_DIR = Path(os.path.expanduser("~/.tradingagents")) / "shared"' \
        in src
    assert "tempfile" not in src and "TEMP" not in src.replace("TEMPORARY", "")


def test_the_cycle_records_minutes_for_practice_coins_held_first(monkeypatch):
    """`_feed_follow` (the end of every `run_cycle`) asks the feed for the
    one-minute bars of every coin a practice trade holds, then the coins
    armed on the practice book — never a coin armed for real money only —
    and the held ones survive the cap."""
    REAL_ONLY, REAL_KEY = "XAUT_USDT", "bb20_1h_sl25tp25"
    settings = {"strategies": [ARMED_KEY, REAL_KEY],
                "strategy_coins": {ARMED_KEY: [ARMED], REAL_KEY: [REAL_ONLY]},
                "strategy_books": {ARMED_KEY: ["paper"], REAL_KEY: ["real"]},
                "margin": 5.0, "enabled": True, "dry_run": True}
    monkeypatch.setattr(at, "load_settings", lambda: settings)
    feed = lp.PriceFeed()
    monkeypatch.setattr(lp, "FEED", feed)
    state = {at.state_key(HELD, True, KEY): {"position": _position()}}
    at._feed_follow(state)
    assert feed._want_minutes == {HELD, ARMED}
    monkeypatch.setattr(lp, "MINUTE_COINS_MAX", 1)
    at._feed_follow(state)
    assert feed._want_minutes == {HELD}, "the cap dropped a held coin"
