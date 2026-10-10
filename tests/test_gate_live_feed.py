"""The live feed on Gate's socket (phase 2, Oct 10, 2026).

Messages below are the real shapes Gate pushed on `wss://fx-ws.gateio.ws/v4/ws/usdt`
on Oct 10, 2026 (40 seconds of BTC_USDT and AAPL_USDT: 560 trades, 35
tickers, 35 candle pushes). The feed keeps every rule it had on MEXC — a
recorder, total, never a print from before the order — and only the address,
the messages and the parsing change (`GateProtocol`).
"""
import json
import time

import pytest

from tradingagents import live_price as lp


@pytest.fixture
def feed():
    f = lp.PriceFeed(protocol=lp.GateProtocol())
    f._connected = True
    f._last_msg_at = time.time()
    return f


def test_a_trade_is_a_tick_at_its_own_millisecond(feed):
    now_ms = int(time.time() * 1000)
    feed._on_message({"time": now_ms // 1000, "time_ms": now_ms,
                      "channel": "futures.trades", "event": "update",
                      "result": [{"id": 849519883, "size": -13,
                                  "create_time": now_ms // 1000,
                                  "create_time_ms": now_ms - 250,
                                  "price": "82799.9", "contract": "BTC_USDT"}]})
    (t, p), = feed.ticks_since("BTC_USDT", 0)
    assert p == 82799.9 and t == pytest.approx((now_ms - 250) / 1000)


def test_a_ticker_is_a_tick_at_the_message_time(feed):
    now_ms = int(time.time() * 1000)
    feed._on_message({"time_ms": now_ms, "channel": "futures.tickers",
                      "event": "update",
                      "result": [{"contract": "AAPL_USDT", "last": "336.72"}]})
    assert feed.last("AAPL_USDT")[0] == 336.72


def test_the_subscribe_answer_is_not_a_tick(feed):
    feed._on_message({"time": 1, "channel": "futures.trades", "event": "subscribe",
                      "payload": ["BTC_USDT"], "result": {"status": "success"}})
    assert feed.last("BTC_USDT") is None


def _candle(n, t, h, l, w=False):
    return {"channel": "futures.candlesticks", "event": "update",
            "result": [{"t": t, "o": "1", "c": "1", "h": str(h), "l": str(l),
                        "a": "0", "n": n, "w": w, "v": 1}]}


def test_a_strategy_bar_closes_when_the_next_one_appears(feed):
    feed.track_klines([("BTC_USDT", "Min15")])
    feed._on_message(_candle("15m_BTC_USDT", 1791613800, 2, 1))
    assert feed.drain_closed_bars() == set(), "the first push is only a baseline"
    feed._on_message(_candle("15m_BTC_USDT", 1791613800, 3, 1))
    assert feed.drain_closed_bars() == set()
    feed._on_message(_candle("15m_BTC_USDT", 1791614700, 3, 1))
    assert feed.drain_closed_bars() == {("BTC_USDT", "Min15")}
    assert feed.wake.is_set()


def test_minutes_come_from_the_one_minute_stream(feed):
    feed.track_minutes(["BTC_USDT"])
    base = int(time.time()) // 60 * 60 - 180
    for k, (h, l) in enumerate([(10, 9), (11, 8), (12, 7), (13, 6)]):
        feed._on_message(_candle("1m_BTC_USDT", base + 60 * k, h, l))
    # the 4th minute is still forming: a minute is final when the next is pushed
    bars = feed.minute_bars("BTC_USDT", base + 1, now=base + 180 + 59)
    assert bars == [(base, 10.0, 9.0), (base + 60, 11.0, 8.0), (base + 120, 12.0, 7.0)]


def test_the_messages_gate_expects():
    g = lp.GateProtocol()
    assert g.url == "wss://fx-ws.gateio.ws/v4/ws/usdt"
    assert json.loads(g.ping())["channel"] == "futures.ping"
    subs = [json.loads(m) for m in g.subscribe_symbols(["BTC_USDT", "AAPL_USDT"])]
    assert {m["channel"] for m in subs} == {"futures.tickers", "futures.trades"}
    assert all(m["event"] == "subscribe" and m["payload"] == ["BTC_USDT", "AAPL_USDT"]
               for m in subs)
    (k,) = [json.loads(m) for m in g.subscribe_kline("BTC_USDT", "Min15")]
    assert k["channel"] == "futures.candlesticks" and k["payload"] == ["15m", "BTC_USDT"]
    (u,) = [json.loads(m) for m in g.unsubscribe_kline("BTC_USDT", "Min15")]
    assert u["event"] == "unsubscribe"


def test_mexc_messages_are_unchanged():
    m = lp.MexcProtocol()
    assert m.url == "wss://contract.mexc.com/edge"
    assert json.loads(m.ping()) == {"method": "ping"}
    assert [json.loads(x) for x in m.subscribe_symbols(["BTC_USDT"])] == [
        {"method": "sub.ticker", "param": {"symbol": "BTC_USDT"}},
        {"method": "sub.deal", "param": {"symbol": "BTC_USDT"}}]
    assert [json.loads(x) for x in m.subscribe_kline("BTC_USDT", "Min15")] == [
        {"method": "sub.kline", "param": {"symbol": "BTC_USDT", "interval": "Min15"}}]


def test_the_feed_follows_the_venue(monkeypatch):
    monkeypatch.setenv("TA_VENUE", "gate")
    assert isinstance(lp.protocol_for_venue(), lp.GateProtocol)
    monkeypatch.setenv("TA_VENUE", "mexc")
    assert isinstance(lp.protocol_for_venue(), lp.MexcProtocol)
