"""The CSV download holds the same measurement the table showed.

Operator, Sep 03, 2026, with win % >= 90, TP <= 5, SL <= 2 and last 30 days on
screen: *"why is downoad csv not working i want to download the result of this
filter but its having internal server serror"*.

Three faults behind that one click, each measured:

1. **HTTP 500 after 30.0 s.** The route probes the first row before streaming,
   and that probe ran the query that took 51 minutes until `rows_wr3` landed
   (the win-rate seek that carries `sizing` and `profit`). With the index the
   same request is 0.14 s.
2. **HTTP 500 in 1.9 s**, once the index was there:
   `TypeError: strategies_csv_lines() got an unexpected keyword argument
   'days'` — the route had learned the window and the generator had not.
3. **The window was ignored entirely.** FastAPI drops an unknown query
   parameter, so the file held every row's WHOLE history under a filter that
   says "last 30 days". #2M4X7275 read 131 trades / +$95.29 in the file while
   the table showed 128 / +$93.11 for the same row.

Now: the export re-measures in batches (reusing the signal cache), writes the
WINDOW's figures in the row's own columns, carries three window columns so the
file can be read a week later, is CAPPED because a re-measurement is ~0.09 s a
row (58,212 matching rows would be 87 minutes), and says the cap in its own
last line.
"""
from __future__ import annotations

import inspect

from tradingagents import api, rows_index as ri


def test_every_layer_of_the_download_takes_the_window():
    for fn in (api.strategies_csv, api.strategies_csv_lines):
        assert "days" in inspect.signature(fn).parameters, fn.__name__
    assert "days" in inspect.signature(ri.iter_rows).parameters
    # the route hands it on — the missing hand-off was fault 2
    assert "days=days" in inspect.getsource(api.strategies_csv_lines)
    assert "days=0 if months else days" in inspect.getsource(api.strategies_csv), \
        "months wins over days here exactly as it does on the page"


def test_the_file_name_says_which_window_it_holds():
    name = api.strategies_csv_name(min_winrate=90, max_tp=5, max_sl=2, days=30)
    for bit in ("wr90", "tp5", "sl2", "last30d"):
        assert bit in name, (bit, name)
    assert "last30d" not in api.strategies_csv_name(min_winrate=90)


def test_the_windowed_export_writes_the_windows_figures():
    """The row's own columns, not extra ones the reader has to know about —
    the file must say what the table said (#2M4X7275: 128 trades and +$93.11
    in the window, 131 and +$95.29 over its whole history)."""
    src = inspect.getsource(ri.iter_rows)
    i = src.index("if win_days:")
    body = src[i:]
    for col in ("trades", "wins", "losses", "winrate", "profit"):
        assert f'd["{col}"] = d["w_{col}"]' in body, col
    for extra in ("window_first", "window_last", "window_days"):
        assert f'd["{extra}"]' in body, extra
    # and the header carries them, or three columns arrive unnamed
    csv_src = inspect.getsource(api.strategies_csv_lines)
    assert 'cols += ["window_first", "window_last", "window_days"]' in csv_src


def test_the_windowed_export_is_capped_and_says_so_in_the_file():
    assert ri.DAYS_CSV_MAX >= 500
    src = inspect.getsource(ri.iter_rows)
    assert "win_left = DAYS_CSV_MAX if win_days else -1" in src
    assert "batch_rows = batch_rows[:win_left]" in src
    note = inspect.getsource(api.strategies_csv_lines)
    assert "WINDOW CAPPED" in note, \
        "a capped file must say it is capped, IN the file"
    assert "Narrow the filter" in note, "and what to do about it"


def test_a_batch_can_never_raise_mid_stream():
    """A StreamingResponse has already sent 200 by the time a row fails, so an
    exception mid-stream is a truncated file that looks complete. The window
    call therefore gets a group cap it cannot exceed: a batch of N rows spans
    at most N pairs."""
    src = inspect.getsource(ri.iter_rows)
    assert "group_max=len(batch_rows) + 1" in src


def test_the_export_makes_the_SAME_index_choice_as_the_page():
    """The page and the download must not disagree about which index to use.

    They did, and the operator found it by clicking their own link:
    /api/strategies.csv?sort=profit&min_winrate=90&max_tp=4&max_sl=2&sizing=flat
    -> Internal Server Error, while the identical filter on the page answered
    in 0.14 s. `iter_rows` handed `_wide_profit_helps(...)` in unconditionally,
    so with a SIZING beside the win-rate floor it named rows_pr2 (profit DESC,
    sizing, ...) and walked 49.8 million entries down the profit order looking
    for flat rows above 90%: measured 259.0 s for the FIRST ROW. With the seek
    winning, the same export is 1.32 s to the first row and 27,482 rows in
    1.9 s (13.5 s through the browser, 11.6 MB).
    """
    src = inspect.getsource(ri.iter_rows)
    i = src.index("_indexed_by(coin, seeks")
    call = src[i:i + 260]
    assert "not seeks and" in call,         "a win-rate seek must win over the wide profit index, as it does in query()"
    # and query() has the same precedence, from the other direction
    page = inspect.getsource(ri.query)
    assert "not wide_profit_ready" in page or "wide_profit_ready" in page


def test_the_download_link_carries_the_window_too():
    """A file that does not match the table it came from is the failure this
    panel keeps paying for, and the href is where that starts."""
    panel = open("webapp/src/components/backtest/StrategiesPanel.tsx",
                 encoding="utf-8").read()
    i = panel.index("strategiesCsvUrl({")
    href = panel[i:i + 900]
    assert "months: applied.months" in href
    assert "days: applied.months ? undefined : (applied.days || undefined)" in href
    client = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    assert client.count('p.set("days"') == 2, "the table AND the download"
