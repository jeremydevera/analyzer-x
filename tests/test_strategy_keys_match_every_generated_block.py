"""A row's strategy key and spec are the rule the Sep 24/25/27 blocks used.

Those blocks say "GENERATED FROM THE MEASURED ROWS, never typed". The watcher
has to generate the same way, unattended, so the rule is pinned against every
key they hold: 309 + 38 + 2."""
import re

import pytest

from tradingagents import auto_trader as at, strategy_keys as sk
from tradingagents.local_history import _sig_of

BLOCKS = {**at._OPERATORS_V2_SEP24, **at._OPERATORS_V2_SEP25,
          **at._OPERATORS_V2_SEP27}
TF_OF = {v[0]: k for k, v in sk.TF_SPEC.items()}


def _row_of(key: str, spec: dict) -> dict:
    sig = _sig_of(key)
    return {"signal": sig, "tf": TF_OF[spec["interval"]],
            "th": round(spec.get("threshold", 0) * 100, 4),
            "sl": round(spec["sl"] * 100, 4), "tp": round(spec["tp"] * 100, 4)}


@pytest.mark.parametrize("key", sorted(BLOCKS))
def test_every_generated_key_is_regenerated_exactly(key):
    spec = BLOCKS[key]
    row = _row_of(key, spec)
    assert sk.key_for(row) == key
    assert sk.spec_for(row) == spec


@pytest.mark.parametrize("pct,code", [(1.2, "12"), (0.5, "05"), (2.0, "2"),
                                      (2.5, "25"), (0.3, "03"), (18.0, "18p0"),
                                      (20.0, "20p0"), (12.5, "12p5")])
def test_percent_codes(pct, code):
    assert sk.pct_code(pct) == code


def test_a_threshold_rule_carries_its_threshold_in_the_name():
    row = {"signal": "fade15", "tf": "4h", "th": 0.8, "sl": 3.0, "tp": 4.0}
    assert sk.key_for(row) == "fade15_4h_t08_sl3tp4"
    assert sk.spec_for(row)["threshold"] == pytest.approx(0.008)


def test_a_rule_without_a_threshold_has_none():
    row = {"signal": "bb20", "tf": "15m", "th": 0.0, "sl": 1.2, "tp": 1.2}
    assert "threshold" not in sk.spec_for(row)
    assert not re.search(r"_t\d", sk.key_for(row))


def test_a_timeframe_the_runner_cannot_trade_is_refused():
    with pytest.raises(ValueError):
        sk.key_for({"signal": "bb20", "tf": "1m", "th": 0, "sl": 1, "tp": 1})
