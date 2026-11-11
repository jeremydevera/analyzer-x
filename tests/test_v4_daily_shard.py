"""The daily shard set (skill rooms, Task 2): every Backtest v4 strategy is re-measured by the daily
GitHub run - the 42 technical-analysis settings x stops, then the backtesting skill's 15,933 PINNED
picks (ids never move) - with every trade paying its funding."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents import skill_bt as sb, skill_ta as sta, v4_pin

ROOT = Path(__file__).resolve().parent.parent


def _df(n=700, seed=11):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n))
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.uniform(100, 1000, n)}, index=idx)


def _pick(strategy, params, stop, target=None):
    return {"label": "x", "strategy": strategy, "params": params, "stop": stop, "target": target,
            "older": {}, "newer": {}, "older_lost": False, "trades": []}


def test_pin_keeps_every_bt_pick_with_its_split(tmp_path):
    src = tmp_path / "skill.json"
    p1 = {"fast_period": 20, "slow_period": 50}
    src.write_text(json.dumps({"lines": {
        "BTC|1h": {"coin": "BTC", "tf": "1h", "split_ms": 111, "picks": [
            _pick("sma_crossover", p1, 0.015), _pick("sma_crossover", p1, 0.03),
            _pick("momentum", {"period": 14, "threshold": 5.0}, 0.03)]},
        "ETH|4h": {"coin": "ETH", "tf": "4h", "split_ms": 222, "picks": [
            _pick("macd", {"fast": 12, "slow": 26, "signal": 9}, 0.015),
            _pick("breakout", {"lookback": 20, "threshold": 0.0}, 0.03),
            _pick("rsi_reversal", {"period": 14, "overbought": 70, "oversold": 30}, 0.015)]}}}),
        encoding="utf-8")
    out = tmp_path / "bt_pinned.json"
    res = v4_pin.build(src, out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["source"] == "skill.json" and isinstance(saved["made_s"], int)
    assert saved == {**res, "pairs": res["pairs"]}
    assert set(saved["pairs"]) == {"BTC|1h", "ETH|4h"}
    assert [len(v["picks"]) for v in saved["pairs"].values()] == [3, 3]
    assert saved["pairs"]["BTC|1h"]["split_ms"] == 111 and saved["pairs"]["ETH|4h"]["split_ms"] == 222
    assert set(saved["pairs"]["BTC|1h"]["picks"][0]) == {"strategy", "params", "stop", "target"}
    assert saved["pairs"]["BTC|1h"]["picks"][2]["strategy"] == "momentum"


def test_daily_line_measures_ta_all_and_only_the_pinned_bt():
    df = _df()
    pinned = {"split_ms": 123456, "picks": [
        {"strategy": "sma_crossover", "params": {"fast_period": 20, "slow_period": 50}, "stop": 0.015, "target": None},
        {"strategy": "momentum", "params": {"period": 14, "threshold": 5.0}, "stop": 0.03, "target": None},
        {"strategy": "bollinger_bands", "params": {"period": 20, "std_dev": 2.0}, "stop": 0.015, "target": None}]}
    line = sb.daily_line("BTC", "1h", df, pinned, fee=0.00075, slip=0.0003, funding=None, bar_ms=3_600_000)
    assert {"coin", "tf", "fee", "slip", "bars", "combos", "split_ms", "start_ms", "end_ms", "bar", "picks"} <= set(line)
    picks = line["picks"]
    assert len(picks) == 42 + 3 == line["combos"]
    ta, bt = picks[:42], picks[42:]
    assert {p["strategy"] for p in ta} <= set(sta.STRATEGIES)
    assert all("split_ms" not in p for p in ta)
    assert [(p["strategy"], p["params"], p["stop"], p["target"]) for p in bt] == \
        [(p["strategy"], p["params"], p["stop"], p["target"]) for p in pinned["picks"]]
    assert all(p["split_ms"] == 123456 for p in bt)
    assert all(p["older_lost"] is False for p in picks)
    t = next(p["trades"][0] for p in picks if p["trades"])
    assert len(t) == 5 and t[2] in (1, -1)                     # [entry_ms, exit_ms, side, why, pnl]


def test_a_coin_with_no_pinned_picks_measures_its_ta_only():
    line = sb.daily_line("NEW", "1d", _df(400), None, fee=0.00075, slip=0.0003, funding=None, bar_ms=86_400_000)
    assert len(line["picks"]) == 42


def test_daily_trades_pay_funding():
    df = _df()
    pinned = [{"strategy": "sma_crossover", "params": {"fast_period": 10, "slow_period": 30}, "stop": 0.03, "target": None}]
    bar_ms = 3_600_000
    t0 = int(df.index.as_unit("ms").asi8[0])
    funding = sb.Funding([{"settle_ms": t0 + h * 8 * bar_ms, "rate": 0.0005} for h in range(1, 120)])
    plain = sb.measure(df, pinned, fee=0.00075, slip=0.0003, funding=None, bar_ms=bar_ms)[0]["trades"]
    paid = sb.measure(df, pinned, fee=0.00075, slip=0.0003, funding=funding, bar_ms=bar_ms)[0]["trades"]
    assert len(plain) == len(paid) > 3
    sigs = sb.signals(df, "sma_crossover", pinned[0]["params"])
    full = sb.walk(df, sigs, stop=0.03, fee=0.00075, slip=0.0003, funding=funding, bar_ms=bar_ms)
    assert len(full) == len(paid)
    differ = 0
    for a, b, f in zip(plain, paid, full):
        assert abs((b[4] - a[4]) - f["fund"]) < 1e-3          # exactly that trade's funding (4 places)
        differ += f["fund"] != 0
    assert differ > 0                                         # the fixture really settles funding


def test_signals_are_computed_once_per_strategy_and_params(monkeypatch):
    calls = []
    real = sb.signals
    monkeypatch.setattr(sb, "signals", lambda df, n, p: (calls.append((n, json.dumps(p, sort_keys=True))), real(df, n, p))[1])
    combos = [{"strategy": "sma_crossover", "params": {"fast_period": 10, "slow_period": 30}, "stop": s, "target": None}
              for s in (0.015, 0.03)]
    sb.measure(_df(300), combos, fee=0.00075, slip=0.0003, bar_ms=3_600_000)
    assert len(calls) == 1


def test_workflow_uploads_the_daily_lines():
    text = (ROOT / ".github" / "workflows" / "skillbt.yml").read_text(encoding="utf-8")
    assert "out/skilldaily-*.jsonl" in text and "out/skilldaily-report-*.json" in text
    head = text.split("\njobs:")[0]
    block = head.split("inputs:")[1].split("\npermissions:")[0]
    assert len(re.findall(r"^      \w+:\s*$", block, flags=re.M)) <= 10
    assert "daily" in block


def test_the_shard_runs_the_daily_set_and_reads_the_pinned_file():
    src = (ROOT / ".github" / "scripts" / "skill_shard.py").read_text(encoding="utf-8")
    assert '"daily"' in src and '"skilldaily"' in src
    assert "bt_pinned.json" in src and "daily_line" in src
    assert "funding_history" in src and "since_ms" in src
    from tradingagents import acs

    assert acs.SKILL_PREFIX["daily"] == "skilldaily"


# ------------------------------------------------------------------ exits settled by the minute (Nov 11, 2026)
def _wicky_fine(df, bar_ms, wick):
    """Minutes under every candle of `df`: the candle's own close for 59 minutes, then a spike to
    `wick` beyond it in minute 30 - so a held trade is stopped by a wick its close never shows."""
    import numpy as np

    opens = df.index.as_unit("ms").asi8
    close = df["close"].to_numpy()
    t, hi, lo = [], [], []
    for k, o in enumerate(opens):
        for m in range(bar_ms // 60_000):
            t.append(int(o) + m * 60_000)
            spike = m == 30
            hi.append(close[k] * (1 + (wick if spike else 0.0)))
            lo.append(close[k] * (1 - (wick if spike else 0.0)))
    return sb.Fine(np.asarray(t), np.asarray(hi), np.asarray(lo), int(opens[0]), int(opens[-1]) + bar_ms)


def test_daily_line_with_minutes_settles_a_wick_and_says_how_it_settled_everything():
    df = _df()
    bar_ms = 3_600_000
    fine = _wicky_fine(df, bar_ms, wick=0.05)                 # every candle has a 5% wick: stops of 1.5% / 3% all hit
    line = sb.daily_line("BTC", "1h", df, None, fee=0.00075, slip=0.0003, funding=None, bar_ms=bar_ms, fine=fine)
    plain = sb.daily_line("BTC", "1h", df, None, fee=0.00075, slip=0.0003, funding=None, bar_ms=bar_ms)
    assert "exits" not in plain, "a line measured on candles says nothing about minutes"
    ex = line["exits"]
    assert ex["from_ms"] == fine.from_ms and ex["minute"] > 0 and ex["candle"] == 0
    sixes = [t for p in line["picks"] for t in p["trades"] if len(t) == 6]
    assert sixes and all(t[3] in ("SL", "TP") and t[5] % 60_000 == 0 and t[1] <= t[5] < t[1] + bar_ms for t in sixes)
    assert sum(1 for p in line["picks"] for t in p["trades"] if t[3] == "SL") > \
        sum(1 for p in plain["picks"] for t in p["trades"] if t[3] == "SL"), "wicks stop trades closes never did"


def test_the_shard_reads_each_coins_minutes_once_from_the_days_window():
    src = (ROOT / ".github" / "scripts" / "skill_shard.py").read_text(encoding="utf-8")
    assert "sb.read_fine(sym, sb.fine_from_ms(today_ms))" in src and "fine=fine" in src
    assert src.count("read_fine(") == 1, "once a coin, never once a timeframe"
    # the follower's warm-up reads the same stretch for the same midnight
    fol = (ROOT / "tradingagents" / "v4_follow.py").read_text(encoding="utf-8")
    assert "sb.fine_from_ms(" in fol and "R.fine(" in fol
