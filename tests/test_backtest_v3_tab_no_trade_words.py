"""A Backtest v3 tab run that made no trade says so in words (RCA-2026-10-27-C):
"no leverage (no trade)", never "leverage —x" or "$— of coin a trade". A run
with zero rows gives a row-shaped test nothing to stand on, so this reads the
WORDS the page prints."""
from __future__ import annotations

DASH_X = r'\?\? "—"\}[^<]{0,160}?\}x'      # `{min ?? "—"}...}x`: "—x" when nothing traded


def _dash_x(text: str) -> list[str]:
    import re

    return re.findall(DASH_X, text)


def test_a_run_with_no_trade_never_prints_a_dash_for_its_leverage():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "webapp/src/components/backtest-v3"
    for f in root.glob("*.tsx"):
        assert not _dash_x(f.read_text(encoding="utf-8")), f"{f.name} prints '—x' for no trade"
    runner = (root / "V3Runner.tsx").read_text(encoding="utf-8")
    assert "no leverage (no trade)" in runner and "no coin bought (no trade)" in runner
    # the pattern finds the old spelling (HEAD before this fix printed `—x` and `$— of coin`)
    assert _dash_x('leverage {s.leverage_min ?? "—"}\n {s.leverage_max !== s.leverage_min ? '
                   '`–${s.leverage_max}` : ""}x')
