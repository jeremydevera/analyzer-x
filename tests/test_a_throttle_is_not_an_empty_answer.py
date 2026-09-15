"""MEXC sends "too frequent" as HTTP 200, so it never looked like a failure.

Found `Sep 16, 2026 1:45am`, minutes after the operator's 127 strategies were
armed. The runner's log:

    WARNING auto-trader cycle failed for TRGPSTOCK_USDT: no Min60 candles
    WARNING auto-trader cycle failed for CTSHSTOCK_USDT: no Min30 candles
    ... and CHYMSTOCK 1h, DXCMSTOCK 30m, SYFSTOCK 30m
    WARNING ... (code=510 msg='Requests are too frequent, please try again later')

The candles were all on disk — CTSHSTOCK-30m **1,954 bars**, DXCMSTOCK-30m
1,708, CHYMSTOCK-1h 658, TRGPSTOCK-1h 492, SYFSTOCK-30m 3,302. Nothing was
missing. MEXC had throttled the keyless klines call and said so in a body:

    HTTP 200  {"success": false, "code": 510,
               "message": "Requests are too frequent, please try again later"}

`_get_public` retried on the HTTP STATUS (`_RETRY_STATUSES` = 429, 5xx). This
one is a 200, so the wire looked perfect, and every caller does
`payload.get("data") or {}` — which turns a refusal into an empty answer. The
strategy then did nothing, and the only trace was a warning that named the
wrong cause.

Why now: the deploy took the runner from 9 coins to 26. `_BAR_CACHE` is empty
on the first cycle after a restart, so it asked for all of them at once. Same
family as the 2026-08-19 burst (166 `code=510` refusals in one minute), and
CLAUDE.md rule 16 already names 510 — but only on the SIGNED path, which is
the one that reads the body code. The keyless path never did.
"""
from __future__ import annotations

import json

import pytest

from tradingagents.dataflows import mexc_futures as mf

THROTTLE = json.dumps({"success": False, "code": 510,
                       "message": "Requests are too frequent, "
                                  "please try again later"}).encode()
GOOD = json.dumps({"success": True, "data": {"time": [1, 2], "close": [3, 4]}}).encode()
REJECT = json.dumps({"success": False, "code": 1001,
                     "message": "contract not exist"}).encode()


class _Resp:
    def __init__(self, raw): self._raw = raw
    def read(self): return self._raw
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _wire(monkeypatch, pages):
    """Serve `pages` in order; record how many calls were made."""
    calls = {"n": 0}

    def fake(req, timeout=None):
        i = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return _Resp(pages[i])

    monkeypatch.setattr(mf.urllib.request, "urlopen", fake)
    monkeypatch.setattr(mf, "_retry_sleep", lambda s: None)
    return calls


def test_a_throttle_is_retried_not_returned_as_empty(monkeypatch):
    """The whole bug: a 200 carrying code 510 was handed back, and
    `payload.get("data") or {}` read it as "no candles"."""
    calls = _wire(monkeypatch, [THROTTLE, GOOD])
    got = mf._get_public("http://x/klines")
    assert calls["n"] == 2, "it did not retry the throttle"
    assert got["data"]["close"] == [3, 4]
    assert got.get("success") is True


def test_a_throttle_that_never_clears_RAISES(monkeypatch):
    """It must not fall back to returning the refusal. A caller that reads
    `.get("data")` off a refusal prints "no candles" and blames the store."""
    _wire(monkeypatch, [THROTTLE])
    with pytest.raises(mf.MexcFuturesThrottled) as exc:
        mf._get_public("http://x/klines")
    assert "510" in str(exc.value)
    assert "too frequent" in str(exc.value).lower()


def test_it_is_still_a_MexcFuturesError(monkeypatch):
    """Every existing `except MexcFuturesError` keeps catching it — a new
    exception type that escapes the handlers already written would turn a
    throttle into a crashed cycle."""
    assert issubclass(mf.MexcFuturesThrottled, mf.MexcFuturesError)


def test_a_real_rejection_is_NOT_retried(monkeypatch):
    """A business code is an ANSWER. Retrying "contract not exist" three times
    is three times the load for the same no — the rule `_RETRY_STATUSES`
    already follows for a 4xx."""
    calls = _wire(monkeypatch, [REJECT, GOOD])
    with pytest.raises(mf.MexcFuturesError) as exc:
        mf._get_public("http://x/klines")
    assert not isinstance(exc.value, mf.MexcFuturesThrottled)
    assert calls["n"] == 1, "a rejection on the merits was retried"


def test_a_healthy_answer_is_untouched(monkeypatch):
    calls = _wire(monkeypatch, [GOOD])
    assert mf._get_public("http://x/k")["data"]["time"] == [1, 2]
    assert calls["n"] == 1, "a good answer must cost exactly one call"


def test_a_plain_list_body_still_works(monkeypatch):
    """Some keyless endpoints answer with a bare list. The throttle check must
    not assume a dict and start raising on those."""
    _wire(monkeypatch, [json.dumps([1, 2, 3]).encode()])
    assert mf._get_public("http://x/k") == [1, 2, 3]


def test_the_retry_budget_still_bounds_it(monkeypatch):
    """A throttle must not outlive `_PUBLIC_RETRY_BUDGET_S` — the runner walks
    through here every cycle and a coin that cannot answer may not hold it."""
    calls = _wire(monkeypatch, [THROTTLE])
    monkeypatch.setattr(mf, "_no_more_tries", lambda attempt, t0: True)
    with pytest.raises(mf.MexcFuturesThrottled):
        mf._get_public("http://x/k")
    assert calls["n"] == 1, "the budget did not stop it"


def test_510_is_named_where_the_codes_live():
    """Rule 16 names 510 for the signed path; this is the keyless half."""
    assert 510 in mf._RETRY_BODY_CODES
    assert 1001 not in mf._RETRY_BODY_CODES, "a rejection is not a throttle"
