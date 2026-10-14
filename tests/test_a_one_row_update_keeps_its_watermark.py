"""A one-row UPDATE never leaves its pair reading "measured through: never"
(RCA-2026-10-14-A).

`pair_watermark` reads only the last 256 bytes of a pair's state file and
expects `"__last_ms__": N}` at the very end, because `save_states` was meant
to write that key last. But a dict keeps a key where it was FIRST inserted:
on a pair GitHub measured, the state is `{"__cloud__": true, "__last_ms__":
X}`, and UPDATE THIS BACKTEST (`run_pair(merge=True, signals=["mom6"])`) then
sets `__last_ms__` again and adds `__signals__` AFTER it. With one signal the
key sits inside the tail but not at its end — and the reader answered 0
instead of reading the file. Oct 10, 2026 7:10am: the v2 press on BTC 1h mom6
measured 280 rows and recorded `after_ms: 0`; the DEMO 30-day figure of a
row updated that way could not be rebuilt ("no stored backtest row for it").
Found by the review of the re-entry rule (Oct 13, 2026), where a one-row
update is how a row is put on the new rule before the daily run.
"""
import json

from tradingagents import market_sweep as msw

X = 1_791_910_800_000


def test_the_watermark_is_written_last(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "STATES", tmp_path)
    monkeypatch.setattr(msw, "_paths", lambda: None)
    states = {"__cloud__": True, "__last_ms__": X}
    states["__last_ms__"] = X + 1               # keeps its FIRST position
    states["__signals__"] = ["mom6"]
    msw.save_states("BTC", "1h", states)
    text = (tmp_path / "BTC-1h.json").read_text()
    assert text.rstrip().endswith(f'"__last_ms__":{X + 1}}}'), text[-80:]
    assert msw.pair_watermark("BTC", "1h") == X + 1


def test_a_file_written_the_old_way_is_still_read(tmp_path, monkeypatch):
    """The files already on disk: the key inside the tail, not at its end."""
    monkeypatch.setattr(msw, "STATES", tmp_path)
    (tmp_path / "BTC-1h.json").write_text(json.dumps(
        {"__cloud__": True, "__last_ms__": X, "__signals__": ["mom6"]},
        separators=(",", ":")))
    assert msw.pair_watermark("BTC", "1h") == X
    # and a long file whose tail holds no key at all still parses
    (tmp_path / "ETH-1h.json").write_text(json.dumps(
        {"__last_ms__": X, "__signals__": [f"s{k}" for k in range(200)]},
        separators=(",", ":")))
    assert msw.pair_watermark("ETH", "1h") == X
