"""Where the per-minute costs live (phase 4, spec D11, Oct 10, 2026).

The daily costs job replays Gate's hourly order books on 40 machines; the v2
shards on those same machines need the result for THEIR coins over the
window. So the store is one file per coin per month, a GitHub release asset
on the account whose machine measured it — public, keyless, downloadable by
any machine of either account — split in two releases a month because one
release holds at most 1,000 assets and Gate lists 1,027 contracts.
"""
import calendar

import numpy as np
import pytest

from tradingagents import cost_store as cs

OCT = calendar.timegm((2026, 10, 1, 0, 0, 0))
SEP = calendar.timegm((2026, 9, 1, 0, 0, 0))


def packed(ts, spread=0.001):
    n = len(ts)
    return {"t": np.asarray(ts, dtype="int64"), "spread": np.full(n, spread, "float32"),
            "buy": np.full(n, spread / 2, "float32"), "sell": np.full(n, spread / 2, "float32"),
            "exhausted": np.zeros(n, "bool"), "source": np.ones(n, "int8"),
            "bid": np.full(n, 99.9), "ask": np.full(n, 100.1)}


def test_names_split_the_coins_over_two_releases_a_month():
    assert cs.tag("BTC_USDT", "202610") == "costs-202610-a"
    assert cs.tag("SOL_USDT", "202610") == "costs-202610-b"
    assert cs.tag("0G_USDT", "202610") == "costs-202610-a"
    assert cs.asset("BTC_USDT", "202610") == "BTC_USDT-202610.npz"
    assert cs.url("o/r", "BTC_USDT", "202610") == \
        "https://github.com/o/r/releases/download/costs-202610-a/BTC_USDT-202610.npz"


def test_bytes_round_trip_and_merge_keeps_the_newer_day():
    a = packed([OCT, OCT + 60], spread=0.001)
    b = packed([OCT + 60, OCT + 120], spread=0.002)
    back = cs.from_bytes(cs.to_bytes(a))
    assert list(back["t"]) == [OCT, OCT + 60]
    m = cs.merge(a, b)
    assert list(m["t"]) == [OCT, OCT + 60, OCT + 120]
    assert float(m["spread"][1]) == pytest.approx(0.002), "the newer reading wins"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "CACHE", tmp_path / "cost_cache")
    monkeypatch.setattr(cs, "_now", lambda: OCT + 9 * 86400)


def test_a_month_is_found_on_whichever_account_measured_it(home):
    asked = []

    def fetch(url):
        asked.append(url)
        if "/a1/" in url:
            return 200, cs.to_bytes(packed([OCT, OCT + 60]))
        return 404, b""
    got = cs.load_month("BTC_USDT", "202610", repos=("a0/r", "a1/r"), fetch=fetch)
    assert list(got["t"]) == [OCT, OCT + 60]
    assert len(asked) == 2


def test_no_account_has_it_is_none_never_an_error(home):
    assert cs.load_month("BTC_USDT", "202610", repos=("a0/r",),
                         fetch=lambda u: (404, b"")) is None


def test_a_past_month_is_read_once_and_the_current_one_again_later(home, monkeypatch):
    n = []

    def fetch(url):
        n.append(url)
        return 200, cs.to_bytes(packed([SEP]))
    cs.load_month("BTC_USDT", "202609", repos=("a/r",), fetch=fetch)
    cs.load_month("BTC_USDT", "202609", repos=("a/r",), fetch=fetch)
    assert len(n) == 1, "a completed month never changes"
    cs.load_month("BTC_USDT", "202610", repos=("a/r",), fetch=fetch)
    monkeypatch.setattr(cs, "_now", lambda: OCT + 9 * 86400 + cs.CURRENT_TTL_S + 1)
    cs.load_month("BTC_USDT", "202610", repos=("a/r",), fetch=fetch)
    assert len(n) == 3, "the current month grows every day"


def test_a_window_spanning_two_months_reads_both_and_keeps_only_the_window(home):
    def fetch(url):
        if "202609" in url:
            return 200, cs.to_bytes(packed([SEP + 29 * 86400, SEP + 29 * 86400 + 60]))
        return 200, cs.to_bytes(packed([OCT, OCT + 60, OCT + 86400]))
    got = cs.book_for("BTC_USDT", SEP + 29 * 86400 + 30, OCT + 60, repos=("a/r",),
                      fetch=fetch)
    assert list(got["t"]) == [SEP + 29 * 86400, SEP + 29 * 86400 + 60, OCT, OCT + 60], \
        "a reading just before the window still answers its first minute"
