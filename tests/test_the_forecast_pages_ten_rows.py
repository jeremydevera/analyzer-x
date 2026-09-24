"""Backtest v2: Stored strategies first, and the account forecast ten rows a
page (operator, Sep 25, 2026: "put stored strategies section before Forecast
for the account / then paginate Forecast for the account 10rows").

The Sep 24 deploy switched on 537 rows and the forecast printed one line
each, in one table. The sort must run over every row BEFORE the page is cut,
or "profit, highest first" would sort ten rows at a time.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "webapp/src/app/(admin)/backtest-v2/page.tsx"
PANEL = ROOT / "webapp/src/components/backtest/PortfolioForecast.tsx"


def test_stored_strategies_come_before_the_forecast():
    src = PAGE.read_text(encoding="utf-8")
    assert src.index('<StrategiesPanel store="v2" />') < src.index("<PortfolioForecast />")


def test_the_forecast_table_shows_ten_rows_a_page_of_the_sorted_whole():
    src = PANEL.read_text(encoding="utf-8")
    assert "const PER_PAGE = 10;" in src
    sort_at = src.index("return [...list].sort(")
    cut_at = src.index("const shown = rows.slice(from, from + PER_PAGE);")
    assert sort_at < cut_at, "sorted first, then cut"
    table = src[src.index("<TableBody"):src.index("</TableBody>")]
    assert "{shown.map((r) => (" in table and "{rows.map(" not in table
    assert "setPage(1);" in src, "a new order starts at its top"
    assert "pageWindow(cur, pages)" in src
    assert "showing ${from + 1}–${from + shown.length} of ${rows.length}" in src, \
        "the count names the page and the whole, never the page alone"
