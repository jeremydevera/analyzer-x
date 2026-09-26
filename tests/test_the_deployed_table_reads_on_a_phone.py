"""The deployed-strategies table reads on a phone (RCA-2026-09-26-A).

Operator, Sep 26, 2026, from their phone: "why is it like this i thought you
already fixed it". The Sep 23 phone fix (RCA-2026-09-23-A) gave cards to the
positions and history tables and left StrategiesGrid out: twelve columns in a
390px screen, ~30px each, so "keltner_30m" and "LIVE W/L" broke letter by
letter. The class guard: EVERY trade-screen component that draws a fixed
table also draws a phone view.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADE = ROOT / "webapp/src/components/trade"
GRID = TRADE / "StrategiesGrid.tsx"


def test_the_grid_has_a_phone_view_and_hides_the_table_below_md():
    src = GRID.read_text(encoding="utf-8")
    assert 'className="flex flex-col gap-2 p-3 md:hidden"' in src
    assert 'className="hidden w-full md:block"' in src
    cards = src[src.index("md:hidden"):src.index("hidden w-full md:block")]
    for must in ("switches(r)", "<CopyableId", "<Live sym=", "bookRecord(",
                 "setMargin(", "strategy_loss_limits", "TOTAL"):
        assert must in cards, f"the phone card lost {must}"


def test_both_views_draw_the_switches_and_records_from_one_definition():
    src = GRID.read_text(encoding="utf-8")
    assert src.count("const switches = (r: StrategyDeployRow)") == 1
    assert src.count("const bookRecord = (") == 1
    assert src.count('aria-label={b === "real" ? "trade real money"') == 1


# a fixed table allowed without cards, and why: six SHORT columns (coin,
# PROFIT $, trades, W, L, win %) are ~60px each on a 390px phone, which fits
NARROW_ENOUGH = {"PnlPanel.tsx"}


def test_every_fixed_table_on_the_trade_screen_has_a_phone_view():
    for f in sorted(TRADE.glob("*.tsx")):
        src = f.read_text(encoding="utf-8")
        if "<Table fixed" in src and f.name not in NARROW_ENOUGH:
            assert "md:hidden" in src, f"{f.name} draws a fixed table with no phone view"
