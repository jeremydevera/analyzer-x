"""Every CLOSED Gate candle is the real candle, at every page break.

Measured Oct 19, 2026 on Gate's own REST, and copied into the fake below:

* `to=` exactly on a candle's opening second answers THAT candle as an empty
  placeholder: open = high = low = close = the previous close, volume 0.
  KSTR_USDT 15m, `to=8:45:00am` -> the 8:45am candle 19.39 flat, volume 0;
  `to=8:45:01am` and `to=8:59:59am` -> 19.36 / 19.44 / 19.36 / 19.40, volume
  1,086 — the real one. Long after the candle closed.
* a page answers `limit + 1` candles, the newest at or before `to`.

`_rest_range` asked every page at a candle's opening second, so a fresh read
of BTC_USDT held a fake candle exactly every 2,001 candles back (15m: Sep 28,
2026 1:30pm and Sep 07, 2026 5:15pm; 5m: Oct 12 11:05am; 1m: Oct 18 12:32am
and Oct 16 3:11pm) — one inside every 15m backtest window, a few among the
exit minutes — while the runner, reading 300 candles in ONE page, never saw
one. KSTR 15m insidebrk TP 3% / SL 0.5% (#WL867UTS) listed 46 trades and its
trade list showed 45: GitHub's read and this PC's had their fake candle in
different places (RCA-2026-10-19-C).
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
NOW = calendar.timegm((2026, 10, 19, 13, 52, 17))   # Oct 19, 2026 1:52:17pm UTC


def minute(t: int) -> dict:
    """A deterministic minute that always traded: never flat, never volume 0."""
    o = 100.0 + (t // 60) % 997 / 10.0
    return {"t": t, "o": o, "h": o + 1.0 + (t // 60) % 3, "l": o - 1.0,
            "c": o + 0.5, "v": 10 + (t // 60) % 7}


def real(t: int, per: int) -> dict:
    """The real `per`-second candle opening at t, built from its minutes —
    so REST, the archive and any resample all agree on it."""
    ms = [minute(x) for x in range(t, t + per, 60)]
    return {"t": t, "o": ms[0]["o"], "h": max(m["h"] for m in ms),
            "l": min(m["l"] for m in ms), "c": ms[-1]["c"],
            "v": sum(m["v"] for m in ms)}


def placeholder(t: int, per: int) -> dict:
    """What Gate answers for the candle opening exactly AT `to`."""
    c = real(t - per, per)["c"]
    return {"t": t, "o": c, "h": c, "l": c, "c": c, "v": 0}


class Gate:
    """Gate's candles as measured Oct 19, 2026 — REST and the archive."""

    def __init__(self):
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.netloc == "download.gatedata.org":
            return self.archive(u.path)
        assert u.path.endswith("/futures/usdt/candlesticks"), u.path
        assert "from" not in q, "the adapter pages with to= and limit="
        per = PER[q["interval"]]
        lim = int(q["limit"])
        assert lim <= 2000, "Gate refuses a limit over 2,000"
        newest = NOW - NOW % per
        to = int(q.get("to", NOW))
        top = min(to - to % per, newest)
        lo = top - lim * per                       # limit + 1 candles
        if lo < newest - (10_000 - 1) * per:
            return 400, (b'{"label":"INVALID_PARAM_VALUE","message":'
                         b'"Candlestick too long ago. Maximum 10000 points '
                         b'recently are allowed"}')
        out = [placeholder(t, per) if t == to else real(t, per)
               for t in range(lo, top + 1, per)]
        return 200, json.dumps([{**b, "o": str(b["o"]), "h": str(b["h"]),
                                 "l": str(b["l"]), "c": str(b["c"])}
                                for b in out]).encode()

    def archive(self, path):
        # /futures_usdt/candlesticks_1m/202609/BTC_USDT-202609.csv.gz
        kind = path.split("/")[2].removeprefix("candlesticks_")
        ym = path.split("/")[3]
        if ym > "202609":                          # completed months only
            return 404, b"<Error>NoSuchKey</Error>"
        y, m = int(ym[:4]), int(ym[4:])
        lo = calendar.timegm((y, m, 1, 0, 0, 0))
        per = PER[kind]
        lines = []
        for t in range(lo, lo + calendar.monthrange(y, m)[1] * 86400, per):
            b = real(t, per)
            lines.append(f"{t},{b['v']},{b['c']},{b['h']},{b['l']},{b['o']}")
        return 200, gzip.compress("\n".join(lines).encode())


@pytest.fixture
def gate(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_VENUE", "gate")
    monkeypatch.setattr(gf, "_now", lambda: NOW)
    monkeypatch.setattr(gf, "KLINE_DISK_DIR", tmp_path / "kline_cache" / "gate")
    monkeypatch.setattr(gf, "PUBLIC_PAUSE_PATH", tmp_path / "pause.json")
    monkeypatch.setattr(gf, "_retry_sleep", lambda s: None)
    gf.clear_kline_cache(disk=False)
    g = Gate()
    monkeypatch.setattr(gf, "_fetch", g)
    yield g
    gf.clear_kline_cache(disk=False)


def rest_asks(g):
    return [dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))
            for u in g.asked if "candlesticks?" in u]


