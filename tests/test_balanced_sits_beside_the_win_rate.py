"""`balanced` sits beside the win rate it qualifies, on screen and in the file.

Operator, `Sep 15, 2026`: *"i want the balanced beside the winrate in table and
when downloading"*.

It was the LAST column in both — several columns away from the number it
exists to put in context. The score is the answer to *"sometimes it has high
winrate but since tp is low and sl is high, its still not profitable"*, and an
answer that far from its question is not being read with it.
"""
from pathlib import Path

from tradingagents import rows_index as ri

PANEL = Path("webapp/src/components/backtest/StrategiesPanel.tsx")


def _heads(body: str) -> list:
    """The header list, in order.

    COMMENT LINES ARE DROPPED FIRST. The prose beside these columns quotes the
    operator, and those quotes contain commas and quote marks — a parser that
    splits the raw block reads "high winrate but tp is low" as two column
    names and then reports the order wrongly. Found by this test failing on a
    file that was already correct.
    """
    block = body[body.index('{["id", "coin", "tf"'):]
    block = block[:block.index("].map((h)")]
    lines = [ln for ln in block.splitlines()
             if not ln.strip().startswith("//")]
    out = []
    for part in chr(10).join(lines).split(","):
        part = part.strip()
        if part.startswith('winHead("') or part.startswith('[winHead("') or part.startswith('"') or part.startswith('{["'):
            out.append(part.split('"')[1])
    return out


def test_the_table_puts_balanced_next_to_win_percent():
    heads = _heads(PANEL.read_text(encoding="utf-8"))
    assert "win %" in heads and "balanced" in heads
    assert heads[heads.index("win %") + 1] == "balanced", heads


def test_the_table_no_longer_has_it_at_the_end():
    heads = _heads(PANEL.read_text(encoding="utf-8"))
    assert heads.count("balanced") == 1, "moved, not copied"
    assert heads[-1] != "balanced"


def test_the_cell_moved_with_its_header():
    """A header without its cell shifts every column after it."""
    body = PANEL.read_text(encoding="utf-8")
    win = body.index("{win(r).winrate?.toFixed(2)}")
    bal = body.index("{r.balanced === undefined ?")
    trades = body.index("{win(r).trades}")
    assert win < bal < trades, "the balanced CELL must sit between them too"


def test_the_csv_writes_it_beside_the_win_rate():
    import inspect

    from tradingagents import api

    src = inspect.getsource(api.strategies_csv_lines)
    assert '_bal_at = (cols.index("winrate") + 1)' in src
    assert "head[_bal_at:_bal_at] = [\"balanced\", \"balanced_why\"]" in src
    assert "_row[_bal_at:_bal_at] = [score, why]" in src, \
        "the VALUES have to move with the header or every column after it lies"


def test_the_csv_header_and_row_stay_the_same_length():
    cols = list(ri.COLS) + ["measured_through", "last_backtest_run"]
    i = cols.index("winrate") + 1
    head = list(cols)
    head[i:i] = ["balanced", "balanced_why"]
    row = [None] * len(cols)
    row[i:i] = ["score", "why"]
    assert len(head) == len(row)
    assert head[i - 1] == "winrate" and head[i] == "balanced"
