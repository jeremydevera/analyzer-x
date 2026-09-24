"""The row's UPDATE button speaks for ITS row (docs/RCA.md RCA-2026-09-18-M).

There is ONE `pairbt` job for the whole app. A job started on AMP 15m made
the button under XPIN 1h (#LG9NSU4B) read "UPDATING…" with the line
"AMP 15m · ibs: index busy, retrying (2/3)" beside it — the operator's own
screenshot, `Sep 18, 2026 6:20am`. Presence of a job is not the same as this
row being re-measured (label-must-match-data).
"""
from __future__ import annotations

from pathlib import Path

PANEL = (Path(__file__).resolve().parents[1]
         / "webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")


def _button_block() -> str:
    # The block stopped being v1-only on Sep 18, 2026 — Backtest v2 has the
    # same button now, driving `pairbt_v2`. The anchor is the row id, which is
    # what actually gates it.
    # ...up to the idle line that closes the block — a fixed 2,600-character
    # window stopped short of the finished branch as soon as the running
    # branch gained its spinner (RCA-2026-09-24-K)
    i = PANEL.index("{open?.id && (")
    j = PANEL.index("measures this pair from its last measured bar to now", i)
    return PANEL[i:j]


def test_the_word_updating_needs_the_job_to_be_this_rows_pair():
    assert "const jobIsThisRow" in PANEL, "the row compares itself with the job's pair"
    assert 'pairJob.pair === `${open.coin} ${open.tf}`' in PANEL
    block = _button_block()
    # the word now sits beside a spinner (RCA-2026-09-24-K); what matters is
    # still that it is gated on THIS row's job (RCA-2026-09-18-M)
    at = block.index("pairJob?.running && jobIsThisRow ? (")
    assert "UPDATING…" in block[at:at + 600], block[at:at + 600]


def test_another_pairs_job_is_named_as_another_pairs_job():
    block = _button_block()
    assert "is being re-measured first — one row at a time" in block
    assert "pairJob?.running && !jobIsThisRow" in block


def test_a_finished_jobs_note_is_only_shown_on_the_row_it_belongs_to():
    block = _button_block()
    assert "pairJob?.note && jobIsThisRow ?" in block, block[:400]
