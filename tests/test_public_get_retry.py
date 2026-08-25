"""The keyless GET tries again when the wire — not the request — failed.

2026-08-25: during a 4,985-pair candle download MEXC closed one connection
after 183,452 bytes of a CHILLGUY_USDT Min15 kline page. `resp.read()` raised
`http.client.IncompleteRead(183452 bytes read)`. That class is an
HTTPException, not an OSError, so `_get_public` did not even translate it,
let alone retry; it fell straight through `_klines_page` → `klines` →
`refresh_candles` and the pair was lost. A second attempt one second later
would have worked — the same endpoint served the other 4,983 pairs.

Only `_get_public` retries. `_request` (signed calls — orders, closes) is left
alone on purpose: a second order submit is a second order.
"""
import http.client
import io
import json
import urllib.error

import pytest

from tradingagents.dataflows import mexc_futures as fx

URL = f"{fx.BASE}/api/v1/contract/kline/CHILLGUY_USDT?interval=Min15"


class _Resp:
    def __init__(self, payload=None, cut_after=None):
        self._payload, self._cut = payload, cut_after

    def read(self):
        if self._cut is not None:
            raise http.client.IncompleteRead(b"x" * self._cut)
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def wire(monkeypatch):
    """Script the wire: a list of outcomes, one per urlopen call. An Exception
    instance is raised; anything else is the response body."""
    script, calls, slept = [], [], []
    clock = {"now": 1000.0}

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        step = script.pop(0)
        if isinstance(step, tuple):          # (seconds the attempt took, outcome)
            clock["now"] += step[0]
            step = step[1]
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(fx.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(fx, "_retry_sleep", lambda s: slept.append(s))
    monkeypatch.setattr(fx, "_clock", lambda: clock["now"])
    return {"script": script, "calls": calls, "slept": slept, "clock": clock}


def test_a_connection_cut_mid_body_is_retried_and_then_succeeds(wire):
    good = {"success": True, "data": {"time": [1]}}
    wire["script"] += [_Resp(cut_after=183452), _Resp(cut_after=90000), _Resp(good)]
    assert fx._get_public(URL) == good
    assert len(wire["calls"]) == 3
    assert wire["slept"] == list(fx._PUBLIC_BACKOFF[:2])
    assert all(s > 0 for s in wire["slept"]), "a redo needs a breath first"


def test_it_gives_up_after_its_attempts_with_a_transport_error(wire):
    wire["script"] += [_Resp(cut_after=183452)] * fx._PUBLIC_RETRIES
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx._get_public(URL)
    assert len(wire["calls"]) == fx._PUBLIC_RETRIES
    msg = str(exc.value)
    assert "transport failure" in msg and "IncompleteRead(183452 bytes read)" in msg
    assert f"after {fx._PUBLIC_RETRIES} attempts" in msg
    # the supervisor decides "retry later" by this wording (db_jobs.is_transient)
    from tradingagents import db_jobs

    assert db_jobs.is_transient(exc.value)


@pytest.mark.parametrize("boom", [
    urllib.error.URLError("[Errno 8] nodename nor servname provided"),
    TimeoutError("The read operation timed out"),
    ConnectionResetError(104, "Connection reset by peer"),
    http.client.RemoteDisconnected("Remote end closed connection without response"),
])
def test_every_wire_failure_is_retried(wire, boom):
    good = {"success": True}
    wire["script"] += [boom, _Resp(good)]
    assert fx._get_public(URL) == good
    assert len(wire["calls"]) == 2


@pytest.mark.parametrize("code", [500, 502, 503, 504, 429])
def test_a_server_side_status_is_retried(wire, code):
    good = {"success": True}
    wire["script"] += [urllib.error.HTTPError(URL, code, "err", {}, io.BytesIO(b"busy")),
                       _Resp(good)]
    assert fx._get_public(URL) == good
    assert len(wire["calls"]) == 2


@pytest.mark.parametrize("code", [400, 401, 404])
def test_a_client_side_status_is_not_retried(wire, code):
    wire["script"] += [urllib.error.HTTPError(URL, code, "err", {},
                                              io.BytesIO(b'{"code":404}'))]
    with pytest.raises(fx.MexcFuturesError):
        fx._get_public(URL)
    assert len(wire["calls"]) == 1 and wire["slept"] == []


def test_an_edge_block_is_not_retried_and_keeps_its_own_exception(wire):
    html = b"<HTML><HEAD>Access Denied</HEAD></HTML>"
    wire["script"] += [urllib.error.HTTPError(URL, 403, "err", {}, io.BytesIO(html))]
    with pytest.raises(fx.MexcFuturesEdgeBlocked):
        fx._get_public(URL)
    assert len(wire["calls"]) == 1


def test_signed_requests_are_never_retried(monkeypatch):
    """A second order submit is a second order."""
    import inspect

    src = inspect.getsource(fx._request)
    assert "_PUBLIC_RETRIES" not in src and "_retry_sleep" not in src


def test_a_dead_network_gets_one_redo_not_three(wire):
    """Each attempt on a dead network burns the full _TIMEOUT. The runner
    walks through _get_public for every coin every cycle, so redos are
    bounded by wall-clock, not only by count: after _PUBLIC_RETRY_BUDGET_S
    has gone, no new attempt starts."""
    slow = fx._TIMEOUT
    wire["script"] += [(slow, TimeoutError("timed out"))] * fx._PUBLIC_RETRIES
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx._get_public(URL)
    assert len(wire["calls"]) == 2, "one redo — the second timeout ends it"
    assert "after 2 attempts" in str(exc.value)


def test_a_fast_failure_keeps_all_its_attempts(wire):
    good = {"success": True}
    wire["script"] += [(0.2, _Resp(cut_after=1)), (0.2, _Resp(cut_after=2)),
                       (0.2, _Resp(good))]
    assert fx._get_public(URL) == good
    assert len(wire["calls"]) == 3


def test_the_budget_is_small_enough_for_the_runner():
    """The longest one call can hold a runner cycle: the budget elapses, one
    more attempt runs to its timeout, plus the breaths between."""
    worst = fx._PUBLIC_RETRY_BUDGET_S + fx._TIMEOUT + sum(fx._PUBLIC_BACKOFF)
    assert fx._PUBLIC_RETRIES >= 3
    assert worst <= 60, worst
