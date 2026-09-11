"""A sweep measures the last 30 days unless somebody asks for more.

Operator, Sep 10, 2026: *"i only need past 30 days not 1 year because thats
too much"*.

What they had just watched: run `34400297077`, "Market sweep (15m / 30m)",
dispatched with a 365-day window over the whole market. After **1.0 hour** its
twenty machines averaged **0.9%** — an implied **112 hours (4.7 days)** —
against the **2.0 h** and **4.3 h** their two earlier sweeps took. Each shard
was walking `Aug 10, 2025 -> Sep 09, 2026`, thirteen months, from scratch.

The cause was not a server default. Their own Backtest screen opened on
**"Previous 1 year"** (`useState("Previous 1 year")`), so every press had been
asking for 365 days, and seven server-side fallbacks said `or 365` behind it.

This is the operator CHOOSING a window, not a cap nobody picked — the dropdown
still offers 30/60/90/180/365, and every row still reports its own
`days`/`bars` depth (CLAUDE.md, "Never cap the grid with a default nobody
chose"). What changed is what a caller that says nothing gets.

The cost of the choice, stated so it is not a surprise later: 30 days cannot
answer "months green", the out-of-sample halves become ~15 days each, and the
`still-working` skill's nested 1/3/6-month windows have nothing to read. That
is a trade the operator made deliberately.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from tradingagents import api, cloud_sweep as cs, db_jobs as dj

PANEL = Path("webapp/src/components/backtest/JobsPanel.tsx")


def test_the_named_default_is_thirty_days():
    assert cs.SWEEP_DAYS == 30, cs.SWEEP_DAYS


def test_dispatch_uses_the_named_default_not_a_literal():
    sig = inspect.signature(cs.dispatch)
    assert sig.parameters["days"].default == cs.SWEEP_DAYS
    src = inspect.getsource(cs.dispatch)
    assert "days: int = SWEEP_DAYS" in src, "a literal here drifts from the rest"


def test_the_screen_opens_on_the_past_month():
    panel = PANEL.read_text(encoding="utf-8")
    assert 'useState("Previous month")' in panel
    assert 'useState("Previous 1 year")' not in panel, \
        "this is what dispatched the 4.7-day sweep"


def test_the_year_window_is_gone_from_the_dropdown():
    """Operator, Sep 10, 2026: *"Also remove the previous 1 year i wont be
    using that"*. Removed rather than merely un-defaulted — an option that is
    still offered gets picked by accident once, and once is 4.7 days."""
    panel = PANEL.read_text(encoding="utf-8")
    assert '"Previous 1 year"' not in panel
    assert "365" not in panel.split("const WINDOWS")[1].split("}")[0]


def test_the_last_two_year_defaults_are_gone_too():
    """The Backtest card on Sep 11, 2026 still read "the whole 365-day window"
    — describing a proof run dispatched with days=365 — and the operator asked
    again why the year was "still there". The screen was already right; two
    DEFAULTS were not: the workflow input (`default: "365"`, what a manual
    GitHub dispatch gets) and the shard's own fallback. A default is a window
    nobody chose; both now say what the PC says."""
    yml = Path(".github/workflows/sweep.yml").read_text(encoding="utf-8")
    block = yml.split("      days:")[1].split("      base:")[0]
    assert f'default: "{cs.SWEEP_DAYS}"' in block, block
    assert '"365"' not in block
    shard = Path(".github/scripts/sweep_shard.py").read_text(encoding="utf-8")
    assert f'os.environ.get("DAYS", "{cs.SWEEP_DAYS}")' in shard
    assert 'os.environ.get("DAYS", "365")' not in shard


def test_the_shorter_windows_are_all_still_offered():
    """Depth stays the reader's decision inside what they kept."""
    panel = PANEL.read_text(encoding="utf-8")
    for label in ("Previous month", "Previous 2 months", "Previous 3 months",
                  "Previous 6 months"):
        assert f'"{label}"' in panel, label


def test_the_capability_is_untouched_only_the_menu_shrank():
    """`dispatch` must still accept any window a caller passes — the removal
    is a menu decision, not a new cap in the engine."""
    import inspect as _i

    sig = _i.signature(cs.dispatch)
    assert "days" in sig.parameters
    assert sig.parameters["days"].annotation in (int, "int")
    assert cs.dispatch.__doc__ and "window" in cs.dispatch.__doc__.lower()


def test_no_server_fallback_still_says_a_year():
    """Seven call sites each carried `or 365`; one place now decides."""
    for mod in (api, dj):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "or 365)" not in src, f"{mod.__name__} still forces a year"
        assert "_sweep_days()" in src


def test_the_fallback_helper_reads_the_one_constant():
    for mod in (api, dj):
        assert mod._sweep_days() == cs.SWEEP_DAYS == 30
        src = inspect.getsource(mod._sweep_days)
        assert "SWEEP_DAYS" in src, "it must not hard-code 30 either"


def test_an_explicit_window_still_wins():
    """The point is what a silent caller gets, not a ceiling."""
    sig = inspect.signature(cs.dispatch)
    assert sig.parameters["days"].kind is inspect.Parameter.KEYWORD_ONLY
    src = inspect.getsource(cs.dispatch)
    assert "days" in src
