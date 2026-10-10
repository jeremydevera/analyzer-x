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


def test_both_accounts_files_are_merged_never_the_first_one_alone(home):
    """The deal moves coins between accounts (a listing earlier in the
    alphabet shifts every coin after it), so one coin-month can sit on both:
    account a0 holds Oct 01, a1 holds Oct 02. Reading only the first that
    answered left Oct 02 unmeasured (final review, RCA-2026-10-10-F)."""
    def fetch(url):
        if "/a0/" in url:
            return 200, cs.to_bytes(packed([OCT, OCT + 60]))
        return 200, cs.to_bytes(packed([OCT + 86400, OCT + 86400 + 60]))
    got = cs.load_month("BTC_USDT", "202610", repos=("a0/r", "a1/r"), fetch=fetch)
    assert list(got["t"]) == [OCT, OCT + 60, OCT + 86400, OCT + 86400 + 60]


def test_a_failed_read_is_never_taken_for_no_file(home):
    """A 502 is not a 404: strict (the costs job, about to OVERWRITE the
    month) raises, so a month is never replaced by one day; a reader keeps
    the account that answered and caches nothing incomplete."""
    def fetch(url):
        if "/a0/" in url:
            return 502, b""
        return 200, cs.to_bytes(packed([OCT]))
    with pytest.raises(cs.CostReadError) as err:
        cs.load_month("BTC_USDT", "202610", repos=("a0/r", "a1/r"), fetch=fetch,
                      strict=True)
    assert "502" in str(err.value) and "a0/r" in str(err.value)
    got = cs.load_month("BTC_USDT", "202610", repos=("a0/r", "a1/r"), fetch=fetch)
    assert list(got["t"]) == [OCT]
    assert not (cs.CACHE / cs.asset("BTC_USDT", "202610")).exists()


def test_the_download_is_retried_on_a_cut_wire_and_a_5xx(monkeypatch):
    calls = []

    def get(u):
        calls.append(u)
        if len(calls) == 1:
            raise OSError("connection reset")
        if len(calls) == 2:
            return 503, b""
        return 200, b"ok"
    monkeypatch.setattr(cs, "_get", get)
    monkeypatch.setattr(cs, "_sleep", lambda s: None)
    assert cs._fetch("u") == (200, b"ok") and len(calls) == 3
    calls.clear()
    monkeypatch.setattr(cs, "_get", lambda u: calls.append(u) or (404, b""))
    assert cs._fetch("u") == (404, b"") and len(calls) == 1, "a 404 is an answer"


def test_no_account_has_it_is_none_never_an_error(home):
    assert cs.load_month("BTC_USDT", "202610", repos=("a0/r",),
                         fetch=lambda u: (404, b"")) is None


def test_an_old_month_is_read_once_and_a_recent_one_again_later(home, monkeypatch):
    """A month is FINAL only once it ended more than FINAL_AFTER_S ago: Sep 30
    is written on Oct 01 and a red day is re-run later inside the 30-day
    backfill, so September read on Oct 10 still changes (final review,
    RCA-2026-10-10-F). August, ended 39 days before, never does."""
    n = []
    AUG = calendar.timegm((2026, 8, 1, 0, 0, 0))

    def fetch(url):
        n.append(url)
        return 200, cs.to_bytes(packed([AUG if "202608" in url else SEP]))
    cs.load_month("BTC_USDT", "202608", repos=("a/r",), fetch=fetch)
    cs.load_month("BTC_USDT", "202608", repos=("a/r",), fetch=fetch)
    assert len(n) == 1, "a month long finished never changes"
    cs.load_month("BTC_USDT", "202609", repos=("a/r",), fetch=fetch)
    cs.load_month("BTC_USDT", "202610", repos=("a/r",), fetch=fetch)
    monkeypatch.setattr(cs, "_now", lambda: OCT + 9 * 86400 + cs.CURRENT_TTL_S + 1)
    cs.load_month("BTC_USDT", "202609", repos=("a/r",), fetch=fetch)
    cs.load_month("BTC_USDT", "202610", repos=("a/r",), fetch=fetch)
    assert len(n) == 5, "September and October still grow on Oct 10"


def test_a_window_spanning_two_months_reads_both_and_keeps_only_the_window(home):
    def fetch(url):
        if "202609" in url:
            return 200, cs.to_bytes(packed([SEP + 29 * 86400, SEP + 29 * 86400 + 60]))
        return 200, cs.to_bytes(packed([OCT, OCT + 60, OCT + 86400]))
    got = cs.book_for("BTC_USDT", SEP + 29 * 86400 + 30, OCT + 60, repos=("a/r",),
                      fetch=fetch)
    assert list(got["t"]) == [SEP + 29 * 86400, SEP + 29 * 86400 + 60, OCT, OCT + 60], \
        "a reading just before the window still answers its first minute"


def test_a_coin_named_in_chinese_gets_a_plain_name_and_a_quoted_address():
    """Oct 10, 2026 (RCA-2026-10-10-S): Gate lists four contracts named in
    Chinese; the costs job built `.../releases/download/<tag>/龙虾_USDT-202610.npz`
    and urlopen raised UnicodeEncodeError — two machines of run 38058335262
    died on it. The file's name is plain ASCII for such a coin (one function,
    so the writer and every reader agree) and every address is quoted."""
    name = cs.asset("龙虾_USDT", "202610")
    assert name.isascii() and name.endswith("-202610.npz")
    assert name != cs.asset("牛市_USDT", "202610"), "two coins never share a file"
    assert cs.asset("BTC_USDT", "202610") == "BTC_USDT-202610.npz", "every ASCII coin keeps its name"
    assert cs.url("o/r", "龙虾_USDT", "202610").isascii()


def test_the_order_book_archive_address_is_quoted():
    from tradingagents import book_history as bh

    u = bh.hour_url("龙虾_USDT", 1791504000)
    assert u.isascii() and "%E9%BE%99" in u
