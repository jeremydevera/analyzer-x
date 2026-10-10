"""Gate candles: REST pages, the monthly archive, and the v2 minutes.

Measured Oct 10, 2026 and copied into the fake below:
* REST serves only the newest 10,000 points of each bar size and answers a
  page reaching past that with 400 "Candlestick too long ago" — even when
  most of the page is inside.
* `to=` + `limit=` pages backwards, at most 2,000 a page.
* The archive (`download.gatedata.org/futures_usdt/candlesticks_<k>/<YYYYMM>/
  <C>-<YYYYMM>.csv.gz`) holds COMPLETED months only, columns t,v,c,h,l,o,
  for k in 1m, 5m, 1h, 4h, 1d — no 15m or 30m, so those are built from 5m.
(spec D10, docs/superpowers/specs/2026-10-10-switch-to-gate-design.md)
"""
import calendar
import gzip
import json
import urllib.parse

import pandas as pd
import pytest

from tradingagents.dataflows import gate_futures as gf

PER = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400,
       "1d": 86400}
NOW = calendar.timegm((2026, 10, 10, 6, 30, 0)) + 17   # Oct 10, 2026 6:30:17am UTC


def bar(t: int, per: int) -> dict:
    """A deterministic candle: open rises with time, every bar is its own."""
    o = 100.0 + (t // 60) % 997 / 10.0
    return {"t": t, "o": o, "h": o + 1.0 + (t // per) % 3, "l": o - 1.0,
            "c": o + 0.5, "v": 10 + (t // 60) % 7}


def minute_bars(lo: int, hi: int) -> list:
    return [bar(t, 60) for t in range(lo - lo % 60, hi, 60)]


def agg(t: int, per: int) -> dict:
    """What a `per`-second candle starting at t is, built from minutes."""
    ms = [bar(x, 60) for x in range(t, t + per, 60)]
    return {"t": t, "o": ms[0]["o"], "h": max(m["h"] for m in ms),
            "l": min(m["l"] for m in ms), "c": ms[-1]["c"],
            "v": sum(m["v"] for m in ms)}


class Fake:
    def __init__(self, archive_months=None, listed_since=None):
        self.asked = []
        # every completed month before NOW is published unless a test says
        self.archive_months = set(archive_months) if archive_months else {
            f"{y}{m:02d}" for y in (2025, 2026) for m in range(1, 13)
            if f"{y}{m:02d}" <= "202609"}
        self.listed_since = listed_since

    def __call__(self, url):
        self.asked.append(url)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.netloc == "download.gatedata.org":
            return self.archive(u.path)
        assert u.path.endswith("/futures/usdt/candlesticks"), u.path
        iv = q["interval"]
        per = PER[iv]
        newest = NOW - NOW % per
        earliest = newest - (10_000 - 1) * per
        if "from" in q:
            lo, hi = int(q["from"]), int(q["to"])
        else:
            hi = int(q.get("to", NOW))
            lim = int(q["limit"])
            assert lim <= 2000, "Gate refuses a limit over 2,000"
            hi -= hi % per
            lo = hi - (lim - 1) * per
        if lo < earliest:
            return 400, b'{"label":"INVALID_PARAM_VALUE","message":"Candlestick too long ago. Maximum 10000 points recently are allowed"}'
        out = [agg(t, per) for t in range(lo - lo % per, min(hi, newest) + 1, per)
               if self.listed_since is None or t >= self.listed_since]
        return 200, json.dumps([{**b, "o": str(b["o"]), "h": str(b["h"]),
                                 "l": str(b["l"]), "c": str(b["c"])}
                                for b in out]).encode()

    def archive(self, path):
        # /futures_usdt/candlesticks_1m/202609/BTC_USDT-202609.csv.gz
        kind = path.split("/")[2].removeprefix("candlesticks_")
        ym = path.split("/")[3]
        if ym not in self.archive_months:
            return 404, b"<Error>NoSuchKey</Error>"
        y, m = int(ym[:4]), int(ym[4:])
        lo = calendar.timegm((y, m, 1, 0, 0, 0))
        days = calendar.monthrange(y, m)[1]
        per = PER[kind]
        lines = []
        for t in range(lo, lo + days * 86400, per):
            if self.listed_since is not None and t < self.listed_since:
                continue
            b = agg(t, per)
            lines.append(f"{t},{b['v']},{b['c']},{b['h']},{b['l']},{b['o']}")
        return 200, gzip.compress("\n".join(lines).encode())


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(gf, "_now", lambda: NOW)
    monkeypatch.setattr(gf, "KLINE_DISK_DIR", tmp_path / "kline_cache" / "gate")
    monkeypatch.setattr(gf, "PUBLIC_PAUSE_PATH", tmp_path / "pause.json")
    monkeypatch.setattr(gf, "_retry_sleep", lambda s: None)
    gf.clear_kline_cache(disk=False)
    f = Fake()
    monkeypatch.setattr(gf, "_fetch", f)
    return f


def rest_asks(f):
    return [dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))
            for u in f.asked if "candlesticks?" in u]


def test_a_short_ask_is_one_call_in_gates_interval_name(fake):
    df = gf.klines("BTC_USDT", "Min60", 300)
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 300
    (q,) = rest_asks(fake)
    assert q["interval"] == "1h" and q["contract"] == "BTC_USDT"
    last = int(df["Date"].iloc[-1].timestamp())
    assert last == NOW - NOW % 3600
    want = agg(last, 3600)
    assert df["Open"].iloc[-1] == pytest.approx(want["o"])
    assert df["Volume"].iloc[-1] == pytest.approx(want["v"])


def test_a_long_ask_pages_back_two_thousand_at_a_time(fake):
    df = gf.klines("BTC_USDT", "Min1", 5000)
    assert len(df) == 5000
    assert df["Date"].is_monotonic_increasing and df["Date"].is_unique
    assert all(int(q["limit"]) <= 2000 for q in rest_asks(fake))


def test_history_deeper_than_rest_comes_from_the_archive_never_a_refused_page(fake):
    """15m: REST holds 10,000 bars (104 days); older complete months are
    built from the 5m archive. No page may reach past REST's edge."""
    df = gf.klines("BTC_USDT", "Min15", 15_000)
    assert df["Date"].is_monotonic_increasing and df["Date"].is_unique
    newest = NOW - NOW % 900
    edge = newest - 9_999 * 900
    oldest = int(df["Date"].iloc[0].timestamp())
    assert oldest < edge, "the front came from the archive"
    # every 15m bar, wherever it came from, is the same candle
    for t in (oldest, oldest + 900 * 7, edge - 900, edge, newest):
        row = df[df["Date"] == pd.Timestamp(t, unit="s")].iloc[0]
        want = agg(t, 900)
        assert (row["Open"], row["High"], row["Low"], row["Close"]) == pytest.approx(
            (want["o"], want["h"], want["l"], want["c"])), t
        assert row["Volume"] == pytest.approx(want["v"])
    assert any("candlesticks_5m" in u for u in fake.asked)
    assert not any("candlesticks_15m" in u for u in fake.asked), \
        "Gate's archive has no 15m files"


def test_a_month_the_archive_has_not_published_leaves_a_gap_never_invented_bars(fake):
    """1m: REST holds 6.9 days; Sep is archived; Oct 1-3 exist nowhere yet."""
    df = gf.klines("BTC_USDT", "Min1", 20_000)
    ts = [int(x.timestamp()) for x in df["Date"]]
    oct1 = calendar.timegm((2026, 10, 1, 0, 0, 0))
    rest_edge = (NOW - NOW % 60) - 9_999 * 60
    assert not [t for t in ts if oct1 <= t < rest_edge], "no bars invented"
    assert ts[-1] == NOW - NOW % 60


def test_the_archive_is_read_once_and_kept(fake):
    gf.klines("BTC_USDT", "Min15", 15_000)
    n = sum("download.gatedata.org" in u for u in fake.asked)
    gf.clear_kline_cache(disk=False)
    gf.klines("BTC_USDT", "Min15", 15_000)
    assert sum("download.gatedata.org" in u for u in fake.asked) == n, \
        "a published month never changes: read it once"


def test_a_young_coin_stops_at_its_first_month(monkeypatch, tmp_path, fake):
    young = Fake(listed_since=calendar.timegm((2026, 9, 20, 0, 0, 0)))
    monkeypatch.setattr(gf, "_fetch", young)
    df = gf.klines("NEW_USDT", "Min15", 30_000)
    assert int(df["Date"].iloc[0].timestamp()) >= young.listed_since
    months = [u.split("/")[-2] for u in young.asked if "gatedata" in u]
    assert len(months) == 1, \
        "REST already covers this coin's whole life; one empty month ends the walk"


def test_minutes_for_v2_mix_minutes_and_five_minute_bars_without_overlap(fake):
    """The v2 exit settles on the finest bars there are: the 1m archive,
    REST 1m (6.9 days), and REST 5m only where no minute exists (D10)."""
    start = calendar.timegm((2026, 9, 12, 0, 0, 0))
    m = gf.minutes("BTC_USDT", start, NOW)
    ts = [int(x.timestamp()) for x in m["Date"]]
    assert ts == sorted(ts) and len(ts) == len(set(ts))
    secs = list(m["Seconds"])
    oct1 = calendar.timegm((2026, 10, 1, 0, 0, 0))
    rest_edge = (NOW - NOW % 60) - 9_999 * 60
    ones = [t for t, s in zip(ts, secs) if s == 60]
    fives = [t for t, s in zip(ts, secs) if s == 300]
    assert min(ones) == start and max(ones) == NOW - NOW % 60
    assert fives and all(oct1 <= t < rest_edge for t in fives), \
        "five-minute bars only fill the hole"
    # no 5m bar shares any instant with a minute
    one_set = set(ones)
    assert not any(any(t + k * 60 in one_set for k in range(5)) for t in fives)
    # a five-minute bar is the real five-minute candle
    t = fives[3]
    row = m[m["Date"] == pd.Timestamp(t, unit="s")].iloc[0]
    want = agg(t, 300)
    assert (row["High"], row["Low"]) == pytest.approx((want["h"], want["l"]))


def test_a_coin_gate_does_not_list_is_an_error(fake, monkeypatch):
    monkeypatch.setattr(gf, "_fetch", lambda url: (400, b'{"label":"CONTRACT_NOT_FOUND"}'))
    with pytest.raises(gf.VenueError, match="CONTRACT_NOT_FOUND"):
        gf.klines("GPNSTOCK_USDT", "Min60", 300)
