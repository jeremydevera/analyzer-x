"""The Backtest v4 tab (operator, Nov 10, 2026: "can you do backtest v4 i want the strategies stored
there, then follow the format like backtest v2 where i can see winrate and filter by day etc")."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PANEL = (REPO / "webapp/src/components/backtest-v4/V4Strategies.tsx").read_text(encoding="utf-8")


def test_the_tab_exists_and_is_on_the_menu_once():
    assert (REPO / "webapp/src/app/(admin)/backtest-v4/page.tsx").is_file()
    nav = (REPO / "webapp/src/layout/AppSidebar.tsx").read_text(encoding="utf-8")
    assert nav.count('path: "/backtest-v4"') == 1 and 'name: "Backtest v4"' in nav


def test_the_store_has_its_own_folder_and_no_job():
    from tradingagents import stores
    assert stores.by_name("v4") is stores.V4
    assert stores.V4.rows_db != stores.V2.rows_db != stores.V1.rows_db and "v4" in str(stores.V4.rows_db)
    assert stores.V4.backtest_kind == "" and stores.V4.download_kind == ""
    assert stores.for_kind("backtest_v4") is stores.V1      # no v4 job kind exists: nothing can run in it


def test_every_filter_of_the_kit_is_a_box_and_travels_to_the_query():
    for api in ("min_winrate", "min_profit", "min_green", "max_dip", "max_tp", "max_sl", "days", "months",
                "min_trades", "row_id", "base_margin", "unseen"):
        assert f'set("{api}"' in PANEL or f"set('{api}'" in PANEL or f'"{api}"' in PANEL, api
    for text in ("Find by ID", "Base margin $", "Min win rate %", "Min months green (count)", "Max TP %",
                 "Max SL %", "Last N days", "Last N months", "Clear all", "TOTAL PROFIT"):
        assert text in PANEL, text


def test_the_grid_has_every_required_column_and_the_provenance_line_holds_margin_and_notional():
    for col in ('"PROFIT / TOTAL $', '"TP %"', '"SL %"', ">Lev<", '"Wins"', '"Losses"', '"Win rate"',
                '"Worst losing run"', '"Trades"', '"Months green"', '"ID"'):
        assert col in PANEL, col
    assert "margin ×" in PANEL and "tested (" in PANEL          # margin x leverage and the count, above the table


def test_no_filter_is_applied_in_the_browser_over_a_list_the_server_already_cut():
    # the predicate travels to the query (CLAUDE.md kit item G): the row list is never .filter()ed
    assert not re.search(r"ans\??\.rows\??\.filter\(|rows\.filter\(", PANEL)


def test_dates_use_the_one_formatter():
    # a number may be grouped with toLocaleString(); a DATE never is (tests/test_webapp.py's rule)
    assert "new Date(" not in PANEL and "toLocaleDateString" not in PANEL and "toLocaleTimeString" not in PANEL
    assert "fmtWhen" in PANEL


def test_the_api_serves_the_list_the_facets_and_the_trade_log():
    api = (REPO / "tradingagents/api.py").read_text(encoding="utf-8")
    for route in ('"/api/v4/strategies"', '"/api/v4/facets"', '"/api/v4/strategies/trades"'):
        assert f"@app.get({route})" in api, route