def fakes(df, per, secs=None):
    """The closed candles in `df` that are not the real candle, by open."""
    bad = []
    for i, row in df.reset_index(drop=True).iterrows():
        t = int(pd.Timestamp(row["Date"]).timestamp())
        p = per if secs is None else int(secs[i])
        if t + p > NOW:
            continue                     # the forming candle is not final
        want = real(t, p)
        got = (row["Open"], row["High"], row["Low"], row["Close"], row["Volume"])
        if got != pytest.approx((want["o"], want["h"], want["l"], want["c"],
                                 want["v"])):
            bad.append(t)
    return bad


def test_a_long_read_has_no_fake_candle_at_a_page_break(gate):
    """The GitHub shard's read of a 15m frame: 6,000 candles is 3 pages, so
    the old asks put a fake at 2,001 and 4,002 candles back."""
    df = gf.klines("BTC_USDT", "Min15", 6000)
    assert len(df) == 6000
    assert df["Date"].is_monotonic_increasing and df["Date"].is_unique
    newest = NOW - NOW % 900
    assert fakes(df, 900) == [], [
        f"{(newest - t) // 900} candles back" for t in fakes(df, 900)]
    assert len(rest_asks(gate)) >= 3, "paged, 2,000 a page"


def test_the_exit_minutes_have_no_fake_minute(gate):
    """The v2 exit minutes (`minutes`, read fresh by every backtest): REST
    1m in five pages over its last 6.9 days, and 5m over the hole before —
    a read that ends on a 5-minute candle's opening second."""
    start = NOW - 9 * 86400
    m = gf.minutes("BTC_USDT", start, NOW)
    secs = list(m["Seconds"])
    assert 300 in secs and 60 in secs, "both kinds were read"
    assert fakes(m, 60, secs) == []


def test_a_read_that_ends_in_the_past_ends_on_the_whole_candle(gate):
    end = NOW - NOW % 900 - 96 * 900                    # a day ago, on an open
    f = gf.klines_page("BTC_USDT", "Min15", 10, end)
    assert int(f["Date"].iloc[-1].timestamp()) == end
    assert fakes(f, 900) == []


def test_the_runners_short_read_asks_exactly_as_before(gate):
    """300 candles is ONE page — what every room's runner reads at a candle
    close. Its ask is unchanged: `to` = the forming candle's opening second,
    which Gate answers as a placeholder, and the runner drops (it is not
    closed). Every closed candle was always real on this path."""
    df = gf.klines("BTC_USDT", "Min15", 300)
    (q,) = rest_asks(gate)
    assert (q["interval"], int(q["limit"]), int(q["to"])) == \
        ("15m", 300, NOW - NOW % 900)
    assert len(df) == 300 and fakes(df, 900) == []


def _save_old_format(symbol, iv, frame):
    """A cache file as the code before Oct 19, 2026 wrote it: no mark."""
    p = gf._disk_path(symbol, iv)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {"t": [int(x.timestamp()) for x in frame["Date"]],
         "o": list(frame["Open"]), "h": list(frame["High"]),
         "l": list(frame["Low"]), "c": list(frame["Close"]),
         "v": list(frame["Volume"])}
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(d, fh)


def _frame(bars):
    return pd.DataFrame({
        "Date": pd.to_datetime([b["t"] for b in bars], unit="s"),
        "Open": [float(b["o"]) for b in bars], "High": [float(b["h"]) for b in bars],
        "Low": [float(b["l"]) for b in bars], "Close": [float(b["c"]) for b in bars],
        "Volume": [float(b["v"]) for b in bars]})


def test_a_copy_saved_before_the_fix_is_read_again_once(gate):
    """This PC's saved copies carry the fakes of their last long read (KSTR
    15m: Sep 28, 2026 1:30pm), and a deep read refreshes only the newest
    candles of a long-enough copy — so a fake inside it would stay for good.
    A copy without the mark is read again once, then trusted."""
    newest = NOW - NOW % 900
    ts = [newest - k * 900 for k in range(5999, -1, -1)]
    planted = {newest - 2001 * 900, newest - 2500 * 900}
    bars = [placeholder(t, 900) if t in planted else real(t, 900) for t in ts]
    _save_old_format("KSTR_USDT", "15m", _frame(bars))
    df = gf.klines("KSTR_USDT", "Min15", 3000)
    assert fakes(df, 900) == [], "a fake candle the old read saved was served"
    n = len(rest_asks(gate))
    gf.clear_kline_cache(disk=False)
    df = gf.klines("KSTR_USDT", "Min15", 3000)
    assert len(rest_asks(gate)) - n == 1, \
        "once read again, the copy is trusted: only its newest candles are asked"
    assert fakes(df, 900) == []


def test_a_copy_saved_by_the_fixed_code_reads_only_its_newest_candles(gate):
    newest = NOW - NOW % 900
    good = _frame([real(newest - k * 900, 900) for k in range(5999, -1, -1)])
    gf._disk_save("BTC_USDT", "15m", good)
    gf.klines("BTC_USDT", "Min15", 3000)
    assert len(rest_asks(gate)) == 1, "a marked copy is never read again whole"
