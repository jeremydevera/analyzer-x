"""The CSV download must contain EVERY filtered row, not the first few thousand.

Operator, 2026-08-27: *"when i filter, and click download csv, i want thefilterd
result to be downloaded only"*. The filters were in fact applied — every row in
the file was flat, >= 80% and profitable — but the file was CUT SHORT: 5,000
rows of the 43,867 that matched `sizing = flat AND win % >= 80 AND profit > 0`
on the operator's store.

The cause was not a cap. Starlette advances a StreamingResponse's iterator in a
threadpool, and each `next()` can land on a different worker; sqlite3 refuses a
connection used off its creating thread, so the export died on its second
`fetchmany` with

    sqlite3.ProgrammingError: SQLite objects created in a thread can only be
    used in that same thread.

By then a 200 and 5,000 rows had already been sent, and a StreamingResponse
cannot take them back — so the download simply stopped and the file looked
complete. Two fixes, both tested here: the export's connection may cross
threads (`check_same_thread=False`, one consumer, in order), and a stream that
dies anyway writes `EXPORT INCOMPLETE after N rows` into the file rather than
ending in silence.
"""
import concurrent.futures as cf
import json
import time

import pytest

from tradingagents import api, market_sweep as msw, rows_index as ri


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Enough rows that the export needs more than one `fetchmany`."""
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")

    def row(i, sizing):
        wr = 50.0 + (i % 50)
        return {"coin": f"C{i % 7}", "tf": "1h", "signal": f"sig{i % 11}",
                "th": 0.1, "sl": 0.3, "tp": 2.0, "rr": 3.0, "sizing": sizing,
                "lev": 20, "base": 5.0, "notional": 100.0, "trades": 120,
                "wins": round(120 * wr / 100),
                "losses": 120 - round(120 * wr / 100), "winrate": wr,
                "profit": float(i), "funding": -0.2, "h1": 1.0, "h2": 1.0,
                "green": 8, "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
                "stop_reachable": True, "days": 360, "bars": 34000,
                "monthly": {"2026-08": 1.0}, "cost_of_tp": 12.5, "rt": 0.04,
                "gate": "ok"}

    batch = [row(i, "flat" if i % 2 else "martingale") for i in range(1, 901)]
    (rows_dir / "AAA-1h.json").write_text(json.dumps(batch))
    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return batch


def _rows(text: str) -> list:
    lines = [ln for ln in text.strip().split("\n") if ln]
    return lines[1:]


def test_the_file_holds_every_matching_row(store):
    """450 flat rows in the store, 450 in the file — the count the screen would
    have printed, not a page of it."""
    body = "".join(api.strategies_csv_lines(sizing="flat", batch=100))
    rows = _rows(body)
    assert len(rows) == 450, len(rows)
    assert "martingale" not in body
    assert "EXPORT INCOMPLETE" not in body


def test_it_survives_being_drained_from_other_threads(store):
    """The real failure, reproduced: advance the generator one row at a time,
    each `next()` on a DIFFERENT thread, exactly as Starlette's threadpool does.
    Before the fix this raised sqlite3.ProgrammingError on the second batch.
    """
    gen = api.strategies_csv_lines(sizing="flat", batch=50)
    chunks = []
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            got = pool.submit(lambda: next(gen, None)).result()
            if got is None:
                break
            chunks.append(got)
    rows = _rows("".join(chunks))
    assert len(rows) == 450, len(rows)
    assert "EXPORT INCOMPLETE" not in "".join(chunks)


def test_every_filter_reaches_the_file(store):
    """Whatever the screen was showing is what downloads: the same filters, the
    same order, the same fields (kit item F)."""
    body = "".join(api.strategies_csv_lines(sizing="flat", min_winrate=80,
                                            profitable=True, batch=100))
    rows = [ln.split(",") for ln in _rows(body)]
    cols = "".join(api.strategies_csv_lines(sizing="flat", batch=1)).split("\n")[0].split(",")
    i_sz, i_wr, i_pf = cols.index("sizing"), cols.index("winrate"), cols.index("profit")
    assert rows, "the filter must not empty the file"
    assert {r[i_sz] for r in rows} == {"flat"}
    assert min(float(r[i_wr]) for r in rows) >= 80
    assert min(float(r[i_pf]) for r in rows) > 0
    # and the order is the one that was asked for
    profits = [float(r[i_pf]) for r in rows]
    assert profits == sorted(profits, reverse=True)


def test_a_stream_that_dies_says_so_in_the_file(store, monkeypatch):
    """A StreamingResponse has already sent 200 by the time a row fails, so the
    only place left to be honest is the file itself."""
    real = ri.iter_rows

    def dying(*a, **kw):
        for i, r in enumerate(real(*a, **kw)):
            if i == 7:
                raise RuntimeError("disk went away")
            yield r

    monkeypatch.setattr(ri, "iter_rows", dying)
    out = []
    with pytest.raises(RuntimeError):
        for chunk in api.strategies_csv_lines(sizing="flat"):
            out.append(chunk)
    body = "".join(out)
    assert "EXPORT INCOMPLETE after 7 rows" in body
    assert "disk went away" in body


def test_the_filename_says_which_slice_is_in_the_file(store):
    name = api.strategies_csv_name(coin="KAVA", tf="1h", min_trades=100,
                                   sort="profit", min_winrate=80, max_tp=4,
                                   sizing="flat")
    for bit in ("KAVA", "1h", "min100", "wr80", "tp4", "flat", "profit"):
        assert bit in name, (bit, name)
